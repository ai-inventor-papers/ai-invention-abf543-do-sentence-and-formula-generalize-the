"""OpenRouter client with a persistent per-call cost ledger and a hard budget cap.

Every call appends {ts, purpose, model, prompt_tokens, completion_tokens, reasoning_tokens, cost}
to results/cost_ledger.jsonl. Cumulative spend is re-read from the ledger at start-up so that a
restarted script keeps counting. BudgetExceeded is raised before any call that would cross the cap.
Responses are cached on disk (results/llm_cache/*.json keyed by sha1 of the request) so reruns are free.
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
CACHE = ROOT / "results" / "llm_cache"
CAP_USD = 5.80
URL = "https://openrouter.ai/api/v1/chat/completions"


class BudgetExceeded(RuntimeError):
    pass


class Ledger:
    def __init__(self):
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        CACHE.mkdir(parents=True, exist_ok=True)
        self.total = 0.0
        if LEDGER.exists():
            for line in LEDGER.read_text().splitlines():
                try:
                    self.total += float(json.loads(line).get("cost") or 0)
                except (json.JSONDecodeError, ValueError):
                    pass
        self.lock = asyncio.Lock()

    def check(self, est: float = 0.0):
        if self.total + est > CAP_USD:
            raise BudgetExceeded(f"spend {self.total:.4f} + est {est:.4f} > cap {CAP_USD}")

    async def add(self, rec: dict):
        async with self.lock:
            self.total += float(rec.get("cost") or 0)
            with LEDGER.open("a") as f:
                f.write(json.dumps(rec) + "\n")


LEDGER_OBJ: Ledger | None = None


def ledger() -> Ledger:
    global LEDGER_OBJ
    if LEDGER_OBJ is None:
        LEDGER_OBJ = Ledger()
    return LEDGER_OBJ


def _key(body: dict) -> str:
    return hashlib.sha1(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


async def call(session: aiohttp.ClientSession, sem: asyncio.Semaphore, *, model: str, messages: list,
               purpose: str, temperature: float = 0.0, reasoning: dict | None = None,
               max_tokens: int = 1024, retries: int = 4) -> tuple[str, dict]:
    body = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens,
            "usage": {"include": True}}
    if reasoning is not None:
        body["reasoning"] = reasoning
    k = _key(body)
    cp = CACHE / f"{k}.json"
    if cp.exists():
        try:
            d = json.loads(cp.read_text())
            return d["text"], {**d["usage"], "cached": True}
        except (json.JSONDecodeError, KeyError):
            pass
    L = ledger()
    L.check()
    headers = {"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}", "Content-Type": "application/json"}
    last = None
    for attempt in range(retries):
        async with sem:
            t0 = time.time()
            try:
                async with session.post(URL, json=body, headers=headers,
                                        timeout=aiohttp.ClientTimeout(total=180)) as r:
                    txt = await r.text()
                    if r.status != 200:
                        last = f"HTTP {r.status}: {txt[:300]}"
                        logger.warning(f"[{purpose}] {last}")
                        await asyncio.sleep(2 ** attempt + 1)
                        continue
                    d = json.loads(txt)
            except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError) as e:
                last = repr(e)
                logger.warning(f"[{purpose}] attempt {attempt}: {last}")
                await asyncio.sleep(2 ** attempt + 1)
                continue
        if "choices" not in d or not d["choices"]:
            last = f"no choices: {str(d)[:300]}"
            logger.warning(f"[{purpose}] {last}")
            await asyncio.sleep(2 ** attempt + 1)
            continue
        text = d["choices"][0]["message"].get("content") or ""
        u = d.get("usage", {}) or {}
        rt = (u.get("completion_tokens_details") or {}).get("reasoning_tokens", 0) or 0
        usage = {"prompt_tokens": u.get("prompt_tokens", 0), "completion_tokens": u.get("completion_tokens", 0),
                 "reasoning_tokens": rt, "cost": float(u.get("cost") or 0.0), "seconds": round(time.time() - t0, 2)}
        await L.add({"ts": time.time(), "purpose": purpose, "model": model, **usage})
        logger.debug(f"[{purpose}] in={str(messages[-1]['content'])[:300]!r} out={text[:300]!r} usage={usage}")
        cp.write_text(json.dumps({"text": text, "usage": usage}, ensure_ascii=False))
        return text, usage
    raise RuntimeError(f"[{purpose}] failed after {retries} attempts: {last}")


async def run_batch(jobs: list[dict], concurrency: int = 8, est_cost_each: float = 0.0) -> list:
    """jobs: dicts of kwargs for call(). Returns list of (text, usage) or Exception, in order."""
    L = ledger()
    uncached = sum(1 for j in jobs if not (CACHE / f"{_key(_body_of(j))}.json").exists())
    L.check(uncached * est_cost_each)
    sem = asyncio.Semaphore(concurrency)
    async with aiohttp.ClientSession() as s:
        return await asyncio.gather(*[call(s, sem, **j) for j in jobs], return_exceptions=True)


def _body_of(j: dict) -> dict:
    body = {"model": j["model"], "messages": j["messages"], "temperature": j.get("temperature", 0.0),
            "max_tokens": j.get("max_tokens", 1024), "usage": {"include": True}}
    if j.get("reasoning") is not None:
        body["reasoning"] = j["reasoning"]
    return body


def spent() -> float:
    return ledger().total
