"""Analysis: AUROC_real with sentence-clustered bootstrap CIs, gates G1-G4, per-operator detection, error-type
confusion, rewrite false alarms, oracle accuracies, costs, label-noise estimates, pre-registered selection rule."""
from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger
from scipy.stats import spearmanr
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, roc_auc_score
from sklearn.model_selection import GroupKFold

ROOT = Path(__file__).resolve().parents[1]
RULE = ["TVJT", "NLI_deberta", "LC_onecoin"]
SECONDARY = ["B1", "B2", "B3sc", "TVJT_gloss", "TVJT_nv", "NLI_deberta_gloss", "NLI_gemini", "LC_huiwalter", "LC_maj",
             "LC_ds_binary", "LC_onecoin_str"]
LC_METRICS = {"LC_onecoin", "LC_huiwalter", "LC_maj", "LC_ds_binary", "LC_onecoin_str", "B3sc"}
OPS = ["NEG", "QUANT", "IMPL_REV", "DROP_CONJ", "ADD_CONJ", "ARG_SWAP", "AND_OR", "SCOPE_SWAP", "MERGE", "CARD"]
N_BOOT = 1000


def dirs(limit):
    d = ROOT / ("data" if limit is None else f"runs/mini_{limit}/data")
    r = ROOT / ("results" if limit is None else f"runs/mini_{limit}/results")
    f = ROOT / ("figures" if limit is None else f"runs/mini_{limit}/figures")
    f.mkdir(parents=True, exist_ok=True)
    return d, r, f


def read_jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


def auc(y, s) -> float:
    """Rank-based (Mann-Whitney) AUROC with tie correction; identical to sklearn roc_auc_score, ~20x faster."""
    from scipy.stats import rankdata
    y = np.asarray(y).astype(int)
    n1 = int(y.sum())
    n0 = len(y) - n1
    if n1 == 0 or n0 == 0:
        return float("nan")
    rk = rankdata(np.asarray(s, dtype=float))
    return float((rk[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def cluster_boot(groups: np.ndarray, fn, n: int = N_BOOT, seed: int = 0) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    ug = np.unique(groups)
    idx_by = {g: np.where(groups == g)[0] for g in ug}
    vals = []
    for _ in range(n):
        pick = rng.choice(ug, size=len(ug), replace=True)
        idx = np.concatenate([idx_by[g] for g in pick])
        v = fn(idx)
        if not math.isnan(v):
            vals.append(v)
    if not vals:
        return float("nan"), float("nan")
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def auroc_ci(df: pd.DataFrame, col: str, lab: str = "y") -> dict:
    d = df[df[lab].notna()]
    if len(d) < 5 or d[lab].nunique() < 2:
        return {"auroc": None, "ci": [None, None], "n": int(len(d))}
    y, s, g = d[lab].values.astype(int), d[col].values.astype(float), d["sid"].values
    a = auc(y, s)
    lo, hi = cluster_boot(g, lambda idx: auc(y[idx], s[idx]))
    return {"auroc": round(a, 4), "ci": [round(lo, 4), round(hi, 4)], "n": int(len(d)), "n_pos": int(y.sum())}


def wilson(k: float, n: int, z: float = 1.96) -> list:
    if n == 0:
        return [None, None]
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [round(c - h, 4), round(c + h, 4)]


def youden(pos: np.ndarray, neg: np.ndarray) -> float:
    vals = np.unique(np.concatenate([pos, neg]))
    best, tau = -1, 0.5
    for t in vals:
        j = (pos >= t).mean() - (neg >= t).mean()
        if j > best:
            best, tau = j, t
    return float(tau)


def oof_delta(df: pd.DataFrame, feat: list[str], base: list[str], seed: int = 0) -> dict:
    d = df[df["y"].notna()].reset_index(drop=True)
    y = d["y"].values.astype(int)
    g = d["sid"].values
    gkf = GroupKFold(n_splits=5)
    oof_b = np.zeros(len(d))
    oof_f = np.zeros(len(d))
    for tr, te in gkf.split(d, y, g):
        for cols, oof in ((base, oof_b), (feat, oof_f)):
            X = d[cols].values.astype(float)
            if len(np.unique(y[tr])) < 2:
                oof[te] = 0.5
                continue
            m = LogisticRegression(C=1.0, max_iter=1000).fit(X[tr], y[tr])
            oof[te] = m.predict_proba(X[te])[:, 1]
    a_b, a_f = auc(y, oof_b), auc(y, oof_f)
    lo, hi = cluster_boot(g, lambda idx: auc(y[idx], oof_f[idx]) - auc(y[idx], oof_b[idx]), seed=seed)
    return {"auroc_base": round(a_b, 4), "auroc_full": round(a_f, 4), "delta": round(a_f - a_b, 4),
            "ci": [round(lo, 4), round(hi, 4)], "pass": bool(lo > 0), "oof_full": oof_f.tolist(), "n": int(len(d))}


def run_analysis(limit) -> dict:
    d, r, fdir = dirs(limit)
    ss = json.loads((d / "screen_set.json").read_text())
    S = pd.DataFrame(read_jsonl(r / "screen_scores.jsonl"))
    sent = {s["sid"]: s for s in ss["sentences"]}
    real = pd.DataFrame(ss["real_items"])
    real["tercile"] = real["sid"].map(lambda x: sent[x]["tercile"])
    real["recipe_gold_source"] = real["sid"].map(lambda x: sent[x]["recipe_gold_source"])
    real["gold_source"] = real["sid"].map(lambda x: sent[x]["gold_source"])
    for lab in ("L_bij", "L_bij_orig", "L_str", "L_str_orig", "L_bij_cur", "L_any"):
        real["y_" + lab] = real[lab].map({"correct": 1, "incorrect": 0})
    real["y"] = real["y_L_bij"]
    metrics = [m for m in RULE + SECONDARY if m in set(S["metric"])]
    piv = S[S["item_kind"] == "real"].pivot_table(index="item_id", columns="metric", values="score", aggfunc="first")
    cov = S[S["item_kind"] == "real"].pivot_table(index="item_id", columns="metric", values="covered", aggfunc="first")
    R = real.set_index("item_id").join(piv, how="left")
    for m in metrics:
        R[m] = R[m].fillna(0.5)
    R = R.reset_index()
    rng = np.random.default_rng(0)
    R["NOISE"] = rng.random(len(R))
    out = {"n_real": int(len(R)), "label_distribution": dict(Counter(R["L_bij"])), "metrics": {}}
    # ------------------------------------------------------------------ per-metric AUROC + gates
    kinds = S.pivot_table(index="item_id", columns="metric", values="score", aggfunc="first")
    items_kind = S.drop_duplicates("item_id").set_index("item_id")[["item_kind", "operator", "sid"]]
    for m in metrics + ["NOISE"]:
        res = {}
        res["auroc_real"] = auroc_ci(R, m)
        res["by_tercile"] = {str(t): auroc_ci(R[R["tercile"] == t], m) for t in (0, 1, 2)}
        res["by_recipe_gold_source"] = {g: auroc_ci(R[R["recipe_gold_source"] == g], m) for g in ("original", "corrected")}
        res["by_label"] = {lab: auroc_ci(R.assign(y2=R["y_" + lab]), m, "y2") for lab in
                           ("L_bij_orig", "L_str", "L_bij_cur", "L_any")}
        res["by_label_parseable_only"] = auroc_ci(R[R["parse_ok"] == 1], m)
        if m != "NOISE":
            c = cov[m] if m in cov else pd.Series(dtype=float)
            res["G1_coverage"] = round(float(R["item_id"].map(c).fillna(False).astype(bool).mean()), 4)
        # G2 false alarms on rewrites (not for LC / B3sc / NOISE)
        if m in kinds.columns and m not in LC_METRICS:
            sc = kinds[m].dropna()
            kk = items_kind.reindex(sc.index)
            gold_s = sc[kk["item_kind"] == "gold"].values
            mut_s = sc[kk["item_kind"] == "mutant"].values
            rw = sc[kk["item_kind"] == "rewrite"]
            if len(gold_s) and len(mut_s) and len(rw):
                tau = youden(gold_s, mut_s)
                gold_by_sid = {kk.loc[i, "sid"]: v for i, v in sc[kk["item_kind"] == "gold"].items()}
                paired = [abs(v - gold_by_sid[kk.loc[i, "sid"]]) > 0.2 for i, v in rw.items() if kk.loc[i, "sid"] in gold_by_sid]
                res["G2"] = {"tau_star": round(tau, 4), "FA_at_tau": round(float((rw.values < tau).mean()), 4),
                             "FA_at_0.5": round(float((rw.values < 0.5).mean()), 4),
                             "FA_paired_absdiff_gt_0.2": round(float(np.mean(paired)), 4) if paired else None,
                             "n_rewrites": int(len(rw)),
                             "FA_by_kind": {k: round(float((rw[kk.loc[rw.index, "operator"] == k].values < tau).mean()), 4)
                                            for k in sorted(set(kk.loc[rw.index, "operator"]))},
                             "gold_vs_mutant_auroc": round(auc(np.r_[np.ones(len(gold_s)), np.zeros(len(mut_s))],
                                                                np.r_[gold_s, mut_s]), 4)}
                # standalone per-operator detection
                det = {}
                for op in OPS:
                    ms = sc[(kk["item_kind"] == "mutant") & (kk["operator"] == op)].values
                    if len(ms):
                        k = int((ms < tau).sum())
                        det[op] = {"rate": round(k / len(ms), 4), "n": int(len(ms)), "wilson": wilson(k, len(ms))}
                res["standalone_detection"] = det
            else:
                res["G2"] = None
        else:
            res["G2"] = "N/A"
        # G3 OOF increment over [B1, parse_ok]
        if m not in ("B1", "B2") and "B1" in R.columns:
            R["_pok"] = R["parse_ok"].astype(float)
            g3 = oof_delta(R, ["B1", "_pok", m], ["B1", "_pok"])
            g3.pop("oof_full")
            res["G3"] = g3
        res["G4_auroc_ge_0.65"] = bool(res["auroc_real"]["auroc"] is not None and res["auroc_real"]["auroc"] >= 0.65)
        if m in RULE:
            cov_ok = res["G1_coverage"] >= 0.70
            g2 = res["G2"]
            g2_ok = True if g2 in ("N/A", None) else g2["FA_at_tau"] <= 0.10
            res["gates"] = {"G1": cov_ok, "G2": ("N/A" if g2 == "N/A" else g2_ok), "G3": res["G3"]["pass"],
                            "G4": res["G4_auroc_ge_0.65"]}
            res["survives"] = bool(cov_ok and g2_ok and res["G3"]["pass"] and res["G4_auroc_ge_0.65"])
        out["metrics"][m] = res
        logger.info(f"{m}: AUROC {res['auroc_real']} G1 {res.get('G1_coverage')} G3 {res.get('G3', {}).get('delta') if isinstance(res.get('G3'), dict) else None}")
    # ------------------------------------------------------------------ robustness: vocab-compatible subset,
    # within-sentence discrimination, item-level correlation, paired deltas
    R["vocab_compatible"] = (R["parse_ok"] == 1) & (R["label_reason"] != "vocab_mismatch")
    Rv = R[R["vocab_compatible"]]
    ws_groups = {}
    for sid, g in R[R["y"].notna()].groupby("sid"):
        if g["y"].nunique() == 2:
            ws_groups[sid] = g
    ws_sids = np.array(sorted(ws_groups))

    def within_parts(m):
        num, den = np.zeros(len(ws_sids)), np.zeros(len(ws_sids))
        for i, sid in enumerate(ws_sids):
            g = ws_groups[sid]
            pos = g.loc[g["y"] == 1, m].values
            neg = g.loc[g["y"] == 0, m].values
            for a in pos:
                num[i] += float((a > neg).sum()) + 0.5 * float((a == neg).sum())
                den[i] += len(neg)
        return num, den
    rob = {}
    for m in metrics + ["NOISE"]:
        num, den = within_parts(m)
        w = float(num.sum() / den.sum()) if den.sum() else float("nan")
        rngw = np.random.default_rng(0)
        bs = []
        for _ in range(N_BOOT if len(ws_sids) else 0):
            k = rngw.integers(0, len(ws_sids), len(ws_sids))
            bs.append(num[k].sum() / den[k].sum())
        from scipy.stats import spearmanr as _sp
        yy = R["y"].notna()
        rob[m] = {"auroc_vocab_compatible_subset": auroc_ci(Rv, m),
                  "within_sentence_pairwise_acc": {"acc": round(w, 4) if not math.isnan(w) else None,
                                                   "ci": [round(float(np.percentile(bs, 2.5)), 4), round(float(np.percentile(bs, 97.5)), 4)] if bs else [None, None],
                                                   "n_sentences_mixed_labels": int(len(ws_sids))},
                  "spearman_with_label": round(float(_sp(R.loc[yy, m], R.loc[yy, "y"]).correlation), 4)}
        if m in out["metrics"]:
            out["metrics"][m]["robustness"] = rob[m]
    out["robustness"] = rob
    yy = R["y"].notna()
    y_all, g_all = R.loc[yy, "y"].values.astype(int), R.loc[yy, "sid"].values
    paired = {}
    for a_, b_ in (("TVJT", "B1"), ("LC_onecoin", "LC_maj"), ("LC_onecoin", "B1"), ("TVJT_gloss", "TVJT"),
                   ("TVJT_nv", "TVJT"), ("NLI_deberta", "B1"), ("NLI_gemini", "NLI_deberta"), ("TVJT", "NLI_gemini")):
        if a_ in R and b_ in R:
            sa, sb = R.loc[yy, a_].values.astype(float), R.loc[yy, b_].values.astype(float)
            dlt = auc(y_all, sa) - auc(y_all, sb)
            lo, hi = cluster_boot(g_all, lambda idx: auc(y_all[idx], sa[idx]) - auc(y_all[idx], sb[idx]))
            top = (R.loc[yy, "tercile"] == 2).values
            dtop = auc(y_all[top], sa[top]) - auc(y_all[top], sb[top])
            lo2, hi2 = cluster_boot(g_all[top], lambda idx: auc(y_all[top][idx], sa[top][idx]) - auc(y_all[top][idx], sb[top][idx]))
            paired[f"{a_}-{b_}"] = {"delta_auroc": round(dlt, 4), "ci": [round(lo, 4), round(hi, 4)],
                                    "delta_auroc_top_tercile": round(dtop, 4), "ci_top_tercile": [round(lo2, 4), round(hi2, 4)]}
    out["paired_auroc_deltas"] = paired
    # system-level ordering (3 systems: tau not reported, only the order)
    order_acc = sorted(R["system"].unique(), key=lambda s_: -R.loc[R["system"] == s_, "y"].mean())
    out["system_level"] = {"order_by_L_bij_accuracy": order_acc,
                           "order_by_metric_mean": {m: sorted(R["system"].unique(), key=lambda s_: -R.loc[R["system"] == s_, m].mean())
                                                    for m in metrics},
                           "note": "only 3 systems: Kendall tau not reported (field norm: >= 6 systems)"}
    # ------------------------------------------------------------------ shuffled-label control
    yl = R["y"].dropna()
    shuf = []
    for i in range(20):
        perm = np.random.default_rng(i).permutation(yl.values)
        shuf.append(auc(perm, R.loc[yl.index, "TVJT"].values if "TVJT" in R else R.loc[yl.index, "B1"].values))
    out["controls"] = {"shuffled_label_auroc_mean_TVJT": round(float(np.mean(shuf)), 4),
                       "noise_metric_G3": out["metrics"]["NOISE"].get("G3")}
    # ------------------------------------------------------------------ selection rule
    cand = {m: out["metrics"][m] for m in RULE if m in out["metrics"]}
    surv = [m for m, v in cand.items() if v.get("survives")]
    verdict = {"rule_candidates": list(cand), "gates": {m: v["gates"] for m, v in cand.items()},
               "gate_values": {m: {"G1_coverage": v["G1_coverage"],
                                   "G2_FA_at_tau": (v["G2"]["FA_at_tau"] if isinstance(v["G2"], dict) else v["G2"]),
                                   "G3_delta": v["G3"]["delta"], "G3_ci": v["G3"]["ci"],
                                   "G4_auroc_real": v["auroc_real"]["auroc"], "auroc_ci": v["auroc_real"]["ci"],
                                   "top_tercile_auroc": v["by_tercile"]["2"]["auroc"]} for m, v in cand.items()},
               "survivors": surv}
    if surv:
        ranked = sorted(surv, key=lambda m: -(cand[m]["by_tercile"]["2"]["auroc"] or 0))
        verdict["ranking_top_tercile"] = [(m, cand[m]["by_tercile"]["2"]["auroc"]) for m in ranked]
        if len(ranked) == 1:
            verdict["outcome"] = "winner"
            verdict["advance"] = [ranked[0]]
        else:
            lead = (cand[ranked[0]]["by_tercile"]["2"]["auroc"] or 0) - (cand[ranked[1]]["by_tercile"]["2"]["auroc"] or 0)
            verdict["lead"] = round(lead, 4)
            if lead >= 0.03:
                verdict["outcome"] = "winner"
                verdict["advance"] = [ranked[0]]
            else:
                rho = spearmanr(R[ranked[0]], R[ranked[1]]).correlation
                verdict["top_two_spearman"] = round(float(rho), 4)
                if rho < 0.5:
                    verdict["outcome"] = "combined_stack"
                    verdict["advance"] = ranked[:2]
                    R["_pok"] = R["parse_ok"].astype(float)
                    st = oof_delta(R, ["B1", "_pok"] + ranked[:2], ["B1", "_pok"])
                    oof = np.array(st.pop("oof_full"))
                    dd = R[R["y"].notna()].reset_index(drop=True)
                    comb = {"auroc_stack_with_B1": st}
                    stack2 = oof_delta(R, ranked[:2], ["_pok"])
                    stack2.pop("oof_full")
                    comb["auroc_stack_two_metrics_plus_parse"] = stack2
                    verdict["combined"] = comb
                else:
                    verdict["outcome"] = "top_one_alone"
                    verdict["advance"] = [ranked[0]]
    else:
        best = max(cand, key=lambda m: cand[m]["G3"]["delta"]) if cand else None
        if best is not None and cand[best]["G3"]["delta"] >= 0.03:
            verdict["outcome"] = "no_survivor_largest_delta_advances"
            verdict["advance"] = [best]
        else:
            verdict["outcome"] = "null"
            verdict["advance"] = []
        verdict["largest_delta_candidate"] = best
    out["verdict"] = verdict
    logger.info(f"VERDICT: {json.dumps({k: v for k, v in verdict.items() if k != 'gate_values'})}")
    # ------------------------------------------------------------------ TVJT pairwise, oracle, confusion
    tv = S[S["metric"] == "TVJT"].set_index("item_id")
    pw = defaultdict(list)
    oracle_by_op = defaultdict(list)
    oracle_all = defaultdict(list)
    for iid, rr in tv.iterrows():
        if rr["item_kind"] in ("gold", "supplement") and isinstance(rr.get("agrees"), list):
            split = "screen" if rr["item_kind"] == "gold" else (rr.get("split") or "supplement")
            for op, a in zip(rr["ops"], rr["agrees"]):
                pw[(op, split)].append(a)
                if rr["item_kind"] == "gold":
                    oracle_by_op[op].append(a)
                    oracle_all[sent[rr["sid"]]["gold_source"]].append(a)
                    oracle_all["recipe_" + sent[rr["sid"]]["recipe_gold_source"]].append(a)
    out["tvjt_pairwise_detection"] = {f"{op}|{sp}": {"rate": round(float(np.mean(v)), 4), "n": len(v),
                                                     "wilson": wilson(sum(v), len(v))} for (op, sp), v in sorted(pw.items())}
    out["tvjt_judge_oracle_accuracy"] = {"overall": round(float(np.mean([a for v in oracle_by_op.values() for a in v])), 4)
                                         if oracle_by_op else None,
                                         "by_world_operator": {op: {"acc": round(float(np.mean(v)), 4), "n": len(v)}
                                                               for op, v in oracle_by_op.items()},
                                         "by_gold_source": {k: {"acc": round(float(np.mean(v)), 4), "n": len(v)}
                                                            for k, v in oracle_all.items()}}
    # NLI oracle (score on golds) + pairwise detection
    for m in ("NLI_deberta", "NLI_gemini"):
        g = S[(S["metric"] == m) & (S["item_kind"] == "gold") & (S["covered"])]
        out[f"{m}_oracle_on_gold"] = {"mean_score": round(float(g["score"].mean()), 4) if len(g) else None, "n": int(len(g)),
                                      "by_recipe_gold_source": {k: round(float(v["score"].mean()), 4) for k, v in
                                                                g.assign(src=g["sid"].map(lambda x: sent[x]["recipe_gold_source"])).groupby("src")}}
    nl = S[(S["metric"] == "NLI_deberta") & (S["item_kind"].isin(["gold", "supplement"]))]
    npw = defaultdict(list)
    ndiff0 = Counter()
    for _, rr in nl.iterrows():
        if not isinstance(rr.get("pairwise"), dict):
            continue
        for mk, v in rr["pairwise"].items():
            if mk.startswith("SUP:"):
                parts = mk.split(":")
                op = parts[3] if len(parts) > 3 else "?"
                split = "screen" if rr["item_kind"] == "gold" else (rr.get("split") or "supplement")
                key = (f"{op}", split)
            else:
                if rr["item_kind"] != "gold":
                    continue
                key = (mk, "screen_controlled")
            npw[key].append(v["detect"])
            if v["n_diff"] == 0:
                ndiff0[key] += 1
    out["nli_pairwise_detection"] = {f"{op}|{sp}": {"rate": round(float(np.mean(v)), 4), "n": len(v),
                                                    "n_no_differing_hypothesis": ndiff0[(op, sp)],
                                                    "wilson": wilson(sum(v), len(v))} for (op, sp), v in sorted(npw.items())}
    # error-type confusion (mutants)
    conf = {}
    for m in ("TVJT", "NLI_deberta", "NLI_gemini"):
        mm = S[(S["metric"] == m) & (S["item_kind"] == "mutant") & (S["covered"])]
        if not len(mm):
            continue
        tab = pd.crosstab(mm["operator"], mm["error_type_pred"].fillna("none"))
        labs = sorted(set(mm["operator"]))
        f1 = f1_score(mm["operator"], mm["error_type_pred"].fillna("none"), labels=labs, average="macro", zero_division=0)
        conf[m] = {"matrix": {str(i): {str(j): int(v) for j, v in row.items()} for i, row in tab.iterrows()},
                   "macro_f1": round(float(f1), 4), "n": int(len(mm)),
                   "top1_accuracy": round(float((mm["operator"] == mm["error_type_pred"]).mean()), 4)}
    out["error_type_confusion"] = conf
    # ------------------------------------------------------------------ costs
    cost = {}
    for m in metrics:
        mm = S[S["metric"] == m]
        cost[m] = {"usd_per_item_mean": round(float(mm["usd"].mean()), 7), "usd_total": round(float(mm["usd"].sum()), 4),
                   "sec_per_item_median": round(float(mm["seconds"].median()), 3),
                   "sec_per_item_mean": round(float(mm["seconds"].mean()), 3), "n_items": int(len(mm))}
    out["cost"] = cost
    led = read_jsonl(ROOT / "results" / "cost_ledger.jsonl") + read_jsonl(ROOT / "results" / "cost_ledger_devtests.jsonl")
    out["total_openrouter_usd_workspace"] = round(sum(x.get("cost", 0) for x in led), 4)
    out["total_openrouter_usd_note"] = "all OpenRouter spend of this workspace (mini runs + dev checks + full screen)"
    out["cost_by_stage"] = {k: round(sum(x.get("cost", 0) for x in led if x["stage"] == k), 4) for k in sorted({x["stage"] for x in led})}
    # ------------------------------------------------------------------ verbalizer failure
    W = read_jsonl(d / "worlds_cache.jsonl")
    vf_items = [any((w.get("verbalizer_fail_preds") or {}).values()) for w in W if w.get("verbalizer_fail_preds") is not None]
    preds_all = {}
    for w in W:
        preds_all.update(w.get("verbalizer_fail_preds") or {})
    out["verbalizer_failure"] = {"per_item": round(float(np.mean(vf_items)), 4) if vf_items else None,
                                 "per_predicate": round(float(np.mean(list(preds_all.values()))), 4) if preds_all else None,
                                 "n_predicates": len(preds_all)}
    out["world_coverage"] = {"targets_with_world": int(sum(1 for w in W if w.get("worlds"))), "targets": len(W),
                             "rate": round(sum(1 for w in W if w.get("worlds")) / max(1, len(W)), 4),
                             "mean_worlds": round(float(np.mean([len(w.get("worlds") or []) for w in W])), 3) if W else None}
    # ------------------------------------------------------------------ per-system, correlations
    persys = {}
    for s_, g in R.groupby("system"):
        persys[s_] = {"n": int(len(g)), "L_bij_accuracy": round(float(g["y"].mean()), 4),
                      "parse_rate": round(float(g["parse_ok"].mean()), 4),
                      **{f"mean_{m}": round(float(g[m].mean()), 4) for m in metrics}}
    out["per_system"] = persys
    corr = {}
    for a in RULE:
        if a not in R:
            continue
        for b in ["B1"] + RULE:
            if b in R and a != b:
                corr[f"{a}~{b}"] = round(float(spearmanr(R[a], R[b]).correlation), 4)
    out["spearman_real"] = corr
    # ------------------------------------------------------------------ label-noise estimates
    lab = {}
    both = R[R["L_bij"].isin(["correct", "incorrect"]) & R["L_str"].isin(["correct", "incorrect"])]
    lab["L_bij_vs_L_str_disagreement"] = round(float((both["L_bij"] != both["L_str"]).mean()), 4)
    lab["L_bij_correct_but_L_str_incorrect"] = int(((both["L_bij"] == "correct") & (both["L_str"] == "incorrect")).sum())
    cur = R[R["L_bij_cur"].isin(["correct", "incorrect"])]
    lab["n_with_curated"] = int(len(cur))
    lab["L_bij_vs_L_bij_cur_disagreement"] = round(float((cur["L_bij"] != cur["L_bij_cur"]).mean()), 4) if len(cur) else None
    lab["v1correct_curated_incorrect"] = int(((cur["L_bij"] == "correct") & (cur["L_bij_cur"] == "incorrect")).sum())
    lab["v1incorrect_curated_correct"] = int(((cur["L_bij"] == "incorrect") & (cur["L_bij_cur"] == "correct")).sum())
    ovc = Counter((s["orig_vs_curated"] or {}).get("label") for s in ss["sentences"] if s.get("curated_fol"))
    ovr = Counter((s["orig_vs_curated"] or {}).get("reason") for s in ss["sentences"] if s.get("curated_fol"))
    lab["v1_gold_vs_curated_gold"] = {"labels": dict(ovc), "reasons": dict(ovr)}
    lab["n_equiv_maps_gt1_rate"] = round(float((R["n_equiv_maps"].fillna(0) > 1).mean()), 4)
    inc = R[R["L_bij"] == "incorrect"]
    lab["incorrect_label_reasons"] = dict(Counter(inc["label_reason"].fillna("?").map(lambda x: x.split(":")[0])))
    lab["incorrect_due_to_vocab_mismatch_share"] = round(float((inc["label_reason"] == "vocab_mismatch").mean()), 4) if len(inc) else None
    lab["note"] = ("vocab_mismatch = different predicate-arity multiset or constant count (e.g. compound predicate, extra "
                   "restrictor, finer decomposition): such candidates can never be bijection-equivalent, so this share "
                   "upper-bounds 'correct-but-non-equivalent' label noise; iter-2 adjudication resolves it.")
    lab["unparseable_rate"] = round(float((R["parse_ok"] == 0).mean()), 4)
    out["label_noise"] = lab
    # ------------------------------------------------------------------ head-to-head on blind spots
    h2h = {"note": "Arm A signature predicted ≈ chance on SCOPE_SWAP/CARD (blind spots); compare in iter 2",
           "TVJT_pairwise": {k: v for k, v in out["tvjt_pairwise_detection"].items() if k.split("|")[0] in ("SCOPE_SWAP", "CARD")},
           "NLI_pairwise": {k: v for k, v in out["nli_pairwise_detection"].items() if k.split("|")[0] in ("SCOPE_SWAP", "CARD")},
           "chance": 0.5}
    for m in ("TVJT", "NLI_deberta"):
        for op in ("SCOPE_SWAP", "CARD"):
            for tag, src in (("TVJT_pairwise", out["tvjt_pairwise_detection"]), ("NLI_pairwise", out["nli_pairwise_detection"])):
                if (tag == "TVJT_pairwise") != (m == "TVJT"):
                    continue
                vals_all = [(v["rate"], v["n"]) for k, v in src.items() if k.split("|")[0] == op and "controlled" not in k]
                vals_scr = [(v["rate"], v["n"]) for k, v in src.items() if k.split("|")[0] == op and k.split("|")[1] == "screen"]
                for nm, vv in (("screen", vals_scr), ("screen+supplement", vals_all)):
                    n = sum(x[1] for x in vv)
                    k = sum(x[0] * x[1] for x in vv)
                    h2h[f"{m}|{op}|{nm}"] = {"rate": round(k / n, 4) if n else None, "n": n, "wilson": wilson(k, n)}
    out["blindspot_headtohead"] = h2h
    (r / "blindspot_headtohead.json").write_text(json.dumps(h2h, indent=1))
    (r / "verdict.json").write_text(json.dumps(verdict, indent=1))
    (r / "analysis.json").write_text(json.dumps(out, indent=1, default=str))
    try:
        make_figures(out, fdir)
    except Exception as e:  # noqa: BLE001 - figures are secondary
        logger.error(f"figures failed: {e!r}")
    return out


def make_figures(out: dict, fdir: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    ms = [m for m in RULE + ["B1", "B3sc", "TVJT_gloss", "TVJT_nv", "NLI_gemini", "NLI_deberta_gloss", "LC_maj"] if m in out["metrics"]]
    fig, ax = plt.subplots(figsize=(10, 4.2))
    w = 0.8 / 4
    for j, (key, lab) in enumerate((("all", "all"), ("0", "tercile 0 (simple)"), ("1", "tercile 1"), ("2", "tercile 2 (complex)"))):
        vals, lo, hi = [], [], []
        for m in ms:
            a = out["metrics"][m]["auroc_real"] if key == "all" else out["metrics"][m]["by_tercile"][key]
            v = a["auroc"] if a["auroc"] is not None else np.nan
            vals.append(v)
            lo.append(v - (a["ci"][0] if a["ci"][0] is not None else v))
            hi.append((a["ci"][1] if a["ci"][1] is not None else v) - v)
        x = np.arange(len(ms)) + (j - 1.5) * w
        ax.bar(x, vals, w, yerr=[lo, hi], capsize=2, label=lab)
    ax.axhline(0.5, color="gray", lw=0.8, ls="--")
    ax.axhline(0.65, color="red", lw=0.8, ls=":")
    ax.set_xticks(np.arange(len(ms)))
    ax.set_xticklabels(ms, rotation=20)
    ax.set_ylabel("AUROC vs L_bij (95% sentence-cluster CI)")
    ax.set_ylim(0.3, 1.0)
    ax.legend(fontsize=8, ncol=4)
    fig.tight_layout()
    fig.savefig(fdir / "auroc_by_tercile.png", dpi=150)
    fig.savefig(fdir / "auroc_by_tercile.pdf")
    plt.close(fig)
    # per-operator detection (pairwise TVJT & NLI on gold's worlds; standalone B1)
    fig, ax = plt.subplots(figsize=(10, 4))
    series = []
    tv = {k.split("|")[0]: v for k, v in out["tvjt_pairwise_detection"].items() if k.endswith("|screen")}
    nl = {k.split("|")[0]: v for k, v in out["nli_pairwise_detection"].items() if k.endswith("|screen_controlled")}
    b1 = (out["metrics"].get("B1", {}).get("standalone_detection") or {})
    for name, dct in (("TVJT pairwise", tv), ("NLI-DeBERTa pairwise", nl), ("B1 standalone", b1)):
        series.append((name, [dct.get(op, {}).get("rate", np.nan) for op in OPS]))
    for j, (name, vals) in enumerate(series):
        ax.bar(np.arange(len(OPS)) + (j - 1) * 0.27, vals, 0.27, label=name)
    ax.axhline(0.5, color="gray", ls="--", lw=0.8)
    if "SCOPE_SWAP" not in tv:
        ax.text(OPS.index("SCOPE_SWAP"), 0.05, "n=0 on screen\n(see supplement)", ha="center", fontsize=7)
    ax.set_title("Per-operator detection on screen golds' controlled mutants (pairwise: judge sides with gold)", fontsize=9)
    ax.set_xticks(np.arange(len(OPS)))
    ax.set_xticklabels(OPS, rotation=25)
    ax.set_ylabel("detection rate")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(fdir / "per_operator_detection.png", dpi=150)
    fig.savefig(fdir / "per_operator_detection.pdf")
    plt.close(fig)
    for m, c in out.get("error_type_confusion", {}).items():
        mat = pd.DataFrame(c["matrix"]).T.fillna(0)
        cols = [x for x in OPS + ["none"] if x in mat.columns]
        rows = [x for x in OPS if x in mat.index]
        mat = mat.reindex(index=rows, columns=cols).fillna(0)
        fig, ax = plt.subplots(figsize=(7, 5))
        ax.imshow(mat.values, cmap="Blues")
        ax.set_xticks(range(len(cols)))
        ax.set_xticklabels(cols, rotation=45, ha="right", fontsize=7)
        ax.set_yticks(range(len(rows)))
        ax.set_yticklabels(rows, fontsize=7)
        for i in range(len(rows)):
            for j in range(len(cols)):
                ax.text(j, i, int(mat.values[i, j]), ha="center", va="center", fontsize=6)
        ax.set_xlabel("predicted error type")
        ax.set_ylabel("true operator")
        ax.set_title(f"{m} error-type confusion (macro-F1 {c['macro_f1']})")
        fig.tight_layout()
        fig.savefig(fdir / f"confusion_{m}.png", dpi=150)
        plt.close(fig)
