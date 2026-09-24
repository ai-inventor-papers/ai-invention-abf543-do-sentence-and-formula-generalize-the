"""S7 TRANSFER (qualitative): A3 on the user's EU-AI-Act pilot formulas (transfer_unlabeled, 367 rows).

Reports coverage (unparseable counted), the distribution of A3-predicted error types, the same distribution on held-out
panel-UNFAITHFUL items and the panel's own L3_primary_error mix (weighted), plus a descriptive type-agreement table on
panel-unfaithful items. Split by grounded / ungrounded pilot condition. No accuracy claim on the pilot (unlabeled).
LC is not applicable (a single system per definition)."""
from __future__ import annotations

from collections import Counter, defaultdict

import numpy as np
from loguru import logger

from common import RES, WORK, jdump, load_frame, read_jsonl

A3_TO_PANEL = {"swapped_args": "argument_swap", "conflation": "conflation", "dropped_condition": "dropped_condition",
               "added_condition": "added_condition", "wrong_split": "wrong_split",
               "reversed_implication": "implication_direction_or_only", "quantifier": "quantifier_forall_exists",
               "negation_polarity": "negation_polarity", "connective_andor": "connective_and_or", "other": "other",
               "none": "none"}


def _dist(c: Counter) -> dict:
    n = sum(c.values())
    return {k: {"n": v, "share": v / n} for k, v in c.most_common()} if n else {}


def run() -> dict:
    rows = load_frame()
    by_id = {r["item_id"]: r for r in rows}
    A = {}
    for r in read_jsonl(WORK / "armA_scores.jsonl"):
        A.setdefault(r["key"], {})[r["metric"]] = r
    T = [r for r in rows if r["fold"] == "transfer_unlabeled"]
    out = {"n_rows": len(T), "LC": "not applicable (one system per definition; latent-class agreement needs >= 2 systems)"}
    for cond in ("all", "grounded", "ungrounded"):
        sub = [r for r in T if cond == "all" or r.get("condition") == cond]
        sc = [A.get(r["item_id"], {}).get("A3") for r in sub]
        cov = [x for x in sc if x and x["covered"]]
        types = Counter(x["error_type_pred"] for x in cov)
        why = Counter((x or {}).get("why_uncovered") or "missing" for x in sc if not (x and x["covered"]))
        out[cond] = {"n": len(sub), "dataset_parse_ok": sum(bool(r["parse_ok"]) for r in sub),
                     "A3_covered": len(cov), "A3_coverage": len(cov) / max(1, len(sub)),
                     "uncovered_reasons": dict(why),
                     "mean_A3_score_covered": float(np.mean([x["score"] for x in cov])) if cov else None,
                     "A3_pred_type_dist_covered": _dist(types),
                     "A3_pred_type_dist_flagged_only": _dist(Counter(x["error_type_pred"] for x in cov
                                                                     if x["error_type_pred"] != "none"))}
    # held-out panel-unfaithful comparison
    G = [r for r in rows if r["fold"] == "heldout_confirm" and r["label_source"] == "panel3"]
    unf = [r for r in G if r["output"] == "unfaithful"]
    w = {r["item_id"]: r["L3_sampling_weight"] for r in G}
    a3t = Counter()
    panel_t = defaultdict(float)
    agree = Counter()
    for r in unf:
        x = A.get(r["item_id"], {}).get("A3")
        panel_t[r["L3_primary_error"]] += w[r["item_id"]]
        if x and x["covered"]:
            a3t[x["error_type_pred"]] += 1
            agree["n"] += 1
            agree["same"] += A3_TO_PANEL.get(x["error_type_pred"]) == r["L3_primary_error"]
            agree["flagged"] += x["error_type_pred"] != "none"
    tot = sum(panel_t.values())
    out["heldout_panel_unfaithful"] = {
        "n": len(unf), "A3_pred_type_dist_covered": _dist(a3t),
        "panel_primary_error_mix_weighted": {k: v / tot for k, v in sorted(panel_t.items(), key=lambda kv: -kv[1])},
        "A3_type_equals_panel_primary_share": agree["same"] / max(1, agree["n"]),
        "A3_flags_any_error_share": agree["flagged"] / max(1, agree["n"]), "n_covered": agree["n"],
        "note": "descriptive; A3 types mapped to the panel taxonomy with A3_TO_PANEL"}
    fa = [A.get(r["item_id"], {}).get("A3") for r in G if r["output"] == "faithful"]
    fa = [x for x in fa if x and x["covered"]]
    out["heldout_panel_faithful_A3_flag_rate"] = sum(x["error_type_pred"] != "none" for x in fa) / max(1, len(fa))
    out["A3_to_panel_type_map"] = A3_TO_PANEL
    jdump(out, RES / "transfer_A3.json")
    logger.info(f"transfer: coverage {out['all']['A3_coverage']:.3f}; types {list(out['all']['A3_pred_type_dist_covered'])[:5]}")
    return out
