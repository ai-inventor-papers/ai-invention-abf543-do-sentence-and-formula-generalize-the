#!/usr/bin/env python3
"""Independent re-derivation of the headline numbers (TODO 4 audit).

Reads RAW per-item files only (data/screen_set.json labels, results/*.jsonl per-item scores, cost ledger) and
recomputes through code paths that share nothing with analyze.py:
  * AUROC by the Mann-Whitney rank formula (average ranks for ties) - no sklearn
  * sentence-clustered bootstrap with its own RNG/seed
  * G3 increment with a hand-written Newton-Raphson logistic regression and hash-based sentence folds
  * G2 false alarms and mutant detection by direct comparison with the gold row
Placebos: permuted labels (AUROC ~ 0.5, increment CI must include 0) and a random-noise "metric".
Output: results/audit_rederive.json
"""
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
R = ROOT / "results"


def rows(p):
    return [json.loads(l) for l in (R / p).read_text().splitlines() if l.strip()]


def mw_auc(y, s):
    y, s = np.asarray(y, int), np.asarray(s, float)
    order = np.argsort(s, kind="mergesort")
    ranks = np.empty(len(s))
    ss = s[order]
    i = 0
    while i < len(ss):
        j = i
        while j + 1 < len(ss) and ss[j + 1] == ss[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2 + 1
        i = j + 1
    n1, n0 = y.sum(), len(y) - y.sum()
    if n1 == 0 or n0 == 0:
        return float("nan")
    return float((ranks[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def newton_logit(X, y, iters=50, l2=1.0):
    X = np.column_stack([np.ones(len(X)), X])
    w = np.zeros(X.shape[1])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-X @ w))
        g = X.T @ (p - y) + l2 * np.r_[0, w[1:]]
        H = X.T @ (X * (p * (1 - p))[:, None]) + l2 * np.diag(np.r_[0, np.ones(len(w) - 1)])
        w -= np.linalg.solve(H, g)
    return w


def oof(X, y, sids, k=5):
    fold = np.array([int(hashlib.md5(s.encode()).hexdigest(), 16) % k for s in sids])
    p = np.zeros(len(y))
    for j in range(k):
        tr, te = fold != j, fold == j
        mu, sd = X[tr].mean(0), X[tr].std(0) + 1e-9
        w = newton_logit((X[tr] - mu) / sd, y[tr])
        Z = np.column_stack([np.ones(te.sum()), (X[te] - mu) / sd])
        p[te] = 1 / (1 + np.exp(-Z @ w))
    return p


def boot_idx(sids, B=500, seed=12345):
    rng = np.random.default_rng(seed)
    by = defaultdict(list)
    for i, s in enumerate(sids):
        by[s].append(i)
    keys = sorted(by)
    for _ in range(B):
        pick = rng.integers(0, len(keys), len(keys))
        yield np.concatenate([by[keys[t]] for t in pick])


def main():
    d = json.loads((ROOT / "data/screen_set.json").read_text())
    real = {r["item_id"]: r for r in d["real"]}
    ids = sorted(real)
    y = np.array([real[i]["correct"] for i in ids], int)
    sids = [real[i]["sid"] for i in ids]
    sc = defaultdict(dict)
    for f in ("screen_scores_signature.jsonl", "baseline_b1.jsonl", "baseline_b3.jsonl", "baseline_b8.jsonl"):
        for r in rows(f):
            sc[(r["metric"], r["set"])][r["item_id"]] = r["score"]
    get = lambda m: np.array([sc[(m, "real")].get(i, 0.5) for i in ids], float)  # noqa: E731
    parse = np.array([float(real[i]["parse_ok"]) for i in ids])
    out = {"n_items": len(ids), "positive_rate": float(y.mean())}

    # AUROC + clustered CI
    out["auroc"] = {}
    for m in ("A1", "A2", "A3", "A0", "Ccov", "B1", "B3nli", "B3cos", "B4", "B5", "B8"):
        s = get(m)
        bs = [mw_auc(y[ix], s[ix]) for ix in boot_idx(sids)]
        out["auroc"][m] = {"auroc": mw_auc(y, s), "ci95": [float(np.nanpercentile(bs, 2.5)), float(np.nanpercentile(bs, 97.5))]}
    out["auroc"]["B2_parse"] = {"auroc": mw_auc(y, parse)}

    # top tercile
    terc = {s["sid"]: s["tercile"] for s in d["sentences"]}
    top = np.array([terc[s] == "top" for s in sids])
    out["top_tercile_auroc"] = {m: mw_auc(y[top], get(m)[top]) for m in ("A1", "A3", "B1", "B5")}

    # G3 increment over [B1, parse]
    def incr(base, extra, yy):
        X0 = np.column_stack(base)
        X1 = np.column_stack(base + [extra])
        p0, p1 = oof(X0, yy, sids), oof(X1, yy, sids)
        bs = [mw_auc(yy[ix], p1[ix]) - mw_auc(yy[ix], p0[ix]) for ix in boot_idx(sids, B=300)]
        return {"delta": mw_auc(yy, p1) - mw_auc(yy, p0), "ci95": [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))]}
    b1 = get("B1")
    out["g3"] = {m: incr([b1, parse], get(m), y) for m in ("A1", "A3")}
    out["increment_over_B1_parse_A0"] = {m: incr([b1, parse, get("A0")], get(m), y) for m in ("A1", "A3")}

    # placebos
    rng = np.random.default_rng(7)
    yp = rng.permutation(y)
    out["placebo_permuted_labels"] = {"auroc_A3": mw_auc(yp, get("A3")), "g3_A3": incr([b1, parse], get("A3"), yp)}
    out["placebo_random_metric"] = {"auroc": mw_auc(y, rng.random(len(y))), "g3": incr([b1, parse], rng.random(len(y)), y)}

    # G2 false alarms (delta=0 for signatures, 0.10 for B1) + mutant detection
    gold = {m: {r["sid"]: r["score"] for r in rows("screen_scores_signature.jsonl") if r["set"] == "gold" and r["metric"] == m}
            for m in ("A1", "A3")}
    gold["B1"] = {r["sid"]: r["score"] for r in rows("baseline_b1.jsonl") if r["set"] == "gold"}
    g2 = {}
    sig_rows = rows("screen_scores_signature.jsonl")
    for m in ("A1", "A3"):
        rr = [r for r in sig_rows if r["set"] == "rewrite" and r["metric"] == m]
        fa = [r["score"] < gold[m][r["sid"]] for r in rr]
        ren = [r["score"] < gold[m][r["sid"]] for r in rr if r["kind"] == "SYN_RENAME"]
        oth = [r["score"] < gold[m][r["sid"]] for r in rr if r["kind"] != "SYN_RENAME"]
        g2[m] = {"rate": float(np.mean(fa)), "n": len(fa), "rename": float(np.mean(ren)), "other": float(np.mean(oth)),
                 "n_other": len(oth)}
    rb = [r for r in rows("baseline_b1.jsonl") if r["set"] == "rewrite"]
    g2["B1"] = {"rate": float(np.mean([r["score"] < gold["B1"][r["sid"]] - 0.10 for r in rb])), "n": len(rb)}
    out["g2"] = g2
    det = {}
    for m in ("A1",):
        for op in ("NEG", "IMPL_REV", "CARD", "ANDOR", "ARG_SWAP"):
            rr = [r for r in sig_rows if r["set"] == "mutant" and r["metric"] == m and r["operator"] == op]
            det[f"{m}_{op}"] = float(np.mean([(r["score"] < gold[m][r["sid"]]) + 0.5 * (r["score"] == gold[m][r["sid"]])
                                              for r in rr]))
    out["mutant_detection_tiehalf"] = det

    # labels + cost
    out["equiv_rate_by_system"] = {s: float(np.mean([real[i]["correct"] for i in ids if real[i]["system"] == s]))
                                   for s in ("gpt-3.5-turbo", "gpt-4", "text-davinci-003")}
    out["total_usd_from_ledger"] = float(sum(r.get("cost") or 0 for r in rows("cost_ledger.jsonl")))
    (R / "audit_rederive.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
