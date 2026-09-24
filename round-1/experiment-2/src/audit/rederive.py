"""Independent re-derivation of headline numbers from RAW files (screen_set.json labels + screen_scores.jsonl rows +
cost ledgers + candidate_pairs.json). Different code path from src/analysis.py: sklearn roc_auc_score (not rank formula),
pandas-based cluster bootstrap, cross_val_predict OOF, brute-force within-sentence pairs, own Youden loop, own MAJ.
Placebo: permuted labels must give AUROC≈0.5 and a G3 CI containing 0."""
import json
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold, cross_val_predict

R = Path(__file__).resolve().parents[1]
ss = json.loads((R / "data/screen_set.json").read_text())
rows = [json.loads(l) for l in (R / "results/screen_scores.jsonl").read_text().splitlines() if l.strip()]
S = pd.DataFrame(rows)
real = pd.DataFrame(ss["real_items"])[["item_id", "sid", "system", "L_bij", "parse_ok", "label_reason"]]
terc = {s["sid"]: s["tercile"] for s in ss["sentences"]}
real["tercile"] = real["sid"].map(terc)
real = real[real["L_bij"].isin(["correct", "incorrect"])].copy()
real["y"] = (real["L_bij"] == "correct").astype(int)
wide = S[S.item_kind == "real"].pivot(index="item_id", columns="metric", values="score")
D = real.merge(wide, left_on="item_id", right_index=True, how="left")
out = {"n_real": len(D), "n_correct": int(D.y.sum()), "n_incorrect": int((1 - D.y).sum()),
       "vocab_mismatch_share_of_incorrect": round(float((D[D.y == 0].label_reason == "vocab_mismatch").mean()), 4)}


def boot_ci(df, fn, n=1000, seed=123):
    rng = np.random.default_rng(seed)
    groups = {k: g for k, g in df.groupby("sid")}
    keys = list(groups)
    vals = []
    for _ in range(n):
        samp = pd.concat([groups[k] for k in rng.choice(keys, len(keys))])
        try:
            vals.append(fn(samp))
        except ValueError:
            pass
    return [round(float(np.quantile(vals, .025)), 4), round(float(np.quantile(vals, .975)), 4)]


def oof(df, cols, ycol="y"):
    X = df[cols].to_numpy(float)
    return cross_val_predict(LogisticRegression(C=1.0, max_iter=2000), X, df[ycol], groups=df["sid"],
                             cv=GroupKFold(5), method="predict_proba")[:, 1]


D["pok"] = D["parse_ok"].astype(float)
for m in ["LC_onecoin", "TVJT", "NLI_deberta", "B1", "LC_maj"]:
    a = roc_auc_score(D.y, D[m])
    ci = boot_ci(D, lambda d: roc_auc_score(d.y, d[m]), n=500)
    t = {k: round(roc_auc_score(g.y, g[m]), 4) for k, g in D.groupby("tercile")}
    out[m] = {"auroc": round(a, 4), "ci": ci, "terciles": t}
for m in ["LC_onecoin", "TVJT", "NLI_deberta"]:
    D["_b"], D["_f"] = oof(D, ["B1", "pok"]), oof(D, ["B1", "pok", m])
    dlt = roc_auc_score(D.y, D._f) - roc_auc_score(D.y, D._b)
    ci = boot_ci(D, lambda d: roc_auc_score(d.y, d._f) - roc_auc_score(d.y, d._b), n=500)
    out[m]["G3_delta"], out[m]["G3_ci"] = round(dlt, 4), ci
# within-sentence brute force
for m in ["TVJT", "LC_onecoin", "B1"]:
    num = den = 0.0
    for sid, g in D.groupby("sid"):
        for (_, a), (_, b) in combinations(g.iterrows(), 2):
            if a.y != b.y:
                pos, neg = (a, b) if a.y == 1 else (b, a)
                num += 1.0 if pos[m] > neg[m] else (0.5 if pos[m] == neg[m] else 0.0)
                den += 1
    out[m]["within_sentence"] = round(num / den, 4)
top = D[D.tercile == 2]
out["TVJT_minus_B1_top_tercile"] = round(roc_auc_score(top.y, top.TVJT) - roc_auc_score(top.y, top.B1), 4)
# G2 for TVJT from raw rows: own Youden on gold vs mutants, FA on rewrites
tv = S[S.metric == "TVJT"]
g, mu, rw = tv[tv.item_kind == "gold"].score.values, tv[tv.item_kind == "mutant"].score.values, tv[tv.item_kind == "rewrite"].score.values
best = max(sorted(set(np.r_[g, mu])), key=lambda t: ((g >= t).mean() - (mu >= t).mean(), -t))
out["TVJT_G2"] = {"tau": float(best), "FA_tau": round(float((rw < best).mean()), 4), "FA_0.5": round(float((rw < 0.5).mean()), 4)}
# LC_maj recomputed from candidate_pairs.json (raw z3 pairwise labels)
pairs = json.loads((R / "data/candidate_pairs.json").read_text())
mism = 0
for sid, g in pd.DataFrame(ss["real_items"]).groupby("sid"):
    ok = [r.system for r in g.itertuples() if r.parse_ok]
    for r in g.itertuples():
        if not r.parse_ok or len(ok) < 2:
            continue
        agree = sum(1 for o in ok if o != r.system and
                    (pairs[sid].get(f"{min(o, r.system)}|{max(o, r.system)}") or {}).get("bij") == "equiv")
        # transitive closure is used by the pipeline; direct agreement suffices except in non-transitive corner cases
        if abs(agree / (len(ok) - 1) - wide.loc[r.item_id, "LC_maj"]) > 1e-9:
            mism += 1
out["LC_maj_direct_recompute_mismatches"] = mism
# spend from raw ledgers
spend = 0.0
for p in [R / "results/cost_ledger.jsonl", R / "results/cost_ledger_devtests.jsonl"]:
    spend += sum(json.loads(l).get("cost", 0) for l in p.read_text().splitlines() if l.strip())
out["total_spend_usd"] = round(spend, 4)
# PLACEBO: permuted labels (within the same data) -> AUROC ~0.5, G3 CI should contain 0
rng = np.random.default_rng(7)
P = D.copy()
P["y"] = rng.permutation(P.y.values)
out["placebo"] = {"auroc_LC_onecoin_permuted": round(roc_auc_score(P.y, P.LC_onecoin), 4),
                  "auroc_TVJT_permuted": round(roc_auc_score(P.y, P.TVJT), 4)}
P["_b"], P["_f"] = oof(P, ["B1", "pok"]), oof(P, ["B1", "pok", "LC_onecoin"])
out["placebo"]["G3_LC_delta_permuted"] = round(roc_auc_score(P.y, P._f) - roc_auc_score(P.y, P._b), 4)
out["placebo"]["G3_LC_ci_permuted"] = boot_ci(P, lambda d: roc_auc_score(d.y, d._f) - roc_auc_score(d.y, d._b), n=300)
out["placebo"]["G3_passes_on_placebo"] = out["placebo"]["G3_LC_ci_permuted"][0] > 0
(R / "audit/rederive_out.json").write_text(json.dumps(out, indent=1))
print(json.dumps(out, indent=1))
