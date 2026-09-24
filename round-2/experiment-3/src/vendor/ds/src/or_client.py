"""Async OpenRouter client with a per-call cost ledger and a hard budget stop.

Every completed call appends one JSON line to cost_ledger.jsonl (workspace) AND to the per-task
ledger named by $AII_COST_LEDGER (same record shape as the aii-openrouter-llms skill), using the
provider-reported usage.cost (usage accounting enabled) or, if absent, tokens x catalog price.
Before each call the cumulative spend is compared with HARD_CAP_USD and with the phase cap.
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import time
from pathlib import Path

import aiohttp
from loguru import logger

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "cost_ledger.jsonl"
CATALOG = ROOT / "work" / "openrouter_catalog.json"
URL = "https://openrouter.ai/api/v1/chat/completions"
HARD_CAP_USD = 9.30


class BudgetExceeded(RuntimeError):
    pass


def _prices() -> dict:
    try:
        d = json.loads(CATALOG.read_text())
        return {m["id"]: (float(m["pricing"]["prompt"]), float(m["pricing"]["completion"])) for m in d}
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return {}


PRICES = _prices()


def ledger_total(phase: str | None = None) -> float:
    if not LEDGER.exists():
        return 0.0
    tot = 0.0
    for line in LEDGER.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if phase is None or r.get("phase") == phase:
            tot += r.get("cost_usd", 0.0)
    return tot


class Client:
    def __init__(self, phase: str, phase_cap: float, concurrency: int = 12, timeout: float = 120.0):
        self.phase, self.phase_cap = phase, phase_cap
        self.sem = asyncio.Semaphore(concurrency)
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.spent_total = ledger_total()
        self.spent_phase = ledger_total(phase)
        self.lock = asyncio.Lock()
        self.session: aiohttp.ClientSession | None = None
        self.n_calls = 0
        self.key = os.environ["OPENROUTER_API_KEY"]

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(timeout=self.timeout)
        return self

    async def __aexit__(self, *a):
        await self.session.close()

    def _cost(self, model: str, usage: dict) -> tuple[float, str]:
        c = usage.get("cost")
        if c is not None:
            return float(c), "usage.cost"
        pin, pout = PRICES.get(model, (0.0, 0.0))
        return usage.get("prompt_tokens", 0) * pin + usage.get("completion_tokens", 0) * pout, "catalog"

    async def _book(self, rec: dict) -> None:
        async with self.lock:
            self.spent_total += rec["cost_usd"]
            self.spent_phase += rec["cost_usd"]
            with open(LEDGER, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
            ext = os.environ.get("AII_COST_LEDGER")
            if ext:
                try:
                    with open(ext, "a", encoding="utf-8") as f:
                        f.write(json.dumps({"ts": rec["ts"], "tool": "openrouter", "cost_usd": rec["cost_usd"],
                                            "model": rec["model"], "phase": rec["phase"]}) + "\n")
                except OSError:
                    pass

    async def chat(self, model: str, messages: list[dict], *, tag: str = "", retries: int = 3,
                   **params) -> dict:
        """Returns {text, reasoning, usage, cost_usd, provider, seconds, error}."""
        if self.spent_total >= HARD_CAP_USD:
            raise BudgetExceeded(f"hard cap reached: ${self.spent_total:.3f}")
        if self.spent_phase >= self.phase_cap:
            raise BudgetExceeded(f"phase {self.phase} cap reached: ${self.spent_phase:.3f}")
        body = {"model": model, "messages": messages, "usage": {"include": True}, **params}
        headers = {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        last_err = ""
        async with self.sem:
            for attempt in range(retries):
                t0 = time.time()
                try:
                    async with self.session.post(URL, json=body, headers=headers) as resp:
                        txt = await resp.text()
                        if resp.status != 200:
                            last_err = f"HTTP {resp.status}: {txt[:300]}"
                            if resp.status in (400, 401, 402, 403, 404):
                                break
                            await asyncio.sleep(2 ** attempt + random.random())
                            continue
                        data = json.loads(txt)
                except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError) as e:
                    last_err = f"{type(e).__name__}: {str(e)[:200]}"
                    await asyncio.sleep(2 ** attempt + random.random())
                    continue
                if "error" in data and not data.get("choices"):
                    last_err = f"API error: {json.dumps(data['error'])[:300]}"
                    await asyncio.sleep(2 ** attempt + random.random())
                    continue
                usage = data.get("usage") or {}
                cost, src = self._cost(model, usage)
                ch = (data.get("choices") or [{}])[0]
                msg = ch.get("message") or {}
                rec = {"ts": time.time(), "phase": self.phase, "model": model, "tag": tag, "cost_usd": cost,
                       "cost_source": src, "prompt_tokens": usage.get("prompt_tokens"),
                       "completion_tokens": usage.get("completion_tokens"),
                       "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
                       "provider": data.get("provider")}
                await self._book(rec)
                self.n_calls += 1
                content = msg.get("content")
                if content is None:
                    content = ""
                return {"text": content, "reasoning": msg.get("reasoning"), "usage": usage, "cost_usd": cost,
                        "provider": data.get("provider"), "seconds": round(time.time() - t0, 2), "error": "",
                        "finish_reason": ch.get("finish_reason"), "model_returned": data.get("model")}
        logger.warning(f"call failed {model} {tag}: {last_err}")
        return {"text": None, "reasoning": None, "usage": {}, "cost_usd": 0.0, "provider": None, "seconds": None,
                "error": last_err, "finish_reason": None, "model_returned": None}
