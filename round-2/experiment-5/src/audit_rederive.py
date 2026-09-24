#!/usr/bin/env python3
"""T5 independent re-derivation: recompute X1 (weighted AUROC of every metric), X2 (cross-fitted increment) and the
per-bin AUROCs from results/scores.jsonl + results/exception_set.jsonl with sklearn.roc_auc_score(sample_weight=...)
and an independent sentence-grouped logistic stacking; compare with results/tests.json (tolerance 0.005 for AUROCs;
X2 is re-derived with a different fold assignment, so its tolerance is reported, not asserted)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parent
RES = ROOT / "results"


def rj(p):
    return [json.loads(l) for l in Path(p).read_text(encoding="utf-8").splitlines() if l.strip()]


def main() -> None:
    sc = {r["cand_id"]: r for r in rj(RES / "scores.jsonl")}
    ex = [r for r in rj(RES / "exception_set.jsonl") if r["label"] is not None]
    tests = json.loads((RES / "tests.json").read_text())
    y = np.array([r["label"] == "faithful" for r in ex], int)
    w = np.array([r["weight"] for r in ex], float)
    groups = np.array([r["sentence_id"] for r in ex])
    out = {"n": len(ex), "x1": {}, "per_bin": {}, "max_abs_diff": 0.0}
    for m, blk in tests["X1"]["baselines"].items():
        vals = [sc[r["item_id"]].get(m) for r in ex]
        ok = np.array([v is not None for v in vals])
        if ok.sum() < 5 or blk.get("auroc_w") is None:
            continue
        s = np.array([v if v is not None else 0.5 for v in vals], float)
        a = roc_auc_score(y[ok], s[ok], sample_weight=w[ok])
        d = abs(a - blk["auroc_w"])
        out["x1"][m] = {"sklearn": a, "analysis": blk["auroc_w"], "abs_diff": d}
        out["max_abs_diff"] = max(out["max_abs_diff"], d)
    for b, blk in tests["X3"]["per_bin"].items():
        idx = np.array([r["marker_bin"] == b for r in ex])
        for m in ("DC", "B1"):
            if blk[m].get("auroc_w") is None or len(set(y[idx])) < 2:
                continue
            s = np.array([sc[r["item_id"]].get(m) if sc[r["item_id"]].get(m) is not None else 0.5 for r in ex], float)
            a = roc_auc_score(y[idx], s[idx], sample_weight=w[idx])
            d = abs(a - blk[m]["auroc_w"])
            out["per_bin"][f"{b}:{m}"] = {"sklearn": a, "analysis": blk[m]["auroc_w"], "abs_diff": d}
            out["max_abs_diff"] = max(out["max_abs_diff"], d)

    def feat(names):
        return np.column_stack([[sc[r["item_id"]].get(n) if sc[r["item_id"]].get(n) is not None else 0.5 for r in ex] for n in names])

    def oof(X):
        p = np.zeros(len(y))
        for tr, te in GroupKFold(n_splits=5).split(X, y, groups):
            ss = StandardScaler().fit(X[tr])
            m = LogisticRegression(max_iter=2000).fit(ss.transform(X[tr]), y[tr], sample_weight=w[tr])
            p[te] = m.predict_proba(ss.transform(X[te]))[:, 1]
        return p
    d2 = roc_auc_score(y, oof(feat(["B1", "B2", "DC"])), sample_weight=w) - roc_auc_score(y, oof(feat(["B1", "B2"])), sample_weight=w)
    out["x2"] = {"groupkfold_delta": d2, "analysis_delta": tests["X2"]["delta"], "abs_diff": abs(d2 - tests["X2"]["delta"]),
                 "note": "different fold assignment (sklearn GroupKFold vs 5x5 seeded sentence folds): agreement in sign/size expected, not 0.005"}
    out["auroc_match_within_0.005"] = out["max_abs_diff"] <= 0.005
    (RES / "audit_rederive.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: out[k] for k in ("n", "max_abs_diff", "auroc_match_within_0.005", "x2")}, indent=1))


if __name__ == "__main__":
    main()
