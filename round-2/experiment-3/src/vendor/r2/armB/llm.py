"""OpenRouter client with disk cache, cost ledger and a hard budget breaker.

All calls use google/gemini-2.5-flash, temperature 0, reasoning disabled (same model for B1, TVJT and
NLI-gemini). Responses are cached by sha1(model+messages+params) under cache/llm/, so re-runs cost $0.
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

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "cache" / "llm"
LEDGER = ROOT / "results" / "cost_ledger.jsonl"
MODEL = "google/gemini-2.5-flash"
HARD_CAP_USD = 6.50
URL = "https://openrouter.ai/api/v1/chat/completions"


class BudgetExceeded(RuntimeError):
    pass


class LLM:
    def __init__(self, concurrency: int = 16, hard_cap: float = HARD_CAP_USD):
        CACHE.mkdir(parents=True, exist_ok=True)
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        self.sem = asyncio.Semaphore(concurrency)
        self.hard_cap = hard_cap
        self.cum = self._ledger_total()
        self.n_calls = 0
        self.n_cached = 0
        self.reasoning_tokens = 0
        self.session: aiohttp.ClientSession | None = None
        self.key = os.environ["OPENROUTER_API_KEY"]

    @staticmethod
    def _ledger_total() -> float:
        """Budget counts EVERY ledger of this workspace (main + dev tests + mini runs)."""
        tot = 0.0
        lines = []
        for lp in list((ROOT / "results").glob("cost_ledger*.jsonl")) + list((ROOT / "runs").glob("*/results/cost_ledger*.jsonl")):
            lines += lp.read_text().splitlines()
        for line in lines:
            try:
                tot += float(json.loads(line).get("cost", 0) or 0)
            except (json.JSONDecodeError, ValueError):
                continue
        return tot

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120))
        return self

    async def __aexit__(self, *a):
        await self.session.close()

    def _payload(self, messages, max_tokens, temperature):
        return {"model": MODEL, "messages": messages, "temperature": temperature, "max_tokens": max_tokens,
                "reasoning": {"max_tokens": 0, "exclude": True}, "usage": {"include": True}}

    def cache_key(self, payload) -> str:
        return hashlib.sha1(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    async def call(self, messages: list[dict], *, stage: str, item_id: str, max_tokens: int = 300,
                   temperature: float = 0.0) -> dict:
        """Returns {'text','cost','cached','seconds','usage'}; raises BudgetExceeded before a paid call."""
        payload = self._payload(messages, max_tokens, temperature)
        key = self.cache_key(payload)
        cp = CACHE / f"{key}.json"
        if cp.exists():
            try:
                d = json.loads(cp.read_text())
                self.n_cached += 1
                return {**d, "cached": True}
            except json.JSONDecodeError:
                cp.unlink(missing_ok=True)
        if self.cum >= self.hard_cap:
            raise BudgetExceeded(f"cumulative ${self.cum:.3f} >= cap ${self.hard_cap}")
        async with self.sem:
            if self.cum >= self.hard_cap:
                raise BudgetExceeded(f"cumulative ${self.cum:.3f} >= cap ${self.hard_cap}")
            t0 = time.time()
            data = None
            for attempt in range(5):
                try:
                    async with self.session.post(URL, json=payload, headers={"Authorization": f"Bearer {self.key}"}) as r:
                        if r.status in (429, 500, 502, 503, 504, 408):
                            raise aiohttp.ClientResponseError(r.request_info, r.history, status=r.status)
                        data = await r.json(content_type=None)
                        if "choices" not in data:
                            raise ValueError(f"bad response {str(data)[:300]}")
                        break
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
                    wait = 2 ** attempt
                    logger.warning(f"LLM retry {attempt} ({stage}/{item_id}): {str(e)[:200]}; sleep {wait}s")
                    await asyncio.sleep(wait)
            if data is None or "choices" not in data:
                raise RuntimeError(f"LLM failed after retries for {item_id}")
            dt = time.time() - t0
        usage = data.get("usage", {}) or {}
        cost = float(usage.get("cost", 0) or 0)
        rt = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0) or 0
        self.reasoning_tokens += rt
        self.cum += cost
        self.n_calls += 1
        text = (data["choices"][0].get("message") or {}).get("content") or ""
        rec = {"ts": time.time(), "stage": stage, "item_id": item_id, "prompt_tokens": usage.get("prompt_tokens"),
               "completion_tokens": usage.get("completion_tokens"), "reasoning_tokens": rt, "cost": cost,
               "seconds": round(dt, 3)}
        with LEDGER.open("a") as f:
            f.write(json.dumps(rec) + "\n")
        out = {"text": text, "cost": cost, "seconds": dt, "usage": usage}
        cp.write_text(json.dumps(out, ensure_ascii=False))
        logger.debug(f"LLM {stage}/{item_id} ${cost:.5f} cum ${self.cum:.3f} | {text[:160]!r}")
        return {**out, "cached": False}
