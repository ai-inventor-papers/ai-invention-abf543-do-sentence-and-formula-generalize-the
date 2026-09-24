#!/usr/bin/env python3
"""STEP 6: panel calibration gate C0 on 40 known-label items (ProverQA dev-EASY, never held-out).

Each member judges every item with the single-formula gold-audit prompt (the L0 prompt), and the
25 mutant/rewrite items as blinded A/B pairs with their source gold (the L3 prompt). Gate: >=80%
accuracy on the 40 single-formula judgments; a failing member is swapped for its fallback and
re-tested once. Writes work/calibration_results.json and work/panel_config.json.
"""
from __future__ import annotations

import asyncio
import json
import random
import sys
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from or_client import Client  # noqa: E402
from panel import ADJ_TMPL, FALLBACKS, GOLD_AUDIT_TMPL, MEMBERS, cached_call, load_cache, save_prompts, yn  # noqa: E402

logger.remove()
logger.add(sys.stdout, level="INFO", format="{time:HH:mm:ss}|{level:<7}|{message}")
logger.add(ROOT / "logs" / "calibrate.log", rotation="30 MB", level="DEBUG")


async def run_member(client, cache, member: str, cfg: dict, items: list[dict]) -> dict:
    rng = random.Random(0)
    audit_tasks = [cached_call(client, cache, f"cal_audit|{it['cal_id']}", cfg,
                               GOLD_AUDIT_TMPL.format(sentence=it["sentence"], formula=it["formula"]), member)
                   for it in items]
    pairs = []
    for it in items:
        if it["kind"] == "gold":
            continue
        gold_first = rng.random() < 0.5
        a, b = (it["gold"], it["formula"]) if gold_first else (it["formula"], it["gold"])
        pairs.append((it, gold_first, cached_call(client, cache, f"cal_adj|{it['cal_id']}", cfg,
                                                  ADJ_TMPL.format(sentence=it["sentence"], a=a, b=b), member)))
    audits = await asyncio.gather(*audit_tasks)
    adjs = await asyncio.gather(*[p[2] for p in pairs])
    correct, n, per = 0, 0, []
    for it, rec in zip(items, audits):
        v = yn((rec.get("parsed") or {}).get("faithful"))
        ok = v is not None and v == it["label_faithful"]
        correct += ok
        n += 1
        per.append({"cal_id": it["cal_id"], "kind": it["kind"], "op": it["op"], "label": it["label_faithful"], "vote": v})
    adj_correct, adj_n, same_ok = 0, 0, 0
    for (it, gold_first, _), rec in zip(pairs, adjs):
        p = rec.get("parsed") or {}
        g_key, c_key = ("A", "B") if gold_first else ("B", "A")
        gv = yn((p.get(g_key) or {}).get("faithful"))
        cv = yn((p.get(c_key) or {}).get("faithful"))
        adj_correct += (gv is True) + (cv == it["label_faithful"])
        adj_n += 2
        same_ok += yn(p.get("same_meaning")) == (it["kind"] == "rewrite")
    return {"member": member, "model": cfg["model"], "audit_accuracy": correct / n, "n_audit": n,
            "adj_accuracy": adj_correct / max(adj_n, 1), "n_adj_judgments": adj_n,
            "same_meaning_accuracy": same_ok / max(len(pairs), 1), "per_item": per}


@logger.catch(reraise=True)
async def amain() -> None:
    save_prompts()
    items = json.loads((ROOT / "work" / "calibration_set.json").read_text())
    cache = load_cache()
    results, config = {}, {}
    async with Client("calibration", phase_cap=1.1, concurrency=16) as client:
        outs = await asyncio.gather(*[run_member(client, cache, m, MEMBERS[m], items) for m in MEMBERS])
        for m, o in zip(MEMBERS, outs):
            logger.info(f"{m} {o['model']} audit_acc={o['audit_accuracy']:.3f} adj_acc={o['adj_accuracy']:.3f} same={o['same_meaning_accuracy']:.3f}")
            results[m] = [o]
            config[m] = MEMBERS[m] if o["audit_accuracy"] >= 0.8 else None
        for m in MEMBERS:
            if config[m] is None:
                o = await run_member(client, cache, m, FALLBACKS[m], items)
                logger.info(f"{m} FALLBACK {o['model']} audit_acc={o['audit_accuracy']:.3f}")
                results[m].append(o)
                config[m] = FALLBACKS[m] if o["audit_accuracy"] >= 0.8 else None
        logger.info(f"calibration spend ${client.spent_phase:.3f}; total ${client.spent_total:.3f}")
    failed = [m for m, c in config.items() if c is None]
    (ROOT / "work" / "calibration_results.json").write_text(json.dumps(results, indent=1))
    (ROOT / "work" / "panel_config.json").write_text(json.dumps({"members": config, "failed_members": failed}, indent=1))
    logger.info(f"panel config: { {m: (c or {}).get('model') for m, c in config.items()} } failed={failed}")


if __name__ == "__main__":
    asyncio.run(amain())
