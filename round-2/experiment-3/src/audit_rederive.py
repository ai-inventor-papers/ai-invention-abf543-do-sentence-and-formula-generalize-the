#!/usr/bin/env python3
"""T5 INTEGRITY: independent re-derivation (numpy only, separate hand-written code) of the headline numbers.

Reads the DATASET parts directly (not work/frame.jsonl) and results/heldout_scores.jsonl, recomputes
  * weighted panel AUROC (L3_sampling_weight) for LC_onecoin, A3 and the cheap judge (B1, or its local substitute B1L)
  * circularity test (b): weighted AUROC inside panel items with L1_audited_status in {non_equiv, non_equiv_no_bijection}
with an O(n^2) pairwise formula, and compares with results/analysis.json (must match to 1e-6).
"""
from __future__ import annotations

import glob
import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
DS = Path("/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_dataset_1")


def pairwise_auc(y, s, w):
    y, s, w = np.asarray(y, int), np.asarray(s, float), np.asarray(w, float)
    pos, neg = np.where(y == 1)[0], np.where(y == 0)[0]
    num = 0.0
    for i in pos:
        d = s[i] - s[neg]
        num += w[i] * np.sum(w[neg] * (np.where(d > 0, 1.0, 0.0) + np.where(d == 0, 0.5, 0.0)))
    return num / (w[pos].sum() * w[neg].sum())


def main():
    panel = {}
    for f in sorted(glob.glob(str(DS / "full_data_out" / "full_data_out_*.json"))):
        d = json.loads(Path(f).read_text())
        for g in d["datasets"]:
            if g["dataset"] != "heldout_confirm":
                continue
            for ex in g["examples"]:
                if ex["metadata_label_source"] == "panel3" and ex["output"] in ("faithful", "unfaithful"):
                    panel[ex["metadata_item_id"]] = (int(ex["output"] == "faithful"), ex["metadata_L3_sampling_weight"],
                                                     ex["metadata_L1_audited_status"])
    scores = {}
    for line in (ROOT / "results" / "heldout_scores.jsonl").read_text().splitlines():
        r = json.loads(line)
        scores[(r["item_id"], r["metric"])] = r["score"]
    ana = json.loads((ROOT / "results" / "analysis.json").read_text())
    judge = "B1" if ("B1" in ana["auroc"] and ana["auroc"]["B1"]["P"]["auroc"] is not None) else "B1L"
    out = {"n_panel": len(panel), "judge_used": judge, "checks": {}}
    for m in ("LC_onecoin", "A3", judge):
        ids = [i for i in panel if (i, m) in scores]
        a = pairwise_auc([panel[i][0] for i in ids], [scores[(i, m)] for i in ids], [panel[i][1] for i in ids])
        ref = ana["auroc"][m]["P"]["auroc"]
        out["checks"][f"P:{m}"] = {"rederived": a, "analysis": ref, "absdiff": abs(a - ref), "ok": bool(abs(a - ref) < 1e-6)}
        ids_b = [i for i in ids if panel[i][2] in ("non_equiv", "non_equiv_no_bijection")]
        ab = pairwise_auc([panel[i][0] for i in ids_b], [scores[(i, m)] for i in ids_b], [panel[i][1] for i in ids_b])
        refb = (ana["circularity"]["b_nonequiv"].get(m) or {}).get("auroc")
        if refb is not None:
            out["checks"][f"circ_b:{m}"] = {"rederived": ab, "analysis": refb, "absdiff": abs(ab - refb),
                                            "n": len(ids_b), "ok": bool(abs(ab - refb) < 1e-6)}
    out["all_ok"] = all(v["ok"] for v in out["checks"].values())
    # placebo: the same AUROC on PERMUTED panel labels (within the panel set) must sit at ~0.5; permutation p-value of
    # the real AUROC; and a sentence-bootstrap CI on permuted labels must cover 0.5 (the 'artefact' reading)
    rng = np.random.default_rng(123)
    plac = {}
    for m in ("LC_onecoin", "A3", judge):
        ids = [i for i in panel if (i, m) in scores]
        ids_b = [i for i in ids if panel[i][2] in ("non_equiv", "non_equiv_no_bijection")]
        for tag, I in (("P", ids), ("circ_b", ids_b)):
            y = np.array([panel[i][0] for i in I]); s = np.array([scores[(i, m)] for i in I])
            w = np.array([panel[i][1] for i in I])
            real = pairwise_auc(y, s, w)
            perm = np.array([pairwise_auc(rng.permutation(y), s, w) for _ in range(200)])
            yp = rng.permutation(y)
            sid = np.array([i.split(":")[0] for i in I])
            us = np.unique(sid)
            boots = []
            for _ in range(200):
                pick = rng.choice(us, len(us))
                idx = np.concatenate([np.where(sid == u)[0] for u in pick])
                if len(np.unique(yp[idx])) == 2:
                    boots.append(pairwise_auc(yp[idx], s[idx], w[idx]))
            lo, hi = np.percentile(boots, [2.5, 97.5])
            plac[f"{tag}:{m}"] = {"real": real, "perm_mean": float(perm.mean()), "perm_sd": float(perm.std()),
                                  "perm_p_one_sided": float((np.sum(perm >= real) + 1) / (len(perm) + 1)),
                                  "shuffled_label_ci": [float(lo), float(hi)],
                                  "shuffled_ci_covers_0.5": bool(lo <= 0.5 <= hi)}
    out["placebo_permuted_labels"] = plac
    out["placebo_ok"] = bool(all(v["shuffled_ci_covers_0.5"] and abs(v["perm_mean"] - 0.5) < 0.02 for v in plac.values()))
    # independent C2 re-derivation: numpy-only weighted logistic (IRLS, ridge 1e-3) with folds = hash(sentence) % 5,
    # base = the analysis' frozen base features; delta for LC_onecoin and A3; placebo = the same metric with its scores
    # SHUFFLED across items (must give ~0)
    base = ana["meta"]["base_features_used"]

    def irls(X, y, w, iters=50):
        X1 = np.c_[np.ones(len(X)), X]
        b = np.zeros(X1.shape[1])
        for _ in range(iters):
            p = 1 / (1 + np.exp(-X1 @ b))
            W = w * p * (1 - p) + 1e-9
            H = X1.T @ (X1 * W[:, None]) + 1e-3 * np.eye(X1.shape[1])
            g = X1.T @ (w * (y - p)) - 1e-3 * b
            b = b + np.linalg.solve(H, g)
        return b

    def oof(feats, ids):
        X = np.array([[scores.get((i, f), 0.5) for f in feats] for i in ids], float)
        X = (X - X.mean(0)) / (X.std(0) + 1e-9)
        y = np.array([panel[i][0] for i in ids], float)
        w = np.array([panel[i][1] for i in ids], float)
        fold = np.array([int(hashlib.md5(i.split(":")[0].encode()).hexdigest(), 16) % 5 for i in ids])
        pr = np.zeros(len(ids))
        for k in range(5):
            tr, te = fold != k, fold == k
            b = irls(X[tr], y[tr], w[tr])
            pr[te] = 1 / (1 + np.exp(-(np.c_[np.ones(te.sum()), X[te]] @ b)))
        return pr, y, w
    ids = sorted(panel)
    p0, y, w = oof(base, ids)
    c2 = {"base": base, "auc_base": pairwise_auc(y, p0, w)}
    for m in ("LC_onecoin", "A3"):
        p1, _, _ = oof(base + [m], ids)
        c2[m] = pairwise_auc(y, p1, w) - c2["auc_base"]
        sh = dict(zip(ids, rng.permutation([scores.get((i, m), 0.5) for i in ids])))
        for i in ids:
            scores[(i, m + "_SHUF")] = sh[i]
        p2, _, _ = oof(base + [m + "_SHUF"], ids)
        c2[m + "_shuffled_placebo"] = pairwise_auc(y, p2, w) - c2["auc_base"]
    c2["analysis_delta"] = {m: (ana["stacking"]["per_metric"].get(m) or {}).get("delta") for m in ("LC_onecoin", "A3")}
    c2["note"] = "different folds and solver than analysis.py; agreement within ~0.02 expected, placebo ~0"
    out["C2_independent"] = c2
    (ROOT / "results" / "audit_rederive.json").write_text(json.dumps(out, indent=1, default=float))
    print(json.dumps(out, indent=1, default=float))


if __name__ == "__main__":
    main()
