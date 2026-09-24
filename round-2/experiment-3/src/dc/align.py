"""Lexical-free vocabulary alignment of two formulas (names are never read, only structure).

align_pair(A, B) searches maps from B's symbols into A's symbols and returns, per level, the strongest
solver-verified relation found (EQUIV > STRONGER/WEAKER > INCOMPARABLE > CONTRADICTORY):
  L1  arity-preserving bijection of predicates and constants (requires equal arity profiles);
  L2  partial injective maps (maximal per arity block); unmapped B symbols stay FRESH, so a B-only
      predicate acts as an extra, unconstrained condition. Maps covering < 50% of the symbol occurrences of
      EITHER formula are not considered (UNALIGNABLE if none qualifies);
  L3  granularity: when the predicate counts differ by exactly 1, one predicate of the smaller-vocabulary
      formula is replaced by a conjunction of 2 fresh literals over its argument slots, then L1 is rerun.
Maps are ranked by structural fingerprint distance and screened on random finite structures (a
disagreement refutes an entailment soundly); only surviving maps reach z3 (relation.pair_relation).
The returned record is CONFIG-AGNOSTIC: every level's result and the index at which EQUIV was found are
stored, so the L3 on/off and cap x0.5 variants are derived from one computation (derive()).
"""
from __future__ import annotations

import heapq
import itertools
import math
import random
import time
from collections import defaultdict
from dataclasses import dataclass

from .parse import fingerprint, fp_distance, rename, sig
from .relation import RANK, Structs, pair_relation, quick_rel


@dataclass(frozen=True)
class Caps:
    L1: int = 5040
    L2: int = 2000
    L3: int = 300
    z3_equiv_attempts: int = 40
    pair_wall_s: float = 20.0
    min_share: float = 0.5


CAPS = Caps()
FRESH = "Fz_"  # prefix for B symbols left unmapped (never produced by the parser: parser names are identifiers)


def _blocks(sa: dict, sb: dict):
    """Group symbols by kind/arity: {key: (B symbols, A symbols)} where key = ('p', arity) or ('c',)."""
    ga, gb = defaultdict(list), defaultdict(list)
    for s, fp in sa.items():
        ga[("c",) if s.startswith("#") else ("p", fp[0])].append(s)
    for s, fp in sb.items():
        gb[("c",) if s.startswith("#") else ("p", fp[0])].append(s)
    keys = sorted(set(ga) | set(gb))
    return {k: (sorted(gb.get(k, [])), sorted(ga.get(k, []))) for k in keys}


def _block_maps(bs: list, as_: list, fpb: dict, fpa: dict, full: bool, limit: int = 20000, seed: int = 0):
    """Injective maps of a block, as (cost, tuple of (b, a)) sorted by cost. full=True requires a bijection."""
    nb, na = len(bs), len(as_)
    if full and nb != na:
        return None
    k = min(nb, na)
    if k == 0:
        return [(0.0, ())]
    D = {(b, a): min(fp_distance(fpb[b], fpa[a]), 1e6) for b in bs for a in as_}
    count = math.comb(nb, k) * math.perm(na, k)
    out = []
    if count <= limit:
        for bsub in itertools.combinations(bs, k):
            for aperm in itertools.permutations(as_, k):
                pairs = tuple(zip(bsub, aperm))
                out.append((sum(D[p] for p in pairs), pairs))
    else:
        rng = random.Random(seed)
        seen = set()
        # greedy best first
        used, pairs = set(), []
        for b in sorted(bs, key=lambda b: min(D[(b, a)] for a in as_))[:k]:
            a = min((a for a in as_ if a not in used), key=lambda a: D[(b, a)])
            used.add(a)
            pairs.append((b, a))
        pairs = tuple(sorted(pairs))
        seen.add(pairs)
        out.append((sum(D[p] for p in pairs), pairs))
        tries = 0
        while len(out) < limit // 4 and tries < limit:
            tries += 1
            bsub = sorted(rng.sample(bs, k))
            aperm = rng.sample(as_, k)
            pairs = tuple(zip(bsub, aperm))
            if pairs in seen:
                continue
            seen.add(pairs)
            out.append((sum(D[p] for p in pairs), pairs))
    out.sort(key=lambda x: x[0])
    return out


def ranked_maps(fpa: dict, fpb: dict, full: bool, cap: int):
    """Yield up to `cap` maps B->A (dict), cheapest total fingerprint distance first (lazy k-best product)."""
    blocks = _blocks(fpa, fpb)
    lists = []
    for key, (bs, as_) in blocks.items():
        if not bs:
            continue
        bm = _block_maps(bs, as_, fpb, fpa, full)
        if bm is None:
            return
        lists.append(bm)
    if not lists:
        yield {}
        return
    start = tuple(0 for _ in lists)
    heap = [(sum(l[0][0] for l in lists), start)]
    seen = {start}
    n = 0
    while heap and n < cap:
        cost, idx = heapq.heappop(heap)
        m = {}
        for l, i in zip(lists, idx):
            for b, a in l[i][1]:
                m[b] = a
        yield m
        n += 1
        for j in range(len(lists)):
            if idx[j] + 1 < len(lists[j]):
                nxt = idx[:j] + (idx[j] + 1,) + idx[j + 1:]
                if nxt not in seen:
                    seen.add(nxt)
                    heapq.heappush(heap, (cost - lists[j][idx[j]][0] + lists[j][idx[j] + 1][0], nxt))


def apply_map(B, m: dict, fpb: dict):
    """Rename B through m (B symbol -> A symbol); unmapped symbols get the FRESH prefix."""
    pmap, cmap = {}, {}
    for s in fpb:
        tgt = m.get(s)
        if s.startswith("#"):
            cmap[s[1:]] = tgt[1:] if tgt else FRESH + s[1:]
        else:
            pmap[s] = tgt if tgt else FRESH + s
    return rename(B, pmap, cmap)


def mapped_share(m: dict, fpb: dict, fpa: dict | None = None) -> float:
    """Share of symbol occurrences covered by the map, taken on BOTH sides (min), so that the admissibility of a
    map from B into A equals that of its inverse (relation symmetry)."""
    tot = sum(v[1] for v in fpb.values())
    sb = sum(v[1] for s, v in fpb.items() if s in m) / tot if tot else 1.0
    if fpa is None:
        return sb
    img = set(m.values())
    tota = sum(v[1] for v in fpa.values())
    sa = sum(v[1] for s, v in fpa.items() if s in img) / tota if tota else 1.0
    return min(sa, sb)


def _better(a: dict | None, b: dict) -> bool:
    """Is b better than a? Stronger relation first, then fewer unmapped symbols, then lower level."""
    if a is None:
        return True
    ka = (RANK[a["rel"]], -a.get("n_unmapped", 0), -a.get("lvl", 9))
    kb = (RANK[b["rel"]], -b.get("n_unmapped", 0), -b.get("lvl", 9))
    return kb > ka


def _search(A, B, fpa, fpb, full: bool, cap: int, caps: Caps, deadline: float, lvl: int, structs: Structs,
            va: tuple) -> dict | None:
    """One level of map search. Returns the level record or None if no map is admissible."""
    best_q = None  # (quick score, -n_unmapped, -cost_rank) of the best non-equiv map
    best_map = None
    n_tried = 0
    z3_attempts = 0
    k_found = None
    eq_rec = None
    any_map = False
    for k, m in enumerate(ranked_maps(fpa, fpb, full, cap)):
        if time.time() > deadline:
            break
        if not full and mapped_share(m, fpb, fpa) < caps.min_share:
            continue
        any_map = True
        n_tried += 1
        Bm = apply_map(B, m, fpb)
        q = quick_rel(va, structs.truth(Bm))
        n_unm = sum(1 for s in fpb if s not in m)
        if q["eq_alive"] and z3_attempts < caps.z3_equiv_attempts:
            z3_attempts += 1
            r = pair_relation(A, Bm, deadline=deadline, alive=q)
            if r["rel"] == "EQUIV":
                k_found = k
                eq_rec = {"rel": "EQUIV", "map": m, "n_unmapped": n_unm, "k_found": k, "lvl": lvl,
                          "bounded_only": r["bounded_only"], "method": r["method"]}
                break
        key = (q["score"], -n_unm, -k)
        if best_q is None or key > best_q:
            best_q, best_map = key, (m, q, n_unm, k)
    if eq_rec is not None:
        eq_rec.update({"n_tried": n_tried})
        return eq_rec
    if not any_map:
        return None
    if best_map is None:
        return {"rel": "UNKNOWN", "map": None, "n_unmapped": None, "k_found": None, "lvl": lvl, "n_tried": n_tried,
                "why": "deadline_before_any_map"}
    m, q, n_unm, k = best_map
    Bm = apply_map(B, m, fpb)
    # entailment claims still alive after screening go to z3; give the final verdict extra time
    r = pair_relation(A, Bm, deadline=max(deadline, time.time() + 5.0), alive=q)
    return {"rel": r["rel"], "map": m, "n_unmapped": n_unm, "k_found": None, "lvl": lvl, "n_tried": n_tried,
            "bounded_only": r.get("bounded_only"), "method": r.get("method"), "best_k": k}


def _split_candidates(X, fpx: dict, limit: int):
    """Granularity splits of one predicate P(args) of X into Q1 ∧ Q2 over P's argument slots (fresh Q's)."""
    out = []
    preds = sorted([s for s in fpx if not s.startswith("#")], key=lambda s: -fpx[s][1])
    for P in preds:
        k = fpx[P][0]
        if k == 0:
            continue
        pats = [("k", "k")]
        if k >= 2:
            pats += [(("u", i), "k") for i in range(k)]
        if k == 2:
            pats += [(("u", 0), ("u", 1))]
        for pat in pats:
            for pol in ((False, False), (False, True), (True, False)):
                out.append((P, pat, pol))
                if len(out) >= limit:
                    return out
    return out


def _apply_split(X, P: str, pat, pol):
    q1, q2 = FRESH + "G1_" + P, FRESH + "G2_" + P

    def lit(name, which, args, neg):
        a = args if which == "k" else (args[which[1]],)
        at = ("atom", name, tuple(a))
        return ("not", at) if neg else at

    def rw(n):
        op = n[0]
        if op in ("forall", "exists"):
            return (op, n[1], rw(n[2]))
        if op == "not":
            return ("not", rw(n[1]))
        if op in ("and", "or", "imp", "iff", "xor"):
            return (op, rw(n[1]), rw(n[2]))
        if op == "atom" and n[1] == P:
            return ("and", lit(q1, pat[0], n[2], pol[0]), lit(q2, pat[1], n[2], pol[1]))
        return n
    return rw(X)


def _profile(fp: dict) -> tuple:
    c = defaultdict(int)
    for s, v in fp.items():
        c["c" if s.startswith("#") else v[0]] += 1
    return tuple(sorted(c.items(), key=str))


def align_pair(A, B, caps: Caps = CAPS, use_L3: bool = True) -> dict:
    """Finds the lexical-free vocabulary map from B's symbols into A's under which the two formulas stand in
    the strongest solver-verified entailment relation. A and B are parsed ASTs. Config-agnostic record."""
    t0 = time.time()
    deadline = t0 + caps.pair_wall_s
    fpa, fpb = fingerprint(A), fingerprint(B)
    pa, ca = sig(A)
    pb, cb = sig(B)
    rec = {"L1": None, "L2": None, "L3": None}
    # random structures over A's vocabulary + every B symbol under its FRESH name
    preds = dict(pa)
    for p, a in pb.items():
        preds[FRESH + p] = a
    consts = set(ca) | {FRESH + c for c in cb}
    structs = Structs({**preds}, consts, seed=0)
    va = structs.truth(A)
    full_ok = _profile(fpa) == _profile(fpb)
    if full_ok:
        rec["L1"] = _search(A, B, fpa, fpb, True, caps.L1, caps, deadline, 1, structs, va)
    if not full_ok:  # with equal arity profiles the maximal partial maps ARE the bijections (L1)
        rec["L2"] = _search(A, B, fpa, fpb, False, caps.L2, caps, deadline, 2, structs, va)
    best = None
    for lv in ("L1", "L2"):
        if rec[lv] is not None and _better(best, rec[lv]):
            best = rec[lv]
    # L3: granularity split, only if predicate counts differ by exactly one and no EQUIV yet
    npa, npb = len(pa), len(pb)
    if use_L3 and (best is None or best["rel"] != "EQUIV") and abs(npa - npb) == 1 and time.time() < deadline:
        rec["L3"] = _granular(A, B, fpa, fpb, caps, deadline)
    rec["seconds"] = round(time.time() - t0, 3)
    rec["timed_out"] = time.time() > deadline
    rec["n_preds"] = (npa, npb)
    return rec


def _granular(A, B, fpa, fpb, caps: Caps, deadline: float) -> dict | None:
    """Split one predicate of the formula with FEWER predicates; rerun an L1 bijection search."""
    swap = len([s for s in fpa if not s.startswith("#")]) > len([s for s in fpb if not s.startswith("#")])
    X, Y = (B, A) if swap else (A, B)  # X has fewer predicates
    fpx = fpb if swap else fpa
    fpy = fpa if swap else fpb
    n_cand = 0
    for P, pat, pol in _split_candidates(X, fpx, caps.L3):
        if time.time() > deadline:
            break
        X2 = _apply_split(X, P, pat, pol)
        fpx2 = fingerprint(X2)
        if _profile(fpx2) != _profile(fpy):
            continue
        n_cand += 1
        # L1 search between X2 (as 'A') and Y (as 'B'); structures over X2's vocab + Y's fresh names
        px, cx = sig(X2)
        py, cy = sig(Y)
        preds = dict(px)
        for p, a in py.items():
            preds[FRESH + p] = a
        structs = Structs(preds, set(cx) | {FRESH + c for c in cy}, seed=1)
        vx = structs.truth(X2)
        r = _search(X2, Y, fpx2, fpy, True, 720, Caps(z3_equiv_attempts=10), deadline, 3, structs, vx)
        if r is not None and r["rel"] == "EQUIV":
            return {"rel": "EQUIV", "map": None, "n_unmapped": 0, "k_found": r.get("k_found"), "lvl": 3,
                    "via_def": {"side": "B" if swap else "A", "pred": P, "pattern": str(pat), "neg": list(pol)},
                    "n_candidates": n_cand}
    return {"rel": "NOEQ", "n_candidates": n_cand, "lvl": 3}


def derive(rec: dict, use_L3: bool = True, half_caps: bool = False, caps: Caps = CAPS) -> dict:
    """Relation under one grid configuration, derived from a config-agnostic pair record (no re-solving)."""
    if rec is None or rec.get("error"):
        return {"rel": "UNKNOWN", "lvl": None, "map": None}
    cands = []
    for lv, cap in (("L1", caps.L1), ("L2", caps.L2)):
        r = rec.get(lv)
        if r is None:
            continue
        if r["rel"] == "EQUIV" and half_caps and r.get("k_found") is not None and r["k_found"] >= cap // 2:
            # EQUIV found only in the second half of the ranked maps: under half caps it is not found
            continue
        cands.append(r)
    if use_L3 and rec.get("L3") and rec["L3"].get("rel") == "EQUIV":
        cands.append(rec["L3"])
    best = None
    for r in cands:
        if _better(best, r):
            best = r
    if best is None:
        # no admissible map at L2 (share < 0.5) and no L1 -> UNALIGNABLE
        return {"rel": "UNALIGNABLE", "lvl": None, "map": None}
    return {"rel": best["rel"], "lvl": best.get("lvl"), "map": best.get("map"), "n_unmapped": best.get("n_unmapped")}


__all__ = ["align_pair", "derive", "Caps", "CAPS", "apply_map", "ranked_maps", "FRESH"]
