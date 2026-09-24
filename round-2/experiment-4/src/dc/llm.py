"""Capped async OpenRouter client (base URL from OPENROUTER_BASE_URL). Every paid call is appended to
cost_ledger.jsonl before returning; responses are cached by sha1(request body) in work/llm_cache/<phase>.jsonl;
HARD_STOP_USD (2.70 of the plan's $3 cap) is checked before every call. Frozen B1 prompt/request from exp3."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import re
import time
from pathlib import Path

import aiohttp
from loguru import logger

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "cost_ledger.jsonl"
CACHE_DIR = ROOT / "work" / "llm_cache"
HARD_STOP_USD = 2.70
FLASH = "google/gemini-2.5-flash"
B1_PROMPT = json.loads((ROOT / "vendor" / "exp3" / "prompts_frozen.json").read_text())["B1_PROMPT"]


class BudgetExceeded(RuntimeError):
    pass


def ledger_total(phase: str | None = None) -> float:
    if not LEDGER.exists():
        return 0.0
    t = 0.0
    for line in LEDGER.read_text().splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if phase is None or r.get("phase") == phase:
            t += float(r.get("cost_usd") or 0)
    return t


def body_key(body: dict) -> str:
    return hashlib.sha1(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def b1_body(sentence: str, fol: str, max_tokens: int = 16) -> dict:
    """Frozen exp3 B1 request (gemini-2.5-flash, temperature 0, reasoning off)."""
    return {"model": FLASH, "messages": [{"role": "user", "content": B1_PROMPT.format(s=sentence, f=fol)}],
            "temperature": 0.0, "max_tokens": max_tokens, "reasoning": {"max_tokens": 0, "exclude": True}}


def first_number(text: str | None):
    m = re.search(r"-?\d+(?:\.\d+)?", text or "")
    if not m:
        return None
    return min(100.0, max(0.0, float(m.group(0)))) / 100.0


class Client:
    def __init__(self, phase: str, phase_cap: float, concurrency: int = 16, timeout: float = 120.0):
        self.phase, self.phase_cap = phase, phase_cap
        self.sem = asyncio.Semaphore(concurrency)
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.url = os.environ["OPENROUTER_BASE_URL"].rstrip("/") + "/chat/completions"
        self.key = os.environ["OPENROUTER_API_KEY"]
        self.spent_total, self.spent_phase = ledger_total(), ledger_total(phase)
        self.lock = asyncio.Lock()
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self.cache_path = CACHE_DIR / f"{phase}.jsonl"
        self.cache = {}
        if self.cache_path.exists():
            for line in self.cache_path.read_text().splitlines():
                try:
                    r = json.loads(line)
                    self.cache[r["k"]] = r["v"]
                except (json.JSONDecodeError, KeyError):
                    continue
        self.n_paid = self.n_cached = self.n_failed = 0

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(timeout=self.timeout)
        return self

    async def __aexit__(self, *a):
        await self.session.close()

    async def chat(self, body: dict, tag: str = "", retries: int = 4) -> dict:
        body = {**body, "usage": {"include": True}}
        k = body_key(body)
        if k in self.cache:
            self.n_cached += 1
            return {**self.cache[k], "cached": True}
        async with self.sem:
            if self.spent_total >= HARD_STOP_USD or self.spent_phase >= self.phase_cap:
                raise BudgetExceeded(f"spent total ${self.spent_total:.4f} phase ${self.spent_phase:.4f}")
            last = ""
            for att in range(retries):
                t0 = time.time()
                try:
                    async with self.session.post(self.url, json=body, headers={
                            "Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}) as resp:
                        txt = await resp.text()
                        if resp.status != 200:
                            last = f"HTTP {resp.status}: {txt[:200]}"
                            if resp.status in (400, 401, 402, 403, 404):
                                break
                            await asyncio.sleep(2 ** att + random.random())
                            continue
                        data = json.loads(txt)
                except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError) as e:
                    last = f"{type(e).__name__}: {str(e)[:150]}"
                    await asyncio.sleep(2 ** att + random.random())
                    continue
                if not data.get("choices"):
                    last = f"API error {json.dumps(data.get('error', data))[:200]}"
                    await asyncio.sleep(2 ** att + random.random())
                    continue
                u = data.get("usage") or {}
                cost = float(u.get("cost") or 0.0)
                text = (data["choices"][0].get("message") or {}).get("content") or ""
                v = {"text": text, "cost_usd": cost, "seconds": round(time.time() - t0, 3),
                     "provider": data.get("provider"), "error": ""}
                async with self.lock:
                    self.spent_total += cost
                    self.spent_phase += cost
                    with open(LEDGER, "a") as f:
                        f.write(json.dumps({"ts": time.time(), "phase": self.phase, "model": body.get("model"),
                                            "tag": tag, "cost_usd": cost, "prompt_tokens": u.get("prompt_tokens"),
                                            "completion_tokens": u.get("completion_tokens"),
                                            "seconds": v["seconds"], "provider": v["provider"]}) + "\n")
                    with open(self.cache_path, "a") as f:
                        f.write(json.dumps({"k": k, "v": v}, ensure_ascii=False) + "\n")
                    self.cache[k] = v
                self.n_paid += 1
                logger.debug(f"[{self.phase}:{tag}] ${cost:.6f} -> {text[:60]!r}")
                return {**v, "cached": False}
            self.n_failed += 1
            logger.warning(f"[{self.phase}:{tag}] failed: {last}")
            return {"text": None, "cost_usd": 0.0, "error": last, "cached": False}


async def run_bodies(phase: str, cap: float, bodies: list[dict], tags: list[str], concurrency: int = 16,
                     n_pilot: int = 20) -> tuple[list[dict], dict]:
    """Pilot n calls -> $/call -> abort if projected spend breaks the phase cap or the hard stop -> sweep."""
    info = {"phase": phase, "n": len(bodies)}
    async with Client(phase, cap, concurrency) as c:
        async def one(b, t):
            try:
                return await c.chat(b, t)
            except BudgetExceeded as e:
                return {"text": None, "error": f"budget:{e}", "cost_usd": 0.0}
        pil = list(range(min(n_pilot, len(bodies))))
        rp = await asyncio.gather(*[one(bodies[i], tags[i]) for i in pil])
        paid = [r for r in rp if not r.get("cached") and r.get("text") is not None]
        upc = sum(r["cost_usd"] for r in paid) / len(paid) if paid else 0.0
        n_unc = sum(1 for b in bodies if body_key({**b, "usage": {"include": True}}) not in c.cache)
        est = upc * n_unc
        info.update(pilot_usd_per_call=upc, projected_usd=est, spent_before=c.spent_total)
        logger.info(f"[{phase}] pilot $/call {upc:.6f}; {n_unc} uncached -> projected ${est:.3f}; "
                    f"spent ${c.spent_total:.3f} (hard stop ${HARD_STOP_USD})")
        if c.spent_total + est > HARD_STOP_USD or c.spent_phase + est > cap:
            info["aborted"] = "projected spend exceeds cap"
            logger.error(f"[{phase}] ABORT sweep")
            res = [None] * len(bodies)
            for i, r in zip(pil, rp):
                res[i] = r
            return res, info
        res = await asyncio.gather(*[one(b, t) for b, t in zip(bodies, tags)])
        info.update(n_paid=c.n_paid, n_cached=c.n_cached, n_failed=c.n_failed, spent_after=c.spent_total,
                    phase_spent=c.spent_phase)
    return list(res), info
