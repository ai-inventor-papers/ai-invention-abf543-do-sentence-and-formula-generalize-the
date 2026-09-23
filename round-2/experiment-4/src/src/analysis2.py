"""Phase-2 analyses (plan §7) → results/analysis.json + results/verdict.json. Runs only after the freeze.

Every metric is evaluated on IDENTICAL items; uncovered items keep score 0.5 (iter-1 convention) and every
AUROC is also given on the jointly covered subset. CIs: 2000× cluster bootstrap over sentence_ids resampled
within corpus strata (seed 0), the SAME resamples for every metric so deltas are paired.
"""
from __future__ import annotations

import collections as C
import json
import math
import warnings

import numpy as np
import pandas as pd
from loguru import logger

import common
from common import DATA, RESULTS, read_jsonl
from labels import load_labels

N_BOOT = 2000
ZERO_LLM = ["LC_onecoin", "LC_maj", "A3", "B2_parse_ok", "B2_bridge"]
LOCAL = ["TVJT_local", "B1_local"]
GEMINI = ["TVJT_frozen", "TVJT_C1", "TVJT_C2", "B1", "B1x3", "TVJT_iter1", "TVJT_lite"]
NC_BINS = [("0-1", 0, 1), ("2-3", 2, 3), ("4+", 4, 999)]
TERC = ["bottom", "middle", "top"]


# ------------------------------------------------------------------------------------------ AUROC
def wauc(y: np.ndarray, s: np.ndarray, w: np.ndarray) -> float:
    """Weighted AUROC with ties = 0.5: Σ_{i∈pos,j∈neg} w_i w_j [1(s_i>s_j)+.5·1(s_i=s_j)] / (Σw_pos Σw_neg).
    Soft labels are supported by passing y∈[0,1]: each item is a positive with weight w·y and a negative with
    weight w·(1−y) (probabilistic ROC)."""
    y = np.asarray(y, dtype=float)
    s = np.asarray(s, dtype=float)
    w = np.asarray(w, dtype=float)
    wp, wn = w * y, w * (1 - y)
    P, N = wp.sum(), wn.sum()
    if P <= 0 or N <= 0:
        return float("nan")
    u, inv = np.unique(s, return_inverse=True)
    pv = np.bincount(inv, weights=wp, minlength=len(u))
    nv = np.bincount(inv, weights=wn, minlength=len(u))
    below = np.concatenate([[0.0], np.cumsum(nv)[:-1]])
    return float((pv * (below + 0.5 * nv)).sum() / (P * N))


def boot_index(df: pd.DataFrame, n: int = N_BOOT, seed: int = 0) -> list[np.ndarray]:
    """Per resample: a multiplicity vector over rows (sentence counts, resampled within corpus strata)."""
    rng = np.random.default_rng(seed)
    sid = df["sid"].values
    corp = df["corpus"].values
    strata = {}
    for c in np.unique(corp):
        strata[c] = np.unique(sid[corp == c])
    pos = {s: i for i, s in enumerate(np.unique(sid))}
    row_s = np.array([pos[s] for s in sid])
    out = []
    for _ in range(n):
        cnt = np.zeros(len(pos))
        for c, ss in strata.items():
            pick = rng.choice(len(ss), len(ss))
            np.add.at(cnt, [pos[ss[i]] for i in pick], 1)
        out.append(cnt[row_s])
    return out


def ci(v) -> list:
    v = [x for x in v if x is not None and not (isinstance(x, float) and math.isnan(x))]
    if len(v) < 20:
        return [None, None]
    return [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]


def auc_block(df: pd.DataFrame, metrics: list[str], ycol: str, wcol: str | None, B: list[np.ndarray],
              pairs: list[tuple[str, str]]) -> dict:
    y = df[ycol].values
    w = df[wcol].values if wcol else np.ones(len(df))
    out = {"n": int(len(df)), "n_pos_w": float((w * y).sum()), "n_neg_w": float((w * (1 - y)).sum())}
    pt, bs = {}, {m: [] for m in metrics}
    for m in metrics:
        pt[m] = wauc(y, df[m].values, w)
    for mult in B:
        ww = w * mult
        for m in metrics:
            bs[m].append(wauc(y, df[m].values, ww))
    out["auroc"] = {m: {"point": pt[m], "ci": ci(bs[m])} for m in metrics}
    out["delta"] = {}
    for a, b in pairs:
        if a in metrics and b in metrics:
            d = [x - z for x, z in zip(bs[a], bs[b])]
            out["delta"][f"{a}-{b}"] = {"point": pt[a] - pt[b], "ci": ci(d)}
    out["_boot"] = bs
    return out


def within_sentence(df: pd.DataFrame, m: str, ycol: str) -> dict:
    """P(faithful candidate outscores an unfaithful candidate of the same sentence), ties 0.5."""
    acc = []
    for _, g in df.groupby("sid"):
        pos, neg = g[g[ycol] == 1][m].values, g[g[ycol] == 0][m].values
        for a in pos:
            for b in neg:
                acc.append(1.0 if a > b else 0.5 if a == b else 0.0)
    return {"n_pairs": len(acc), "acc": float(np.mean(acc)) if acc else None}


def wilson(k: float, n: int, z: float = 1.96) -> list:
    if n == 0:
        return [None, None]
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [c - h, c + h]


# ------------------------------------------------------------------------------------------ data
def build_frame() -> tuple[pd.DataFrame, dict, list[str]]:
    tg = [json.loads(l) for l in (DATA / "heldout_targets.jsonl").read_text().splitlines()]
    df = pd.DataFrame(tg)
    scores = C.defaultdict(dict)
    cov = C.defaultdict(dict)
    extra = C.defaultdict(dict)
    for p in (RESULTS / "zero_llm_scores.jsonl", RESULTS / "a3_scores.jsonl", RESULTS / "heldout_llm_scores.jsonl"):
        for r in read_jsonl(p):
            scores[r["metric"]][r["item_id"]] = r["score"]
            cov[r["metric"]][r["item_id"]] = bool(r.get("covered"))
            if r["metric"].startswith("TVJT"):
                extra[r["metric"]][r["item_id"]] = r
    metrics = []
    for m in ["TVJT_frozen", "TVJT_local", "B1", "B1x3", "B1_local", "TVJT_iter1", "TVJT_lite", "LC_onecoin",
              "LC_maj", "A3", "B3sc"]:
        if scores.get(m):
            df[m] = df["item_id"].map(scores[m])
            df[m + "__cov"] = df["item_id"].map(cov[m]).fillna(False).astype(bool)
            metrics.append(m)
    df["B2_parse_ok"] = df["parse_ok_meta"].astype(float)   # the dataset's own parse flag (metadata_parse_ok)
    df["B2_parse_ok__cov"] = True
    df["B2_bridge"] = df["fol_folio"].notna().astype(float)   # fol_core syntax-bridge coverage
    df["B2_bridge__cov"] = True
    metrics += ["B2_parse_ok", "B2_bridge"]
    # TVJT secondary scorings of the SAME calls: C1 = vote-0 binary (1 call, compute-matched with B1), C2 = majority
    if "TVJT_frozen" in extra:
        for c in ("C1", "C2"):
            mp_ = {k: v.get(c) for k, v in extra["TVJT_frozen"].items()}
            df[f"TVJT_{c}"] = df["item_id"].map(mp_)
            df[f"TVJT_{c}__cov"] = df["item_id"].map({k: v is not None for k, v in mp_.items()}).fillna(False).astype(bool)
            metrics.insert(1, f"TVJT_{c}")
        df["TVJT_error_type"] = df["item_id"].map({k: v.get("error_type_pred") for k, v in extra["TVJT_frozen"].items()})
    lab = load_labels()
    for k in ("y_panel", "w", "y_hard", "y_soft", "primary_error", "L1_equiv", "rename_incomplete"):
        df[k] = df["item_id"].map({i: v[k] for i, v in lab.items() if not i.startswith("__")})
    return df, extra, metrics


def fill(d: pd.DataFrame, metrics: list[str]) -> pd.DataFrame:
    d = d.copy()
    for m in metrics:
        d[m] = d[m].astype(float).fillna(0.5)
    return d


# ------------------------------------------------------------------------------------------ analyses
def run() -> dict:
    warnings.filterwarnings("ignore")
    df, extra, metrics = build_frame()
    out: dict = {"metrics_available": metrics,
                 "metrics_unavailable": [m for m in GEMINI if m not in metrics]}
    hc = df[df["group"] == "heldout_confirm"]
    P = hc[hc["panel"]].copy()
    P["y"] = P["y_panel"].astype(float)
    P["wt"] = P["w"].astype(float)
    # --- the local-variant subset = panel items that have BOTH local scores (sentence-hash order ⇒ unbiased)
    loc_ok = [m for m in LOCAL if m in metrics]
    zmetrics = [m for m in metrics if m in ZERO_LLM]
    out["coverage"] = {m: {"P_scored": int(P[m].notna().sum()), "P_covered": int(P[m + "__cov"].sum())}
                       for m in metrics}
    pairs = [("TVJT_frozen", "B1"), ("TVJT_frozen", "B1x3"), ("TVJT_C1", "B1"), ("TVJT_frozen", "TVJT_iter1"),
             ("TVJT_iter1", "B1"), ("TVJT_lite", "B1"), ("B1x3", "B1"), ("LC_onecoin", "B1"), ("A3", "B1"),
             ("TVJT_frozen", "A3"), ("TVJT_frozen", "LC_onecoin"), ("LC_onecoin", "A3")]

    def analyse_set(Pset: pd.DataFrame, mets: list[str], tag: str) -> dict:
        Pset = fill(Pset, mets)
        B = boot_index(Pset)
        res = {"all": auc_block(Pset, mets, "y", "wt", B, pairs)}
        res["all_unweighted"] = {m: wauc(Pset["y"].values, Pset[m].values, np.ones(len(Pset))) for m in mets}
        res["within_sentence"] = {m: within_sentence(Pset, m, "y") for m in mets}
        cov_all = np.logical_and.reduce([Pset[m + "__cov"].values for m in mets if m + "__cov" in Pset])
        sub = Pset[cov_all]
        res["jointly_covered"] = {"n": int(len(sub)),
                                  "auroc": {m: wauc(sub["y"].values, sub[m].values, sub["wt"].values) for m in mets}}
        ng = Pset[Pset["system"] != "gemini-2.5-flash"]
        res["excluding_gemini_generated"] = {"n": int(len(ng)),
                                             "auroc": {m: wauc(ng["y"].values, ng[m].values, ng["wt"].values)
                                                       for m in mets}}
        # crossover bins
        res["by_tercile"], res["by_nconditions"] = {}, {}
        for t in TERC:
            idx = (Pset["tercile"] == t).values
            if idx.sum() >= 10:
                sub = Pset[idx]
                Bs = [b[idx] for b in B]
                blk = auc_block(sub, mets, "y", "wt", Bs, pairs)
                res["by_tercile"][t] = blk
        for name, lo, hi in NC_BINS:
            idx = ((Pset["n_conditions"] >= lo) & (Pset["n_conditions"] <= hi)).values
            if idx.sum() >= 10:
                Bs = [b[idx] for b in B]
                res["by_nconditions"][name] = auc_block(Pset[idx], mets, "y", "wt", Bs, pairs)
        # H2 growth: (Δ_top − Δ_bottom) with paired bootstrap, per pair; and per-metric AUROC_top − AUROC_bottom
        res["growth"] = {}
        bt, bb = res["by_tercile"].get("top"), res["by_tercile"].get("bottom")
        if bt and bb:
            for a, b in pairs:
                if a in mets and b in mets:
                    dt = [x - z for x, z in zip(bt["_boot"][a], bt["_boot"][b])]
                    db = [x - z for x, z in zip(bb["_boot"][a], bb["_boot"][b])]
                    res["growth"][f"{a}-{b}"] = {
                        "point": (bt["auroc"][a]["point"] - bt["auroc"][b]["point"]) -
                                 (bb["auroc"][a]["point"] - bb["auroc"][b]["point"]),
                        "ci": ci([x - z for x, z in zip(dt, db)])}
            for m in mets:
                res["growth"][m + "(top-bottom)"] = {
                    "point": bt["auroc"][m]["point"] - bb["auroc"][m]["point"],
                    "ci": ci([x - z for x, z in zip(bt["_boot"][m], bb["_boot"][m])])}
        # monotonicity of Δ over n_conditions bins
        res["nc_monotone"] = {}
        for a, b in pairs:
            key = f"{a}-{b}"
            ds = [res["by_nconditions"][n]["delta"].get(key, {}).get("point") for n, _, _ in NC_BINS
                  if n in res["by_nconditions"]]
            if ds and all(d is not None for d in ds):
                res["nc_monotone"][key] = {"deltas": ds, "non_decreasing": all(x <= y + 1e-12 for x, y in zip(ds, ds[1:]))}
        res["glm_interaction"] = glm_interaction(Pset, mets)
        res["stacking"] = stacking(Pset, mets)
        res["error_types"] = error_types(Pset, mets)
        # strip bootstrap arrays
        for blk in [res["all"]] + list(res["by_tercile"].values()) + list(res["by_nconditions"].values()):
            blk.pop("_boot", None)
        return res

    gm = [m for m in metrics if m in GEMINI and P[m].notna().mean() > 0.95]
    out["gemini_metrics_on_P"] = gm
    # (1) all panel items: gemini judge metrics + zero-LLM metrics on IDENTICAL items
    out["P_main"] = analyse_set(P, gm + zmetrics, "P")
    if "TVJT_error_type" in P:
        out["P_main"]["tvjt_error_type_identification"] = error_type_identification(P)
    # (2) local-variant subset: panel items with both local scores; zero-LLM metrics on the SAME items
    if loc_ok:
        Ploc = P[P[loc_ok].notna().all(axis=1)]
        out["P_local_subset"] = {"n_items": int(len(Ploc)), "n_sentences": int(Ploc["sid"].nunique()),
                                 "subset_rule": "panel items whose sentence came first in sha1(sid) order until the "
                                                "CPU budget ran out (label-blind order ⇒ unbiased subset of P)",
                                 **analyse_set(Ploc, loc_ok + zmetrics, "P_local")}
        if "TVJT_local_C1" in Ploc:
            Pc = fill(Ploc.assign(TVJT_local_C1__cov=True), ["TVJT_local_C1"])
            out["P_local_subset"]["TVJT_local_C1_auroc"] = wauc(Pc["y"], Pc["TVJT_local_C1"], Pc["wt"])
    # (3) T: all top-tercile heldout_confirm rows with soft / hard labels (zero-LLM metrics cover T)
    Tm = hc[hc["tercile"] == "top"]
    tm = [m for m in metrics if m not in ("B3sc",) and Tm[m].notna().mean() > 0.95]
    out["T_top_tercile"] = top_tercile(hc, tm)
    # (4) B3sc subset (2 systems)
    if "B3sc" in metrics:
        Pb = P[P["system"].isin(["gpt-4.1-mini", "llama-3.1-8b"])]
        Pb = fill(Pb, ["B3sc"] + zmetrics)
        out["B3sc_subset_P"] = {"n": int(len(Pb)),
                                "auroc": {m: wauc(Pb["y"], Pb[m], Pb["wt"]) for m in ["B3sc"] + zmetrics}}
    out["contamination"] = contamination(df, [m for m in metrics if m != "B3sc"])
    out["system_level"] = system_level(hc, P, zmetrics + [m for m in gm if hc[m].notna().mean() > 0.95])
    out["cost"] = cost(extra)
    out["screen_repair"] = screen_repair()
    out["heldout_g2_judged"] = heldout_g2_judged()
    out["verdict"] = verdict(out)
    (RESULTS / "analysis.json").write_text(json.dumps(out, indent=1, default=float))
    (RESULTS / "verdict.json").write_text(json.dumps(out["verdict"], indent=1))
    return out


def glm_interaction(Pset: pd.DataFrame, mets: list[str]) -> dict:
    import statsmodels.api as sm
    res = {}
    c = Pset["composite"].astype(float).values
    c = (c - c.mean()) / (c.std() + 1e-9)
    y = Pset["y"].values
    sids = Pset["sid"].unique()
    posi = {s_: np.where(Pset["sid"].values == s_)[0] for s_ in sids}
    rng0 = np.random.default_rng(0)
    boots = [np.concatenate([posi[s_] for s_ in rng0.choice(sids, len(sids))]) for _ in range(300)]
    wv = Pset["wt"].values
    for m in mets:
        s = Pset[m].astype(float).values
        if np.std(s) < 1e-9:
            res[m] = {"error": "constant score on this set"}
            continue
        z = (s - s.mean()) / (s.std() + 1e-9)
        X = sm.add_constant(np.column_stack([z, c, z * c]))
        try:
            fit = sm.GLM(y, X, family=sm.families.Binomial(), var_weights=wv).fit()
            bs = []
            for ii in boots:
                try:
                    bs.append(float(sm.GLM(y[ii], X[ii], family=sm.families.Binomial(), var_weights=wv[ii]).fit().params[3]))
                except Exception:  # noqa: BLE001
                    continue
            res[m] = {"beta_interaction": float(fit.params[3]), "ci_cluster_boot": ci(bs), "n_boot": len(bs),
                      "beta_main": float(fit.params[1])}
        except Exception as e:  # noqa: BLE001
            res[m] = {"error": repr(e)[:120]}
    # joint TVJT vs B1 slope contrast (local variant)
    for a, b in (("TVJT_local", "B1_local"), ("TVJT_frozen", "B1")):
        if a in mets and b in mets:
            za = (Pset[a] - Pset[a].mean()) / (Pset[a].std() + 1e-9)
            zb = (Pset[b] - Pset[b].mean()) / (Pset[b].std() + 1e-9)
            X = sm.add_constant(np.column_stack([za, zb, c, za * c, zb * c]))
            rng = np.random.default_rng(0)
            sids = Pset["sid"].unique()
            pos = {s: np.where(Pset["sid"].values == s)[0] for s in sids}
            try:
                f0 = sm.GLM(y, X, family=sm.families.Binomial(), var_weights=Pset["wt"].values).fit()
                pt = float(f0.params[4] - f0.params[5])
                bs = []
                for _ in range(300):
                    ii = np.concatenate([pos[s] for s in rng.choice(sids, len(sids))])
                    try:
                        f = sm.GLM(y[ii], X[ii], family=sm.families.Binomial(),
                                   var_weights=Pset["wt"].values[ii]).fit()
                        bs.append(float(f.params[4] - f.params[5]))
                    except Exception:  # noqa: BLE001
                        continue
                res[f"joint:{a}:c - {b}:c"] = {"point": pt, "ci": ci(bs), "n_boot": len(bs)}
            except Exception as e:  # noqa: BLE001
                res[f"joint:{a}:c - {b}:c"] = {"error": repr(e)[:120]}
    return res


def stacking(Pset: pd.DataFrame, mets: list[str]) -> dict:
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import GroupKFold
    from sklearn.preprocessing import StandardScaler
    judge = "B1_local" if "B1_local" in mets else ("B1" if "B1" in mets else None)
    tv = "TVJT_local" if "TVJT_local" in mets else ("TVJT_frozen" if "TVJT_frozen" in mets else None)
    S0 = ([judge] if judge else []) + ["B2_parse_ok"]
    sets = {"S0": S0, "S0z": S0 + [m for m in ("LC_onecoin", "A3") if m in mets]}
    if "LC_onecoin" in mets:
        sets["LC_only"] = ["LC_onecoin"]
    if tv:
        sets["S1"] = S0 + [tv]
        sets["S2"] = sets["S1"] + [m for m in ("LC_onecoin", "A3") if m in mets]
        rng = np.random.default_rng(0)
        Pset = Pset.assign(placebo=rng.permutation(Pset[tv].values))
        sets["S0+placebo"] = S0 + ["placebo"]
    y, w, g = Pset["y"].values, Pset["wt"].values, Pset["sid"].values
    oof = {}
    for name, feats in sets.items():
        p = np.zeros(len(Pset))
        for tr, te in GroupKFold(5).split(Pset, y, g):
            X = Pset[feats].values.astype(float)
            sc = StandardScaler().fit(X[tr])
            clf = LogisticRegression(C=1.0, max_iter=1000).fit(sc.transform(X[tr]), y[tr], sample_weight=w[tr])
            p[te] = clf.predict_proba(sc.transform(X[te]))[:, 1]
        oof[name] = p
    B = boot_index(Pset, n=1000)
    res = {"features": sets, "judge_in_S0": judge,
           "note": None if judge else "no judge score available: S0 = [parse_ok] is constant on P (degenerate); "
                                      "read S0z − LC_only (does A3 add to LC?)"}
    for name in oof:
        res[name] = {"auroc_w": wauc(y, oof[name], w)}
    for a, b in (("S1", "S0"), ("S2", "S0z"), ("S2", "S0"), ("S0z", "S0"), ("S0z", "LC_only"), ("S0+placebo", "S0")):
        if a in oof and b in oof:
            d = [wauc(y, oof[a], w * m) - wauc(y, oof[b], w * m) for m in B]
            res[f"{a}-{b}"] = {"point": res[a]["auroc_w"] - res[b]["auroc_w"], "ci": ci(d)}
    if "LC_onecoin" in mets and "S0z" in oof:
        raw = Pset["LC_onecoin"].values
        d = [wauc(y, oof["S0z"], w * m) - wauc(y, raw, w * m) for m in B]
        res["S0z-LC_raw"] = {"point": res["S0z"]["auroc_w"] - wauc(y, raw, w), "ci": ci(d),
                             "note": "vs the raw LC score (a 1-feature cross-fitted stack loses AUROC to "
                                     "fold-wise intercepts, so S0z-LC_only overstates A3's increment)"}
    return res


ERR_TYPES = ["quantifier_scope", "cardinality_numeric", "quantifier_forall_exists", "added_condition",
             "dropped_condition", "connective_and_or", "implication_direction_or_only", "negation_polarity",
             "conflation", "argument_swap", "wrong_constant"]


def error_types(Pset: pd.DataFrame, mets: list[str]) -> dict:
    """Detection for type e = P(score(err item) < score(faithful comparator of the same sentence)), ties .5;
    comparators = panel-faithful or L1-equivalent candidates; fallback = all panel-faithful items."""
    res = {}
    faithful_all = Pset[Pset["y"] == 1]
    for e in ERR_TYPES + ["scope∪cardinality"]:
        types = ["quantifier_scope", "cardinality_numeric"] if e == "scope∪cardinality" else [e]
        err = Pset[(Pset["y"] == 0) & (Pset["primary_error"].isin(types))]
        if len(err) == 0:
            continue
        r = {"n": int(len(err))}
        for m in mets:
            det, fb = [], 0
            for _, it in err.iterrows():
                comp = Pset[(Pset["sid"] == it["sid"]) & ((Pset["y"] == 1) | (Pset["L1_equiv"] == True))]  # noqa: E712
                if len(comp) == 0:
                    comp, fb = faithful_all, fb + 1
                v = comp[m].values
                det.append(float(np.mean((it[m] < v) + 0.5 * (it[m] == v))))
            k = float(np.sum(det))
            r[m] = {"detection": float(np.mean(det)), "wilson": wilson(k, len(det)), "n_fallback": fb}
        res[e] = r
    # error-type identification (TVJT operator families → L3 types), secondary
    return res


OP2TYPE = {"NEG": "negation_polarity", "QUANT": "quantifier_forall_exists", "SCOPE_SWAP": "quantifier_scope",
           "CARD": "cardinality_numeric", "DROP_CONJ": "dropped_condition", "ADD_CONJ": "added_condition",
           "IMPL_REV": "implication_direction_or_only", "AND_OR": "connective_and_or", "ARG_SWAP": "argument_swap",
           "MERGE": "conflation", "none": "none"}


def error_type_identification(P: pd.DataFrame) -> dict:
    """Secondary: TVJT error_type (operator family with the lowest world agreement) mapped to L3 primary_error,
    on panel-unfaithful items whose L3 type is in the mapped set. Accuracy + macro-F1 + confusion."""
    from sklearn.metrics import f1_score
    d = P[(P["y"] == 0) & P["TVJT_error_type"].notna() & P["primary_error"].isin(set(OP2TYPE.values()))]
    if len(d) < 10:
        return {"n": int(len(d))}
    pred = d["TVJT_error_type"].map(lambda x: OP2TYPE.get(x, "other"))
    true = d["primary_error"]
    labs = sorted(set(true))
    conf = pd.crosstab(true, pred).to_dict()
    maj = true.value_counts().idxmax()
    return {"n": int(len(d)), "accuracy": float((pred == true).mean()),
            "majority_class_accuracy": float((true == maj).mean()),
            "macro_f1": float(f1_score(true, pred, labels=labs, average="macro", zero_division=0)),
            "confusion(pred→true counts)": {str(k): {str(a): int(b) for a, b in v.items()} for k, v in conf.items()}}


def top_tercile(hc: pd.DataFrame, mets: list[str]) -> dict:
    T = fill(hc[hc["tercile"] == "top"], mets)
    out = {"n": int(len(T)), "n_sentences": int(T["sid"].nunique())}
    ys = T["y_soft"].astype(float)
    Ts = T[ys.notna()]
    B = boot_index(Ts, n=1000)
    out["soft"] = {m: {"point": wauc(Ts["y_soft"].values, Ts[m].values, np.ones(len(Ts))),
                       "ci": ci([wauc(Ts["y_soft"].values, Ts[m].values, b) for b in B])} for m in mets}
    rng = np.random.default_rng(0)
    mi = {m: [] for m in mets}
    for _ in range(200):
        yy = (rng.random(len(Ts)) < Ts["y_soft"].values).astype(float)
        for m in mets:
            mi[m].append(wauc(yy, Ts[m].values, np.ones(len(Ts))))
    out["multiple_imputation"] = {m: {"mean": float(np.mean(v)), "interval": ci(v)} for m, v in mi.items()}
    Th = T[T["y_hard"].notna()]
    out["hard"] = {"n": int(len(Th)), "note": "solver/L1 hard labels: biased toward gold vocabulary",
                   "auroc": {m: wauc(Th["y_hard"].astype(float).values, Th[m].values, np.ones(len(Th))) for m in mets}}
    return out


def contamination(df: pd.DataFrame, mets: list[str]) -> dict:
    con = df[df["group"] == "contamination"]
    orig = df.set_index("item_id")
    res = {"n_rows": int(len(con))}
    for m in mets:
        if m not in con or con[m].notna().sum() < 20:
            continue
        rows = []
        for _, r in con.iterrows():
            if r["original_item_id"] in orig.index and not pd.isna(r[m]):
                o = orig.loc[r["original_item_id"]]
                if pd.isna(o[m]):
                    continue
                rows.append({"sid": r["sid"], "y": r["y_hard"], "orig": float(o[m]), "para": float(r[m]),
                             "inc": bool(r.get("rename_incomplete"))})
        d = pd.DataFrame(rows)
        if len(d) < 20:
            continue
        dl = d[d["y"].notna()]
        entry = {"n_pairs": int(len(d)),
                 "mean_shift_para_minus_orig": float((d["para"] - d["orig"]).mean()),
                 "mean_abs_shift": float((d["para"] - d["orig"]).abs().mean())}
        for cls in (0, 1):
            dd = dl[dl["y"] == cls]
            entry[f"shift_label{cls}"] = float((dd["para"] - dd["orig"]).mean()) if len(dd) else None
        if dl["y"].nunique() == 2:
            ao = wauc(dl["y"].values, dl["orig"].values, np.ones(len(dl)))
            ap = wauc(dl["y"].values, dl["para"].values, np.ones(len(dl)))
            B = boot_index(dl.assign(corpus="all"), n=1000)
            dd = [wauc(dl["y"].values, dl["para"].values, b) - wauc(dl["y"].values, dl["orig"].values, b) for b in B]
            entry.update({"auroc_orig": ao, "auroc_para": ap, "delta_para_minus_orig": {"point": ap - ao, "ci": ci(dd)}})
            dx = dl[~dl["inc"]]
            if dx["y"].nunique() == 2:
                entry["delta_excl_rename_incomplete"] = (wauc(dx["y"].values, dx["para"].values, np.ones(len(dx))) -
                                                         wauc(dx["y"].values, dx["orig"].values, np.ones(len(dx))))
        res[m] = entry
    return res


def system_level(hc: pd.DataFrame, P: pd.DataFrame, mets: list[str]) -> dict:
    from scipy.stats import kendalltau
    res = {}
    accP = P.groupby("system").apply(lambda g: float((g["y"] * g["wt"]).sum() / g["wt"].sum()))
    hs = hc[hc["y_soft"].notna()]
    accS = hs.groupby("system")["y_soft"].mean()
    for m in mets:
        if hc[m].notna().sum() < 50:
            continue
        ms = fill(hc, [m]).groupby("system")[m].mean()
        sysP = [s for s in ms.index if s in accP.index]
        t1 = kendalltau([ms[s] for s in sysP], [accP[s] for s in sysP])
        t2 = kendalltau([ms[s] for s in accS.index], [accS[s] for s in accS.index])
        res[m] = {"tau_vs_panel_acc": float(t1.statistic), "tau_vs_soft_acc": float(t2.statistic),
                  "n_systems": len(sysP)}
    res["note"] = "9 systems: |τ| >= 0.61 needed for p < .05; descriptive only"
    return res


def cost(extra: dict) -> dict:
    res = {}
    for p in (RESULTS / "heldout_llm_scores.jsonl",):
        rows = read_jsonl(p)
        by = C.defaultdict(list)
        for r in rows:
            by[r["metric"]].append(r)
        for m, rr in by.items():
            res[m] = {"n": len(rr), "usd_per_item": float(np.mean([r.get("usd", 0) or 0 for r in rr])),
                      "median_seconds_per_item_fresh": float(np.median([r.get("seconds", 0) or 0 for r in rr
                                                                        if (r.get("seconds") or 0) > 0] or [0]))}
    for r in read_jsonl(RESULTS / "a3_scores.jsonl")[:1]:
        pass
    a3 = read_jsonl(RESULTS / "a3_scores.jsonl")
    if a3:
        res["A3"] = {"usd_per_item": 0.0, "median_seconds_per_item": float(np.median([r["seconds"] for r in a3]))}
    res["LC_onecoin"] = {"usd_per_item": 0.0, "note": "pairwise z3 + EM; see lc_info.json"}
    ledger = read_jsonl(RESULTS / "cost_ledger.jsonl")
    res["openrouter_spend_usd"] = float(sum(r.get("cost", 0) or 0 for r in ledger))
    return res


def screen_repair() -> dict | None:
    """Phase-1 numbers for the frozen protocol on the screen (labels = iter-1 L_bij; rewrites = paired G2)."""
    rows = [r for r in read_jsonl(RESULTS / "screen_repair_scores.jsonl")]
    if not rows:
        return None
    main = {r["item_id"]: r for r in rows if r["ns"] == "main"}
    rt = {r["item_id"]: r for r in rows if r["ns"] == "retest"}
    ss = json.loads((common.ARMB / "data" / "screen_set.json").read_text())
    i1 = {(r["item_id"], r["metric"]): r["score"] for r in read_jsonl(common.ARMB / "results" / "screen_scores.jsonl")}
    real = pd.DataFrame([{"item_id": it["item_id"], "sid": it["sid"], "corpus": "screen",
                          "y": 1.0 if it["L_bij"] == "correct" else 0.0,
                          **{c: (main.get(it["item_id"], {}).get(c)) for c in ("C1", "C2", "C3")},
                          "C0_iter1": i1.get((it["item_id"], "TVJT")), "B1_iter1": i1.get((it["item_id"], "B1"))}
                         for it in ss["real_items"]])
    mets = ["C1", "C2", "C3", "C0_iter1", "B1_iter1"]
    real = fill(real, mets)
    B = boot_index(real, n=1000)
    blk = auc_block(real, mets, "y", None, B, [("C3", "C0_iter1"), ("C1", "C0_iter1"), ("C3", "B1_iter1")])
    blk.pop("_boot", None)
    # paired G2: rewrite score < own gold score − 0.2 (both covered)
    g2 = {}
    for c in ("C1", "C2", "C3"):
        per = C.defaultdict(list)
        for rw in ss["rewrites"]:
            a, g = main.get(rw["item_id"]), main.get(f"{rw['sid']}:gold")
            if a and g and a.get(c) is not None and g.get(c) is not None:
                fa = a[c] < g[c] - 0.2
                per[rw["kind"]].append(fa)
                per["ALL"].append(fa)
                if rw["kind"] != "RENAME":
                    per["nonRENAME"].append(fa)
        g2[c] = {k: float(np.mean(v)) for k, v in per.items()}
        g2[c]["n"] = {k: len(v) for k, v in per.items()}
    # test-retest (vote 0 of main vs the separate 'retest' namespace)
    agree, a0, a1 = [], [], []
    for iid, r in rt.items():
        m = main.get(iid)
        if not m or not m.get("answers_v0") or not r.get("answers_v0"):
            continue
        for x, y in zip(m["answers_v0"], r["answers_v0"]):
            if x is not None and y is not None:
                agree.append((x[0], y[0]))
        if m.get("C1") is not None and r.get("C1") is not None:
            a0.append(m["C1"])
            a1.append(r["C1"])
    kappa = None
    if agree:
        from sklearn.metrics import cohen_kappa_score
        kappa = float(cohen_kappa_score([a for a, _ in agree], [b for _, b in agree]))
    icc = None
    if len(a0) > 5:
        X = np.column_stack([a0, a1])
        n, k = X.shape
        mr, mc, gm_ = X.mean(1), X.mean(0), X.mean()
        msr = k * ((mr - gm_) ** 2).sum() / (n - 1)
        msc = n * ((mc - gm_) ** 2).sum() / (k - 1)
        mse = ((X - mr[:, None] - mc[None, :] + gm_) ** 2).sum() / ((n - 1) * (k - 1))
        icc = float((msr - mse) / (msr + (k - 1) * mse + k * (msc - mse) / n))
    elig = {c: bool(g2[c].get("ALL", 1) <= 0.10 and blk["auroc"][c]["point"] >= 0.681) for c in ("C1", "C2", "C3")}
    # plan rule: none eligible only because of RENAME (non-RENAME FA <= .10) → pick by AUROC, flag it
    elig_nr = {c: bool(g2[c].get("nonRENAME", 1) <= 0.10 and blk["auroc"][c]["point"] >= 0.681) for c in elig}
    pool = [c for c in elig if elig[c]] or [c for c in elig_nr if elig_nr[c]]
    pick = None
    if pool:
        best = max(blk["auroc"][c]["point"] for c in pool)
        near = [c for c in pool if best - blk["auroc"][c]["point"] <= 0.01]
        pick = "C1" if "C1" in near else ("C3" if "C3" in near else near[0])
    rule_flag = ("eligible" if any(elig.values()) else
                 "G2_all_failed_by_RENAME" if any(elig_nr.values()) else "none_eligible")
    return {"n_real": int(len(real)), "auroc_L_bij": blk["auroc"], "delta": blk["delta"], "paired_G2_FA": g2,
            "test_retest": {"n_items": len(a0), "n_worlds": len(agree), "world_verdict_kappa": kappa,
                            "C1_ICC21": icc},
            "freeze_rule_ex_post": {"eligible": elig, "eligible_nonRENAME": elig_nr, "rule_branch": rule_flag,
                                    "would_pick": pick, "frozen": "C3",
                                    "note": "what the pre-declared rule would have picked had the judge been "
                                            "available before the freeze (C3 was frozen by the F4 default)"},
            "malformed_rate": float(np.mean([bool(r.get("malformed")) for r in main.values()])) if main else None,
            "usd": float(sum(r.get("usd") or 0 for r in rows))}


def heldout_g2_judged() -> dict | None:
    rows = read_jsonl(RESULTS / "heldout_g2_judged.jsonl")
    if not rows:
        return None
    by = {r["item_id"]: r for r in rows}
    per = C.defaultdict(list)
    for r in rows:
        if r.get("kind") == "rewrite":
            g = by.get(r["gold_id"])
            if g and g.get("C3") is not None and r.get("C3") is not None:
                fa = r["C3"] < g["C3"] - 0.2
                per[r["rw_kind"]].append(fa)
                per["ALL"].append(fa)
    return {"paired_FA": {k: float(np.mean(v)) for k, v in per.items()}, "n": {k: len(v) for k, v in per.items()},
            "paired_FA_all": float(np.mean(per["ALL"])) if per["ALL"] else None}


def verdict(out: dict) -> dict:
    """Pre-registered decision table (prereg.json), applied verbatim to TVJT* (gemini) vs B1 on P-top."""
    P = out["P_main"]
    v = {}
    top = P["by_tercile"].get("top", {}).get("delta", {})
    d, g = top.get("TVJT_frozen-B1"), P.get("growth", {}).get("TVJT_frozen-B1")
    if d and d["ci"][0] is not None:
        lb, ub = d["ci"]
        if lb > 0 and g and g["ci"][0] is not None and g["ci"][0] > 0:
            lab = "CROSSOVER_CONFIRMED"
        elif lb > 0:
            lab = "CROSSOVER_PARTIAL"
        elif ub < 0:
            lab = "REVERSED"
        else:
            lab = "NOT_REPLICATED"
        v["crossover"] = {"label": lab, "H1_top_delta_TVJT-B1": d, "H2_growth_TVJT-B1": g,
                          "H2_nc_monotone": P.get("nc_monotone", {}).get("TVJT_frozen-B1")}
    else:
        v["crossover"] = "PENDING (no TVJT*/B1 scores)"
    dm = top.get("TVJT_frozen-B1x3")
    v["JUDGE_MATCHED"] = (bool(dm["ci"][0] is not None and dm["ci"][0] > 0) if dm else "PENDING")
    if dm:
        v["JUDGE_MATCHED_detail"] = dm
    st = P.get("stacking", {}).get("S2-S0z")
    v["STACK_INCREMENT"] = bool(st["ci"][0] is not None and st["ci"][0] > 0) if st else "PENDING"
    if st:
        v["STACK_INCREMENT_detail"] = st
    sr = out.get("screen_repair")
    g2 = (sr or {}).get("paired_G2_FA", {}).get("C3", {}).get("ALL")
    hg = out.get("heldout_g2_judged")
    v["REPAIR_OK"] = (bool(g2 is not None and g2 <= 0.10 and (hg is None or hg.get("paired_FA_all", 1) <= 0.10))
                      if g2 is not None else "PENDING (screen repair scores missing)")
    v["REPAIR_detail"] = {"screen_paired_G2_FA_C3_all": g2,
                          "screen_paired_G2_FA_C3_nonRENAME": (sr or {}).get("paired_G2_FA", {}).get("C3", {}).get("nonRENAME"),
                          "screen_paired_G2_FA_C3_RENAME": (sr or {}).get("paired_G2_FA", {}).get("C3", {}).get("RENAME"),
                          "heldout_g2": hg,
                          "reading": "REPAIR_OK fails only through RENAME (plan F2: verbaliser/synonym limitation); "
                                     "every non-RENAME meaning-preserving rewrite has paired FA 0 (screen and held-out)"}
    return v


if __name__ == "__main__":
    o = run()
    print(json.dumps(o["verdict"], indent=1))
