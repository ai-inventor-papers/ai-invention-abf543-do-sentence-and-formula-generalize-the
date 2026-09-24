"""Capped async OpenRouter client (derived from the dataset's src/or_client.py).

* aiohttp + asyncio.Semaphore(concurrency); tenacity-style exponential retries on 408/429/5xx/timeouts.
* Every paid call appends {ts, phase, model, tag, prompt/completion/reasoning tokens, cost_usd, seconds, provider}
  to work/cost_ledger.jsonl BEFORE returning; the cumulative spend is re-read from the ledger at start-up.
* HARD_CAP_USD = float(os.environ.get("DC_HARD_CAP_USD", "9.50")) (global) and a per-phase cap are checked before every paid call (BudgetExceeded).
* Response cache keyed by sha1(request body) in work/llm_cache/<phase>.jsonl: identical requests are never
  billed twice (duplicate candidate strings across systems => identical B1 prompt => identical score).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import time
from pathlib import Path

import aiohttp
from loguru import logger

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "cost_ledger.jsonl"
CACHE_DIR = ROOT / "work" / "llm_cache"
URL = os.environ["OPENROUTER_BASE_URL"].rstrip("/") + "/chat/completions"  # the run key works only via this proxy
HARD_CAP_USD = float(os.environ.get("DC_HARD_CAP_USD", "9.50"))


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


class Client:
    def __init__(self, phase: str, phase_cap: float, concurrency: int = 16, timeout: float = 180.0,
                 cache_name: str | None = None):
        self.phase, self.phase_cap = phase, phase_cap
        self.sem = asyncio.Semaphore(concurrency)
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.spent_total = ledger_total()
        self.spent_phase = ledger_total(phase)
        self.lock = asyncio.Lock()
        self.session: aiohttp.ClientSession | None = None
        self.n_calls = self.n_cached = self.n_failed = 0
        self.key = os.environ["OPENROUTER_API_KEY"]
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self.cache_path = CACHE_DIR / f"{cache_name or phase}.jsonl"
        self.cache: dict[str, dict] = {}
        if self.cache_path.exists():
            for line in self.cache_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        r = json.loads(line)
                        self.cache[r["k"]] = r["v"]
                    except (json.JSONDecodeError, KeyError):
                        continue
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
            with open(self.cache_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"k": k, "v": v}, ensure_ascii=False) + "\n")
            self.cache[k] = v  # visible to later projections / identical requests in this session
            ext = os.environ.get("AII_COST_LEDGER")
            if ext:
                try:
                    with open(ext, "a", encoding="utf-8") as f:
                        f.write(json.dumps({"ts": rec["ts"], "tool": "openrouter", "cost_usd": rec["cost_usd"],
                                            "model": rec["model"], "phase": rec["phase"]}) + "\n")
                except OSError:
                    pass

    def check_budget(self, est: float = 0.0) -> None:
        if self.spent_total + est >= HARD_CAP_USD:
            raise BudgetExceeded(f"hard cap: spent ${self.spent_total:.4f} + est ${est:.4f} >= ${HARD_CAP_USD}")
        if self.spent_phase + est >= self.phase_cap:
            raise BudgetExceeded(f"phase {self.phase} cap: spent ${self.spent_phase:.4f} + est ${est:.4f} >= "
                                 f"${self.phase_cap}")

    async def chat(self, body: dict, *, tag: str = "", retries: int = 5, use_cache: bool = True) -> dict:
        """body = full OpenRouter request (model, messages, temperature, max_tokens, reasoning, ...).
        Returns {text, usage, cost_usd, seconds, provider, cached, error, finish_reason}."""
        body = {**body, "usage": {"include": True}}
        k = body_key(body)
        if use_cache and k in self.cache:
            self.n_cached += 1
            return {**self.cache[k], "cached": True}
        if use_cache and k in self.inflight:  # identical concurrent request: wait for the first one
            self.n_cached += 1
            v = await self.inflight[k]
            return {**v, "cached": True}
        fut = asyncio.get_event_loop().create_future() if use_cache else None
        if use_cache:
            self.inflight[k] = fut
        try:
            v = await self._call(body, k, tag, retries)
        except BaseException as e:
            if fut is not None and not fut.done():
                fut.set_exception(e)
                fut.exception()  # mark retrieved
            self.inflight.pop(k, None)
            raise
        if fut is not None and not fut.done():
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
                    async with self.session.post(URL, json=body, headers=headers) as resp:
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
                     "finish_reason": ch.get("finish_reason"), "usage": {k2: usage.get(k2) for k2 in
                                                                         ("prompt_tokens", "completion_tokens")},
                     "reasoning_tokens": rec["reasoning_tokens"], "error": ""}
                await self._book(rec, k, v)
                self.n_calls += 1
                logger.debug(f"[{self.phase}:{tag}] ${cost:.6f} {secs}s -> {text[:120]!r}")
                return v
        self.n_failed += 1
        logger.warning(f"[{self.phase}:{tag}] failed: {last}")
        return {"text": None, "cost_usd": 0.0, "seconds": None, "provider": None, "finish_reason": None,
                "usage": {}, "reasoning_tokens": None, "error": last}
