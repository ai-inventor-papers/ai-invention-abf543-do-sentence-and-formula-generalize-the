#!/usr/bin/env python3
"""Extra secondary analyses -> results/analysis_extra.json.

1. Per-error-type sensitivity (panel): weighted AUROC of faithful vs unfaithful-of-type-X items; n < 30 descriptive.
2. Within-sentence paired AUROC (panel): P(score(faithful) > score(unfaithful)) over same-sentence pairs.
3. Complexity strata under both labels: n_tokens, n_quantifiers, nesting_depth, n_conditions bins.
4. System-wise AUROC under solver labels, and own-family AUROC of the Qwen substitutes (qwen-2.5-7b rows).
5. DC score distribution by relation profile (how often DC = 0 / 1 / in between) and DC vs DC0 on unparseable items.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict

import numpy as np
from loguru import logger

from aframe import boot, ci_auc, load_frame, sc, wauc
from common import RES, SYSTEMS, setup_logging

METS = ["DC", "DC0", "LC_maj", "LC_ds_binary", "B1", "B3nliL", "VC", "TJ_L"]


def auc_b(rows, m, label, nboot=1000):
    y = np.array([r["y_panel"] if label == "panel" else r["y_solver"] for r in rows], float)
    if len(set(y)) < 2 or len(rows) < 10:
        return None
    s = np.array([sc(r, m) for r in rows], float)
    w = np.array([r["w_panel"] for r in rows], float) if label == "panel" else None
    return {**ci_auc(y, s, w, boot(rows, n=nboot, seed=3)), "n": len(rows), "n_pos": int(y.sum())}


@logger.catch(reraise=True)
def main() -> None:
    setup_logging("s12b_extra")
    rows, meta = load_frame()
    P = [r for r in rows if r["y_panel"] is not None]
    S = [r for r in rows if r["y_solver"] is not None]
    out = {}
    # 1 per error type
    F = [r for r in P if r["y_panel"] == 1]
    types = Counter(r["panel_primary"] for r in P if r["y_panel"] == 0)
    per = {}
    for t, n in types.most_common():
        R = F + [r for r in P if r["y_panel"] == 0 and r["panel_primary"] == t]
        per[t] = {"n_unfaithful": n, "status": "descriptive (n<30)" if n < 30 else "ok",
                  **{m: (auc_b(R, m, "panel", 500) or {}).get("auc") for m in METS}}
    out["per_error_type_panel"] = per
    # 2 within-sentence paired AUROC
    by = defaultdict(list)
    for r in P:
        by[r["sid"]].append(r)
    pairs = [(a, b) for L in by.values() for a in L for b in L if a["y_panel"] == 1 and b["y_panel"] == 0]
    ws = {"n_pairs": len(pairs), "n_sentences": len({a["sid"] for a, _ in pairs})}
    rng = np.random.default_rng(0)
    for m in METS:
        v = np.array([1.0 if sc(a, m) > sc(b, m) else (0.5 if sc(a, m) == sc(b, m) else 0.0) for a, b in pairs])
        if len(v):
            bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(1000)]
            ws[m] = {"p": float(v.mean()), "ci95": [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))]}
    out["within_sentence_paired_panel"] = ws
    # 3 complexity strata
    bins = {"n_tokens": [(0, 12, "<=12"), (13, 20, "13-20"), (21, 999, ">20")],
            "n_quantifiers": [(0, 0, "0"), (1, 1, "1"), (2, 99, "2+")],
            "nesting_depth": [(0, 3, "<=3"), (4, 5, "4-5"), (6, 99, "6+")],
            "n_conditions": [(0, 1, "0-1"), (2, 2, "2"), (3, 99, "3+")]}
    comp = {}
    for lab, R in (("panel", P), ("solver", S)):
        d = {}
        for feat, bl in bins.items():
            for lo, hi, nm in bl:
                sub = [r for r in R if lo <= (r.get(feat) or 0) <= hi]
                d[f"{feat}={nm}"] = {m: auc_b(sub, m, lab, 300) for m in ("DC", "B1", "LC_ds_binary", "LC_maj")}
        comp[lab] = d
    out["complexity_bins"] = comp
    # 4 per system (solver labels) and own-family check of the Qwen substitutes
    out["per_system_solver"] = {s: {m: (auc_b([r for r in S if r["system"] == s], m, "solver", 300) or {}).get("auc")
                                    for m in ("DC", "B1", "LC_ds_binary")} for s in SYSTEMS}
    q = [r for r in P if r["system"] == "qwen-2.5-7b"]
    nq = [r for r in P if r["system"] != "qwen-2.5-7b"]
    out["qwen_substitute_own_family"] = {m: {"own_family": (auc_b(q, m, "panel", 200) or {}).get("auc"),
                                             "others": (auc_b(nq, m, "panel", 200) or {}).get("auc"), "n_own": len(q)}
                                         for m in ("B3nliL", "TJ_L")}
    # 5 DC distribution
    dc = [sc(r, "DC") for r in rows if r["S"].get("DC__cov")]
    out["DC_distribution"] = {"share_0": float(np.mean([x == 0 for x in dc])), "share_1": float(np.mean([x == 1 for x in dc])),
                              "share_mid": float(np.mean([0 < x < 1 for x in dc])), "n_covered": len(dc),
                              "uncovered_reasons": dict(Counter(("unparseable" if not r["parse_ok"] else "fewer_than_2_covered_peers")
                                                                for r in rows if not r["S"].get("DC__cov")))}
    unp = [r for r in P if not r["parse_ok"]]
    out["unparseable_panel_items"] = {"n": len(unp), "panel_faithful": sum(r["y_panel"] for r in unp)}
    (RES / "analysis_extra.json").write_text(json.dumps(out, indent=1, default=str))
    logger.info(json.dumps({"per_type": per, "within": ws}, default=str)[:2500])


if __name__ == "__main__":
    main()
