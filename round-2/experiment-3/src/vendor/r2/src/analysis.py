"""S5 analyses on the held-out confirmation set (all CIs: 1000x bootstrap resampling SENTENCES within sentence-level
strata corpus x complexity tercile, seed 0; the dataset's L3 design strata are item-level, so their sentence-level
projection corpus x tercile is used as the resampling stratum).

Labelings: (P) panel3 adjudication, weighted by L3_sampling_weight (primary); (S) audited-solver labels on all
labelled rows (secondary); (T) soft labels q (tertiary); (U) panel unanimous subset; (D) design-weight sensitivity.
Pre-registered: C1 AUROC_P >= .70; C2 cross-fitted delta-AUROC over [B1,B2,B3nli,B3cos,B7] lower bound > 0;
C3 coverage >= 70% (unscored = 0.5). CONFIRMED iff C1 & C2 & C3.
"""
from __future__ import annotations

import json
import math
import time
from collections import Counter, defaultdict

import numpy as np
from loguru import logger

from common import DS_DIR, RES, SAMPLE_SYSTEMS, SYSTEMS, WORK, jdump, load_frame, read_jsonl, sha1
from scores import METRICS, build_long, wide, write_long
from stats import (StratBoot, ci, kendall_pairwise, kish, oof_stack, soft_auc, wauc, wauc_pairwise)

BASE = ["B1", "B2", "B3nli", "B3cos", "B7"]  # FROZEN 'best other baselines' (plan 5.2)
CANDIDATES = ["LC_onecoin", "LC_huiwalter", "LC_maj", "LC_ds_binary", "LC_onecoin_str", "LC_granular", "A3", "A1", "A0",
              "Ccov", "B1plus", "B3c", "B7_jacc", "B8", "LC_within"]
CROSSOVER = ["LC_onecoin", "A3", "A1", "B1plus", "B3nli"]
# metrics run on a restricted item set (coverage for C3 is computed over the rows they ran on): the round-trip metrics
# and frontier judges run on panel (+ contamination slice) items by design; the gemini A1 probe was restricted to the
# panel sentences + contamination pairs for budget (shared OpenRouter key, deviation D-LLM)
PANEL_ONLY = {"B1plus", "B3cos", "B3nli", "B3c", "B1plusL", "B3cosL", "B3nliL", "B3cL", "A1"}
LOCAL_SUB = {"B1": "B1L", "B1plus": "B1plusL", "A1": "A1L", "B3cos": "B3cosL", "B3nli": "B3nliL", "B3c": "B3cL"}


def resolve(m: str, metrics: list[str]) -> str | None:
    """Frozen metric if it was run, else its local-GPU substitute (declared in results/deviations.json)."""
    if m in metrics:
        return m
    s = LOCAL_SUB.get(m)
    return s if s in metrics else None
TWO_SYS = {"LC_within", "B8", "B7_jacc"}
TERC = {"bottom": 1, "middle": 2, "top": 3}
FAMILY = {"google": {"gemini-2.5-flash", "gemma-3-27b"}, "openai": {"gpt-4.1-mini", "gpt-oss-120b"}}


def nbin(n):
    return "0-1" if n <= 1 else ("2-3" if n <= 3 else "4+")


class Data:
    def __init__(self, limit=None):
        rows = load_frame()
        self.rows = rows
        long_rows, self.lc_info = build_long(rows)
        self.long = long_rows
        self.W = wide(long_rows)
        G = [r for r in rows if r["fold"] == "heldout_confirm"]
        if limit:
            import pipeline as P
            keep = set(P.mini_sids(G, limit))
            G = [r for r in G if r["sentence_id"] in keep]
        self.G = G
        self.C = [r for r in rows if r["fold"] == "contamination" and (not limit or r["sentence_id"] in
                                                                         {g["sentence_id"] for g in G})]
        lr = json.loads((DS_DIR / "label_report.json").read_text())
        # label_report: {'n': 63, 'weighted_p': 0.0988, ...} -> the 0.099 equivalent-but-unfaithful rate
        self.eq_unfaithful = float(lr["L3_equivalent_items_panel_unfaithful_rate"]["weighted_p"])
        self._labels()

    def _labels(self):
        for r in self.G:
            ls, out = r["label_source"], r["output"]
            r["y_panel"] = (1 if out == "faithful" else 0) if (ls == "panel3" and out in ("faithful", "unfaithful")) else None
            r["y_solver"] = {"faithful": 1, "unfaithful": 0}.get(out)
            st = r["L1_orig_status"] if (r["corpus"] == "proverqa" and r["gold_source"] == "original") else r[
                "L1_audited_status"]
            r["y_solver_pure"] = 1 if st in ("equiv_proved", "equiv_bounded") else (
                0 if st in ("non_equiv", "non_equiv_no_bijection") else None)
            r["L1_used_status"] = st
            if r["y_panel"] is not None:
                q = float(r["y_panel"])
            elif not r["parse_ok"]:
                q = 0.0
            elif out == "faithful":
                q = 1 - self.eq_unfaithful
            elif out == "unfaithful":
                q = r["L3_stratum_p_faithful"]
            else:
                q = None
            r["q"] = q
            r["w"] = r["L3_sampling_weight"] if r["y_panel"] is not None else None
            r["wd"] = r["L3_design_weight"] if r["y_panel"] is not None else None
            r["tn"] = TERC[r["complexity_tercile"]]
            r["nbin"] = nbin(r["n_conditions"] or 0)
            r["unanimous"] = (r["y_panel"] is not None) and not r.get("L3_dissent")

    def col(self, rows, m):
        """score vector (uncovered/missing -> 0.5) and 'present' mask (metric was run on the item)."""
        s, pres, cov = [], [], []
        for r in rows:
            v = self.W.get(r["item_id"], {}).get(m)
            s.append(0.5 if v is None else v[0])
            pres.append(v is not None)
            cov.append(bool(v and v[1]))
        return np.array(s, dtype=float), np.array(pres), np.array(cov)


def strata(rows):
    return {r["sentence_id"]: f"{r['corpus']}|{r['complexity_tercile']}" for r in rows}


def auc_block(D: Data, rows, m, ykey="y_panel", wkey="w", boot: StratBoot | None = None) -> dict:
    s, pres, cov = D.col(rows, m)
    y = np.array([r[ykey] for r in rows], dtype=float)
    w = np.array([r[wkey] if wkey else 1.0 for r in rows], dtype=float) if wkey else np.ones(len(rows))
    msk = pres
    if msk.sum() < 5 or len(np.unique(y[msk])) < 2:
        return {"auroc": None, "ci": [None, None], "n": int(msk.sum())}
    a = wauc(y[msk], s[msk], w[msk])
    lo_hi = [None, None]
    if boot is not None:
        vals = []
        for idx in boot:
            ii = idx[msk[idx]]
            if len(ii) > 5 and len(np.unique(y[ii])) == 2:
                vals.append(wauc(y[ii], s[ii], w[ii]))
        lo_hi = ci(vals)
    return {"auroc": a, "ci": lo_hi, "n": int(msk.sum()), "n_pos": int(y[msk].sum()),
            "kish_n_eff": kish(w[msk]) if wkey else None}


def run(limit=None):
    t0 = time.time()
    D = Data(limit)
    write_long(D.long)
    out = {"meta": {"n_G": len(D.G), "limit_sents": limit, "eq_unfaithful_rate_used_for_q": D.eq_unfaithful,
                    "bootstrap": "1000x sentences within corpus x tercile strata, seed 0",
                    "base_features_frozen": BASE}}
    G = D.G
    P = [r for r in G if r["y_panel"] is not None]
    S = [r for r in G if r["y_solver"] is not None]
    Tq = [r for r in G if r["q"] is not None]
    U = [r for r in P if r["unanimous"]]
    out["meta"].update(n_panel=len(P), n_solver_labelled=len(S), n_soft=len(Tq), n_unanimous=len(U),
                       panel_kish_n_eff=kish([r["w"] for r in P]), panel_sum_w=float(sum(r["w"] for r in P)),
                       panel_label_counts=dict(Counter(r["y_panel"] for r in P)),
                       unknown_label_rows=sum(r["y_solver"] is None for r in G))
    bP = StratBoot([r["sentence_id"] for r in P], strata(P))
    bS = StratBoot([r["sentence_id"] for r in S], strata(S))
    bU = StratBoot([r["sentence_id"] for r in U], strata(U))
    bT = StratBoot([r["sentence_id"] for r in Tq], strata(Tq))
    out["meta"]["boot_strata_panel"] = bP.by_stratum
    # ---------------------------------------------------------------- T0b / T4 checks
    rng = np.random.default_rng(0)
    yy, ss, ww = rng.integers(0, 2, 300), rng.integers(0, 10, 300) / 10, rng.random(300)
    from sklearn.metrics import roc_auc_score
    chk = {"wauc_vs_sklearn_absdiff": abs(wauc(yy, ss, ww) - roc_auc_score(yy, ss, sample_weight=ww)),
           "wauc_vs_pairwise_absdiff": abs(wauc(yy, ss, ww) - wauc_pairwise(yy, ss, ww)),
           "soft_q01_vs_hard_absdiff": abs(soft_auc(yy.astype(float), ss) - wauc(yy, ss))}
    out["checks"] = chk
    # placebo random metric
    for r in G:
        D.W[r["item_id"]]["RANDOM"] = (float(np.random.default_rng(int(sha1(r["item_id"])[:8], 16)).random()), True)
    # a metric is 'available' only if at least one held-out item was actually scored (covered)
    metrics = [m for m in METRICS if any(D.W.get(r["item_id"], {}).get(m, (0, False))[1] for r in G)] + ["RANDOM"]
    out["meta"]["metrics_available"] = metrics
    out["meta"]["base_features_used"] = [resolve(b, metrics) for b in BASE if resolve(b, metrics)]
    out["meta"]["local_substitutes_used"] = {k: v for k, v in LOCAL_SUB.items() if k not in metrics and v in metrics}
    # ---------------------------------------------------------------- 5.1 item-level AUROCs
    table = {}
    for m in metrics:
        t = {}
        t["P"] = auc_block(D, P, m, "y_panel", "w", bP)
        t["S"] = auc_block(D, S, m, "y_solver", None, bS)
        t["U"] = auc_block(D, U, m, "y_panel", "w", bU)
        t["D"] = auc_block(D, P, m, "y_panel", "wd", None)
        # soft labels
        s, pres, _ = D.col(Tq, m)
        q = np.array([r["q"] for r in Tq])
        if pres.sum() > 5:
            a = soft_auc(q[pres], s[pres])
            vals = [soft_auc(q[idx[pres[idx]]], s[idx[pres[idx]]]) for idx in bT] if not limit else []
            t["T"] = {"auroc": a, "ci": ci(vals), "n": int(pres.sum())}
        else:
            t["T"] = {"auroc": None, "n": int(pres.sum())}
        # coverage over all 6300 (or over rows the metric was run on, for panel-only / 2-system metrics)
        _, presG, covG = D.col(G, m)
        t["coverage_all_G"] = float(covG.mean())
        t["coverage_run_rows"] = float(covG[presG].mean()) if presG.sum() else None
        t["n_run_rows"] = int(presG.sum())
        # cost / time per item
        lr = [x for x in D.long if x["metric"] == m and x["fold"] == "heldout_confirm"]
        t["usd_per_item"] = float(np.mean([x["usd"] or 0.0 for x in lr])) if lr else 0.0
        secs = [x["seconds"] for x in lr if x.get("seconds") is not None]
        t["seconds_per_item"] = float(np.mean(secs)) if secs else None
        # within-sentence AUROC (P labels where >= 30 sentences have both classes, else S labels)
        t["within_sentence"] = within_sentence(D, G, m)
        table[m] = t
        logger.info(f"{m}: P={_f(t['P']['auroc'])} {_ci(t['P']['ci'])} S={_f(t['S']['auroc'])} "
                    f"T={_f(t['T'].get('auroc'))} cov={t['coverage_all_G']:.3f}")
    out["auroc"] = table
    # ---------------------------------------------------------------- LC fit info + LC_within vs LC_onecoin (same items)
    out["lc_fit_info"] = {k: v for k, v in D.lc_info.items() if not k.startswith("LC_gold")}
    cmp = {}
    for lab, rows_, wk in (("P", P, "w"), ("S", S, None)):
        sub = [r for r in rows_ if r["system"] in SAMPLE_SYSTEMS]
        bb = StratBoot([r["sentence_id"] for r in sub], strata(sub))
        yk = "y_panel" if lab == "P" else "y_solver"
        cmp[lab] = {m: auc_block(D, sub, m, yk, wk, bb) for m in ("LC_within", "LC_onecoin", "B8", "B7_jacc")}
        cmp[lab]["n"] = len(sub)
    out["lc_within_vs_onecoin_same_items"] = cmp
    # ---------------------------------------------------------------- per-error-type sensitivity (panel)
    out["per_error_type"] = per_error_type(D, P, metrics)
    # ---------------------------------------------------------------- 5.3 stacking + 5.2 C1-C3
    stack = stacking(D, P, bP, metrics)
    out["stacking"] = stack
    out["confirmation"] = confirm(table, stack)
    # ---------------------------------------------------------------- 5.4 circularity
    out["circularity"] = circularity(D, P, bP)
    # ---------------------------------------------------------------- 5.5 system level
    out["system_level"] = system_level(D, G, P, metrics, limit)
    # ---------------------------------------------------------------- 5.6 complexity
    out["complexity"] = complexity(D, G, P, S, Tq, metrics, bP, bS, limit)
    # ---------------------------------------------------------------- 5.7 contamination + recall
    out["contamination"] = contamination(D)
    # ---------------------------------------------------------------- 5.8 judge reliability
    out["judge_reliability"] = judge_reliability(D, P, bP)
    # ---------------------------------------------------------------- sanity (T4)
    out["sanity"] = sanity(D, G, P, table, stack)
    out["meta"]["seconds"] = time.time() - t0
    suffix = "" if not limit else f"_mini{limit}"
    jdump(out, RES / f"analysis{suffix}.json")
    jdump(out["circularity"], RES / f"circularity{suffix}.json")
    jdump(out["system_level"], RES / f"system_level{suffix}.json")
    jdump(confirmation_table(out), RES / f"confirmation_table{suffix}.json")
    logger.info(f"analysis done in {time.time() - t0:.0f}s")
    return out


def _f(x):
    return "NA" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.3f}"


def _ci(c):
    return f"[{_f(c[0])},{_f(c[1])}]" if c else ""


def within_sentence(D: Data, G, m) -> dict:
    res = {}
    for lab in ("y_panel", "y_solver"):
        by = defaultdict(list)
        for r in G:
            if r[lab] is not None:
                by[r["sentence_id"]].append(r)
        vals = []
        for sid, rs in by.items():
            y = np.array([r[lab] for r in rs])
            if len(np.unique(y)) < 2:
                continue
            s, pres, _ = D.col(rs, m)
            if pres.sum() < len(rs):
                continue
            vals.append(wauc(y, s))
        res[lab] = {"mean": float(np.mean(vals)) if vals else None, "n_sentences": len(vals)}
    use = "y_panel" if res["y_panel"]["n_sentences"] >= 30 else "y_solver"
    return {**res, "primary": use}


def per_error_type(D: Data, P, metrics) -> dict:
    """Sensitivity per REAL error type: weighted AUROC of panel-faithful items vs panel-unfaithful items whose
    L3 primary error is t (n>=10 unfaithful items)."""
    types = Counter(r["L3_primary_error"] for r in P if r["y_panel"] == 0)
    out = {"type_counts_unweighted": dict(types)}
    for t, n in types.items():
        if n < 10:
            continue
        rows = [r for r in P if r["y_panel"] == 1 or r["L3_primary_error"] == t]
        out[t] = {}
        for m in metrics:
            s, pres, _ = D.col(rows, m)
            y = np.array([r["y_panel"] for r in rows], dtype=float)
            w = np.array([r["w"] for r in rows])
            if pres.sum() > 10 and len(np.unique(y[pres])) == 2:
                out[t][m] = {"auroc": wauc(y[pres], s[pres], w[pres]), "n_err": int(((y == 0) & pres).sum())}
    return out


def _stack_eval(D, P, feats, bP, y, w, sids, placebo=None):
    X = np.column_stack([D.col(P, f)[0] for f in feats] + ([placebo] if placebo is not None else []))
    return oof_stack(X, y, sids, w)


def stacking(D: Data, P, bP: StratBoot, metrics) -> dict:
    y = np.array([r["y_panel"] for r in P])
    w = np.array([r["w"] for r in P])
    sids = np.array([r["sentence_id"] for r in P])
    base = [resolve(b, metrics) for b in BASE if resolve(b, metrics)]
    oof = {}
    oof["base"] = _stack_eval(D, P, base, bP, y, w, sids)

    def delta(tag_with, tag_wo):
        a1, a0 = oof[tag_with], oof[tag_wo]
        d = wauc(y, a1, w) - wauc(y, a0, w)
        vals = [wauc(y[i], a1[i], w[i]) - wauc(y[i], a0[i], w[i]) for i in bP]
        c = ci(vals)
        return {"auc_with": wauc(y, a1, w), "auc_without": wauc(y, a0, w), "delta": d, "ci": c,
                "lb_gt_0": bool(c[0] is not None and c[0] > 0)}
    res = {"base_features": base, "n": len(P), "auc_base": wauc(y, oof["base"], w), "per_metric": {}}
    for m in [x for x in metrics if x not in base and x not in TWO_SYS and x != "RANDOM"] + ["RANDOM"]:
        oof[m] = _stack_eval(D, P, base + [m], bP, y, w, sids)
        res["per_metric"][m] = delta(m, "base")
    # composite models
    a1 = resolve("A1", metrics) or "A1"
    combos = {"base+A3_over_base+A0": (["A0", "A3"], ["A0"]), "base+LC+A3": (["LC_onecoin", "A3"], []),
              f"base+LC+A3+{a1}": (["LC_onecoin", "A3", a1], []),
              "base+all": ([m for m in CANDIDATES + ["A1L", "B1plusL", "B3cL"] if m in metrics and m not in TWO_SYS
                             and m != "LC_granular" and m not in base], [])}
    res["combos"] = {}
    for name, (add, sub) in combos.items():
        if not all(a in metrics for a in add):
            continue
        tw, two = name + ":with", name + ":without"
        oof[tw] = _stack_eval(D, P, base + add, bP, y, w, sids)
        oof[two] = _stack_eval(D, P, base + sub, bP, y, w, sids) if sub else oof["base"]
        res["combos"][name] = delta(tw, two)
    # sensitivity: base WITHOUT the round-trip features (B3nli/B3cos or their substitutes) -> [judge, B2, B7]
    base_nb3 = [b for b in base if not b.startswith("B3")]
    if base_nb3 != base:
        oof["base_nb3"] = _stack_eval(D, P, base_nb3, bP, y, w, sids)
        res["base_without_roundtrip"] = {"base": base_nb3, "auc_base": wauc(y, oof["base_nb3"], w), "per_metric": {}}
        for m in ["LC_onecoin", "LC_maj", "LC_ds_binary", "LC_huiwalter", "A3", "A0", "Ccov", a1, "B3nliL", "B3nli"]:
            if m in metrics:
                oof[f"nb3:{m}"] = _stack_eval(D, P, base_nb3 + [m], bP, y, w, sids)
                res["base_without_roundtrip"]["per_metric"][m] = delta(f"nb3:{m}", "base_nb3")
    # placebo random-uniform feature
    rnd = np.random.default_rng(7).random(len(P))
    oof["placebo"] = _stack_eval(D, P, base, bP, y, w, sids, placebo=rnd)
    res["placebo_random_feature"] = delta("placebo", "base")
    # second table: B1plus added to the base
    b1p = resolve("B1plus", metrics)
    if b1p:
        base2 = base + [b1p]
        oof["base2"] = _stack_eval(D, P, base2, bP, y, w, sids)
        res["with_B1plus_in_base"] = {"auc_base": wauc(y, oof["base2"], w), "per_metric": {}, "B1plus_used": b1p}
        for m in ["LC_onecoin", "A3", a1, "A0", "LC_maj", "LC_huiwalter"]:
            if m in metrics:
                oof[f"b2:{m}"] = _stack_eval(D, P, base2 + [m], bP, y, w, sids)
                res["with_B1plus_in_base"]["per_metric"][m] = delta(f"b2:{m}", "base2")
    # B8 / LC_within table on the 2-system panel subset (B8 in base)
    sub = [i for i, r in enumerate(P) if r["system"] in SAMPLE_SYSTEMS]
    if len(sub) > 30 and "B8" in metrics:
        Ps = [P[i] for i in sub]
        ys, ws, ss = y[sub], w[sub], sids[sub]
        bS2 = StratBoot(ss, strata(Ps))
        b8base = base + ["B8"]
        o0 = _stack_eval(D, Ps, b8base, bS2, ys, ws, ss)
        r2 = {"n": len(Ps), "base": b8base, "auc_base": wauc(ys, o0, ws), "per_metric": {}}
        for m in ["LC_onecoin", "LC_within", "A3", a1, "B7_jacc"]:
            if m in metrics:
                o1 = _stack_eval(D, Ps, b8base + [m], bS2, ys, ws, ss)
                vals = [wauc(ys[i], o1[i], ws[i]) - wauc(ys[i], o0[i], ws[i]) for i in bS2]
                r2["per_metric"][m] = {"delta": wauc(ys, o1, ws) - wauc(ys, o0, ws), "ci": ci(vals)}
        # B8 itself over the 9-system base on this subset
        o_b = _stack_eval(D, Ps, base, bS2, ys, ws, ss)
        vals = [wauc(ys[i], o0[i], ws[i]) - wauc(ys[i], o_b[i], ws[i]) for i in bS2]
        r2["B8_over_base"] = {"delta": wauc(ys, o0, ws) - wauc(ys, o_b, ws), "ci": ci(vals)}
        res["two_system_subset"] = r2
    return res


def confirm(table, stack) -> dict:
    out = {}
    for m, t in table.items():
        a = t["P"]["auroc"]
        c1 = a is not None and a >= 0.70
        st = stack["per_metric"].get(m) or (stack.get("two_system_subset", {}).get("per_metric", {}).get(m))
        if m == "B8":  # B8 is the 2-system base member; its C2 is B8 over the 9-system base on that subset
            st = stack.get("two_system_subset", {}).get("B8_over_base")
        c2 = bool(st and st.get("ci") and st["ci"][0] is not None and st["ci"][0] > 0)
        cov = t["coverage_all_G"] if m not in PANEL_ONLY | TWO_SYS else t["coverage_run_rows"]
        c3 = cov is not None and cov >= 0.70
        aS = t["S"]["auroc"]
        out[m] = {"C1": bool(c1), "C2": c2, "C3": bool(c3), "CONFIRMED": bool(c1 and c2 and c3),
                  "C1_solver": bool(aS is not None and aS >= 0.70), "coverage_used_for_C3": cov,
                  "note": ("post-hoc; never a CONFIRM claim" if m == "LC_granular" else
                           "C2 on the 2-system subset" if m in TWO_SYS else "")}
        if m == "LC_granular":
            out[m]["CONFIRMED"] = False
    return out


def circularity(D: Data, P, bP) -> dict:
    res = {}
    comps = ["LC_onecoin", "LC_maj", "LC_huiwalter", "LC_onecoin_str", "LC_ds_binary", "LC_granular", "A3", "A1", "A0",
             "B1", "B1plus", "B3nli", "B3cos", "B3c", "B1L", "B1plusL", "A1L", "B3nliL", "B3cosL", "B3cL", "B7", "Ccov"]
    # (a) same 609 items: panel vs solver-pure labels
    Pa = [r for r in P if r["y_solver_pure"] is not None]
    y1 = np.array([r["y_panel"] for r in Pa], dtype=float)
    y2 = np.array([r["y_solver_pure"] for r in Pa], dtype=float)
    w = np.array([r["w"] for r in Pa])
    ba = StratBoot([r["sentence_id"] for r in Pa], strata(Pa))
    res["a_panel_vs_solver_same_items"] = {"n": len(Pa), "label_agreement_weighted":
                                           float(np.average(y1 == y2, weights=w))}
    for m in comps:
        s, pres, _ = D.col(Pa, m)
        if pres.sum() < 10:
            continue
        ap, as_ = wauc(y1[pres], s[pres], w[pres]), wauc(y2[pres], s[pres], w[pres])
        vals = []
        for idx in ba:
            ii = idx[pres[idx]]
            vals.append(wauc(y1[ii], s[ii], w[ii]) - wauc(y2[ii], s[ii], w[ii]))
        res["a_panel_vs_solver_same_items"][m] = {"auroc_panel": ap, "auroc_solver_pure": as_, "diff_panel_minus_solver":
                                                  ap - as_, "diff_ci": ci(vals)}
    # (b) inside solver-NON-equivalent panel items; (d) no-bijection only
    for tag, sts in (("b_nonequiv", ("non_equiv", "non_equiv_no_bijection")), ("d_no_bijection", ("non_equiv_no_bijection",))):
        Pb = [r for r in P if r["L1_audited_status"] in sts]
        yb = np.array([r["y_panel"] for r in Pb], dtype=float)
        wb = np.array([r["w"] for r in Pb])
        bb = StratBoot([r["sentence_id"] for r in Pb], strata(Pb))
        d = {"n": len(Pb), "faithful_share_weighted": float(np.average(yb, weights=wb)) if len(Pb) else None,
             "kish_n_eff": kish(wb)}
        for m in comps:
            s, pres, _ = D.col(Pb, m)
            if pres.sum() < 10 or len(np.unique(yb[pres])) < 2:
                continue
            a = wauc(yb[pres], s[pres], wb[pres])
            vals = []
            for idx in bb:
                ii = idx[pres[idx]]
                if len(np.unique(yb[ii])) == 2:
                    vals.append(wauc(yb[ii], s[ii], wb[ii]))
            c = ci(vals)
            reading = None
            if m == "LC_onecoin" or m.startswith("LC"):
                reading = ("not a checker artefact" if (c[0] is not None and c[0] > 0.5 and a >= 0.60) else
                           "partial" if (c[0] is not None and c[0] > 0.5) else "artefact")
            d[m] = {"auroc": a, "ci": c, "n": int(pres.sum()), "preregistered_reading": reading}
        res[tag] = d
    # (c) LC class position of panel-faithful & solver-non-equivalent items vs panel-unfaithful non-equivalent items
    struct = {}
    for x in read_jsonl(WORK / "lc_struct.jsonl"):
        struct[x["item_id"]] = x
    g_key = {r["item_id"]: f"{r['sentence_id']}:{r['system']}" for r in P}
    cres = {}
    for lab, name in ((1, "panel_faithful_nonequiv"), (0, "panel_unfaithful_nonequiv")):
        rs = [r for r in P if r["L1_audited_status"] in ("non_equiv", "non_equiv_no_bijection") and r["y_panel"] == lab]
        ww = np.array([r["w"] for r in rs])
        s, _, _ = D.col(rs, "LC_onecoin")
        st = [struct.get(g_key[r["item_id"]], {}) for r in rs]
        mino = np.array([bool(x.get("minority")) for x in st])
        sing = np.array([bool(x.get("singleton")) for x in st])
        cres[name] = {"n": len(rs), "share_LC_lt_0.5": float(np.average(s < 0.5, weights=ww)) if len(rs) else None,
                      "share_minority_class": float(np.average(mino, weights=ww)) if len(rs) else None,
                      "share_singleton": float(np.average(sing, weights=ww)) if len(rs) else None,
                      "share_minority_or_singleton": float(np.average(mino | sing, weights=ww)) if len(rs) else None,
                      "mean_LC": float(np.average(s, weights=ww)) if len(rs) else None}
    res["c_class_position"] = cres
    res["reading_rule"] = ("'not a checker artefact' iff (b) AUROC 95% LB > 0.5 AND point >= 0.60; 'partial' iff LB > "
                           "0.5 but point < 0.60; 'artefact' iff CI includes 0.5")
    return res


def system_level(D: Data, G, P, metrics, limit) -> dict:
    # truth: mean q over the system's items; unparseable = 0; unknown = corpus x tercile mean q among known
    cell = defaultdict(list)
    for r in G:
        if r["q"] is not None:
            cell[(r["corpus"], r["complexity_tercile"])].append(r["q"])
    cmean = {k: float(np.mean(v)) for k, v in cell.items()}
    qfill = np.array([r["q"] if r["q"] is not None else cmean[(r["corpus"], r["complexity_tercile"])] for r in G])
    n_unknown = sum(r["q"] is None for r in G)
    sysv = np.array([r["system"] for r in G])
    sids = np.array([r["sentence_id"] for r in G])
    boot = StratBoot(sids, strata(G), n=1000 if not limit else 200)
    wP = np.array([r["w"] for r in P])
    yP = np.array([r["y_panel"] for r in P], dtype=float)
    sysP = np.array([r["system"] for r in P])
    bootP = StratBoot([r["sentence_id"] for r in P], strata(P), n=1000 if not limit else 200)

    def per_sys(vals, sv, w=None, idx=None):
        idx = np.arange(len(vals)) if idx is None else idx
        out = {}
        for s in SYSTEMS:
            ii = idx[sv[idx] == s]
            if len(ii):
                out[s] = float(np.average(vals[ii], weights=None if w is None else w[ii]))
        return out
    truth = per_sys(qfill, sysv)
    truthP = per_sys(yP, sysP, wP)
    res = {"truth_all_items": truth, "truth_panel": truthP, "n_unknown_imputed": n_unknown,
           "note": "n=9 systems: Kendall tau null SD ~0.27; underpowered by design, NOT a gate", "metrics": {}}
    for m in metrics:
        sG, presG, _ = D.col(G, m)
        r = {}
        if presG.mean() > 0.99:
            ms = per_sys(sG, sysv)
            r["all_items"] = kendall_pairwise(ms, truth)
            r["all_items"]["metric_by_system"] = ms
            taus, accs = [], []
            for idx in boot:
                kp = kendall_pairwise(per_sys(sG, sysv, idx=idx), per_sys(qfill, sysv, idx=idx))
                taus.append(kp["tau_b"])
                accs.append(kp["pairwise_acc"])
            r["all_items"]["tau_ci"], r["all_items"]["acc_ci"] = ci(taus), ci(accs)
        sP, presP, _ = D.col(P, m)
        if presP.sum() > 0.9 * len(P):
            ms = per_sys(sP, sysP, wP)
            r["panel_items"] = kendall_pairwise(ms, truthP)
            r["panel_items"]["metric_by_system"] = ms
            taus = []
            for idx in bootP:
                taus.append(kendall_pairwise(per_sys(sP, sysP, wP, idx), per_sys(yP, sysP, wP, idx))["tau_b"])
            r["panel_items"]["tau_ci"] = ci(taus)
        res["metrics"][m] = r
    return res


def complexity(D: Data, G, P, S, Tq, metrics, bP, bS, limit) -> dict:
    res = {"per_cell": {}, "crossover": {}}
    pops = {"P": (P, "y_panel", "w"), "S": (S, "y_solver", None)}
    for pname, (rows, yk, wk) in pops.items():
        for dim in ("tn", "nbin"):
            for val in sorted({r[dim] for r in rows}, key=str):
                cell = [r for r in rows if r[dim] == val]
                y = np.array([r[yk] for r in cell])
                n_pos, n_neg = int((y == 1).sum()), int((y == 0).sum())
                key = f"{pname}|{dim}={val}"
                ent = {"n": len(cell), "n_pos": n_pos, "n_neg": n_neg}
                if len(cell) < 40 or n_pos < 10 or n_neg < 10:
                    ent["insufficient_n"] = True
                bc = StratBoot([r["sentence_id"] for r in cell], strata(cell), n=300)
                for m in metrics:
                    b = auc_block(D, cell, m, yk, wk, bc if not limit else None)
                    ent[m] = {"auroc": b["auroc"], "ci": b["ci"]}
                res["per_cell"][key] = ent
    # pre-registered crossover vs B1 (gap slope over terciles, computed inside each bootstrap replicate)
    for pname, (rows, yk, wk, boot) in {"P": (P, "y_panel", "w", bP), "S": (S, "y_solver", None, bS),
                                        "T": (Tq, "q", None, None)}.items():
        y = np.array([r[yk] for r in rows], dtype=float)
        w = np.array([r[wk] for r in rows]) if wk else np.ones(len(rows))
        tn = np.array([r["tn"] for r in rows])
        if boot is None:
            boot = StratBoot([r["sentence_id"] for r in rows], strata(rows), n=1000 if not limit else 100)
        b1ref = resolve("B1", metrics) or "B1"
        res["B1_reference"] = b1ref
        b1, pres_b1, _ = D.col(rows, b1ref)
        for m0 in CROSSOVER:
            m = resolve(m0, metrics)
            if m is None:
                continue
            sm, pres, _ = D.col(rows, m)
            ok = pres & pres_b1
            if ok.sum() < 30:
                continue

            def gaps(idx):
                g = []
                for t in (1, 2, 3):
                    ii = idx[(tn[idx] == t) & ok[idx]]
                    if pname == "T":
                        a_m, a_b = soft_auc(y[ii], sm[ii]), soft_auc(y[ii], b1[ii])
                    else:
                        if len(np.unique(y[ii])) < 2:
                            return None
                        a_m, a_b = wauc(y[ii], sm[ii], w[ii]), wauc(y[ii], b1[ii], w[ii])
                    g.append(a_m - a_b)
                return g
            g0 = gaps(np.arange(len(rows)))
            if g0 is None:
                continue
            slope0 = float(np.polyfit([1, 2, 3], g0, 1)[0])
            slopes, tops = [], []
            for idx in boot:
                g = gaps(idx)
                if g is None or any(math.isnan(x) for x in g):
                    continue
                slopes.append(float(np.polyfit([1, 2, 3], g, 1)[0]))
                tops.append(g[2])
            cs, ct = ci(slopes), ci(tops)
            res["crossover"][f"{pname}|{m}"] = {
                "gap_by_tercile": dict(zip(["bottom", "middle", "top"], g0)), "slope": slope0, "slope_ci": cs,
                "top_gap_ci": ct, "CROSSOVER_CONFIRMED": bool(cs[0] is not None and cs[0] > 0 and ct[0] is not None and
                                                             ct[0] > 0)}
        # logistic interaction test (panel + solver only)
        if pname in ("P", "S"):
            for m0 in CROSSOVER:
                m = resolve(m0, metrics)
                if m is None:
                    continue
                sm, pres, _ = D.col(rows, m)
                ok = pres & pres_b1
                if ok.sum() < 30:
                    continue
                res["crossover"][f"{pname}|{m}"]["interaction"] = interaction(y, sm, b1, tn, w, ok, boot, limit)
    return res


def interaction(y, sm, b1, tn, w, ok, boot, limit):
    """y ~ z(s_m) + z(s_B1) + tercile + z(s_m):tercile + z(s_B1):tercile ; statistic = b[s_m:t] - b[s_B1:t]."""
    from sklearn.linear_model import LogisticRegression

    def fit(idx):
        ii = idx[ok[idx]]
        if len(np.unique(y[ii])) < 2:
            return None
        zm = (sm[ii] - sm[ii].mean()) / (sm[ii].std() + 1e-9)
        zb = (b1[ii] - b1[ii].mean()) / (b1[ii].std() + 1e-9)
        t = tn[ii].astype(float) - 2.0
        X = np.column_stack([zm, zb, t, zm * t, zb * t])
        mdl = LogisticRegression(C=1e4, max_iter=2000).fit(X, y[ii], sample_weight=w[ii])
        return float(mdl.coef_[0][3] - mdl.coef_[0][4])
    d0 = fit(np.arange(len(y)))
    vals = []
    for k, idx in enumerate(boot):
        if limit and k >= 100:
            break
        v = fit(idx)
        if v is not None:
            vals.append(v)
    c = ci(vals)
    return {"b_m_x_t_minus_b_B1_x_t": d0, "ci": c, "positive": bool(c[0] is not None and c[0] > 0)}


def contamination(D: Data) -> dict:
    res = {"prediction_recorded_in_advance": "A1 and A3 delta ~ 0; B1 may drop"}
    rows = [r for r in D.C if r.get("original_item_id")]
    for excl in (False, True):
        sub = [r for r in rows if not (excl and r.get("contamination_rename_incomplete"))]
        tag = "excl_rename_incomplete" if excl else "all"
        res[tag] = {"n_rows": len(sub), "n_sentences": len({r["sentence_id"] for r in sub})}
        for m in ["B1", "B1plus", "B3cos", "B3nli", "B3c", "A1", "B1L", "B1plusL", "B3cosL", "B3nliL", "B3cL", "A1L", "A3",
                  "A0", "Ccov", "LC_onecoin"]:
            pairs = []
            for r in sub:
                o = D.W.get(r["original_item_id"], {}).get(m)
                c = D.W.get(r["item_id"], {}).get(m)
                if o is None or c is None:
                    continue
                pairs.append((r["sentence_id"], o[0], c[0], {"faithful": 1, "unfaithful": 0}.get(r["output"])))
            if len(pairs) < 10:
                continue
            sids = np.array([p[0] for p in pairs])
            so = np.array([p[1] for p in pairs])
            sc = np.array([p[2] for p in pairs])
            y = np.array([np.nan if p[3] is None else p[3] for p in pairs])
            b = StratBoot(sids, {s: "all" for s in sids})
            d = so - sc
            ent = {"n_pairs": len(pairs), "n_sentences": len(set(sids.tolist())), "mean_delta": float(d.mean()),
                   "delta_ci": ci(d[i].mean() for i in b)}
            lab = ~np.isnan(y)
            if lab.sum() > 10 and len(np.unique(y[lab])) == 2:
                ao, ac = wauc(y[lab], so[lab]), wauc(y[lab], sc[lab])
                vals = []
                for i in b:
                    ii = i[lab[i]]
                    if len(np.unique(y[ii])) == 2:
                        vals.append(wauc(y[ii], so[ii]) - wauc(y[ii], sc[ii]))
                ent.update(auroc_original=ao, auroc_paraphrase=ac, auroc_diff=ao - ac, auroc_diff_ci=ci(vals),
                           n_labelled=int(lab.sum()))
            res[tag][m] = ent
    res["gold_recall_probe"] = recall_probe(D, "recall.jsonl")
    res["gold_recall_probe_local_Qwen3_8B"] = recall_probe(D, "recallL.jsonl")
    return res


def _pred_names(s):
    import re
    return set(re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(", s or "")) - {"forall", "exists", "all", "some"}


def _norm(s):
    return "".join((s or "").split())


def recall_probe(D: Data, fname: str) -> dict:
    R = {r["key"]: r for r in read_jsonl(WORK / fname)}
    if not R:
        return {"status": "not run"}
    first = {}
    for r in D.C:
        first.setdefault(r["sentence_id"], r)
    gold = {}
    for r in D.rows:
        if r["fold"] == "heldout_confirm":
            gold.setdefault(r["sentence_id"], r["gold_fol_original"])
    out = {"orig": [], "para": [], "para_vs_orig_gold": []}
    for sid, r in first.items():
        go, gr = gold.get(sid), r.get("gold_fol_renamed")
        o, p = R.get(f"{sid}:orig"), R.get(f"{sid}:para")
        if o and go:
            G0, O = _pred_names(go), _pred_names(o["text"])
            out["orig"].append((len(G0 & O) / len(G0) if G0 else None, _norm(o["text"]) == _norm(go)))
        if p and gr:
            G1, Pp = _pred_names(gr), _pred_names(p["text"])
            out["para"].append((len(G1 & Pp) / len(G1) if G1 else None, _norm(p["text"]) == _norm(gr)))
        if p and go:
            G0, Pp = _pred_names(go), _pred_names(p["text"])
            out["para_vs_orig_gold"].append((len(G0 & Pp) / len(G0) if G0 else None, False))
    res = {}
    for k, v in out.items():
        rec = [x[0] for x in v if x[0] is not None]
        res[k] = {"n": len(v), "mean_pred_name_recall": float(np.mean(rec)) if rec else None,
                  "exact_match_rate": float(np.mean([x[1] for x in v])) if v else None}
    if out["orig"] and out["para"]:
        a = np.array([x[0] for x in out["orig"] if x[0] is not None])
        b = np.array([x[0] for x in out["para"] if x[0] is not None])
        res["orig_minus_para_recall"] = float(a.mean() - b.mean())
        rng = np.random.default_rng(0)
        vals = [rng.choice(a, len(a)).mean() - rng.choice(b, len(b)).mean() for _ in range(1000)]
        res["orig_minus_para_recall_ci"] = ci(vals)
    res["note"] = ("predicate-name recall = |gold predicate names ∩ output predicate names| / |gold names|; original "
                   "sentences scored against the original gold, paraphrases (renamed entities) against the renamed gold")
    return res


def judge_reliability(D: Data, P, bP) -> dict:
    """Test-retest (B1: sequential re-call; B1L: re-generation in a different batch composition), duplicate-prompt
    share, and own-family vs other-family AUROC of the frontier / reasoning judge (self-preference check)."""
    from scipy.stats import spearmanr
    res = {}
    G = [r for r in D.rows if r["fold"] in ("heldout_confirm", "contamination")]
    for tag, f1, f2 in (("B1", "b1_scores.jsonl", "b1_retest.jsonl"), ("B1L", "b1L_scores.jsonl", "b1L_retest.jsonl")):
        first = {r["key"]: r for r in read_jsonl(WORK / f1)}
        rt = read_jsonl(WORK / f2)
        pairs = [(first[r["key"]]["score"], r["score2"]) for r in rt if r["key"] in first and r.get("score2") is not None]
        if pairs:
            a, b = np.array(pairs).T
            rho = float(spearmanr(a, b).statistic) if np.std(a) > 0 and np.std(b) > 0 else None
            res[f"{tag}_test_retest"] = {"n": len(pairs), "spearman": rho, "mean_abs_diff": float(np.abs(a - b).mean()),
                                         "share_absdiff_gt_0.2": float((np.abs(a - b) > 0.2).mean()),
                                         "exact_same_share": float((a == b).mean()),
                                         "flag_spearman_lt_0.8": bool(rho is not None and rho < 0.8)}
        rows = [first[r["item_id"]] for r in G if r["item_id"] in first]
        if rows:
            n_u = len({r.get("prompt_sha1") for r in rows})
            sc = np.array([r["score"] for r in rows if r["covered"]])
            res[f"{tag}_prompts"] = {"n_rows": len(rows), "n_unique_prompts": n_u, "duplicate_share": 1 - n_u / len(rows),
                                     "parse_rate": float(np.mean([r["covered"] for r in rows])),
                                     "score_sd": float(sc.std()) if len(sc) else None,
                                     "n_distinct_scores": int(len(np.unique(sc)))}
    y = np.array([r["y_panel"] for r in P], dtype=float)
    w = np.array([r["w"] for r in P])
    for tag, f in (("B1plus", "b1plus_scores.jsonl"), ("B1plusL", "b1plusL_scores.jsonl")):
        bp = read_jsonl(WORK / f)
        if not bp:
            continue
        model = bp[0].get("model", "")
        fam = ("google" if model.startswith("google/") else "openai" if model.startswith("openai/") else
               "qwen" if model.startswith("Qwen/") else None)
        own = {**FAMILY, "qwen": {"qwen-2.5-7b"}}.get(fam, set())
        s, pres, _ = D.col(P, tag)
        m_own = np.array([r["system"] in own for r in P]) & pres
        m_oth = np.array([r["system"] not in own for r in P]) & pres
        ref = "B1" if tag == "B1plus" else "B1L"
        s1, _, _ = D.col(P, ref)
        ok = m_own.sum() > 10 and len(np.unique(y[m_own])) == 2
        res[f"{tag}_self_preference"] = {
            "model": model, "own_family_systems": sorted(own), "n_own": int(m_own.sum()), "n_other": int(m_oth.sum()),
            "auroc_own_family": wauc(y[m_own], s[m_own], w[m_own]) if ok else None,
            "auroc_other_family": wauc(y[m_oth], s[m_oth], w[m_oth]) if m_oth.sum() > 10 else None,
            "mean_score_own_minus_other": float(s[m_own].mean() - s[m_oth].mean()) if m_own.sum() and m_oth.sum() else None,
            f"{ref}_mean_score_own_minus_other": float(s1[m_own].mean() - s1[m_oth].mean())
            if m_own.sum() and m_oth.sum() else None,
            "panel_faithful_rate_own_minus_other": float(np.average(y[m_own], weights=w[m_own]) -
                                                         np.average(y[m_oth], weights=w[m_oth]))
            if m_own.sum() and m_oth.sum() else None}
    return res


def sanity(D: Data, G, P, table, stack) -> dict:
    from scipy.stats import spearmanr
    res = {"random_metric_P": table["RANDOM"]["P"], "placebo_stack": stack.get("placebo_random_feature")}
    a, _, _ = D.col(G, "LC_maj")
    b, _, _ = D.col(G, "LC_onecoin")
    res["spearman_LC_maj_vs_LC_onecoin"] = float(spearmanr(a, b).statistic)
    res["B2_auroc_P"] = table.get("B2", {}).get("P")
    res["A0_le_A3_P"] = (table.get("A0", {}).get("P", {}).get("auroc") or 0) <= (
        table.get("A3", {}).get("P", {}).get("auroc") or 0)
    return res


def confirmation_table(out) -> dict:
    T = {}
    A = out["auroc"]
    cr = out["complexity"]["crossover"]
    cont = out["contamination"].get("all", {})
    for m, t in A.items():
        if m == "RANDOM":
            continue
        st = out["stacking"]["per_metric"].get(m) or out["stacking"].get("two_system_subset", {}).get(
            "per_metric", {}).get(m)
        if m == "B8":
            st = out["stacking"].get("two_system_subset", {}).get("B8_over_base")
        cf = out["confirmation"].get(m, {})
        top = out["complexity"]["per_cell"].get("P|tn=3", {}).get(m, {})
        T[m] = {"AUROC_P": t["P"]["auroc"], "CI_P": t["P"]["ci"], "n_P": t["P"]["n"],
                "AUROC_S": t["S"]["auroc"], "CI_S": t["S"]["ci"], "AUROC_T": t["T"].get("auroc"),
                "AUROC_U": t["U"]["auroc"], "AUROC_D": t["D"]["auroc"], "coverage": t["coverage_all_G"],
                "coverage_run_rows": t["coverage_run_rows"], "n_run_rows": t["n_run_rows"],
                "C1": cf.get("C1"), "C2_delta": (st or {}).get("delta"), "C2_ci": (st or {}).get("ci"),
                "C2": cf.get("C2"), "C3": cf.get("C3"), "CONFIRMED": cf.get("CONFIRMED"),
                "top_tercile_AUROC_P": top.get("auroc"), "top_tercile_CI_P": top.get("ci"),
                "crossover_P": (cr.get(f"P|{m}") or {}).get("CROSSOVER_CONFIRMED"),
                "crossover_S": (cr.get(f"S|{m}") or {}).get("CROSSOVER_CONFIRMED"),
                "contamination_delta": (cont.get(m) or {}).get("mean_delta"),
                "contamination_delta_ci": (cont.get(m) or {}).get("delta_ci"),
                "usd_per_item": t["usd_per_item"], "seconds_per_item": t["seconds_per_item"],
                "note": cf.get("note", "")}
    return T
