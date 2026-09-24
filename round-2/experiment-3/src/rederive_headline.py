#!/usr/bin/env python3
"""Independent re-derivation of the headline numbers from RAW files through a different code path
(pandas + sklearn; no import of src/ or vendor stats). Reads: work/l3_fresh.json (panel votes/majority/strata),
work/l1_fresh.jsonl (solver statuses), work/l0_results.json (gold audit), work/fresh_frame.jsonl, results/scores.jsonl
(per-item metric outputs). Re-rakes the panel weights itself (IPF over stratum x system, cap 6).
Placebos: permuted labels (AUROC ~0.5) and the T1 increment with DC shuffled (must not pass).
Writes results/rederive_headline.json.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import StandardScaler

R = Path(__file__).resolve().parent
rows = [json.loads(x) for x in open(R / "work/fresh_frame.jsonl")]
fr = pd.DataFrame([r for r in rows if r["fold"] == "fresh_greedy"]).set_index("item_id")
l0 = json.loads((R / "work/l0_results.json").read_text())
l3 = json.loads((R / "work/l3_fresh.json").read_text())["results"]
l1 = pd.DataFrame([json.loads(x) for x in open(R / "work/l1_fresh.jsonl")]).set_index("key")
sc = pd.DataFrame([json.loads(x) for x in open(R / "results/scores.jsonl")])
wide = sc.pivot_table(index="item_id", columns="metric", values="score", aggfunc="first")
fr = fr.join(wide)
fr["S"] = l1["status"].reindex(fr.index)
fr["y_s"] = fr["S"].map({"equiv_proved": 1, "equiv_bounded": 1, "non_equiv": 0, "non_equiv_no_bijection": 0})
P = pd.DataFrame([{"item_id": k, "y": int(v["L3_majority"]), "stratum": v["stratum"], "system": v["system"]}
                  for k, v in l3.items() if v["L3_majority"] is not None]).set_index("item_id")
# independent raking: frame = greedy rows whose sentence has an audited gold
frame = fr[[bool((l0.get(s) or {}).get("gold_fol_audited")) for s in fr["sid"]]]
N_sys = frame["system"].value_counts()
N_st = pd.Series(json.loads((R / "work/l3_fresh.json").read_text())["design"]["frame_N"])
w = pd.Series(1.0, index=P.index)
for _ in range(50):
    for col, N in (("stratum", N_st), ("system", N_sys)):
        tot = w.groupby(P[col]).sum()
        w = w * P[col].map(N / tot)
w = w.clip(lower=w.max() / 6.0)
P["w"] = w / w.sum() * len(frame)
P = P.join(fr[["sid", "DC", "LC_ds_binary", "LC_maj", "B1", "B2", "B7", "B3nliL", "B3cosL", "VC"]])
S = fr[fr["y_s"].notna()]
out = {"n_panel": len(P), "n_solver": len(S), "kish": float(P.w.sum() ** 2 / (P.w ** 2).sum())}
for m in ("DC", "LC_ds_binary", "LC_maj", "B1", "VC"):
    out[f"AUROC_panel_{m}"] = roc_auc_score(P.y, P[m], sample_weight=P.w)
    out[f"AUROC_solver_{m}"] = roc_auc_score(S.y_s, S[m])
out["T2_DC_minus_LCds_panel"] = out["AUROC_panel_DC"] - out["AUROC_panel_LC_ds_binary"]


def oof(X, y, g, w, seed):
    """sklearn GroupKFold on a seeded permutation of sentence ids (different folds from the pipeline)."""
    rng = np.random.default_rng(seed)
    ug = np.unique(g)
    code = dict(zip(ug, rng.permutation(len(ug))))
    gg = np.array([code[x] for x in g])
    p = np.zeros(len(y))
    for tr, te in GroupKFold(5).split(X, y, gg):
        s = StandardScaler().fit(X[tr])
        m = LogisticRegression(C=1.0, max_iter=5000).fit(s.transform(X[tr]), y[tr], sample_weight=None if w is None else w[tr])
        p[te] = m.predict_proba(s.transform(X[te]))[:, 1]
    return p


def t1(D, ycol, wcol, base, extra, seed=7):
    y = D[ycol].to_numpy().astype(int)
    w = None if wcol is None else D[wcol].to_numpy()
    g = D["sid"].to_numpy()
    Xb = D[base].to_numpy(float)
    Xa = np.column_stack([Xb, extra])
    return roc_auc_score(y, oof(Xa, y, g, w, seed), sample_weight=w) - roc_auc_score(y, oof(Xb, y, g, w, seed), sample_weight=w)


def cluster_boot_lb(D, ycol, wcol, base, extra, n=300, seed=1):
    """One-sided 5th percentile of the T1 delta over sentence-cluster resamples (oof refit per draw)."""
    rng = np.random.default_rng(seed)
    sids = D["sid"].unique()
    vals = []
    for _ in range(n):
        pick = rng.choice(sids, len(sids))
        idx = np.concatenate([np.where(D["sid"].to_numpy() == s)[0] for s in pick])
        Db = D.iloc[idx].copy()
        Db["sid"] = [f"{s}#{i}" for i, s in enumerate(Db["sid"])]  # resampled clusters stay grouped by position
        Db["sid"] = D["sid"].to_numpy()[idx]
        try:
            vals.append(t1(Db, ycol, wcol, base, extra[idx], seed=11))
        except ValueError:
            continue
    return float(np.percentile(vals, 5)), len(vals)


base = ["B1", "B2", "B3nliL", "B3cosL", "B7"]
out["T1_panel_delta"] = t1(P, "y", "w", base, P["DC"].to_numpy())
PS = P.join(fr[["y_s"]]).dropna(subset=["y_s"])
out["T1_solver_panelframe_delta"] = t1(PS, "y_s", None, base, PS["DC"].to_numpy())
out["T1_solver_allrows_noB3_delta"] = t1(S, "y_s", None, ["B1", "B2", "B7"], S["DC"].to_numpy())
lb, nb = cluster_boot_lb(P, "y", "w", base, P["DC"].to_numpy())
out["T1_panel_LB5_refit_bootstrap"] = lb
out["T1_panel_LB5_n_draws"] = nb
# placebos
rng = np.random.default_rng(0)
perm = [roc_auc_score(rng.permutation(S.y_s.to_numpy()), S["DC"]) for _ in range(200)]
out["placebo_permuted_labels_solver_DC_AUROC_mean"] = float(np.mean(perm))
out["placebo_permuted_labels_p_value"] = float(np.mean([p >= out["AUROC_solver_DC"] for p in perm]))
shuf = P["DC"].to_numpy().copy()
rng.shuffle(shuf)
out["placebo_T1_panel_delta_shuffledDC"] = t1(P, "y", "w", base, shuf)
lbp, _ = cluster_boot_lb(P, "y", "w", base, shuf)
out["placebo_T1_panel_LB5_shuffledDC"] = lbp
out["placebo_T1_passes"] = lbp > 0
# label rates straight from the audit records
sents = {s["sid"]: s["corpus"] for s in json.loads((R / "results/fresh_sentences.json").read_text())}
wr = pd.DataFrame([{"corpus": sents[k], "wrong": 1 - int(v["gold_faithful_final"])} for k, v in l0.items()
                   if v["gold_faithful_final"] is not None])
out["wrong_gold_by_corpus"] = wr.groupby("corpus")["wrong"].mean().to_dict()
ne = P.join(fr[["S"]])
ne = ne[ne.S.isin(["non_equiv", "non_equiv_no_bijection"])]
out["correct_but_inequivalent_weighted"] = float((ne.y * ne.w).sum() / ne.w.sum())
spend = sum(json.loads(x)["cost_usd"] for x in open(R / "cost_ledger.jsonl"))
out["ledger_usd"] = round(spend, 4)
(R / "results/rederive_headline.json").write_text(json.dumps(out, indent=1, default=float))
print(json.dumps(out, indent=1, default=float))
