#!/usr/bin/env python3
"""STEP 8: PRE-REGISTERED tests on the FRESH set only, each under PANEL (weighted) and AUDITED-SOLVER labels.
2,000 sentence-cluster draws within corpus x tercile strata; one-sided alpha 0.05 = the 5th percentile.

T1 base = [B1, B2, B3nli, B3cos, B7]; oof_stack (5 sentence-grouped folds x 5 shuffles, L2 logistic C=1,
   standardised); Delta = AUROC(oof[base + DC]) - AUROC(oof[base]); PASS if LB > 0. Placebo: DC shuffled within
   strata. B3 exists on the panel items only (budget fallback F2(2)), so T1 runs on the panel frame under both
   labels; a sensitivity arm uses base [B1, B2, B7] on ALL solver-labelled rows.
T2 paired AUROC differences: DC - LC_maj (LB > 0), DC - LC_ds_binary (point > 0), DC - VC (LB > 0).
T3 (panel only; panel-unfaithful items, weighted): PASS_a top1 >= majority + 0.10 AND >= TJ_top1 - 0.05;
   PASS_b recall >= 0.5 for added_condition, dropped_condition, quantifier_forall_exists (n >= 30 each);
   PASS_c within-sentence AUROC over (faithful, unfaithful-of-type-X) pairs, X in {dropped_condition,
   implication_direction_or_only}: DC > B1 (paired bootstrap LB > 0). n < 30 -> 'underpowered = not passed'.
T4 per system (gpt-4.1-mini, llama-3.1-8b): AUROC(DC_self) - AUROC(B8) LB > 0; oof Delta of [base + DC_self]
   over base within the system's rows LB > 0 (panel: base [B1,B2,B3nli,B3cos,B7] on panel rows; solver: base
   [B1,B2,B7] on all rows, B3 being panel-only).
A test PASSES only if it passes under both labels (T3: panel only); otherwise 'label-dependent' or 'fail'.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict

import numpy as np
from loguru import logger

from aframe import NBOOT, boot, ci_auc, ci_diff, load_frame, sc, wauc
from common import RES, SAMPLE_SYSTEMS, assert_frozen, setup_logging
from dcscore import r2stats

BASE = ["B1", "B2", "B3nliL", "B3cosL", "B7"]  # D-KEY: local B3 substitute (pre-registered 04:27 UTC, before any test)
BASE_S = ["B1", "B2", "B7"]


def placebo_shuffle(rows, metric, seed=0):
    rng = np.random.default_rng(seed)
    by = defaultdict(list)
    for i, r in enumerate(rows):
        by[f"{r['corpus']}|{r['tercile']}"].append(i)
    s = np.array([sc(r, metric) for r in rows], dtype=float)
    out = s.copy()
    for idx in by.values():
        out[idx] = s[rng.permutation(idx)]
    return out


def stack_delta(rows, label, base, add, B, extra_cols=None):
    y = np.array([r["y_panel"] if label == "panel" else r["y_solver"] for r in rows], dtype=int)
    w = np.array([r["w_panel"] for r in rows], dtype=float) if label == "panel" else None
    sids = np.array([r["sid"] for r in rows])
    Xb = np.array([[sc(r, m) for m in base] for r in rows], dtype=float)
    Xa = np.column_stack([Xb] + [np.array([sc(r, m) for r in rows], dtype=float) for m in add] +
                         ([extra_cols] if extra_cols is not None else []))
    pb = r2stats.oof_stack(Xb, y, sids, w)
    pa = r2stats.oof_stack(Xa, y, sids, w)
    d = ci_diff(rows, pa, pb, y.astype(float), w, B)
    d.update({"auc_base": wauc(y, pb, w), "auc_base_plus": wauc(y, pa, w), "n": len(rows),
              "n_pos": int(y.sum()), "n_neg": int((1 - y).sum())})
    return d, pa, pb


def irls_oof(X, y, sids, w, k=5, seed=999, lam=1.0, iters=50):
    """Second implementation for the T1 re-derivation: numpy IRLS logistic (L2 lam), other fold seed."""
    y = y.astype(float)
    w = np.ones(len(y)) if w is None else w
    uniq = np.unique(sids)
    rng = np.random.default_rng(seed)
    perm = rng.permutation(uniq)
    fold = {s: i % k for i, s in enumerate(perm)}
    f = np.array([fold[s] for s in sids])
    p = np.zeros(len(y))
    for j in range(k):
        tr, te = f != j, f == j
        mu, sd = X[tr].mean(0), X[tr].std(0) + 1e-9
        Z = np.column_stack([np.ones(tr.sum()), (X[tr] - mu) / sd])
        beta = np.zeros(Z.shape[1])
        for _ in range(iters):
            eta = Z @ beta
            pr = 1 / (1 + np.exp(-eta))
            W = w[tr] * pr * (1 - pr) + 1e-9
            g = Z.T @ (w[tr] * (y[tr] - pr)) - lam * np.r_[0, beta[1:]]
            H = (Z.T * W) @ Z + lam * np.diag(np.r_[0, np.ones(Z.shape[1] - 1)])
            beta = beta + np.linalg.solve(H, g)
        Zt = np.column_stack([np.ones(te.sum()), (X[te] - mu) / sd])
        p[te] = 1 / (1 + np.exp(-(Zt @ beta)))
    return p


def verdict(res_p: bool | None, res_s: bool | None) -> str:
    if res_p is None and res_s is None:
        return "not_run"
    if res_p and res_s:
        return "PASS"
    if res_p or res_s:
        return "label-dependent"
    return "fail"


@logger.catch(reraise=True)
def main() -> None:
    setup_logging("s11_tests")
    fz = assert_frozen()
    rows, meta = load_frame()
    P = [r for r in rows if r["y_panel"] is not None]
    S = [r for r in rows if r["y_solver"] is not None]
    PS = [r for r in P if r["y_solver"] is not None]
    logger.info(f"panel items {len(P)} (Kish {meta['weights'].get('kish_n_eff')}); solver rows {len(S)}; panel&solver {len(PS)}")
    BP, BS, BPS = boot(P), boot(S), boot(PS)
    out = {"frozen_config": fz["config_name"], "n_panel": len(P), "n_solver": len(S), "n_panel_with_solver": len(PS),
           "weights": meta["weights"], "n_boot": NBOOT,
           "label_counts": {"panel": dict(Counter(r["y_panel"] for r in P)), "solver": dict(Counter(r["y_solver"] for r in S)),
                            "solver_unknown": dict(Counter(r["S_status"] for r in rows if r["y_solver"] is None)),
                            "panel_unknown_majority": sum(1 for v in meta["l3"].values() if v["L3_majority"] is None)}}
    # ---------------- headline AUROCs
    metrics = ["DC", "DC0", "LC_maj", "LC_ds_binary", "LC_onecoin", "LC_huiwalter", "VC", "B1", "B2", "B3nliL", "B3cosL",
               "B7", "TJ_L", "sp_net",
               "B1plus", "DC_self", "B8"]
    head = {}
    for m in metrics:
        for lab, R, B in (("panel", P, BP), ("solver", S, BS)):
            rr = [r for r in R if m in r["S"]]
            if len(rr) < 20:
                continue
            y, s, w = (np.array([r["y_panel"] if lab == "panel" else r["y_solver"] for r in rr], float),
                       np.array([sc(r, m) for r in rr], float),
                       np.array([r["w_panel"] for r in rr], float) if lab == "panel" else None)
            Bm = boot(rr, n=1000, seed=1)
            head[f"{m}|{lab}"] = {**ci_auc(y, s, w, Bm), "n": len(rr),
                                  "coverage": float(np.mean([r["S"].get(m + "__cov", False) for r in rr]))}
    out["auroc"] = head
    # ---------------- T1
    t1 = {}
    for lab, R, B in (("panel", P, BP), ("solver", PS, BPS)):
        d, pa, pb = stack_delta(R, lab, BASE, ["DC"], B)
        pl = placebo_shuffle(R, "DC")
        dpl, _, _ = stack_delta(R, lab, BASE, [], B, extra_cols=pl)
        # independent re-derivation (numpy IRLS, other fold seed)
        y = np.array([r["y_panel"] if lab == "panel" else r["y_solver"] for r in R], dtype=int)
        w = np.array([r["w_panel"] for r in R], float) if lab == "panel" else None
        sids = np.array([r["sid"] for r in R])
        Xb = np.array([[sc(r, m) for m in BASE] for r in R], float)
        Xa = np.column_stack([Xb, [sc(r, "DC") for r in R]])
        d2 = wauc(y, irls_oof(Xa, y, sids, w), w) - wauc(y, irls_oof(Xb, y, sids, w), w)
        t1[lab] = {**d, "pass": d["lb_one_sided_5"] > 0, "placebo": dpl, "rederive_irls_delta": d2,
                   "rederive_abs_diff": abs(d2 - d["point"])}
    # sensitivity arms: base without B3 (every piece frozen and API-scored): panel frame, and ALL solver rows
    d, _, _ = stack_delta(P, "panel", BASE_S, ["DC"], BP)
    t1["panel_base_noB3"] = {**d, "pass": d["lb_one_sided_5"] > 0}
    d, _, _ = stack_delta(S, "solver", BASE_S, ["DC"], BS)
    t1["solver_all_rows_base_noB3"] = {**d, "pass": d["lb_one_sided_5"] > 0}
    t1["verdict"] = verdict(t1["panel"]["pass"], t1["solver"]["pass"])
    out["T1"] = t1
    logger.info(f"T1: {json.dumps({k: (v['point'], v['lb_one_sided_5']) for k, v in t1.items() if isinstance(v, dict)})}")
    # ---------------- T2
    t2 = {}
    for lab, R, B in (("panel", P, BP), ("solver", S, BS)):
        y = np.array([r["y_panel"] if lab == "panel" else r["y_solver"] for r in R], float)
        w = np.array([r["w_panel"] for r in R], float) if lab == "panel" else None
        s_dc = np.array([sc(r, "DC") for r in R], float)
        res = {}
        for m in ("LC_maj", "LC_ds_binary", "VC"):
            res[m] = ci_diff(R, s_dc, np.array([sc(r, m) for r in R], float), y, w, B)
        ok = (res["LC_maj"]["lb_one_sided_5"] > 0 and res["LC_ds_binary"]["point"] > 0 and res["VC"]["lb_one_sided_5"] > 0)
        t2[lab] = {**res, "pass": ok,
                   "sub": {"vs_LC_maj_LB>0": res["LC_maj"]["lb_one_sided_5"] > 0,
                           "vs_LC_ds_binary_point>0": res["LC_ds_binary"]["point"] > 0,
                           "vs_VC_LB>0": res["VC"]["lb_one_sided_5"] > 0}}
    t2["verdict"] = verdict(t2["panel"]["pass"], t2["solver"]["pass"])
    out["T2"] = t2
    logger.info(f"T2: panel {t2['panel']['sub']} solver {t2['solver']['sub']}")
    # ---------------- T3 (panel only)
    U = [r for r in P if r["y_panel"] == 0]

    def dc_type(r):
        if not r["parse_ok"]:
            return "syntax_unparseable"
        return r["dc_extra"].get("error_type") or "other"
    wU = np.array([r["w_panel"] for r in U], float)
    pt = [r["panel_primary"] for r in U]
    top1 = float(np.sum(wU * np.array([dc_type(r) == p for r, p in zip(U, pt)])) / wU.sum()) if len(U) else None
    wt = defaultdict(float)
    for r, p in zip(U, pt):
        wt[p] += r["w_panel"]
    maj_type = max(wt, key=wt.get) if wt else None
    majority = wt[maj_type] / wU.sum() if wt else None
    tj_types = {}
    from common import WORK, read_jsonl
    for x in read_jsonl(WORK / "tjL_fresh.jsonl"):
        tj_types[x["item_id"]] = x.get("primary") if x.get("faithful") is False else ("none" if x.get("faithful") else None)
    tj_top1 = float(np.sum(wU * np.array([tj_types.get(r["item_id"]) == p for r, p in zip(U, pt)])) / wU.sum()) if len(U) else None
    pass_a = (top1 is not None and majority is not None and tj_top1 is not None and
              top1 >= majority + 0.10 and top1 >= tj_top1 - 0.05)
    recall = {}
    for cls in ("added_condition", "dropped_condition", "quantifier_forall_exists"):
        idx = [i for i, p in enumerate(pt) if p == cls]
        n = len(idx)
        rec = float(np.sum(wU[idx] * np.array([dc_type(U[i]) == cls for i in idx])) / wU[idx].sum()) if n else None
        recall[cls] = {"n": n, "recall_weighted": rec, "tj_recall_weighted": (float(np.sum(wU[idx] * np.array(
            [tj_types.get(U[i]["item_id"]) == cls for i in idx])) / wU[idx].sum()) if n else None),
            "status": "underpowered" if n < 30 else ("pass" if rec >= 0.5 else "fail")}
    pass_b = all(v["status"] == "pass" for v in recall.values())
    # PASS_c within-sentence pairs (faithful, unfaithful-of-type-X) among panel items of the same sentence
    by_sid = defaultdict(list)
    for r in P:
        by_sid[r["sid"]].append(r)
    pc = {}
    for X in ("dropped_condition", "implication_direction_or_only"):
        pairs = []
        for sid, L in by_sid.items():
            f = [r for r in L if r["y_panel"] == 1]
            u = [r for r in L if r["y_panel"] == 0 and r["panel_primary"] == X]
            pairs += [(a, b) for a in f for b in u]

        def pw(m, prs):
            v = [1.0 if sc(a, m) > sc(b, m) else (0.5 if sc(a, m) == sc(b, m) else 0.0) for a, b in prs]
            return float(np.mean(v)) if v else None
        n = len(pairs)
        res = {"n_pairs": n, "DC": pw("DC", pairs), "B1": pw("B1", pairs)}
        if n >= 1:
            rng = np.random.default_rng(0)
            ds = []
            for _ in range(NBOOT):
                bs = [pairs[i] for i in rng.integers(0, n, n)]
                ds.append(pw("DC", bs) - pw("B1", bs))
            res["diff_lb_5"] = float(np.percentile(ds, 5))
        res["status"] = "underpowered" if n < 30 else ("pass" if res.get("diff_lb_5", -1) > 0 else "fail")
        pc[X] = res
    pass_c = all(v["status"] == "pass" for v in pc.values())
    conf = defaultdict(Counter)
    for r, p in zip(U, pt):
        conf[p][dc_type(r)] += 1
    out["T3"] = {"n_unfaithful_panel": len(U), "top1_DC": top1, "majority_type": maj_type, "majority_share": majority,
                 "TJ_top1": tj_top1, "pass_a": pass_a, "recall": recall, "pass_b": pass_b, "within_sentence": pc,
                 "pass_c": pass_c, "confusion_panel_vs_DC": {k: dict(v) for k, v in conf.items()},
                 "verdict": "PASS" if (pass_a and pass_b and pass_c) else "fail",
                 "note": "panel-only test; classes with n<30 are 'underpowered = not passed'"}
    logger.info(f"T3: top1 {top1} majority {majority} ({maj_type}) TJ {tj_top1}; recall {recall}; pc {pc}")
    # ---------------- T4
    t4 = {}
    for sysn in SAMPLE_SYSTEMS:
        res = {}
        for lab, R in (("panel", [r for r in P if r["system"] == sysn]), ("solver", [r for r in S if r["system"] == sysn])):
            if len(R) < 20 or len({r["y_panel"] if lab == "panel" else r["y_solver"] for r in R}) < 2:
                res[lab] = {"n": len(R), "status": "underpowered"}
                continue
            B = boot(R, n=NBOOT, seed=2)
            y = np.array([r["y_panel"] if lab == "panel" else r["y_solver"] for r in R], float)
            w = np.array([r["w_panel"] for r in R], float) if lab == "panel" else None
            a = ci_diff(R, np.array([sc(r, "DC_self") for r in R], float), np.array([sc(r, "B8") for r in R], float), y, w, B)
            base = BASE if lab == "panel" else BASE_S
            d, _, _ = stack_delta(R, lab, base, ["DC_self"], B)
            res[lab] = {"n": len(R), "DC_self_minus_B8": a, "stack_delta": d,
                        "pass": a["lb_one_sided_5"] > 0 and d["lb_one_sided_5"] > 0,
                        "note": "underpowered (n<150)" if len(R) < 150 else ""}
        pp = res.get("panel", {}).get("pass")
        ps = res.get("solver", {}).get("pass")
        res["verdict"] = verdict(pp, ps)
        t4[sysn] = res
    out["T4"] = t4
    out["decision"] = {k: out[k]["verdict"] if k in ("T1", "T2", "T3") else {s: t4[s]["verdict"] for s in t4}
                       for k in ("T1", "T2", "T3", "T4")}
    (RES / "tests.json").write_text(json.dumps(out, indent=1, default=str))
    logger.info(f"DECISION {out['decision']}")


if __name__ == "__main__":
    main()
