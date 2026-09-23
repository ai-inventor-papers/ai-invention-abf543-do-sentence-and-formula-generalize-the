"""OpenRouter client with a persistent cost ledger, a HARD budget cap and a content-hash disk cache.

- Every billed call appends one line to results/cost_ledger.jsonl with usage.cost from the response.
- HARD_CAP_USD (default 6.00): BudgetExceeded is raised BEFORE any call that would cross the cap
  (running total + estimated cost of the call).
- Disk cache: cache/llm/<sha1(request body)>.json. The iter-1 Arm A cache (cache/llm_iter1/) is consulted
  read-only first, so identical iter-1 requests (screen probes, MED/HELP B6 items) cost $0.
- Concurrency: asyncio.Semaphore(16); retries with tenacity-style exponential backoff (and a long
  backoff of up to 30 min on daily/key-limit errors, as the plan's fallback requires).
Only OpenRouter is used. Panel families (anthropic / x-ai / z-ai) are refused so the label source stays
family-disjoint from every model this experiment calls.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from pathlib import Path

import aiohttp
from loguru import logger

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "results" / "cost_ledger.jsonl"
CACHE = ROOT / "cache" / "llm"
CACHE_RO = [ROOT / "cache" / "llm_iter1"]
HARD_CAP_USD = float(os.environ.get("SIGFAITH_CAP_USD", "6.00"))
URL = "https://openrouter.ai/api/v1/chat/completions"
FORBIDDEN_PREFIX = ("anthropic/", "x-ai/", "z-ai/")


class BudgetExceeded(RuntimeError):
    pass


class Ledger:
    def __init__(self, path: Path = LEDGER, cap: float | None = None):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        CACHE.mkdir(parents=True, exist_ok=True)
        self.cap = HARD_CAP_USD if cap is None else cap
        self.total = 0.0
        self.reserved = 0.0
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                try:
                    self.total += float(json.loads(line).get("cost") or 0)
                except (json.JSONDecodeError, ValueError):
                    pass
        self.lock = asyncio.Lock()

    def check(self, est: float = 0.0):
        if self.total + self.reserved + est > self.cap:
            raise BudgetExceeded(f"spend {self.total:.4f} + reserved {self.reserved:.4f} + est {est:.4f} > cap {self.cap}")

    async def add(self, rec: dict):
        async with self.lock:
            self.total += float(rec.get("cost") or 0)
            with self.path.open("a") as f:
                f.write(json.dumps(rec) + "\n")


_LEDGER: Ledger | None = None


def ledger() -> Ledger:
    global _LEDGER
    if _LEDGER is None:
        _LEDGER = Ledger()
    return _LEDGER


def set_cap(cap: float):
    ledger().cap = cap


def body_of(model: str, messages: list, temperature: float = 0.0, max_tokens: int = 1024,
            reasoning: dict | None = None) -> dict:
    body = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens,
            "usage": {"include": True}}
    if reasoning is not None:
        body["reasoning"] = reasoning
    return body


def key_of(body: dict) -> str:
    return hashlib.sha1(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def cached(body: dict):
    k = key_of(body)
    for d in [CACHE] + CACHE_RO:
        p = d / f"{k}.json"
        if p.exists():
            try:
                x = json.loads(p.read_text())
                return x["text"], {**x["usage"], "cached": True, "cost": 0.0,
                                   "cost_original": x["usage"].get("cost", 0.0)}
            except (json.JSONDecodeError, KeyError):
                continue
    return None


async def call(session: aiohttp.ClientSession, sem: asyncio.Semaphore, *, model: str, messages: list, purpose: str,
               temperature: float = 0.0, reasoning: dict | None = None, max_tokens: int = 1024,
               est_cost: float = 0.002, retries: int = 5) -> tuple[str, dict]:
    if model.startswith(FORBIDDEN_PREFIX):
        raise ValueError(f"model {model} belongs to a panel family; refused (label firewall)")
    body = body_of(model, messages, temperature, max_tokens, reasoning)
    hit = cached(body)
    if hit is not None:
        return hit
    L = ledger()
    headers = {"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}", "Content-Type": "application/json"}
    last = None
    long_wait = 0.0
    attempt = 0
    while attempt < retries:
        async with sem:
            async with L.lock:
                L.check(est_cost)
                L.reserved += est_cost
            t0 = time.time()
            d = None
            try:
                async with session.post(URL, json=body, headers=headers,
                                        timeout=aiohttp.ClientTimeout(total=240)) as r:
                    txt = await r.text()
                    if r.status != 200:
                        last = f"HTTP {r.status}: {txt[:300]}"
                    else:
                        d = json.loads(txt)
            except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError) as e:
                last = repr(e)
            finally:
                async with L.lock:
                    L.reserved -= est_cost
        if d is None or "choices" not in d or not d["choices"]:
            if d is not None:
                last = f"no choices: {str(d)[:300]}"
            logger.warning(f"[{purpose}] attempt {attempt}: {last}")
            if last and ("limit" in last.lower() and ("daily" in last.lower() or "key" in last.lower())) \
                    and long_wait < 1800:
                long_wait += 300
                logger.warning(f"[{purpose}] key/daily limit hit; waiting 300 s (total {long_wait:.0f}s)")
                await asyncio.sleep(300)
                continue
            attempt += 1
            await asyncio.sleep(2 ** attempt + 1)
            continue
        msg = d["choices"][0]["message"]
        text = msg.get("content") or ""
        u = d.get("usage", {}) or {}
        rt = (u.get("completion_tokens_details") or {}).get("reasoning_tokens", 0) or 0
        usage = {"prompt_tokens": u.get("prompt_tokens", 0), "completion_tokens": u.get("completion_tokens", 0),
                 "reasoning_tokens": rt, "cost": float(u.get("cost") or 0.0), "seconds": round(time.time() - t0, 2),
                 "provider": d.get("provider")}
        await L.add({"ts": time.time(), "purpose": purpose, "model": model, **usage})
        logger.debug(f"[{purpose}] in={str(messages[-1]['content'])[:300]!r} out={text[:300]!r} usage={usage}")
        (CACHE / f"{key_of(body)}.json").write_text(json.dumps({"text": text, "usage": usage}, ensure_ascii=False))
        return text, usage
    raise RuntimeError(f"[{purpose}] failed after {retries} attempts: {last}")


async def run_batch(jobs: list[dict], concurrency: int = 16, est_cost_each: float = 0.002) -> list:
    """jobs: dicts of kwargs for call() (model, messages, purpose, reasoning, max_tokens, temperature).
    Returns list of (text, usage) or Exception, in order. Refuses up-front if the projected uncached
    spend would cross the cap."""
    L = ledger()
    n_unc = sum(1 for j in jobs if cached(body_of(j["model"], j["messages"], j.get("temperature", 0.0),
                                                  j.get("max_tokens", 1024), j.get("reasoning"))) is None)
    logger.info(f"run_batch: {len(jobs)} jobs, {n_unc} uncached, est ${n_unc * est_cost_each:.3f}; "
                f"spent so far ${L.total:.4f} of cap ${L.cap}")
    L.check(n_unc * est_cost_each)
    sem = asyncio.Semaphore(concurrency)
    async with aiohttp.ClientSession() as s:
        return await asyncio.gather(*[call(s, sem, est_cost=est_cost_each, **j) for j in jobs],
                                    return_exceptions=True)


def run(jobs: list[dict], concurrency: int = 16, est_cost_each: float = 0.002) -> list:
    return asyncio.run(run_batch(jobs, concurrency, est_cost_each))


def spent() -> float:
    return ledger().total


def n_uncached(jobs: list[dict]) -> int:
    return sum(1 for j in jobs if cached(body_of(j["model"], j["messages"], j.get("temperature", 0.0),
                                                 j.get("max_tokens", 1024), j.get("reasoning"))) is None)
