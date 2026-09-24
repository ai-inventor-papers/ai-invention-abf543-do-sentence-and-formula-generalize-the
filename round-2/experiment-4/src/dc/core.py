"""directional_consensus and its pieces: peer clustering, one-coin Dawid–Skene weights, error typing, VC control.

directional_consensus(text, fol, peers, ...) MEASURES the reliability-weighted share of peer formalisations that are
logically EQUIVALENT to `fol` up to a lexical-free (granularity-aware) vocabulary alignment. It never reads `text`
(accepted for API symmetry only), never reads symbol names (alignment is name-free), and needs no gold.
"""
from __future__ import annotations

import math
import re
import time
from collections import Counter
from functools import lru_cache
from typing import Callable

import numpy as np

from . import front
from .pairs import best_relation
from .relation import flip

REL_OK = ("EQUIV", "STRONGER", "WEAKER", "COMPATIBLE", "CONTRADICTORY")
TYPES = ["added_condition", "dropped_condition", "quantifier_forall_exists", "implication_direction_or_only",
         "negation_polarity", "argument_swap", "other"]


def _default_rel_fn() -> Callable[[str, str], dict]:
    cache: dict = {}

    def f(a: str, b: str) -> dict:
        from .pairs import compute_record, oriented
        k = (a, b) if a <= b else (b, a)
        if k not in cache:
            cache[k] = compute_record(a, b)
        return oriented(cache[k], a == cache[k]["lo"])
    return f


def rel_of(rec: dict | None, key: str = "rel") -> str:
    if rec is None:
        return "UNKNOWN"
    return rec.get(key) or "UNKNOWN"


def clusters(items: list[str], rel: Callable[[str, str], str]) -> list[int]:
    """Connected components of EQUIV among canonical strings (None = unparseable -> own singleton, flagged -1)."""
    n = len(items)
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for i in range(n):
        for j in range(i + 1, n):
            if items[i] is None or items[j] is None:
                continue
            if items[i] == items[j] or rel(items[i], items[j]) == "EQUIV":
                parent[find(i)] = find(j)
    roots: dict = {}
    out = []
    for i in range(n):
        if items[i] is None:
            out.append(-1)
        else:
            out.append(roots.setdefault(find(i), len(roots)))
    return out


# ------------------------------------------------------------------------------------------ DS weights
def ds_weights(obs: list[dict], systems: list[str], seeds=(0, 1, 2)) -> dict:
    """One-coin Dawid–Skene (vendor latent_class.em, 10 restarts) on EQUIV clusters over sentences.
    w_s = clip(logit(p_s), 0.05, 3). Stability across 3 seeds reported; degenerate -> equal weights (fallback 3)."""
    import latent_class as lc
    fits = [lc.em(obs, systems, seed=s) for s in seeds]
    p = {s: fits[0]["p"][(0, s)] for s in systems}
    spread = max(abs(f["p"][(0, s)] - p[s]) for f in fits for s in systems)
    degenerate = bool(any(v > 0.99 or v < 0.01 for v in p.values()) or fits[0]["pi"][0] < 0.02 or spread > 0.05)

    def lg(x):
        x = min(max(x, 1e-6), 1 - 1e-6)
        return math.log(x / (1 - x))
    w = {s: float(min(3.0, max(0.05, lg(p[s])))) for s in systems}
    return {"p": p, "w": w, "pi": fits[0]["pi"][0], "rho": fits[0]["rho"], "loglik": fits[0]["ll"],
            "seed_spread_p": spread, "degenerate": degenerate, "iters": fits[0]["iters"]}


# ------------------------------------------------------------------------------------------ DC
def directional_consensus(text: str | None, fol: str | None, peers: list[str | None], peer_ids: list[str] | None = None,
                          weights: dict | None = None, rel_fn: Callable[[str, str], dict] | None = None,
                          self_weight: float | None = None, rel_key: str = "rel", with_type: bool = True) -> dict:
    """Score in [0,1]: sum_{peers} w * [rel(fol, peer) = EQUIV] / sum_{peers with rel != UNKNOWN} w.
    fol / peers are raw or canonical FOL strings (None/'' = unparseable). Unparseable fol or < 2 covered peers
    (rel not in {UNALIGNABLE, UNKNOWN}) -> 0.5, covered=False. Returns score, strength_profile, error_type,
    coverage, cost, per_peer."""
    t0 = time.time()
    rel_fn = rel_fn or _default_rel_fn()
    peer_ids = peer_ids or [f"p{i}" for i in range(len(peers))]
    weights = weights or {}
    w_of = [float(weights.get(pid, 1.0)) for pid in peer_ids]
    fc_ = front.canon(fol) if fol else {"ok": False}
    c_fol = fc_["canon"] if fc_.get("ok") else None
    c_peers = []
    for p in peers:
        cp = front.canon(p) if p else {"ok": False}
        c_peers.append(cp["canon"] if cp.get("ok") else None)
    per_peer, n_calls = [], 0
    num = den = 0.0
    masses = Counter()
    for pid, cp, w in zip(peer_ids, c_peers, w_of):
        if cp is None:
            per_peer.append({"peer": pid, "rel": "PEER_UNPARSEABLE", "w": w})
            continue
        if c_fol is None:
            per_peer.append({"peer": pid, "rel": "SELF_UNPARSEABLE", "w": w})
            continue
        rec = {"rel": "EQUIV", "rel_L1": "EQUIV", "rel_L2": "EQUIV", "rel_L3": "EQUIV"} if cp == c_fol else rel_fn(c_fol, cp)
        n_calls += 1
        r = rel_of(rec, rel_key)
        per_peer.append({"peer": pid, "rel": r, "w": w})
        if r != "UNKNOWN":
            den += w
            num += w * (r == "EQUIV")
            masses[r] += w
    covered = [x for x in per_peer if x["rel"] in REL_OK]
    ok = c_fol is not None and len(covered) >= 2 and den > 0
    score = num / den if ok else 0.5
    tot = sum(masses.values()) or 1.0
    prof = {"stronger_mass": masses["STRONGER"] / tot, "weaker_mass": masses["WEAKER"] / tot,
            "contra_mass": masses["CONTRADICTORY"] / tot, "incomp_mass": masses["COMPATIBLE"] / tot,
            "unalign_mass": masses["UNALIGNABLE"] / tot, "equiv_mass": masses["EQUIV"] / tot}
    out = {"score": float(score), "covered": bool(ok), "strength_profile": prof,
           "coverage": {"n_peers": len(peers), "n_peer_parseable": sum(c is not None for c in c_peers),
                        "n_covered": len(covered), "self_parseable": c_fol is not None},
           "per_peer": per_peer}
    if with_type and c_fol is not None:
        items = [c_fol] + c_peers
        wts = [self_weight if self_weight is not None else (float(np.median(w_of)) if w_of else 1.0)] + w_of

        def rr(a, b):
            if a == b:
                return "EQUIV"
            return rel_of(rel_fn(a, b), rel_key)
        cl = clusters(items, rr)
        mass = Counter()
        size = Counter()
        for c, w in zip(cl, wts):
            if c >= 0:
                mass[c] += w
                size[c] += 1
        mode = max(mass, key=lambda c: (mass[c], size[c], -c)) if mass else None
        out["mode_mass"] = (mass[mode] / sum(mass.values())) if mode is not None else None
        out["in_mode"] = bool(mode is not None and cl[0] == mode)
        if mode is not None and cl[0] != mode:
            reps = [i for i in range(1, len(items)) if cl[i] == mode]
            rep = max(reps, key=lambda i: (wts[i], -i))
            rec = rel_fn(c_fol, items[rep])
            out["rel_to_mode"] = rel_of(rec, rel_key)
            et = error_type_contract(c_fol, items[rep], rec, rel_key)
            out["error_type"] = et
            out["mode_rep"] = items[rep]
        else:
            out["rel_to_mode"] = "EQUIV" if mode is not None else None
            out["error_type"] = "none" if mode is not None else "other"
    else:
        out["error_type"] = None
    out["cost"] = {"seconds": round(time.time() - t0, 4), "n_relation_lookups": n_calls, "usd": 0.0}
    return out


# ------------------------------------------------------------------------------------------ typing
def _quant_multiset(ast) -> Counter:
    c = Counter()

    def rec(m, pol):
        k = m[0]
        if k in ("forall", "exists"):
            q = k if pol > 0 else ("exists" if k == "forall" else "forall")
            c[q] += 1
            rec(m[2], pol)
        elif k == "not":
            rec(m[1], -pol)
        elif k == "imp":
            rec(m[1], -pol)
            rec(m[2], pol)
        elif k in ("atom", "eq"):
            return
        else:
            for a in m[1:]:
                rec(a, pol)
    rec(ast, 1)
    return c


def _map_parts(a: str, b: str, rec: dict) -> tuple[dict, dict, set, set]:
    """From a best_relation record for (a,b): pmap a->b predicate names (for mapped symbols), cmap, and the sets of
    predicates of a / of b left unmapped."""
    import fol_core as fc
    A, B = front.parse_canon(a), front.parse_canon(b)
    pA, pB = set(fc.predicates(A, strict=False) or {}), set(fc.predicates(B, strict=False) or {})
    lo = rec.get("lo") or min(a, b)
    tgt_is_a = (rec.get("target") == "A") == (a == lo)  # record target role is relative to (lo, hi)
    pm, cm = {}, {}
    for kind, s, t in rec.get("map") or []:
        if t is None:
            continue
        if tgt_is_a:  # source = b
            (pm if kind == "P" else cm)[t] = s
        else:
            (pm if kind == "P" else cm)[s] = t
    un_a = {p for p in pA if p not in pm}
    un_b = {p for p in pB if p not in set(pm.values())}
    if rec.get("defs"):
        # symbols linked by granularity definitions are accounted for
        for q, body in (rec["defs"].get("defs") or {}).items():
            q0 = re.sub(r"(__s_*)$", "", q)
            un_a.discard(q0)
            un_b.discard(q0)
            for l in body:
                p0 = re.sub(r"(__s_*)$", "", l[1])
                un_a.discard(p0)
                un_b.discard(p0)
    return pm, cm, un_a, un_b


def error_type_contract(a: str, rep: str, rec: dict, rel_key: str = "rel") -> str:
    """Contract order: negation (CONTRADICTORY, same mapped predicates) -> added (STRONGER/WEAKER, a has an unmapped
    predicate) -> dropped (STRONGER/WEAKER, mode has a predicate absent from a) -> forall/exists (same predicates,
    quantifier multiset differs) -> implication direction (same predicates, COMPATIBLE, reversing some -> gives
    EQUIV) -> argument swap (same predicates, swapping args of one binary atom gives EQUIV) -> other."""
    rel = rel_of(rec, rel_key)
    if rel in ("UNALIGNABLE", "UNKNOWN", "UNPARSEABLE"):
        return "other"
    try:
        pm, cm, un_a, un_b = _map_parts(a, rep, rec)
    except (ValueError, KeyError, TypeError):
        return "other"
    same = not un_a and not un_b
    if rel == "CONTRADICTORY" and same:
        return "negation_polarity"
    if rel in ("STRONGER", "WEAKER"):
        if un_a and not un_b:
            return "added_condition"
        if un_b and not un_a:
            return "dropped_condition"
        if un_a and un_b:
            return "added_condition" if len(un_a) >= len(un_b) else "dropped_condition"
    A, R = front.parse_canon(a), front.parse_canon(rep)
    if same and _quant_multiset(A) != _quant_multiset(R):
        return "quantifier_forall_exists"
    if same and rel in ("COMPATIBLE", "STRONGER", "WEAKER", "CONTRADICTORY"):
        rt = repair_type(a, rep, rec, ops=("IMPL_REV", "ARG_SWAP", "NEG"))
        if rt:
            return rt
    return "other"


REPAIR_NAME = {"NEG": "negation_polarity", "QUANT": "quantifier_forall_exists",
               "IMPL_REV": "implication_direction_or_only", "DROP_CONJ": "added_condition",
               "ADD_CONJ": "dropped_condition", "ARG_SWAP": "argument_swap"}


def repair_type(a: str, rep: str, rec: dict, ops=("NEG", "QUANT", "IMPL_REV", "DROP_CONJ", "ADD_CONJ", "ARG_SWAP"),
                max_sites: int = 8) -> str | None:
    """'repair' variant: apply each single-edit operator to `a` (in rep's vocabulary via the record's map); the first
    operator whose edit makes `a` EQUIV to the mode representative names the type (the edit that REPAIRS an added
    condition is DROP_CONJ, etc.). ADD_CONJ adds a literal of the mode's unmapped predicates."""
    import fol_core as fc
    import mutants as mu
    from .fp import slotmap, truth_vector
    from .relation import pair_relation
    try:
        pm, cm, un_a, un_b = _map_parts(a, rep, rec)
    except (ValueError, KeyError, TypeError):
        return None
    A, R = front.parse_canon(a), front.parse_canon(rep)
    pA = fc.predicates(A, strict=False) or {}
    pmap = {p: pm.get(p, f"{p}__a") for p in pA}
    cmap = {c: cm.get(c, f"{c}__a") for c in fc.constants(A)}
    RA = fc.rename(A, pmap, cmap)
    pR = fc.predicates(R, strict=False) or {}
    for op in ops:
        if op == "ADD_CONJ":
            sites = []
            for path, m in mu.preorder(RA):
                if m[0] in ("forall", "exists"):
                    v, body = m[1], m[2]
                    for P in sorted(un_b):
                        if pR.get(P) != 1:
                            continue
                        for lit in (("atom", P, (("v", v),)), ("not", ("atom", P, (("v", v),)))):
                            if body[0] == "imp":
                                sites.append(mu.replace(RA, path + (0, 0), mu.mk_and([body[1], lit])))
                            else:
                                sites.append(mu.replace(RA, path + (0,), mu.mk_and([body, lit])))
        else:
            try:
                sites = mu.OP_FUNCS[op](RA, mu.rng_for("repair", op))
            except (ValueError, RecursionError, mu.NotPrenexable):
                sites = []
        for s in sites[:max_sites]:
            try:
                ps, cs = slotmap(R, s)
                vR, vS = truth_vector(R, ps, cs), truth_vector(s, ps, cs)
            except (KeyError, IndexError, ValueError):
                continue
            if not np.array_equal(vR, vS):
                continue
            pr = pair_relation(s, R, vS, vR, deadline=time.time() + 3)
            if pr["rel"] == "EQUIV":
                return REPAIR_NAME[op]
    return None


# ------------------------------------------------------------------------------------------ VC control
@lru_cache(maxsize=100000)
def norm_pred(name: str) -> str:
    """lowercase, camel/snake split, WordNet lemma per word (user's pilot vocabulary normalisation)."""
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name.replace("_", " "))
    words = [w.lower() for w in s.split() if w]
    try:
        from nltk.stem import WordNetLemmatizer
        lem = _LEM()
        words = [lem.lemmatize(w) for w in words]
    except LookupError:
        pass
    return " ".join(words)


@lru_cache(maxsize=1)
def _LEM():
    from nltk.stem import WordNetLemmatizer
    L = WordNetLemmatizer()
    L.lemmatize("dogs")
    return L


def vocab_conformity(fol: str | None, peers: list[str | None]) -> dict:
    """VC(C) = mean over parseable peers of 0.5*Jaccard(normalised predicate-name sets) + 0.5*1[arity profile equal].
    The user's structural/vocabulary family, used as the conformity CONTROL (rewards conventional naming)."""
    c = front.canon(fol) if fol else {"ok": False}
    if not c.get("ok"):
        return {"score": 0.5, "covered": False}
    P0 = {norm_pred(p) for p in c["preds"]}
    a0 = sorted(c["preds"].values())
    vals = []
    for p in peers:
        q = front.canon(p) if p else {"ok": False}
        if not q.get("ok"):
            continue
        P1 = {norm_pred(x) for x in q["preds"]}
        j = len(P0 & P1) / len(P0 | P1) if (P0 | P1) else 1.0
        vals.append(0.5 * j + 0.5 * float(sorted(q["preds"].values()) == a0))
    if not vals:
        return {"score": 0.5, "covered": False}
    return {"score": float(np.mean(vals)), "covered": True}
