"""Statistics helpers: weighted AUROC (fast tie-aware + hand pairwise reference), soft-label expected AUROC,
stratified sentence-cluster bootstrap, Kish n_eff, cross-fitted logistic stacking, Kendall tau-b + pairwise accuracy."""
from __future__ import annotations

import math
from collections import defaultdict

import numpy as np

NBOOT = 1000


def wauc(y, s, w=None) -> float:
    """Weighted AUROC = sum_{i in pos, j in neg} w_i w_j (1[s_i>s_j] + 0.5 1[s_i=s_j]) / (W+ W-). Ties handled by
    grouping equal scores. Equals sklearn roc_auc_score(y, s, sample_weight=w)."""
    y = np.asarray(y, dtype=float)
    s = np.asarray(s, dtype=float)
    w = np.ones(len(y)) if w is None else np.asarray(w, dtype=float)
    wp, wn = w * y, w * (1 - y)
    Wp, Wn = wp.sum(), wn.sum()
    if Wp <= 0 or Wn <= 0:
        return float("nan")
    order = np.argsort(s, kind="mergesort")
    s_o, wp_o, wn_o = s[order], wp[order], wn[order]
    uniq, idx = np.unique(s_o, return_index=True)
    gp = np.add.reduceat(wp_o, idx)
    gn = np.add.reduceat(wn_o, idx)
    cum_n_below = np.concatenate([[0.0], np.cumsum(gn)[:-1]])
    num = (gp * cum_n_below).sum() + 0.5 * (gp * gn).sum()
    return float(num / (Wp * Wn))


def wauc_pairwise(y, s, w=None) -> float:
    """O(n^2) hand implementation (T0b cross-check)."""
    y = np.asarray(y, dtype=int)
    s = np.asarray(s, dtype=float)
    w = np.ones(len(y)) if w is None else np.asarray(w, dtype=float)
    P, N = np.where(y == 1)[0], np.where(y == 0)[0]
    if len(P) == 0 or len(N) == 0:
        return float("nan")
    num = den = 0.0
    for i in P:
        d = s[i] - s[N]
        num += w[i] * (w[N] * ((d > 0) + 0.5 * (d == 0))).sum()
        den += w[i] * w[N].sum()
    return float(num / den)


def soft_auc(q, s, w=None) -> float:
    """Expected AUROC with soft labels: item i is positive with weight q_i*w_i and negative with (1-q_i)*w_i;
    self-pairs (i as both positive and negative) are excluded."""
    q = np.asarray(q, dtype=float)
    s = np.asarray(s, dtype=float)
    w = np.ones(len(q)) if w is None else np.asarray(w, dtype=float)
    yy = np.r_[np.ones(len(q)), np.zeros(len(q))]
    ss = np.r_[s, s]
    ww = np.r_[q * w, (1 - q) * w]
    Wp, Wn = (q * w).sum(), ((1 - q) * w).sum()
    a = wauc(yy, ss, ww)
    if math.isnan(a):
        return a
    num = a * Wp * Wn - 0.5 * (q * (1 - q) * w * w).sum()
    den = Wp * Wn - (q * (1 - q) * w * w).sum()
    return float(num / den) if den > 0 else float("nan")


def kish(w) -> float:
    w = np.asarray(w, dtype=float)
    return float(w.sum() ** 2 / (w ** 2).sum()) if len(w) else 0.0


class StratBoot:
    """Pre-drawn bootstrap resamples of SENTENCES within sentence-level strata (paired across metrics)."""

    def __init__(self, sids, strata_of_sid: dict, n: int = NBOOT, seed: int = 0):
        sids = np.asarray(sids)
        self.idx_by = defaultdict(list)
        for i, s in enumerate(sids):
            self.idx_by[s].append(i)
        self.idx_by = {k: np.asarray(v) for k, v in self.idx_by.items()}
        by_stratum = defaultdict(list)
        for s in sorted(self.idx_by):
            by_stratum[strata_of_sid.get(s, "NA")].append(s)
        rng = np.random.default_rng(seed)
        self.draws = []
        for _ in range(n):
            pick = []
            for st in sorted(by_stratum):
                L = by_stratum[st]
                pick.extend(L[j] for j in rng.choice(len(L), size=len(L), replace=True))
            self.draws.append(np.concatenate([self.idx_by[s] for s in pick]))
        self.by_stratum = {k: len(v) for k, v in by_stratum.items()}

    def __iter__(self):
        return iter(self.draws)


def ci(vals) -> list:
    v = np.array([x for x in vals if x is not None and not (isinstance(x, float) and math.isnan(x))])
    if len(v) == 0:
        return [None, None]
    return [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]


def boot_stat(boot: StratBoot, fn) -> list:
    return ci(fn(idx) for idx in boot)


def oof_stack(X: np.ndarray, y: np.ndarray, sids: np.ndarray, w: np.ndarray | None = None, k: int = 5,
              n_rep: int = 5, seed0: int = 100) -> np.ndarray:
    """Sentence-grouped k-fold x n_rep shuffles; standardised features; LogisticRegression(C=1, lbfgs, max_iter 2000)
    fitted with sample weights; OOF probabilities averaged over shuffles."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    y = np.asarray(y).astype(int)
    w = np.ones(len(y)) if w is None else np.asarray(w, dtype=float)
    uniq = np.unique(sids)
    out = np.zeros(len(y))
    for r in range(n_rep):
        rng = np.random.default_rng(seed0 + r)
        perm = rng.permutation(uniq)
        fold_of = {s: i % k for i, s in enumerate(perm)}
        f = np.array([fold_of[s] for s in sids])
        p = np.zeros(len(y))
        for j in range(k):
            tr, te = f != j, f == j
            if te.sum() == 0:
                continue
            if len(np.unique(y[tr])) < 2:
                p[te] = np.average(y[tr], weights=w[tr])
                continue
            sc = StandardScaler().fit(X[tr])
            m = LogisticRegression(C=1.0, solver="lbfgs", max_iter=2000).fit(sc.transform(X[tr]), y[tr],
                                                                            sample_weight=w[tr])
            p[te] = m.predict_proba(sc.transform(X[te]))[:, 1]
        out += p / n_rep
    return out


def kendall_pairwise(metric_s: dict, truth_s: dict) -> dict:
    from scipy.stats import kendalltau
    ks = sorted(set(metric_s) & set(truth_s))
    m = np.array([metric_s[k] for k in ks])
    t = np.array([truth_s[k] for k in ks])
    tau = kendalltau(m, t, variant="b").statistic if len(ks) >= 3 else float("nan")
    agree = tot = 0
    for i in range(len(ks)):
        for j in range(i + 1, len(ks)):
            if t[i] == t[j]:
                continue
            tot += 1
            agree += (m[i] - m[j]) * (t[i] - t[j]) > 0
    return {"tau_b": None if tau is None or (isinstance(tau, float) and math.isnan(tau)) else float(tau),
            "pairwise_acc": agree / tot if tot else None, "n_pairs": tot, "n_systems": len(ks)}
