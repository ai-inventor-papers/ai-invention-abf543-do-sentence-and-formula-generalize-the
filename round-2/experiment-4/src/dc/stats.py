"""Statistics: exp3's weighted AUROC / stratified sentence-cluster bootstrap / cross-fitted stacking (vendored,
imported by path), NBOOT = 2000, plus within-sentence pairwise detection helpers."""
from __future__ import annotations

import importlib.util
import math
from collections import defaultdict

import numpy as np

from .common import ROOT

_spec = importlib.util.spec_from_file_location("exp3_stats", ROOT / "vendor" / "exp3" / "stats.py")
S3 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(S3)
wauc, wauc_pairwise, kish, oof_stack, ci = S3.wauc, S3.wauc_pairwise, S3.kish, S3.oof_stack, S3.ci
NBOOT = 2000


def boot(sids, strata: dict, n: int = NBOOT, seed: int = 0):
    return S3.StratBoot(sids, strata, n=n, seed=seed)


def auc_ci(y, s, w, sids, strata, n: int = NBOOT, seed: int = 0) -> dict:
    y, s = np.asarray(y, float), np.asarray(s, float)
    w = np.ones(len(y)) if w is None else np.asarray(w, float)
    if len(y) < 5 or len(np.unique(y)) < 2:
        return {"auroc": None, "ci": [None, None], "n": int(len(y))}
    a = wauc(y, s, w)
    b = boot(sids, strata, n=n, seed=seed)
    vals = [wauc(y[ix], s[ix], w[ix]) for ix in b]
    return {"auroc": a, "ci": ci(vals), "n": int(len(y)), "n_sentences": int(len(set(sids)))}


def paired_delta(y, s1, s2, w, sids, strata, n: int = NBOOT, seed: int = 0) -> dict:
    y, s1, s2 = np.asarray(y, float), np.asarray(s1, float), np.asarray(s2, float)
    w = np.ones(len(y)) if w is None else np.asarray(w, float)
    d = wauc(y, s1, w) - wauc(y, s2, w)
    b = boot(sids, strata, n=n, seed=seed)
    vals = [wauc(y[ix], s1[ix], w[ix]) - wauc(y[ix], s2[ix], w[ix]) for ix in b]
    return {"delta": d, "ci": ci(vals)}


def cluster_boot_mean(vals, wts, groups, n: int = NBOOT, seed: int = 0) -> dict:
    """Weighted mean with a sentence-clustered bootstrap CI (for detection rates)."""
    v, w = np.asarray(vals, float), np.asarray(wts, float)
    ok = ~np.isnan(v)
    if not ok.any():
        return {"mean": None, "ci": [None, None], "n": 0}
    v, w = v[ok], w[ok]
    g = np.asarray(groups)[ok]
    by = defaultdict(list)
    for i, x in enumerate(g):
        by[x].append(i)
    arrs = [np.array(a) for a in by.values()]
    rng = np.random.default_rng(seed)
    bs = []
    for _ in range(n):
        pick = rng.integers(0, len(arrs), len(arrs))
        ix = np.concatenate([arrs[k] for k in pick])
        bs.append(float(np.sum(v[ix] * w[ix]) / np.sum(w[ix])))
    return {"mean": float(np.sum(v * w) / np.sum(w)), "ci": ci(bs), "n": int(len(v)), "n_groups": len(arrs)}


def det(s_good, s_bad) -> float:
    """1[s_good > s_bad] + 0.5 * tie."""
    if s_good is None or s_bad is None or (isinstance(s_good, float) and math.isnan(s_good)):
        return float("nan")
    return 1.0 if s_good > s_bad else (0.5 if s_good == s_bad else 0.0)
