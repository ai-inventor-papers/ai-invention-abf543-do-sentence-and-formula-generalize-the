"""align_pair: which vocabulary correspondences between two formulas are admissible, found by solver-guided search
with NO use of symbol names.

Roles: the SOURCE formula (fewer predicates; ties -> fewer occurrences -> the second argument) is mapped into the
TARGET's vocabulary. A map sends each source predicate/constant to a same-arity target symbol or leaves it FRESH
(a distinct new symbol).
  L1  arity-preserving bijections of predicates + constants (cap 5040)
  L2  partial injective arity-preserving maps covering >= 50% of the source's predicate OCCURRENCES (cap 2000)
  L3  granularity definitions on top of the best L2 maps: an unmapped predicate Q of either side is DEFINED as a
      conjunction of <= 2 literals over the other side's predicates with a consistent argument pattern
      (unary: P(x) / ¬P(x) / L1(x) ∧ L2(x); binary: P(y,x) / ¬P(x,y) / P(x,y)); <= 2 definitions per pair,
      <= 300 candidate definition sets.
Ordering of candidate maps uses name-independent keys only: fingerprint agreement, occurrence-count match, polarity
match, first-occurrence positions. Renaming either formula therefore cannot change which maps are searched.
"""
from __future__ import annotations

import itertools
import time

import numpy as np

from . import front  # noqa: F401
import fol_core as fc  # noqa: E402
from .fp import first_occurrence, slotmap, truth_vector

L1_CAP = 5040
L2_CAP = 2000
L3_CAP = 300
L2_MIN_COVER = 0.5


# ------------------------------------------------------------------------------------------ profiles
def profiles(F) -> dict:
    """Per symbol: arity, occurrences, positive/negative polarity occurrences, first-occurrence index.
    Constants have arity 'c'."""
    preds, consts = first_occurrence(F)
    ar = fc.predicates(F, strict=False) or {}
    prof = {p: {"arity": ar.get(p, 0), "occ": 0, "pos": 0, "neg": 0, "idx": i} for i, p in enumerate(preds)}
    cprof = {c: {"arity": "c", "occ": 0, "pos": 0, "neg": 0, "idx": i} for i, c in enumerate(consts)}

    def rec(m, pol):
        k = m[0]
        if k == "atom":
            d = prof[m[1]]
            d["occ"] += 1
            if pol >= 0:
                d["pos"] += 1
            if pol <= 0:
                d["neg"] += 1
            for t in m[2]:
                if t[0] == "c":
                    cprof[t[1]]["occ"] += 1
        elif k == "eq":
            for t in m[1:]:
                if t[0] == "c":
                    cprof[t[1]]["occ"] += 1
        elif k == "not":
            rec(m[1], -pol)
        elif k == "imp":
            rec(m[1], -pol)
            rec(m[2], pol)
        elif k in ("iff", "xor"):
            rec(m[1], 0)
            rec(m[2], 0)
        elif k in ("forall", "exists"):
            rec(m[2], pol)
        else:
            for a in m[1:]:
                rec(a, pol)
    rec(F, 1)
    return {"P": prof, "C": cprof}


def _pdist(a: dict, b: dict) -> tuple:
    return (abs(a["occ"] - b["occ"]) + abs(a["pos"] - b["pos"]) + abs(a["neg"] - b["neg"]), abs(a["idx"] - b["idx"]),
            b["idx"])


def roles(FA, FB) -> tuple[str, str]:
    """('T','S') assignment: returns which of 'A'/'B' is the target and which the source."""
    pa, pb = fc.predicates(FA, strict=False) or {}, fc.predicates(FB, strict=False) or {}
    occa = sum(profiles(FA)["P"][p]["occ"] for p in pa)
    occb = sum(profiles(FB)["P"][p]["occ"] for p in pb)
    if (len(pb), occb) <= (len(pa), occa):
        return "A", "B"
    return "B", "A"


# ------------------------------------------------------------------------------------------ map enumeration
def _symbols(prof: dict) -> list[tuple[str, str, dict]]:
    """Source symbols in first-occurrence order: predicates first, then constants."""
    ps = sorted(prof["P"].items(), key=lambda kv: kv[1]["idx"])
    cs = sorted(prof["C"].items(), key=lambda kv: kv[1]["idx"])
    return [("P", n, d) for n, d in ps] + [("C", n, d) for n, d in cs]


def enumerate_maps(profS: dict, profT: dict, level: int, cap: int, deadline: float) -> list[dict]:
    """DFS over source symbols; targets ordered by profile distance then first-occurrence index (name-free).
    level 1: bijections (every symbol mapped, arity multisets equal); level 2: partial injective, >=50% occurrence
    coverage of source predicates; FRESH (None) tried last."""
    syms = _symbols(profS)
    tsyms = {"P": profT["P"], "C": profT["C"]}
    occ_tot = sum(d["occ"] for k, _, d in syms if k == "P") or 1
    if level == 1:
        arS = sorted(d["arity"] for d in profS["P"].values())
        arT = sorted(d["arity"] for d in profT["P"].values())
        if arS != arT or len(profS["C"]) != len(profT["C"]):
            return []
    options = []
    for kind, n, d in syms:
        cands = [(t, td) for t, td in tsyms[kind].items() if td["arity"] == d["arity"]]
        cands.sort(key=lambda x: _pdist(d, x[1]))
        opts = [t for t, _ in cands]
        if level == 2:
            opts.append(None)
        options.append(opts)
    # remaining-occurrence suffix sums for coverage pruning
    rem = [0] * (len(syms) + 1)
    for i in range(len(syms) - 1, -1, -1):
        rem[i] = rem[i + 1] + (syms[i][2]["occ"] if syms[i][0] == "P" else 0)
    out: list[dict] = []
    used: set = set()
    cur: dict = {}

    def dfs(i: int, covered: int) -> bool:
        if len(out) >= cap or time.time() > deadline:
            return False
        if level == 2 and covered + rem[i] < L2_MIN_COVER * occ_tot:
            return True
        if i == len(syms):
            out.append(dict(cur))
            return True
        kind, n, d = syms[i]
        for t in options[i]:
            if t is not None and (kind, t) in used:
                continue
            cur[(kind, n)] = t
            if t is not None:
                used.add((kind, t))
            ok = dfs(i + 1, covered + (d["occ"] if (kind == "P" and t is not None) else 0))
            if t is not None:
                used.discard((kind, t))
            del cur[(kind, n)]
            if not ok:
                return False
        return True
    if not syms:
        return [{}]
    dfs(0, 0)
    return out


def apply_map(S, m: dict, T_names: tuple[set, set]):
    """Rename source S by map m ((kind,name)->target or None). FRESH symbols get a suffix that cannot collide."""
    tp, tc = T_names
    pmap, cmap = {}, {}
    for (kind, n), t in m.items():
        if kind == "P":
            pmap[n] = t if t is not None else f"{n}__s"
        else:
            cmap[n] = t if t is not None else f"{n}__s"
    for p in list(pmap):
        while pmap[p] in tp and m.get(("P", p)) is None:
            pmap[p] += "_"
    for c in list(cmap):
        while cmap[c] in tc and m.get(("C", c)) is None:
            cmap[c] += "_"
    return fc.rename(S, pmap, cmap), pmap, cmap


def map_key(m: dict) -> tuple:
    return tuple(sorted((k[0], k[1], v or "") for k, v in m.items()))


def score_maps(T, S, maps: list[dict], profS: dict, profT: dict, deadline: float) -> list[dict]:
    """Fingerprint every candidate map; name-independent sort key."""
    Tn = (set(profT["P"]), set(profT["C"]))
    scored = []
    for m in maps:
        if time.time() > deadline:
            break
        RS, pmap, cmap = apply_map(S, m, Tn)
        ps, cs = slotmap(T, RS)
        vT = truth_vector(T, ps, cs)
        vS = truth_vector(RS, ps, cs)
        agree = float(np.mean(vT == vS))
        occ_match = -sum(abs(profS["P"][n]["occ"] - profT["P"][t]["occ"]) for (k, n), t in m.items()
                         if k == "P" and t is not None)
        pol_match = -sum(abs(profS["P"][n]["pos"] - profT["P"][t]["pos"]) + abs(profS["P"][n]["neg"] -
                         profT["P"][t]["neg"]) for (k, n), t in m.items() if k == "P" and t is not None)
        n_mapped = sum(1 for v in m.values() if v is not None)
        struct = tuple(sorted((profS["P" if k == "P" else "C"][n]["idx"],
                               -1 if t is None else profT["P" if k == "P" else "C"][t]["idx"]) for (k, n), t in m.items()))
        scored.append({"map": m, "RS": RS, "vT": vT, "vS": vS, "agree": agree, "pmap": pmap, "cmap": cmap,
                       "key": (-agree, -occ_match, -pol_match, -n_mapped, struct)})
    scored.sort(key=lambda x: x["key"])
    return scored


# ------------------------------------------------------------------------------------------ L3 definitions
def _vars2():
    return ("v", "x"), ("v", "y")


def candidate_definitions(Q: str, arity: int, other_preds: dict[str, int], order: dict[str, int]) -> list[tuple]:
    """Bodies for Q over the OTHER side's UNMAPPED predicates, as templates over argument slots 0..arity-1.
    Body representation: tuple of literals (sign, pred, argslots). A positive single literal in the same argument
    order is excluded (that is a plain map, L2's job). Ordered name-independently by `order`."""
    bodies = []
    if arity == 1:
        un = sorted([p for p, k in other_preds.items() if k == 1], key=lambda p: order[p])
        lits = [(s, p, (0,)) for p in un for s in (True, False)]
        for p in un:
            bodies.append(((False, p, (0,)),))
        for L1, L2 in itertools.combinations(lits, 2):
            if L1[1] != L2[1]:
                bodies.append((L1, L2))
    elif arity == 2:
        bi = sorted([p for p, k in other_preds.items() if k == 2], key=lambda p: order[p])
        for p in bi:
            bodies.append(((True, p, (1, 0)),))
            bodies.append(((False, p, (0, 1)),))
    elif arity == 0:
        pr = sorted([p for p, k in other_preds.items() if k == 0], key=lambda p: order[p])
        for p in pr:
            bodies.append(((False, p, ()),))
    return bodies


def substitute(F, defs: dict):
    """Replace atoms Q(t1..tk) by the conjunction of the body literals instantiated with (t1..tk)."""
    k = F[0]
    if k == "atom":
        if F[1] in defs:
            lits = []
            for sign, p, slots in defs[F[1]]:
                a = ("atom", p, tuple(F[2][i] for i in slots))
                lits.append(a if sign else ("not", a))
            return lits[0] if len(lits) == 1 else ("and",) + tuple(lits)
        return F
    if k == "eq":
        return F
    if k in ("forall", "exists"):
        return (k, F[1], substitute(F[2], defs))
    return (k,) + tuple(substitute(a, defs) for a in F[1:])


def unmapped(T, RS) -> tuple[list[str], list[str]]:
    pT = fc.predicates(T, strict=False) or {}
    pS = fc.predicates(RS, strict=False) or {}
    shared = set(pT) & set(pS)
    return ([p for p in first_occurrence(T)[0] if p not in shared], [p for p in first_occurrence(RS)[0] if p not in shared])


def definition_sets(T, RS, cap: int = L3_CAP) -> list[tuple[str, dict]]:
    """Definition sets linking the UNMAPPED predicates of T and of RS (the mapped source): each definition defines an
    unmapped predicate of one side over the other side's unmapped predicates. A set is admissible only if it COVERS
    every unmapped predicate of both sides (each is defined or used in a body) -> no predicate is silently ignored.
    Returns [(side, {Q: body}) ...] with side in {'T','S','TS'}."""
    pT = fc.predicates(T, strict=False) or {}
    pS = fc.predicates(RS, strict=False) or {}
    uT, uS = unmapped(T, RS)
    if not uT or not uS:
        return []
    ordT = {p: i for i, p in enumerate(first_occurrence(T)[0])}
    ordS = {p: i for i, p in enumerate(first_occurrence(RS)[0])}
    singles = []
    for Q in uT:
        for b in candidate_definitions(Q, pT[Q], {p: pS[p] for p in uS}, ordS):
            singles.append(("T", Q, b))
    for Q in uS:
        for b in candidate_definitions(Q, pS[Q], {p: pT[p] for p in uT}, ordT):
            singles.append(("S", Q, b))
    need = set(uT) | set(uS)

    def covers(defs: dict) -> bool:
        got = set(defs)
        for b in defs.values():
            got |= {l[1] for l in b}
        return need <= got
    out = [(s, {Q: b}) for s, Q, b in singles if covers({Q: b})]
    for (s1, Q1, b1), (s2, Q2, b2) in itertools.combinations(singles, 2):
        if len(out) >= cap:
            break
        if Q1 == Q2 or any(l[1] in (Q1, Q2) for l in b1 + b2):
            continue
        d = {Q1: b1, Q2: b2}
        if covers(d):
            out.append((s1 if s1 == s2 else "TS", d))
    return out[:cap]


def apply_defs(T, RS, side_defs: tuple[str, dict]):
    _, defs = side_defs
    dT = {q: b for q, b in defs.items() if q in (fc.predicates(T, strict=False) or {})}
    dS = {q: b for q, b in defs.items() if q in (fc.predicates(RS, strict=False) or {}) and q not in dT}
    return substitute(T, dT), substitute(RS, dS)


def align_pair(fa, fb, level_max: int = 3, deadline: float | None = None) -> list[dict]:
    """Candidate maps best-first: [{'level', 'map', 'agree', 'target', 'defs'}]. Target/source roles as in roles()."""
    deadline = deadline or (time.time() + 12)
    tgt, _ = roles(fa, fb)
    T, S = (fa, fb) if tgt == "A" else (fb, fa)
    profT, profS = profiles(T), profiles(S)
    out = []
    for level in (1, 2)[:level_max]:
        maps = enumerate_maps(profS, profT, level, L1_CAP if level == 1 else L2_CAP, deadline)
        for x in score_maps(T, S, maps, profS, profT, deadline):
            out.append({"level": level, "map": x["map"], "agree": x["agree"], "target": tgt, "defs": None})
    if level_max >= 3:
        l2 = [x for x in out if x["level"] == 2][:3]
        for x in l2:
            RS, _, _ = apply_map(S, x["map"], (set(profT["P"]), set(profT["C"])))
            for sd in definition_sets(T, RS):
                out.append({"level": 3, "map": x["map"], "agree": None, "target": tgt, "defs": sd})
    return out
