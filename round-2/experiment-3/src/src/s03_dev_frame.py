#!/usr/bin/env python3
"""Build work/dev_frame.jsonl: one row per DEV output (700 sentences x 9 greedy + 2 x 5 samples) with the fields
the DC freeze and the dev ladder need (candidate string, parse status, panel / solver labels, weights, strata),
plus work/dev_baselines.json (round-2 frozen dev scores, reused at $0 from heldout_scores.jsonl).
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict

from loguru import logger

from common import R2, WORK, load_dev_rows, read_jsonl, setup_logging, write_jsonl
from dc import canon, parse_fol

FAITHFUL = {"equiv_proved", "equiv_bounded"}
UNFAITHFUL = {"non_equiv", "non_equiv_no_bijection"}


def slabel(status: str | None):
    if status in FAITHFUL:
        return 1
    if status in UNFAITHFUL:
        return 0
    return None


@logger.catch(reraise=True)
def main() -> None:
    setup_logging("s03_dev_frame")
    rows = load_dev_rows(("heldout_confirm", "heldout_samples", "contamination"))
    logger.info(f"loaded {len(rows)} dev rows {Counter(r['metadata_fold'] for r in rows)}")
    out = []
    for r in rows:
        inp = json.loads(r["input"])
        cand = inp.get("candidate_fol") or ""
        ast = parse_fol(cand)
        fold = r["metadata_fold"]
        rec = {"item_id": r["metadata_item_id"], "fold": fold, "sid": r["metadata_sentence_id"],
               "sentence": inp["sentence"], "system": r.get("metadata_system"), "sample_idx": r.get("metadata_sample_idx", 0),
               "cand": cand, "parse_ok": ast is not None, "canon": canon(ast) if ast is not None else None,
               "ds_parse_ok": r.get("metadata_parse_ok"), "output": r["output"], "label_source": r.get("metadata_label_source"),
               "y_panel": ({"yes": 1, "no": 0}.get(r.get("metadata_L3_majority")) if r.get("metadata_label_source") == "panel3" else None),
               "L3_majority": r.get("metadata_L3_majority"), "L3_primary_error": r.get("metadata_L3_primary_error"),
               "w_panel": r.get("metadata_L3_sampling_weight"), "L3_poststratum": r.get("metadata_L3_poststratum"),
               "L1_audited_status": r.get("metadata_L1_audited_status"), "L1_orig_status": r.get("metadata_L1_orig_status"),
               "y_solver": slabel(r.get("metadata_L1_audited_status")),
               "corpus": r.get("metadata_corpus"), "tercile": r.get("metadata_complexity_tercile"),
               "n_tokens": r.get("metadata_n_tokens"), "n_quantifiers": r.get("metadata_n_quantifiers"),
               "nesting_depth": r.get("metadata_nesting_depth"), "n_conditions": r.get("metadata_n_conditions"),
               "gold_fol_original": r.get("metadata_gold_fol_original"), "gold_fol_audited": r.get("metadata_gold_fol_audited"),
               "gold_faithful_final": r.get("metadata_gold_faithful_final"), "sentence_ambiguous": r.get("metadata_sentence_ambiguous"),
               "gold_source": r.get("metadata_gold_source"), "stratum_p_faithful": r.get("metadata_L3_stratum_p_faithful")}
        if fold == "contamination":
            rec["original_item_id"] = r.get("metadata_original_item_id")
            rec["original_sentence"] = r.get("metadata_original_sentence")
            rec["rename_incomplete"] = r.get("metadata_contamination_rename_incomplete")
        out.append(rec)
    # the panel label field: L3_majority may be 'faithful'/'unfaithful' or yes/no; derive from output when panel3
    for rec in out:
        if rec["label_source"] == "panel3":
            rec["y_panel"] = {"faithful": 1, "unfaithful": 0}.get(rec["output"])
    write_jsonl(WORK / "dev_frame.jsonl", out)
    G = [r for r in out if r["fold"] == "heldout_confirm"]
    logger.info(f"dev greedy {len(G)}; parse_ok {sum(r['parse_ok'] for r in G)}; panel items "
                f"{sum(r['y_panel'] is not None for r in G)}; solver-labelled {sum(r['y_solver'] is not None for r in G)}")
    # round-2 frozen dev scores (item_id / metric / score / covered) reused at $0
    keep = {"B1", "B1plus", "B2", "B3nli", "B3cos", "B7", "B8", "LC_maj", "LC_onecoin", "LC_ds_binary", "A3",
            "LC_within", "B7_jacc"}
    base = defaultdict(dict)
    n = 0
    with open(R2 / "results" / "heldout_scores.jsonl", encoding="utf-8") as f:
        for line in f:
            x = json.loads(line)
            if x["metric"] in keep:
                base[x["item_id"]][x["metric"]] = [x["score"], x["covered"]]
                n += 1
    (WORK / "dev_baselines.json").write_text(json.dumps(base))
    logger.info(f"dev baselines: {n} scores for {len(base)} items")


if __name__ == "__main__":
    main()
