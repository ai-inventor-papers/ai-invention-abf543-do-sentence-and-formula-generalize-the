#!/usr/bin/env python3
"""Complexity-stratified reliability (terciles, n_conditions bins, n_quantifiers, nesting depth), system-level Kendall
tau (9 systems; underpowered, not a gate), per-pair cost by level / timeouts / UNKNOWN (T1 summary).
-> results/complexity_system_cost.json"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from dc.common import RES, WORK, jdump, rj  # noqa: E402
from dc import stats as ST  # noqa: E402
from m0_anchor import load_all, strata  # noqa: E402

M = ["DC", "DC_L2w", "S0_L1", "LC_maj_star", "LC_maj", "LC_ds_binary", "B1", "B3nli", "VC", "B7"]


def block(R, yk, wk, nb=1000):
    out = {"n": len(R)}
    if len(R) < 20 or len({r[yk] for r in R}) < 2:
        return out
    for m in M:
        Rm = [r for r in R if r["m"].get(m) is not None]
        if len(Rm) < 20 or len({r[yk] for r in Rm}) < 2:
            continue
        out[m] = ST.auc_ci([r[yk] for r in Rm], [r["m"][m] for r in Rm], [r[wk] for r in Rm] if wk else None,
                           [r["sentence_id"] for r in Rm], strata(Rm), n=nb)
        out[m].pop("n_sentences", None)
    if "DC_L2w" in out and "B1" in out:
        Rm = [r for r in R if r["m"].get("B1") is not None]
        out["DC_L2w_minus_B1"] = ST.paired_delta([r[yk] for r in Rm], [r["m"]["DC_L2w"] for r in Rm], [r["m"]["B1"] for r in Rm],
                                                 [r[wk] for r in Rm] if wk else None, [r["sentence_id"] for r in Rm], strata(Rm), n=nb)
    return out


def main():
    G, sc = load_all()
    res = {"complexity": {}}
    for lab, yk, wk in (("panel", "y_panel", "w"), ("solver", "y_solver", None)):
        R = [r for r in G if r[yk] is not None]
        c = {}
        for t in ("bottom", "middle", "top"):
            c[f"tercile={t}"] = block([r for r in R if r["complexity_tercile"] == t], yk, wk)
        for lo, hi, nm in ((0, 1, "0"), (1, 2, "1"), (2, 3, "2"), (3, 99, ">=3")):
            c[f"n_conditions={nm}"] = block([r for r in R if lo <= (r["n_conditions"] or 0) < hi], yk, wk)
        for lo, hi, nm in ((0, 2, "<=1"), (2, 3, "2"), (3, 99, ">=3")):
            c[f"n_quantifiers={nm}"] = block([r for r in R if lo <= (r["n_quantifiers"] or 0) < hi], yk, wk)
        for lo, hi, nm in ((0, 4, "<=3"), (4, 6, "4-5"), (6, 99, ">=6")):
            c[f"nesting_depth={nm}"] = block([r for r in R if lo <= (r["nesting_depth"] or 0) < hi], yk, wk)
        for lo, hi, nm in ((0, 12, "<12"), (12, 20, "12-19"), (20, 999, ">=20")):
            c[f"n_tokens={nm}"] = block([r for r in R if lo <= (r["n_tokens"] or 0) < hi], yk, wk)
        res["complexity"][lab] = c
    # coverage by tercile (unparseable counted)
    cov = {}
    for t in ("bottom", "middle", "top"):
        R = [r for r in G if r["complexity_tercile"] == t]
        cov[t] = {"n": len(R), "DC_covered": float(np.mean([bool(sc[r["item_id"]]["DC_cov"]) for r in R])),
                  "self_unparseable": int(sum(not sc[r["item_id"]]["coverage"]["self_parseable"] for r in R))}
    res["coverage_by_tercile"] = cov
    # system level
    from scipy.stats import kendalltau
    sysm = defaultdict(lambda: defaultdict(list))
    for r in G:
        for m in M:
            if r["m"].get(m) is not None:
                sysm[r["system"]][m].append(r["m"][m])
    acc_p, acc_s = {}, {}
    for s in sysm:
        P = [r for r in G if r["system"] == s and r["y_panel"] is not None]
        S = [r for r in G if r["system"] == s and r["y_solver"] is not None]
        acc_p[s] = sum(r["y_panel"] * r["w"] for r in P) / sum(r["w"] for r in P)
        acc_s[s] = float(np.mean([r["y_solver"] for r in S]))
    ks = sorted(sysm)
    sl = {}
    for m in M:
        mv = [float(np.mean(sysm[k][m])) for k in ks]
        sl[m] = {"tau_panel": float(kendalltau(mv, [acc_p[k] for k in ks]).statistic),
                 "tau_solver": float(kendalltau(mv, [acc_s[k] for k in ks]).statistic),
                 "system_means": dict(zip(ks, mv))}
    res["system_level"] = {"n_systems": len(ks), "panel_accuracy": acc_p, "solver_accuracy": acc_s, "metrics": sl,
                           "note": "9 systems: underpowered, not a gate"}
    # cost
    recs = rj(WORK / "pairs_dc.jsonl")
    sec = defaultdict(list)
    for r in recs:
        if r.get("seconds") is not None:
            sec[str(r.get("level"))].append(r["seconds"])
    res["pair_cost"] = {"n_pairs_total": len(recs),
                        "seconds_by_best_level": {k: {"n": len(v), "mean": float(np.mean(v)), "p95": float(np.percentile(v, 95)),
                                                      "max": float(np.max(v))} for k, v in sec.items()},
                        "timeout_rate": float(np.mean([bool(r.get("timeout")) for r in recs])),
                        "unknown_rate": float(np.mean([r.get("rel") == "UNKNOWN" for r in recs])),
                        "error_rate": float(np.mean(["error" in r for r in recs])),
                        "rel_distribution": dict(Counter(r.get("rel") for r in recs)),
                        "method_distribution": dict(Counter(r.get("method") for r in recs))}
    dcs = [sc[r["item_id"]].get("seconds") or 0 for r in G]
    res["dc_cost_per_item"] = {"mean_seconds_scoring_given_cached_pairs": float(np.mean(dcs)),
                               "pair_seconds_per_item_estimate": float(np.mean([v for vs in sec.values() for v in vs]) * 8),
                               "usd": 0.0,
                               "B1_usd_per_item_reference": 2.9e-5}
    jdump(res, RES / "complexity_system_cost.json")
    for lab in ("panel", "solver"):
        for k in ("tercile=bottom", "tercile=middle", "tercile=top", "n_conditions=0", "n_conditions=1", "n_conditions=2", "n_conditions=>=3"):
            b = res["complexity"][lab][k]
            print(lab, k, b["n"], {m: round(b[m]["auroc"], 3) for m in ("DC", "DC_L2w", "LC_maj", "LC_ds_binary", "B1") if m in b and b[m].get("auroc")})
    print({m: round(v["tau_panel"], 2) for m, v in sl.items()})


if __name__ == "__main__":
    main()
