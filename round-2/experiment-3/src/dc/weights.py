"""Label-free system reliability weights for Directional Consensus.

fit_weights: one-coin Dawid-Skene over systems, fitted WITHOUT labels on the EQUIV clusters of each sentence
(classes = connected components of the solver EQUIV graph over the parseable outputs). The latent truth of a
sentence is one of its observed clusters (uniform prior); system s lands in the true cluster with probability p_s.
A wrong system lands in one specific wrong cluster with chance q = 1/max(2, #clusters); without this
per-wrong-answer penalty EM drifts to the label-switched optimum (truth = the cluster of the weakest systems).
A 'none of the clusters' hypothesis is not modelled (it is a degenerate attractor).
Weight w_s = clip(logit(p_s), 0.05, 3); mode 'uniform' gives w_s = 1.
"""
from __future__ import annotations

import math


def fit_weights(sentences: list[dict], systems: list[str], mode: str = "DS", n_iter: int = 200,
                tol: float = 1e-7) -> tuple[dict[str, float], dict]:
    """sentences: [{'cls': {system: cluster_id or None (unparseable/absent)}}]. Returns (weights, info)."""
    if mode == "uniform":
        return {s: 1.0 for s in systems}, {"mode": "uniform"}
    # initialise from the majority-vote agreement rate (breaks the symmetric start)
    agree = {s: [0, 0] for s in systems}
    for sent in sentences:
        vals = [c for c in sent["cls"].values() if c is not None]
        if not vals:
            continue
        top = max(set(vals), key=lambda c: (vals.count(c), -c if isinstance(c, int) else 0))
        for s_, c in sent["cls"].items():
            if s_ in agree:
                agree[s_][0] += c == top
                agree[s_][1] += 1
    p = {s: min(0.95, max(0.05, agree[s][0] / agree[s][1])) if agree[s][1] else 0.5 for s in systems}
    ll_old = -float("inf")
    it = 0
    posts = []
    for it in range(n_iter):
        posts = []
        ll = 0.0
        acc = {s: 0.0 for s in systems}
        none_mass = 0.0
        for sent in sentences:
            cls = sent["cls"]
            present = [s for s in systems if s in cls]
            valid = sorted({c for c in cls.values() if c is not None})
            if not present:
                posts.append({})
                continue
            logs = {}
            # a wrong system lands in one specific wrong cluster with chance q = 1/max(2, #clusters)
            lq = -math.log(max(2, len(valid)))
            for c in valid:
                lg = -math.log(len(valid))
                for s in present:
                    lg += math.log(p[s]) if cls[s] == c else (math.log(1 - p[s]) + lq)
                logs[c] = lg
            if not valid:
                posts.append({})
                continue
            mx = max(logs.values())
            z = sum(math.exp(v - mx) for v in logs.values())
            ll += mx + math.log(z)
            post = {c: math.exp(v - mx) / z for c, v in logs.items()}
            posts.append(post)
            
            for s in present:
                c = cls[s]
                if c is not None:
                    acc[s] += post.get(c, 0.0)
        cnt = {s: sum(1 for sent in sentences if s in sent["cls"]) for s in systems}
        p = {s: min(0.995, max(0.005, acc[s] / cnt[s])) if cnt[s] else 0.5 for s in systems}
        if abs(ll - ll_old) < tol:
            break
        ll_old = ll
    w = {s: min(3.0, max(0.05, math.log(p[s] / (1 - p[s])))) for s in systems}
    return w, {"mode": "DS", "p": p, "iters": it + 1, "loglik": ll_old}


__all__ = ["fit_weights"]
