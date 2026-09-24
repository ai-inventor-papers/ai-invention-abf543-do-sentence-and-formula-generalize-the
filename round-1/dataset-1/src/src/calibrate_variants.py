#!/usr/bin/env python3
"""Calibration of fallback / cheaper member configs (same frozen prompts, same 40 items)."""
import asyncio, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from calibrate import run_member  # noqa: E402
from or_client import Client  # noqa: E402
from panel import load_cache  # noqa: E402

VARIANTS = {
    "M1_fallback_haiku": ("M1", {"model": "anthropic/claude-haiku-4.5", "params": {"temperature": 0.0, "max_tokens": 900}}),
    "M3_nothink": ("M3", {"model": "z-ai/glm-4.6", "params": {"temperature": 0.0, "max_tokens": 900, "reasoning": {"enabled": False}}}),
}


async def amain(names):
    items = json.loads((ROOT / "work" / "calibration_set.json").read_text())
    cache = load_cache()
    out = {}
    async with Client("calibration", phase_cap=1.0, concurrency=16) as client:
        res = await asyncio.gather(*[run_member(client, cache, VARIANTS[n][0] + "v" if n == "M3_nothink" else VARIANTS[n][0], VARIANTS[n][1], items) for n in names])
        for n, r in zip(names, res):
            r["config"] = VARIANTS[n][1]
            out[n] = r
            print(n, r["model"], "audit", round(r["audit_accuracy"], 3), "adj", round(r["adj_accuracy"], 3), "same", round(r["same_meaning_accuracy"], 3))
        print("calibration phase spend", round(client.spent_phase, 3), "total", round(client.spent_total, 3))
    p = ROOT / "work" / "calibration_variants.json"
    old = json.loads(p.read_text()) if p.exists() else {}
    old.update(out)
    p.write_text(json.dumps(old, indent=1))

asyncio.run(amain(sys.argv[1:] or list(VARIANTS)))
