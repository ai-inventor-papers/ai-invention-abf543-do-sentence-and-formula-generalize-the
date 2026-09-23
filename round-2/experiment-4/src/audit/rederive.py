"""T6 independent re-derivation of headline numbers via a different code path (sklearn roc_auc_score with
sample_weight + a pandas groupby bootstrap). Point estimates must match results/analysis.json exactly (1e-9);
CIs to the second decimal (different resampling code ⇒ small Monte-Carlo differences are expected)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

W = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(W / "src"))
from labels import load_labels  # noqa: E402

A = json.loads((W / "results" / "analysis.json").read_text())
tg = pd.DataFrame([json.loads(l) for l in (W / "data" / "heldout_targets.jsonl").read_text().splitlines()])
sc = {}
for p in ("zero_llm_scores.jsonl", "a3_scores.jsonl", "heldout_llm_scores.jsonl"):
    for l in (W / "results" / p).read_text().splitlines():
        r = json.loads(l)
        sc.setdefault(r["metric"], {})[r["item_id"]] = r["score"]
lab = load_labels()
P = tg[(tg["group"] == "heldout_confirm") & (tg["panel"])].copy()
P["y"] = P["item_id"].map(lambda i: lab[i]["y_panel"])
P["w"] = P["item_id"].map(lambda i: lab[i]["w"])
checks = {}
for m in [x for x in ("TVJT_frozen", "B1", "B1x3", "TVJT_iter1", "TVJT_lite", "LC_onecoin", "LC_maj", "A3") if x in sc]:
    s = P["item_id"].map(sc[m]).fillna(0.5)
    for name, idx in [("all", P.index)] + [(t, P.index[P["tercile"] == t]) for t in ("bottom", "middle", "top")]:
        v = roc_auc_score(P.loc[idx, "y"], s.loc[idx], sample_weight=P.loc[idx, "w"])
        ref = (A["P_main"]["all"] if name == "all" else A["P_main"]["by_tercile"][name])["auroc"][m]
        checks[f"{m}|{name}"] = {"rederived": v, "analysis": ref["point"], "match": abs(v - ref["point"]) < 1e-9}
    # pandas-groupby cluster bootstrap for the overall CI
    rng = np.random.default_rng(1)
    g = P.assign(s=s).groupby("sid")
    groups = [d for _, d in g]
    bs = []
    for _ in range(1000):
        d = pd.concat([groups[i] for i in rng.integers(0, len(groups), len(groups))])
        if d["y"].nunique() == 2:
            bs.append(roc_auc_score(d["y"], d["s"], sample_weight=d["w"]))
    ref_ci = A["P_main"]["all"]["auroc"][m]["ci"]
    checks[f"{m}|all|ci"] = {"rederived": [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))],
                             "analysis": ref_ci,
                             "match_2dp": bool(max(abs(a - b) for a, b in zip(
                                 [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))], ref_ci)) < 0.02)}
# H1 point: ΔAUROC_w(TVJT* − B1) on P-top, recomputed with sklearn
if "TVJT_frozen" in sc and "B1" in sc:
    top = P[P["tercile"] == "top"]
    d = (roc_auc_score(top["y"], top["item_id"].map(sc["TVJT_frozen"]).fillna(0.5), sample_weight=top["w"]) -
         roc_auc_score(top["y"], top["item_id"].map(sc["B1"]).fillna(0.5), sample_weight=top["w"]))
    ref = A["P_main"]["by_tercile"]["top"]["delta"]["TVJT_frozen-B1"]["point"]
    checks["H1_delta_top"] = {"rederived": d, "analysis": ref, "match": abs(d - ref) < 1e-9}
# shuffled-label sanity: AUROC ≈ 0.5
rng = np.random.default_rng(0)
ys = rng.permutation(P["y"].values)
checks["shuffled_labels_LC"] = roc_auc_score(ys, P["item_id"].map(sc["LC_onecoin"]).fillna(0.5), sample_weight=P["w"])
checks["random_noise_metric"] = roc_auc_score(P["y"], rng.random(len(P)), sample_weight=P["w"])
out = {"all_points_match": all(v["match"] for k, v in checks.items() if isinstance(v, dict) and "match" in v),
       "all_ci_match_2dp(unstratified bootstrap)": all(v["match_2dp"] for k, v in checks.items()
                                                       if isinstance(v, dict) and "match_2dp" in v),
       "checks": checks}
(W / "results" / "audit_rederive.json").write_text(json.dumps(out, indent=1, default=float))
print(json.dumps({k: v for k, v in out.items() if k != "checks"}, indent=1))
print(json.dumps(checks, indent=1, default=float)[:2500])
