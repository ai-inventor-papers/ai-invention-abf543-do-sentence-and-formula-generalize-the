"""Capped async OpenRouter client (derived from iter-2 exp-3 src/or_client.py; vendor/iter2/or_client.py).

Changes vs the vendored client: base URL is os.environ['OPENROUTER_BASE_URL'] (the run's proxy; the vendored copy
hard-codes openrouter.ai), one cache file work/llm_cache.jsonl keyed by sha1(request body), ledger
work/cost_ledger.jsonl, HARD_CAP_USD = 9.00 (plan), per-phase caps checked before every paid call.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import time

import aiohttp
from loguru import logger

from common import WORK

LEDGER = WORK / "cost_ledger.jsonl"
CACHE = WORK / "llm_cache.jsonl"
HARD_CAP_USD = 9.00
PHASE_CAPS = {"generation": 0.9, "calibration": 0.4, "panel": 5.6, "sensitivity": 0.15, "B1": 0.15, "B1plus": 1.3,
              "B3": 0.25, "arb": 0.1, "panel4": 0.4, "smoke": 0.1}


class BudgetExceeded(RuntimeError):
    pass


def ledger_total(phase: str | None = None) -> float:
    if not LEDGER.exists():
        return 0.0
    tot = 0.0
    for line in LEDGER.read_text().splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if phase is None or r.get("phase") == phase:
            tot += float(r.get("cost_usd") or 0.0)
    return tot


def body_key(body: dict) -> str:
    return hashlib.sha1(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


_CACHE: dict[str, dict] | None = None


def load_cache() -> dict:
    global _CACHE
    if _CACHE is None:
        _CACHE = {}
        if CACHE.exists():
            for line in CACHE.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        r = json.loads(line)
                        _CACHE[r["k"]] = r["v"]
                    except (json.JSONDecodeError, KeyError):
                        continue
    return _CACHE


class Client:
    def __init__(self, phase: str, phase_cap: float | None = None, concurrency: int = 16, timeout: float = 240.0):
        self.phase = phase
        self.phase_cap = PHASE_CAPS.get(phase, 0.5) if phase_cap is None else phase_cap
        self.sem = asyncio.Semaphore(concurrency)
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.spent_total = ledger_total()
        self.spent_phase = ledger_total(phase)
        self.lock = asyncio.Lock()
        self.session: aiohttp.ClientSession | None = None
        self.n_calls = self.n_cached = self.n_failed = 0
        self.key = os.environ["OPENROUTER_API_KEY"]
        self.url = os.environ["OPENROUTER_BASE_URL"].rstrip("/") + "/chat/completions"
        self.cache = load_cache()
        self.inflight: dict[str, asyncio.Future] = {}

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(timeout=self.timeout)
        return self

    async def __aexit__(self, *a):
        await self.session.close()

    async def _book(self, rec: dict, k: str, v: dict) -> None:
        async with self.lock:
            self.spent_total += rec["cost_usd"]
            self.spent_phase += rec["cost_usd"]
            with open(LEDGER, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
            with open(CACHE, "a", encoding="utf-8") as f:
                f.write(json.dumps({"k": k, "v": v}, ensure_ascii=False) + "\n")
            self.cache[k] = v
            ext = os.environ.get("AII_COST_LEDGER")
            if ext:
                try:
                    with open(ext, "a", encoding="utf-8") as f:
                        f.write(json.dumps({"ts": rec["ts"], "tool": "openrouter", "cost_usd": rec["cost_usd"],
                                            "model": rec["model"], "phase": rec["phase"]}) + "\n")
                except OSError:
                    pass

    def check_budget(self) -> None:
        if self.spent_total >= HARD_CAP_USD:
            raise BudgetExceeded(f"hard cap: spent ${self.spent_total:.4f} >= ${HARD_CAP_USD}")
        if self.spent_phase >= self.phase_cap:
            raise BudgetExceeded(f"phase {self.phase} cap: spent ${self.spent_phase:.4f} >= ${self.phase_cap}")

    async def chat(self, body: dict, *, tag: str = "", retries: int = 4, use_cache: bool = True) -> dict:
        """body = full request (model, messages, temperature, max_tokens, reasoning...). Returns
        {text, cost_usd, seconds, provider, finish_reason, usage, cached, error}."""
        body = {**body, "usage": {"include": True}}
        k = body_key(body)
        if use_cache and k in self.cache:
            self.n_cached += 1
            return {**self.cache[k], "cached": True}
        if use_cache and k in self.inflight:
            self.n_cached += 1
            v = await self.inflight[k]
            return {**v, "cached": True}
        fut = asyncio.get_event_loop().create_future()
        self.inflight[k] = fut
        try:
            v = await self._call(body, k, tag, retries)
        except BaseException as e:
            if not fut.done():
                fut.set_exception(e)
                fut.exception()
            self.inflight.pop(k, None)
            raise
        if not fut.done():
            fut.set_result(v)
        self.inflight.pop(k, None)
        return {**v, "cached": False}

    async def _call(self, body: dict, k: str, tag: str, retries: int) -> dict:
        headers = {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        last = ""
        async with self.sem:
            self.check_budget()
            for attempt in range(retries):
                t0 = time.time()
                try:
                    async with self.session.post(self.url, json=body, headers=headers) as resp:
                        txt = await resp.text()
                        if resp.status != 200:
                            last = f"HTTP {resp.status}: {txt[:300]}"
                            if resp.status in (400, 401, 402, 403, 404):
                                break
                            await asyncio.sleep(2 ** attempt + random.random())
                            continue
                        data = json.loads(txt)
                except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError) as e:
                    last = f"{type(e).__name__}: {str(e)[:200]}"
                    await asyncio.sleep(2 ** attempt + random.random())
                    continue
                if not data.get("choices"):
                    last = f"API error: {json.dumps(data.get('error', data))[:300]}"
                    await asyncio.sleep(2 ** attempt + random.random())
                    continue
                usage = data.get("usage") or {}
                cost = float(usage.get("cost") or 0.0)
                ch = data["choices"][0]
                msg = ch.get("message") or {}
                text = msg.get("content") or ""
                secs = round(time.time() - t0, 3)
                rec = {"ts": time.time(), "phase": self.phase, "model": body.get("model"), "tag": tag,
                       "cost_usd": cost, "prompt_tokens": usage.get("prompt_tokens"),
                       "completion_tokens": usage.get("completion_tokens"),
                       "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
                       "seconds": secs, "provider": data.get("provider")}
                v = {"text": text, "cost_usd": cost, "seconds": secs, "provider": data.get("provider"),
                     "finish_reason": ch.get("finish_reason"), "model_returned": data.get("model"),
                     "usage": {k2: usage.get(k2) for k2 in ("prompt_tokens", "completion_tokens")},
                     "reasoning_tokens": rec["reasoning_tokens"], "error": ""}
                await self._book(rec, k, v)
                self.n_calls += 1
                logger.debug(f"[{self.phase}:{tag}] ${cost:.6f} {secs}s -> {text[:160]!r}")
                return v
        self.n_failed += 1
        logger.warning(f"[{self.phase}:{tag}] failed: {last}")
        return {"text": None, "cost_usd": 0.0, "seconds": None, "provider": None, "finish_reason": None,
                "model_returned": None, "usage": {}, "reasoning_tokens": None, "error": last}


async def gather_bodies(client: Client, bodies: list[dict], tags: list[str]) -> list[dict]:
    async def one(b, t):
        try:
            return await client.chat(b, tag=t)
        except BudgetExceeded as e:
            return {"text": None, "error": f"budget:{e}", "cost_usd": 0.0, "seconds": None, "cached": False}
    return await asyncio.gather(*[one(b, t) for b, t in zip(bodies, tags)])
