#!/usr/bin/env python3
"""Entry point + export. Stages (each resumable, see README):
  prep -> m6 -> m0 pairs -> m0 score -> m0 anchor/freeze -> prereg -> m1 -> m1 B1 -> m2 -> m3 -> m4 -> m5/m6/m7 ->
  extra -> audit -> verdicts -> export.
`uv run method.py export` writes method_out.json (exp_gen_sol_out): one example per dev greedy row (DC and variants,
baselines), the M1 constructed probes (fold m1_probe) and the M7 gold rows. `uv run method.py all` runs everything."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from loguru import logger  # noqa: E402

logger.remove()
logger.add(sys.stdout, level="INFO", format="{time:HH:mm:ss}|{level:<7}|{message}")
logger.add(str(ROOT / "logs" / "method.log"), rotation="30 MB", level="DEBUG")
PY = sys.executable
STAGES = [["scripts/prep.py"], ["scripts/m6_record.py"], ["scripts/m0_pairs.py", "all"], ["scripts/m0_score.py", "all"],
          ["scripts/m0_anchor.py"], ["scripts/prereg.py"], ["scripts/m1_build_score.py", "all"], ["scripts/m1_b1.py"],
          ["scripts/m1_analyze.py"], ["scripts/m2_invariance.py", "1000"], ["scripts/m2_diagnose.py"], ["scripts/m3_boundary.py"],
          ["scripts/m3_analyze.py"], ["scripts/m4_placebo.py"], ["scripts/m5_m6_m7.py"], ["scripts/extra_analyses.py"],
          ["audit_rederive.py"], ["scripts/verdicts.py"]]


def s(x):
    return "" if x is None else (f"{x:.6f}" if isinstance(x, float) else str(x))


@logger.catch(reraise=True)
def export():
    from dc.common import WORK, RES, EXP3, load_frame, rj
    from m0_anchor import load_all
    G, sc = load_all()
    arb = {}
    m3 = json.loads((RES / "m3_boundary.json").read_text())
    arb_status = "RUN" if m3.get("n_calls_arbiter") else "NOT_RUN: OpenRouter 403 aii_run_budget_exhausted (DC_arb = DC)"
    ex1 = []
    for r in G:
        x = sc[r["item_id"]]
        e = {"input": json.dumps({"sentence": r["sentence"], "candidate_fol": r["candidate_fol"]}, ensure_ascii=False),
             "output": r["output"]}
        for m in ("DC", "DC_L2w", "DC_lex", "S0_L1", "S1_L2", "S2_L3", "LC_maj_star", "VC"):
            e[f"predict_{m}"] = s(x.get(m))
        e["predict_DC_arb"] = s(x.get("DC"))
        for m in ("B1", "LC_maj", "LC_onecoin", "LC_ds_binary", "B3nli", "B3cos", "B7", "B8"):
            if r["m"].get(m) is not None:
                e[f"predict_baseline_{m}"] = s(r["m"][m])
        e.update({"metadata_fold": "heldout_confirm_dev", "metadata_item_id": r["item_id"], "metadata_sentence_id": r["sentence_id"],
                  "metadata_system": r["system"], "metadata_corpus": r["corpus"], "metadata_complexity_tercile": r["complexity_tercile"],
                  "metadata_n_conditions": r["n_conditions"], "metadata_label_source": r["label_source"],
                  "metadata_L3_sampling_weight": r["L3_sampling_weight"], "metadata_L3_primary_error": r["L3_primary_error"],
                  "metadata_DC_covered": x.get("DC_cov"), "metadata_error_type": x.get("error_type"),
                  "metadata_rel_to_mode": x.get("rel_to_mode"), "metadata_in_mode": x.get("in_mode"),
                  "metadata_strength_profile": x.get("strength_profile"), "metadata_coverage": x.get("coverage"),
                  "metadata_peer_relations": {p["peer"]: p["rel"] for p in x.get("per_peer", [])},
                  "metadata_seconds": x.get("seconds"), "metadata_usd": 0.0, "metadata_arbiter_status": arb_status})
        ex1.append(e)
    b1 = {(q["sid"], q["arm"], q["kind"], q["op"]): q for q in rj(WORK / "m1_b1.jsonl")}
    ex2 = []
    for p in rj(WORK / "m1_probes.jsonl"):
        e = {"input": json.dumps({"sentence": p["sentence"], "candidate_fol": p["fol"]}, ensure_ascii=False),
             "output": "faithful" if p["kind"] == "F" else "unfaithful"}
        for m in ("DC", "DC_L2w", "S0_L1", "S2_L3", "LC_maj_star", "VC"):
            e[f"predict_{m}"] = s(p.get(m))
        q = b1.get((p["sid"], p["arm"], p["kind"], p["op"]))
        if q:
            e["predict_baseline_B1"] = s(q["B1"])
        e.update({"metadata_fold": "m1_probe", "metadata_sentence_id": p["sid"], "metadata_arm": p["arm"],
                  "metadata_kind": p["kind"], "metadata_operator": p["op"], "metadata_iso_L1": p.get("iso_L1"),
                  "metadata_fresh_pred": p.get("fresh_pred"), "metadata_type_contract": p.get("type_contract"),
                  "metadata_type_repair": p.get("type_repair"), "metadata_corpus": p.get("corpus"),
                  "metadata_peer_relations": p.get("rels")})
        ex2.append(e)
    gd = {x["item_id"]: x for x in rj(WORK / "gold_dc_scores.jsonl")}
    ex3 = []
    seen = set()
    for r in G:
        if r["sentence_id"] in seen:
            continue
        seen.add(r["sentence_id"])
        g = gd.get(f"{r['sentence_id']}:GOLD")
        if g is None or r.get("gold_faithful_final") is None:
            continue
        ex3.append({"input": json.dumps({"sentence": r["sentence"], "candidate_fol": r["gold_fol_original"]}, ensure_ascii=False),
                    "output": "faithful" if r["gold_faithful_final"] else "unfaithful",
                    "predict_DC_gold_as_peer": s(g["DC"]), "predict_S0_L1_gold": s(g["S0_L1"]),
                    "metadata_fold": "m7_gold", "metadata_sentence_id": r["sentence_id"], "metadata_corpus": r["corpus"],
                    "metadata_DC_covered": g.get("DC_cov"), "metadata_error_type_vs_mode": g.get("error_type"),
                    "metadata_gold_audit_primary_error": r.get("gold_audit_primary_error")})
    out = {"metadata": {"method_name": "Directional Consensus (DC)",
                        "description": "Gold-free NL->FOL faithfulness: reliability-weighted share of peer formalisations "
                                       "logically EQUIVALENT to the candidate up to a lexical-free (granularity-aware) "
                                       "alignment; stress-tested on constructed truth (DEV set, not confirmatory)",
                        "frozen_dc_config_sha256": (ROOT / "frozen_dc_config.sha256").read_text().strip(),
                        "labels": "output = dataset label (panel3 for 609 rows, else audited-solver; unknown kept)",
                        "arbiter_status": arb_status,
                        "predictions": "predict_* are scores in [0,1] as strings; predict_baseline_* are frozen exp3 baselines"},
           "datasets": [{"dataset": "heldout_confirm_dev", "examples": ex1}, {"dataset": "m1_constructed_probes", "examples": ex2},
                        {"dataset": "m7_gold_as_peer", "examples": ex3}]}
    (ROOT / "method_out.json").write_text(json.dumps(out, ensure_ascii=False))
    logger.info(f"method_out.json: {len(ex1)} + {len(ex2)} + {len(ex3)} examples")


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "export"
    if arg == "all":
        for st in STAGES:
            logger.info(f"stage {' '.join(st)}")
            subprocess.run([PY, *st], cwd=ROOT, check=True)
    export()


if __name__ == "__main__":
    main()
