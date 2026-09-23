#!/usr/bin/env python3
"""STEP 6: PHASE-2 SCORING with the FROZEN configuration (inputs only: heldout_io.load_inputs; no label is read).

S6.1 every heldout_confirm greedy row (6,300): S_frozen (A3, frozen aligner + text side), P_frozen (polarity-only
     subscore), A0_frozen (alignment-only), Ccov_frozen (concept coverage), A3_iter1 / A0_iter1 (iter-1 aligner +
     rules, same front-end parser), D_rule ranked types, D_lr types, legacy iter-1 type.
S6.2 gold_audit on each distinct held-out sentence's ORIGINAL gold (700) and on the 360 screen golds.
S6.3 text side: T0 zero-LLM unless the frozen side is a probe (then one probe call per sentence, cached).
Transfer: the EU-AI-Act pilot formulas (transfer_unlabeled).
Outputs: results/heldout_scores.jsonl, results/gold_scores.jsonl, results/transfer_scores.jsonl, results/phase2_meta.json
Usage: python phase2_score.py [--limit N]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import sigfaith  # noqa: E402
from sigfaith import core, heldout_io, textside  # noqa: E402
from align import align as legacy_align, is_optional  # noqa: E402  (legacy)

logger.remove()
logger.add(sys.stdout, level="INFO", format="{time:HH:mm:ss}|{level:<7}|{message}")
logger.add(ROOT / "logs" / "phase2_score.log", rotation="30 MB", level="DEBUG")
RES = ROOT / "results"


def legacy_scores(ex, p, S):
    """A3_iter1 / A0_iter1: iter-1 lexical aligner + rules marker (T0) through the same front-end."""
    if p is None or S is None or "error" in S:
        return 0.5, 0.5, None
    T = core.make_T(ex, core.choose_labels({int(k): v for k, v in ex["marker"].items()}, None, None, "T0"))
    optional = {c["cid"] for c in ex["concepts"] if is_optional(c)}
    A = legacy_align(p.preds, p.consts, ex["concepts"])
    r3 = core.signature_score_full(T, S, A, variant="A3", parse_ok=True, optional=optional)
    r0 = core.signature_score_full(T, S, A, variant="A0", parse_ok=True, optional=optional)
    return r3["score"], r0["score"], r3.get("legacy_type_panel")


def score_rows(units: list[dict], exs: dict, labels_of: dict, sigs: dict, fz: dict, aligner) -> list[dict]:
    out = []
    t0 = time.time()
    for i, u in enumerate(units):
        t1 = time.time()
        ex = exs[u["sentence"]]
        p, err = core.parse_front(u["fol"])
        S = sigs.get(u["fol"]) if p is not None else None
        r = sigfaith.score_parsed(ex, labels_of[u["sentence"]], p, S, fz, aligner)
        a3i, a0i, legacy_t = legacy_scores(ex, p, S)
        rec = {"unit_id": u["unit_id"], "kind": u["kind"], "sentence_id": u.get("sentence_id"),
               "parse_ok_front": p is not None, "parse_error": err or None,
               "sig_error": (S or {}).get("error") if p is not None else None,
               "S_frozen": r["score"], "S_raw": r["raw_score"], "covered": r["covered"], "coverage": r["coverage"],
               "why_uncovered": r.get("why_uncovered"), "P_frozen": r["P"], "A0_frozen": r["A0"],
               "Ccov_frozen": r["coverage"] if p is not None else 0.5,
               "A3_iter1": a3i, "A0_iter1": a0i, "legacy_type_panel": legacy_t,
               "types_rule": r["error_types"][:4], "type_top1": r["error_type_top1"], "types_lr": r["lr_types"][:4],
               "evidence": r.get("evidence"), "features": r.get("features"), "mismatches": r.get("mismatches", [])[:8],
               "n_coords": r.get("n_coords"), "sig_seconds": (S or {}).get("seconds"),
               "seconds": round(time.time() - t1 + ((S or {}).get("seconds") or 0.0), 4)}
        out.append(rec)
        if (i + 1) % 1000 == 0:
            logger.info(f"scored {i + 1}/{len(units)} ({time.time() - t0:.0f}s)")
    return out


@logger.catch(reraise=True)
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    fz = heldout_io.check_frozen()
    side = fz["text_side"]
    rows = heldout_io.load_inputs(with_design=False)
    if a.limit:
        rows = rows[: a.limit]
    sigs = json.loads((RES / "heldout_formula_sigs.json").read_text())
    screen = [json.loads(l) for l in (ROOT / "data" / "screen_l4.jsonl").read_text().splitlines()]
    transfer = [json.loads(l) for l in (ROOT / "data" / "transfer_inputs.jsonl").read_text().splitlines()]
    if a.limit:
        screen, transfer = screen[: a.limit], transfer[: a.limit]
    units_c = [{"unit_id": r["item_id"], "kind": "heldout_candidate", "sentence": r["sentence"],
                "fol": r["candidate_fol"], "sentence_id": r["sentence_id"]} for r in rows]
    seen, units_g = set(), []
    for r in rows:
        if r["sentence_id"] not in seen:
            seen.add(r["sentence_id"])
            units_g.append({"unit_id": f"{r['sentence_id']}:gold", "kind": "gold_heldout", "sentence": r["sentence"],
                            "fol": r["gold_fol_original"], "sentence_id": r["sentence_id"]})
    seen = set()
    for x in screen:
        if x["sentence_id"] not in seen:
            seen.add(x["sentence_id"])
            units_g.append({"unit_id": f"{x['sentence_id']}:screen_gold", "kind": "gold_screen",
                            "sentence": x["sentence"], "fol": x["gold_fol_original"], "sentence_id": x["sentence_id"]})
    units_t = [{"unit_id": x["item_id"], "kind": "transfer", "sentence": x["sentence"], "fol": x["candidate_fol"],
                "sentence_id": x.get("definition_id")} for x in transfer]
    sents = [u["sentence"] for u in units_c + units_g + units_t]
    t0 = time.time()
    exs = textside.extract_many(sents)
    logger.info(f"text extraction: {len(exs)} sentences in {time.time() - t0:.0f}s")
    probe_cost = 0.0
    probes = {}
    if side != "T0":
        need = sorted({u["sentence"] for u in units_c + units_g})
        probes = textside.probe_many(need, exs)
        probe_cost = sum(v.get("usd", 0.0) for v in probes.values())
        logger.info(f"probes: {len(probes)} sentences, ${probe_cost:.3f}")
    labels_of = {s: textside.labels_for(ex, side if side in ("T0", "T1a", "T1b", "T1c") else "T1b",
                                        probes.get(s)) for s, ex in exs.items()}
    aligner = sigfaith.aligner_from(fz["aligner"])
    missing = [u["fol"] for u in units_c + units_g + units_t if u["fol"] and u["fol"] not in sigs]
    if missing:
        logger.warning(f"{len(missing)} formulas lack precomputed signatures (they will be computed inline)")
        from solver_sig import signature
        for f in set(missing):
            p, _ = core.parse_front(f)
            if p is not None:
                try:
                    sigs[f] = signature(p.ast, N=3, timeout_ms=5000, with_rel=True, rel_max_unary=8)
                except Exception as e:  # noqa: BLE001
                    sigs[f] = {"error": repr(e)}
    for name, units in (("heldout_scores", units_c), ("gold_scores", units_g), ("transfer_scores", units_t)):
        t1 = time.time()
        out = score_rows(units, exs, labels_of, sigs, fz, aligner)
        for rec, u in zip(out, units):
            rec["text_side"] = side
            rec["probe_usd_sentence"] = probes.get(u["sentence"], {}).get("usd", 0.0) if probes else 0.0
        with (RES / f"{name}{'_mini' if a.limit else ''}.jsonl").open("w") as f:
            for rec in out:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        logger.info(f"{name}: {len(out)} rows in {time.time() - t1:.0f}s")
    meta = {"text_side": side, "probe_cost_usd": probe_cost, "n_candidates": len(units_c), "n_golds": len(units_g),
            "n_transfer": len(units_t), "seconds_total": round(time.time() - t0, 1),
            "probe_usd_by_sentence": {s: v.get("usd", 0.0) for s, v in probes.items()}}
    (RES / f"phase2_meta{'_mini' if a.limit else ''}.json").write_text(json.dumps(meta, indent=1))


if __name__ == "__main__":
    main()
