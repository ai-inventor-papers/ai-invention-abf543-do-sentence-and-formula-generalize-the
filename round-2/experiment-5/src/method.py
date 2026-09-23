#!/usr/bin/env python3
"""Naming FOL errors and flagging bad gold — repaired monotonicity-signature metric (iter-2, experiment 5).

METHOD (sigfaith/): the iter-1 Arm-A signature (A3) with three screen-only repairs, then frozen:
  R1 renaming-robust, polarity-blind Hungarian aligner (lemma / WordNet / SBERT + arity term)   -> sigfaith/align2.py
  R2 text-side polarity chooser (rules / gemini probe variants) on MED/HELP-DEV + in-domain silver -> phase1_r2.py
  R3 decoder from the mismatch vector to the panel's error taxonomy (D_rule primary, D_lr secondary)-> sigfaith/decoder.py
BASELINES on identical items: B1 gemini-2.5-flash judge (iter-1 prompt), TJ typed gemini judge, A0 alignment-only,
  Ccov concept coverage, A3_iter1 / A0_iter1 (iter-1 aligner), parse rate, majority-class / prior-random type baselines.
VALIDATION (held-out, labels behind a hash-checked firewall): V1 type naming, V2 blind spots on real errors, V3 wrong-gold
  flagging, V4 polarity increment, criterion 5, V5 document conflation (exploratory), V6 EU-AI-Act transfer.

Pipeline:  python method.py --stages all      (or a comma list of stage names; every stage is resumable/cached)
Outputs:   method_out.json (exp_gen_sol_out) + results/{analysis,verdict,frozen_config,...}.json + figures/
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).resolve().parent
logger.remove()
logger.add(sys.stdout, level="INFO", format="{time:HH:mm:ss}|{level:<7}|{message}")
(ROOT / "logs").mkdir(exist_ok=True)
logger.add(ROOT / "logs" / "method.log", rotation="30 MB", level="DEBUG")
PY = sys.executable

STAGES = [
    ("prep", ["prep_data.py"]),
    ("regress", ["phase1_r1.py", "--stage", "regress"]),
    ("rename2", ["phase1_r1.py", "--stage", "rename2"]),
    ("screen_sigs", ["phase1_r1.py", "--stage", "sigs"]),
    ("r1_grid", ["phase1_r1.py", "--stage", "grid"]),
    ("r2_dev", ["phase1_r2.py", "--stage", "dev"]),
    ("r2_pilot", ["phase1_r2.py", "--stage", "pilot"]),
    ("r2_select", ["phase1_r2.py", "--stage", "select"]),
    ("r2_test", ["phase1_r2.py", "--stage", "test"]),
    ("r3", ["phase1_r3.py"]),
    ("freeze", ["freeze.py"]),
    ("llm_baselines", ["phase2_llm.py", "--methods", "B1,TJ"]),
    ("heldout_sigs", ["phase2_sigs.py", "--workers", "3"]),
    ("score", ["phase2_score.py"]),
    ("analyze", ["analyze.py"]),
    ("figures", ["make_figures.py"]),
    ("audit", ["audit_rederive.py"]),
    ("outputs", None),
]


def fmt(x) -> str:
    if x is None:
        return "NA"
    if isinstance(x, float):
        return f"{x:.6f}"
    return json.dumps(x, ensure_ascii=False) if isinstance(x, (list, dict)) else str(x)


def make_outputs():
    """method_out.json in exp_gen_sol_out format: one example per heldout_confirm row (6,300) with the method's and the
    baselines' predictions, plus one example per held-out gold (gold-audit block) and per transfer formula."""
    sys.path.insert(0, str(ROOT))
    from sigfaith import heldout_io
    labels = heldout_io.load_labels()
    inputs = {r["item_id"]: r for r in heldout_io.load_inputs(with_design=False)}
    rj = lambda p: [json.loads(l) for l in (ROOT / p).read_text().splitlines() if l.strip()]  # noqa: E731
    sc = {r["unit_id"]: r for r in rj("results/heldout_scores.jsonl")}
    gs = {r["unit_id"]: r for r in rj("results/gold_scores.jsonl")}
    llm = {}
    for r in rj("results/llm_baselines.jsonl"):
        if r.get("error") is None:
            llm[(r["unit_id"], r["method"])] = r
    ex_c = []
    for iid, inp in inputs.items():
        s, lab = sc[iid], labels[iid]
        b1, tj = llm.get((iid, "B1"), {}), llm.get((iid, "TJ"), {})
        ex_c.append({
            "input": json.dumps({"sentence": inp["sentence"], "candidate_fol": inp["candidate_fol"]}, ensure_ascii=False),
            "output": lab["output"],
            "metadata_item_id": iid, "metadata_sentence_id": inp["sentence_id"], "metadata_system": inp["system"],
            "metadata_corpus": inp["corpus"], "metadata_complexity_tercile": inp.get("complexity_tercile"),
            "metadata_label_source": lab.get("label_source"), "metadata_L3_primary_error": lab.get("L3_primary_error"),
            "metadata_L3_sampling_weight": lab.get("L3_sampling_weight"), "metadata_parse_ok_front": s["parse_ok_front"],
            "metadata_covered": s["covered"], "metadata_coverage": s["coverage"], "metadata_why_uncovered": s["why_uncovered"],
            "metadata_mismatches": s["mismatches"][:6], "metadata_seconds": s["seconds"],
            "predict_S_frozen": fmt(s["S_frozen"]), "predict_S_raw": fmt(s["S_raw"]), "predict_P": fmt(s["P_frozen"]),
            "predict_A0": fmt(s["A0_frozen"]), "predict_Ccov": fmt(s["Ccov_frozen"]),
            "predict_A3_iter1": fmt(s["A3_iter1"]), "predict_A0_iter1": fmt(s["A0_iter1"]),
            "predict_type_top1": s["type_top1"], "predict_types_top3": fmt(s["types_rule"][:3]),
            "predict_types_lr_top3": fmt(s["types_lr"][:3]), "predict_legacy_type": fmt(s["legacy_type_panel"]),
            "predict_B1": fmt(b1.get("p_faithful")), "predict_TJ": fmt(tj.get("p_faithful")),
            "predict_TJ_primary": fmt(tj.get("primary")), "predict_TJ_secondary": fmt(tj.get("secondary"))})
    ex_g = []
    seen = set()
    for iid, inp in inputs.items():
        sid = inp["sentence_id"]
        if sid in seen:
            continue
        seen.add(sid)
        g, lab = gs[f"{sid}:gold"], labels[iid]
        b1, tj = llm.get((f"{sid}:gold", "B1"), {}), llm.get((f"{sid}:gold", "TJ"), {})
        ex_g.append({
            "input": json.dumps({"sentence": inp["sentence"], "gold_fol": inp["gold_fol_original"]}, ensure_ascii=False),
            "output": "gold_wrong" if lab.get("gold_faithful_final") is False else
                      ("gold_ok" if lab.get("gold_faithful_final") else "unknown"),
            "metadata_sentence_id": sid, "metadata_corpus": inp["corpus"],
            "metadata_gold_audit_primary_error": lab.get("gold_audit_primary_error"),
            "metadata_paper_corrected_flag": lab.get("paper_corrected_flag"),
            "predict_flag_S": fmt(1 - g["S_frozen"]), "predict_flag_P": fmt(1 - g["P_frozen"]),
            "predict_flag_A0": fmt(1 - g["A0_frozen"]), "predict_flag_A3_iter1": fmt(1 - g["A3_iter1"]),
            "predict_type_top1": g["type_top1"], "predict_types_top3": fmt(g["types_rule"][:3]),
            "predict_flag_B1": fmt(None if b1.get("p_faithful") is None else 1 - b1["p_faithful"]),
            "predict_flag_TJ": fmt(None if tj.get("p_faithful") is None else 1 - tj["p_faithful"]),
            "predict_TJ_primary": fmt(tj.get("primary"))})
    ex_t = []
    for t in rj("results/transfer_scores.jsonl"):
        ex_t.append({"input": json.dumps({"unit_id": t["unit_id"]}), "output": "unlabeled",
                     "metadata_parse_ok_front": t["parse_ok_front"], "metadata_covered": t["covered"],
                     "predict_S_frozen": fmt(t["S_frozen"]), "predict_type_top1": t["type_top1"]})
    A = json.loads((ROOT / "results" / "analysis.json").read_text())
    V = json.loads((ROOT / "results" / "verdict.json").read_text())
    fz = json.loads((ROOT / "results" / "frozen_config.json").read_text())
    out = {"metadata": {"method_name": "sigfaith (repaired monotonicity signature: D_rule type namer + gold flagger)",
                        "description": __doc__, "verdict": V, "analysis": A,
                        "frozen_config": {k: v for k, v in fz.items() if k != "tables"},
                        "screen_tables": fz.get("tables"), "api_cost": A.get("api_cost")},
           "datasets": [{"dataset": "heldout_confirm_candidates", "examples": ex_c},
                        {"dataset": "heldout_golds_gold_audit", "examples": ex_g},
                        {"dataset": "transfer_eu_ai_act", "examples": ex_t}]}
    (ROOT / "method_out.json").write_text(json.dumps(out, ensure_ascii=False, default=float))
    logger.info(f"method_out.json: {len(ex_c)} candidates, {len(ex_g)} golds, {len(ex_t)} transfer rows")


@logger.catch(reraise=True)
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stages", default="all")
    a = ap.parse_args()
    names = [s for s, _ in STAGES] if a.stages == "all" else a.stages.split(",")
    for name, cmd in STAGES:
        if name not in names:
            continue
        logger.info(f"=== stage {name}")
        if cmd is None:
            make_outputs()
            continue
        r = subprocess.run([PY, *cmd], cwd=ROOT)
        if r.returncode != 0:
            raise RuntimeError(f"stage {name} failed ({r.returncode})")


if __name__ == "__main__":
    main()
