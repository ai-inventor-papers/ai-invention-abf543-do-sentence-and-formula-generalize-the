#!/usr/bin/env python3
"""STEP 10: export. results/fresh_set.jsonl (every fresh output with provenance and labels) and method_out.json
(exp_gen_sol_out: one example per fresh GREEDY output; output = final label; predict_* = metric scores)."""
from __future__ import annotations

import hashlib
import json
from collections import Counter

from loguru import logger

from aframe import load_frame
from common import RES, ROOT, WORK, assert_frozen, read_jsonl, setup_logging, write_jsonl

PRED = ["DC", "DC0", "DC_self", "LC_maj", "LC_ds_binary", "LC_onecoin", "VC", "B1", "B2", "B7", "B7_jacc", "B8",
        "B3nliL", "B3cosL", "TJ_L", "sp_net", "sp_incomparable", "sp_contradictory"]


@logger.catch(reraise=True)
def main() -> None:
    setup_logging("s13_export")
    fz = assert_frozen()
    rows, meta = load_frame()
    allrows = read_jsonl(WORK / "fresh_frame.jsonl")
    l1 = {x["key"]: x for x in read_jsonl(WORK / "l1_fresh.jsonl")}
    l0, l3 = meta["l0"], meta["l3"]
    sents = {s["sid"]: s for s in json.loads((RES / "fresh_sentences.json").read_text())}
    wmap = {r["item_id"]: r["w_panel"] for r in rows}
    fs = []
    for r in allrows:
        g = l0.get(r["sid"], {})
        p = l3.get(r["item_id"])
        st = l1.get(r["item_id"], {}).get("status")
        if p is not None and p["L3_majority"] is not None:
            label, src = ("faithful" if p["L3_majority"] else "unfaithful"), "panel3"
        elif st in ("equiv_proved", "equiv_bounded"):
            label, src = "faithful", "equiv_audited_gold"
        elif st in ("non_equiv", "non_equiv_no_bijection"):
            label, src = "unfaithful", "equiv_audited_gold"
        else:
            label, src = "unknown", "unknown"
        fs.append({**{k: r[k] for k in ("item_id", "sid", "sentence", "system", "model", "sample_idx", "fold", "raw_output",
                                         "cand", "parse_ok", "parse_ok_dataset_parser", "provider", "finish_reason",
                                         "gen_usd", "gen_seconds", "prompt_sha1", "corpus", "corpus_subset", "story_id",
                                         "source_id", "tercile", "n_tokens", "n_quantifiers", "nesting_depth",
                                         "n_conditions", "complexity_composite")},
                   "output": label, "label_source": src,
                   "gold_fol_original": sents[r["sid"]]["gold_fol_original"], "gold_fol_audited": g.get("gold_fol_audited"),
                   "gold_source": g.get("gold_source"), "gold_faithful_final": g.get("gold_faithful_final"),
                   "gold_audit_votes": g.get("votes"), "gold_audit_cascade_rule": g.get("cascade_rule"),
                   "gold_audit_primary_error": g.get("primary_error"), "sentence_ambiguous_L0": g.get("sentence_ambiguous"),
                   "L1_audited_status": st, "L1_entail_cand_to_gold": l1.get(r["item_id"], {}).get("entail_cand_to_gold"),
                   "L1_entail_gold_to_cand": l1.get(r["item_id"], {}).get("entail_gold_to_cand"),
                   "L3_selected": p is not None, "L3_votes": p["L3_votes"] if p else None,
                   "L3_majority": p["L3_majority"] if p else None, "L3_primary_error": p["L3_primary_error"] if p else None,
                   "L3_design_stratum": p["stratum"] if p else None, "L3_pair_kind": p["pair_kind"] if p else None,
                   "L3_weight_raked": wmap.get(r["item_id"]), "L3_design_weight": p["w_design"] if p else None,
                   "L3_full_panel_subset": p["full_panel_subset"] if p else None})
    write_jsonl(RES / "fresh_set.jsonl", fs)
    # method_out.json
    fsm = {x["item_id"]: x for x in fs}
    ex = []
    for r in rows:
        x = fsm[r["item_id"]]
        e = {"input": json.dumps({"sentence": r["sentence"], "candidate_fol": r["cand"]}, ensure_ascii=False),
             "output": x["output"]}
        for m in PRED:
            if m in r["S"]:
                e[f"predict_{m}"] = f"{r['S'][m]:.6f}"
        et = r["dc_extra"].get("error_type")
        e["predict_DC_error_type"] = str(et if r["parse_ok"] else "syntax_unparseable")
        for k in ("item_id", "sid", "system", "corpus", "tercile", "n_tokens", "n_quantifiers", "nesting_depth",
                  "n_conditions", "label_source", "L1_audited_status", "L3_primary_error", "L3_weight_raked",
                  "gold_source", "gold_fol_original", "gold_fol_audited", "parse_ok"):
            e[f"metadata_{k}"] = x.get(k)
        e["metadata_DC_covered"] = r["S"].get("DC__cov")
        e["metadata_DC_in_mode"] = r["dc_extra"].get("in_mode")
        e["metadata_DC_relations"] = r["dc_extra"].get("relations")
        ex.append(e)
    tests = json.loads((RES / "tests.json").read_text())
    out = {"metadata": {"method_name": "Directional Consensus (DC), freeze-then-confirm on fresh NL->FOL data",
                        "description": ("Gold-free, text-blind faithfulness score: reliability-weighted share of peer "
                                        "formalizations that are solver-equivalent under lexical-free alignment. Config "
                                        "frozen on 700 dev sentences before fresh labels; tested on 450 fresh sentences x "
                                        "9 systems under panel (L3) and audited-solver (L1) labels."),
                        "frozen_config": fz["config"], "frozen_config_sha256": (RES / "frozen_config.sha256").read_text().split()[0],
                        "decision": tests["decision"], "n_examples": len(ex),
                        "label_counts": dict(Counter(e["output"] for e in ex)),
                        "predict_fields": [f"predict_{m}" for m in PRED] + ["predict_DC_error_type"],
                        "workspace": str(ROOT)},
           "datasets": [{"dataset": "fresh_confirm_greedy_450x9", "examples": ex}]}
    (ROOT / "method_out.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    logger.info(f"exported {len(fs)} fresh rows, {len(ex)} method_out examples")


if __name__ == "__main__":
    main()
