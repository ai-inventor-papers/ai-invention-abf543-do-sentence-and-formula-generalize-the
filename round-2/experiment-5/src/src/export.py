#!/usr/bin/env python3
"""S7: results/scores.jsonl (every greedy/pilot candidate x every metric, with missing-value reasons) and
method_out.json (exp_gen_sol_out): dataset 'legal_panel_labelled' = one example per panel-labelled candidate
(input = {sentence, candidate_fol}, output = panel label, predict_* = metric scores as strings) and dataset
'legal_all_candidates' = every scored candidate (output = panel label or 'unlabelled')."""
from __future__ import annotations

import json
from collections import defaultdict

from common import RES, ROOT, WORK, jdump, jload, read_jsonl, setup_logger, write_jsonl

logger = setup_logger("export")
METRICS = ["DC", "DC_noL3", "DC_fp", "DC_unw", "DC_lone", "DC_arb", "DS_dc", "LC_maj", "DS_bin", "VC", "B1", "B1plus",
           "B3nli", "B3cos", "B2", "B7", "B7_arity_self", "B7_arity_doc", "B7_joint", "B7_jacc", "B8", "DC_placebo"]


def reason(c: dict, m: str, row: dict) -> str | None:
    if row.get(m) is not None:
        return None
    if m in ("B1plus", "B3nli", "B3cos"):
        return "not_in_panel_sample"
    if m in ("B8", "B7_jacc") or (m == "DC_lone" and c["frame"] == "system"):
        return "not_sampled_system"
    if m == "DS_bin" and c["frame"] == "pilot":
        return "pilot_not_a_rater_in_round2_definition"
    if m == "DC_placebo":
        return "placebo_only_on_panel_items"
    return "not_computed"


def main() -> None:
    sents = {s["sentence_id"]: s for s in jload(WORK / "sentences.json")}
    cands = [c for c in read_jsonl(WORK / "candidates.jsonl") if c["frame"] == "pilot" or c["sample_idx"] == 0]
    dc = {r["cand_id"]: r for r in read_jsonl(RES / "dc_scores_frozen.jsonl")}
    extra = defaultdict(dict)
    for f in ("b1.jsonl", "b1plus.jsonl", "b3.jsonl", "struct.jsonl", "dc_arb.jsonl", "placebo_scores.jsonl"):
        for r in read_jsonl(WORK / f):
            extra[r["key"]].update({k: v for k, v in r.items() if k != "key"})
    ex = {r["item_id"]: r for r in read_jsonl(RES / "exception_set.jsonl")}
    rows = []
    for c in cands:
        r = {"cand_id": c["cand_id"], "sentence_id": c["sentence_id"], "system": c["system"], "frame": c["frame"],
             "parse_ok": c["parse_ok"], "marker_bin": sents[c["sentence_id"]]["marker_bin"]}
        d = dc.get(c["cand_id"], {})
        for k, v in d.items():
            if k not in r:
                r[k] = v
        r.update(extra.get(c["cand_id"], {}))
        if not c["parse_ok"] and r.get("DC_unw") is None:  # contract rule for unparseable candidates (as in analysis)
            r["DC_unw"], r["DC_unw_cov"] = 0.5, 0
        e = ex.get(c["cand_id"])
        r["panel_label"] = e["label"] if e else None
        r["panel_weight"] = e["weight"] if e else None
        r["missing_reasons"] = {m: reason(c, m, r) for m in METRICS if r.get(m) is None}
        rows.append(r)
    write_jsonl(RES / "scores.jsonl", rows)
    n_lab = sum(r["panel_label"] is not None for r in rows)
    logger.info(f"scores.jsonl {len(rows)} rows, {n_lab} labelled")

    def example(r):
        c = next(x for x in cands if x["cand_id"] == r["cand_id"]) if False else None  # noqa: F841
        s = sents[r["sentence_id"]]
        e = ex.get(r["cand_id"]) or {}
        out = {"input": json.dumps({"sentence": s["sentence"], "candidate_fol": fol_of[r["cand_id"]]}, ensure_ascii=False),
               "output": r["panel_label"] or "unlabelled"}
        for m in METRICS:
            if r.get(m) is not None:
                out[f"predict_{m}"] = f"{float(r[m]):.6f}"
        if r.get("DC_error_type") is not None:
            out["predict_DC_error_type"] = str(r["DC_error_type"])
            out["predict_DC_exception_involved"] = str(bool(r.get("DC_exception_involved")))
        meta = {"cand_id": r["cand_id"], "sentence_id": r["sentence_id"], "system": r["system"], "frame": r["frame"],
                "parse_ok": r["parse_ok"], "marker_bin": s["marker_bin"], "n_markers": s["n_markers"],
                "exception_markers": s["exception_markers"], "n_tokens": s["n_tokens"], "act": s["act"], "article": s["article"],
                "source": s["source"], "licence": s["licence"], "url": s["url"], "has_cross_reference": s["has_cross_reference"],
                "panel_weight": r["panel_weight"], "label_source": "panel3_nogold" if r["panel_label"] else "unlabelled",
                "panel_primary_error": e.get("primary_error"), "panel_exception_involved": e.get("exception_involved"),
                "panel_stratum": e.get("stratum"), "DC_coverage": r.get("DC_cov"), "DC_rel_to_mode": r.get("DC_rel_to_mode"),
                "missing_reasons": r["missing_reasons"]}
        for k, v in meta.items():
            out[f"metadata_{k}"] = v
        return out
    fol_of = {c["cand_id"]: (c["fol"] or c.get("raw_output") or "") for c in cands}
    lab = [example(r) for r in rows if r["panel_label"] is not None]
    allc = [example(r) for r in rows]
    tests = jload(RES / "tests.json")
    mo = {"metadata": {"method_name": "Directional consensus (DC) contract v1 on long legal definitions",
                       "label_source": "panel-only (sentence-only no-gold 3-member panel); secondary transfer",
                       "X1": {k: tests["X1"].get(k) for k in ("auroc_w", "ci95", "lb90", "pass")},
                       "X2": {k: tests["X2"].get(k) for k in ("delta", "ci95", "lb90", "pass")},
                       "workspace": str(ROOT)},
          "datasets": [{"dataset": "legal_panel_labelled", "examples": lab},
                       {"dataset": "legal_all_candidates", "examples": allc}]}
    (ROOT / "method_out.json").write_text(json.dumps(mo, ensure_ascii=False, indent=1))
    logger.info(f"method_out.json: labelled {len(lab)}, all {len(allc)}")


if __name__ == "__main__":
    main()
