"""Vectorised finite-model fingerprints (name-independent).

A fixed bank of N=64 random finite structures (32 of domain size 2, 32 of size 3; padded to 3 elements, quantifiers
masked by the per-structure domain size). Predicates and constants are bound to bank SLOTS by first-occurrence
position, never by name, so a renamed formula receives exactly the same interpretations.
truth_vector(F, slots) -> bool[N]. Every refutation derived from these vectors is sound (real finite models).
"""
from __future__ import annotations

import numpy as np

N = 64
D = 3
MAXSLOT = 96
DOM = np.array([2] * (N // 2) + [3] * (N // 2))
_AR = np.arange(N)


def _bank():
    P = {}
    for a in range(0, 5):
        P[a] = []
        for s in range(MAXSLOT):
            rng = np.random.default_rng(1_000_003 * (a + 1) + 7919 * s)
            P[a].append(rng.random((N,) + (D,) * a) < 0.5)
    C = []
    for s in range(MAXSLOT):
        rng = np.random.default_rng(424242 + 31 * s)
        C.append((rng.random(N) * DOM).astype(int))
    return P, C


PB, CB = _bank()


def first_occurrence(F) -> tuple[list[str], list[str]]:
    """Predicate names and constant names in pre-order first-occurrence order."""
    preds, consts = [], []

    def rec(m):
        k = m[0]
        if k == "atom":
            if m[1] not in preds:
                preds.append(m[1])
            for t in m[2]:
                if t[0] == "c" and t[1] not in consts:
                    consts.append(t[1])
        elif k == "eq":
            for t in m[1:]:
                if t[0] == "c" and t[1] not in consts:
                    consts.append(t[1])
        elif k in ("forall", "exists"):
            rec(m[2])
        else:
            for a in m[1:]:
                rec(a)
    rec(F)
    return preds, consts


def slotmap(*formulas) -> tuple[dict, dict]:
    """Slots by first occurrence across the given formulas (in order)."""
    ps, cs = {}, {}
    for F in formulas:
        p, c = first_occurrence(F)
        for x in p:
            if x not in ps:
                ps[x] = len(ps)
        for x in c:
            if x not in cs:
                cs[x] = len(cs)
    return ps, cs


def _val(t, env, cs):
    return env[t[1]] if t[0] == "v" else CB[cs[t[1]] % MAXSLOT]


def _ev(n, env, ps, cs):
    k = n[0]
    if k == "atom":
        a = len(n[2])
        ext = PB[min(a, 4)][ps[n[1]] % MAXSLOT]
        if a == 0:
            return ext
        idx = (_AR,) + tuple(_val(t, env, cs) for t in n[2])
        return ext[idx]
    if k == "eq":
        a, b = _val(n[1], env, cs), _val(n[2], env, cs)
        return np.broadcast_to(np.asarray(a) == np.asarray(b), (N,))
    if k == "not":
        return ~_ev(n[1], env, ps, cs)
    if k == "and":
        out = _ev(n[1], env, ps, cs)
        for x in n[2:]:
            out = out & _ev(x, env, ps, cs)
        return out
    if k == "or":
        out = _ev(n[1], env, ps, cs)
        for x in n[2:]:
            out = out | _ev(x, env, ps, cs)
        return out
    if k == "imp":
        return (~_ev(n[1], env, ps, cs)) | _ev(n[2], env, ps, cs)
    if k == "iff":
        return _ev(n[1], env, ps, cs) == _ev(n[2], env, ps, cs)
    if k == "xor":
        return _ev(n[1], env, ps, cs) != _ev(n[2], env, ps, cs)
    if k == "forall":
        acc = np.ones(N, dtype=bool)
        for e in range(D):
            acc &= _ev(n[2], {**env, n[1]: e}, ps, cs) | (e >= DOM)
        return acc
    if k == "exists":
        acc = np.zeros(N, dtype=bool)
        for e in range(D):
            acc |= _ev(n[2], {**env, n[1]: e}, ps, cs) & (e < DOM)
        return acc
    raise ValueError(k)


def truth_vector(F, ps: dict, cs: dict) -> np.ndarray:
    return np.asarray(_ev(F, {}, ps, cs), dtype=bool)
