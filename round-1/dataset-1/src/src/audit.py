#!/usr/bin/env python3
"""STEP 7: L0 held-out gold audit + L4 screen gold audit with the cascaded family-disjoint panel.

Cascade: M2 and M3 vote on every gold; M1 votes where they disagree (or one failed to answer) plus
on a seeded random 20% (the full-panel subset used for Fleiss kappa). Final = M2 if M2 == M3 else
M1 (majority of available votes if a member failed).

When final = not faithful: corrected_fol is taken from M1, then M2, then M3; it must parse, be
satisfiable (bounded) and be non-equivalent (bounded countermodel, identity naming) to the
original. Otherwise gold_fol_audited = null.

Scope: all MALLS + FOLIO-train held-out sentences, a 30-sentence ProverQA spot check (escalated to
all ProverQA if > 10% is flagged), and the 360 screen sentences (L4).
Writes work/audit_results.json.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from collections import Counter
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from fol_equiv import bounded_check, sat_valid_check  # noqa: E402
from fol_parse import parse, signature, to_str  # noqa: E402
from or_client import BudgetExceeded, Client  # noqa: E402
from panel import GOLD_AUDIT_TMPL, cached_call, load_cache, norm_errs, yn  # noqa: E402

logger.remove()
logger.add(sys.stdout, level="INFO", format="{time:HH:mm:ss}|{level:<7}|{message}")
logger.add(ROOT / "logs" / "audit.log", rotation="30 MB", level="DEBUG")

CFG = json.loads((ROOT / "work" / "panel_config.json").read_text())["members"]


def vote_of(rec: dict) -> dict | None:
    p = rec.get("parsed")
    if not p:
        return None
    return {"faithful": yn(p.get("faithful")), "sentence_ambiguous": yn(p.get("sentence_ambiguous")),
            "error_types": norm_errs(p.get("error_types")), "primary_error": (norm_errs(p.get("primary_error")) or ["other"])[0],
            "explanation": str(p.get("explanation", ""))[:400], "corrected_fol": str(p.get("corrected_fol") or "")[:600],
            "model": rec["model"]}


def validate_correction(orig: str, corr: str) -> tuple[bool, str]:
    if not corr.strip():
        return False, "empty"
    pc = parse(corr)
    if not pc.ok:
        return False, "unparseable: " + pc.error[:80]
    sv = sat_valid_check(pc.ast)
    if not sv["satisfiable"]:
        return False, "unsat"
    po = parse(orig)
    if po.ok:
        _, c1 = signature(po.ast)
        _, c2 = signature(pc.ast)
        r, _ = bounded_check(pc.ast, po.ast, sorted(c1 | c2), {}, "equiv")
        if r == "none":
            return False, "equivalent_to_original"
    return True, "ok"


async def audit_item(client, cache, item: dict, full_panel: bool) -> dict:
    prompt = GOLD_AUDIT_TMPL.format(sentence=item["sentence"], formula=item["gold_fol_original"])
    key = f"l0|{item['audit_key']}"
    r2, r3 = await asyncio.gather(cached_call(client, cache, key, CFG["M2"], prompt, "M2"),
                                  cached_call(client, cache, key, CFG["M3"], prompt, "M3"))
    v2, v3 = vote_of(r2), vote_of(r3)
    votes = {"M2": v2, "M3": v3}
    f2 = v2["faithful"] if v2 else None
    f3 = v3["faithful"] if v3 else None
    need_m1 = full_panel or f2 is None or f3 is None or f2 != f3
    if need_m1:
        r1 = await cached_call(client, cache, key, CFG["M1"], prompt, "M1")
        votes["M1"] = vote_of(r1)
    f1 = votes["M1"]["faithful"] if votes.get("M1") else None
    if f2 is not None and f2 == f3:
        final = f2
        rule = "M2==M3"
    elif f1 is not None and (f2 is not None or f3 is not None):
        final = f1
        rule = "M1_tiebreak"
    else:
        avail = [f for f in (f1, f2, f3) if f is not None]
        final = Counter(avail).most_common(1)[0][0] if avail else None
        rule = "majority_available"
    amb = [v["sentence_ambiguous"] for v in votes.values() if v and v["sentence_ambiguous"] is not None]
    out = {"audit_key": item["audit_key"], "votes": votes, "gold_faithful_final": final, "cascade_rule": rule,
           "full_panel_subset": full_panel, "sentence_ambiguous": (sum(amb) > len(amb) / 2) if amb else None,
           "correction": None, "correction_status": None}
    if final is False:
        order = [m for m in ("M1", "M2", "M3") if votes.get(m) and votes[m]["faithful"] is False]
        tried = []
        for m in order:
            ok, why = validate_correction(item["gold_fol_original"], votes[m]["corrected_fol"])
            tried.append(f"{m}:{why}")
            if ok:
                out["correction"] = to_str(parse(votes[m]["corrected_fol"]).ast)
                out["correction_raw"] = votes[m]["corrected_fol"]
                out["correction_by"] = m
                break
        out["correction_status"] = ";".join(tried)
        # final error type = majority primary_error among unfaithful voters
        pe = Counter(votes[m]["primary_error"] for m in order)
        out["primary_error"] = pe.most_common(1)[0][0] if pe else None
    return out


@logger.catch(reraise=True)
async def amain(args) -> None:
    held = json.loads((ROOT / "work" / "heldout_sentences.json").read_text())
    screen = json.loads((ROOT / "work" / "screen_sentences.json").read_text())
    rng = random.Random(0)
    items = []
    for s in held:
        if s["corpus"] in ("malls", "folio"):
            items.append({"audit_key": f"heldout:{s['sentence_id']}", "sentence": s["sentence"],
                          "gold_fol_original": s["gold_fol_original"], "group": s["corpus"]})
    pq = sorted([s for s in held if s["corpus"] == "proverqa"], key=lambda s: s["sentence_id"])
    pq_spot = rng.sample(pq, 30)
    for s in pq_spot:
        items.append({"audit_key": f"heldout:{s['sentence_id']}", "sentence": s["sentence"],
                      "gold_fol_original": s["gold_fol_original"], "group": "proverqa_spot"})
    for s in screen:
        items.append({"audit_key": f"screen:{s['sentence_id']}", "sentence": s["sentence"],
                      "gold_fol_original": s["gold_fol_original"], "group": "screen"})
    if args.limit:
        items = items[: args.limit]
    for it in items:
        it["full_panel"] = rng.random() < 0.20
    cache = load_cache()
    results = {}
    logger.info(f"auditing {len(items)} golds")
    async with Client("gold_audit", phase_cap=args.cap, concurrency=args.concurrency) as client:
        async def run(batch):
            outs = await asyncio.gather(*[audit_item(client, cache, it, it["full_panel"]) for it in batch], return_exceptions=True)
            for it, o in zip(batch, outs):
                if isinstance(o, BudgetExceeded):
                    raise o
                if isinstance(o, Exception):
                    logger.error(f"audit failed {it['audit_key']}: {o!r}")
                    continue
                o["group"] = it["group"]
                results[it["audit_key"]] = o
        await run(items)
        spot = [results[f"heldout:{s['sentence_id']}"] for s in pq_spot if f"heldout:{s['sentence_id']}" in results]
        flagged = sum(r["gold_faithful_final"] is False for r in spot)
        rate = flagged / max(len(spot), 1)
        logger.info(f"ProverQA spot check flagged {flagged}/{len(spot)} = {rate:.2%}")
        escalated = False
        if rate > 0.10 and not args.limit:
            escalated = True
            rest = [s for s in pq if s not in pq_spot]
            extra = [{"audit_key": f"heldout:{s['sentence_id']}", "sentence": s["sentence"],
                      "gold_fol_original": s["gold_fol_original"], "group": "proverqa_escalated",
                      "full_panel": rng.random() < 0.20} for s in rest]
            logger.info(f"escalating ProverQA audit to all {len(pq)}")
            await run(extra)
        logger.info(f"audit spend ${client.spent_phase:.3f}; total ${client.spent_total:.3f}")
    meta = {"proverqa_spot_flagged": flagged, "proverqa_spot_n": len(spot), "proverqa_escalated": escalated,
            "n_items": len(results), "final_counts": dict(Counter(str(r["gold_faithful_final"]) for r in results.values())),
            "cascade_rules": dict(Counter(r["cascade_rule"] for r in results.values()))}
    logger.info(f"audit meta: {meta}")
    (ROOT / "work" / "audit_results.json").write_text(json.dumps({"meta": meta, "results": results}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--cap", type=float, default=3.2)
    ap.add_argument("--concurrency", type=int, default=24)
    asyncio.run(amain(ap.parse_args()))
