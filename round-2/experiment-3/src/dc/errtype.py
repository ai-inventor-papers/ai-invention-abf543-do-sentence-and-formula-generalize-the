"""Error typing: a solver diff of a candidate C against the heaviest member M of the modal EQUIV cluster.

type_error(C, M, rec): rules applied IN ORDER (the names are the panel taxonomy names):
 1.  r == CONTRADICTORY and predicate sets equal under the map        -> negation_polarity
 1b. predicate sets equal and flipping ONE literal's polarity in C makes it EQUIV to M -> negation_polarity
     (switchable; frozen on dev)
 2.  r in {STRONGER, WEAKER} and some C predicate has no counterpart in M -> added_condition
 3.  r in {STRONGER, WEAKER} and some M predicate has no counterpart in C -> dropped_condition
 4.  predicate sets equal and the quantifier multiset differs         -> quantifier_forall_exists
 5.  predicate sets equal, INCOMPARABLE, and swapping antecedent/consequent of C's main implication (below the
     leading quantifiers) makes it EQUIV to M                          -> implication_direction_or_only
 6.  permuting the slots of one binary+ predicate in C makes it EQUIV  -> argument_swap
 7.  otherwise                                                          -> other (sub-flags: scope, and_or)
"""
from __future__ import annotations

import time

from .align import apply_map, derive
from .parse import connective_multiset, fingerprint, quantifier_multiset, quantifier_prefix_order, sig

TYPES = ["negation_polarity", "quantifier_forall_exists", "implication_direction_or_only", "dropped_condition",
         "added_condition", "argument_swap", "other", "none"]


def _flip_one(ast):
    """All formulas obtained by flipping the polarity of exactly one atom occurrence."""
    out = []

    def rec(n, rebuild):
        op = n[0]
        if op in ("forall", "exists"):
            rec(n[2], lambda x, n=n: rebuild((n[0], n[1], x)))
        elif op == "not":
            if n[1][0] in ("atom", "eq"):
                out.append(rebuild(n[1]))
            else:
                rec(n[1], lambda x: rebuild(("not", x)))
        elif op in ("and", "or", "imp", "iff", "xor"):
            rec(n[1], lambda x, n=n: rebuild((n[0], x, n[2])))
            rec(n[2], lambda x, n=n: rebuild((n[0], n[1], x)))
        elif op in ("atom", "eq"):
            out.append(rebuild(("not", n)))
    rec(ast, lambda x: x)
    return out


def _swap_main_imp(ast):
    if ast[0] in ("forall", "exists"):
        inner = _swap_main_imp(ast[2])
        return None if inner is None else (ast[0], ast[1], inner)
    if ast[0] == "imp":
        return ("imp", ast[2], ast[1])
    return None


def _arg_swaps(ast):
    """For every predicate of arity >= 2: all occurrences with arguments reversed (global per predicate)."""
    preds, _ = sig(ast)
    out = []
    for P, a in preds.items():
        if a < 2:
            continue

        def rw(n, P=P):
            op = n[0]
            if op in ("forall", "exists"):
                return (op, n[1], rw(n[2]))
            if op == "not":
                return ("not", rw(n[1]))
            if op in ("and", "or", "imp", "iff", "xor"):
                return (op, rw(n[1]), rw(n[2]))
            if op == "atom" and n[1] == P:
                return ("atom", P, tuple(reversed(n[2])))
            return n
        out.append(rw(ast))
    return out


def _is_equiv(X, M, deadline) -> bool:
    """EQUIV of X and M under ANY lexical-free alignment (L1/L2 search), not only the modal map."""
    from .align import Caps, align_pair
    wall = max(0.5, min(5.0, deadline - time.time()))
    try:
        return derive(align_pair(X, M, caps=Caps(pair_wall_s=wall), use_L3=False), use_L3=False)["rel"] == "EQUIV"
    except (ValueError, KeyError, RecursionError):
        return False


def type_error(C, M, rec: dict, use_L3: bool = False, rule_1b: bool = True, wall_s: float = 10.0) -> dict:
    """Error type of candidate C relative to modal representative M. rec = align_pair(C, M) record
    (map from M's symbols into C's)."""
    t0 = time.time()
    deadline = t0 + wall_s
    d = derive(rec, use_L3=use_L3)
    r = d["rel"]
    if r == "EQUIV":
        return {"type": "none", "rule": 0, "rel": r}
    m = d.get("map")
    if m is None:
        return {"type": "other", "rule": 7, "rel": r, "flags": ["unaligned"]}
    fpc, fpm = fingerprint(C), fingerprint(M)
    Mm = apply_map(M, m, fpm)
    c_preds = {s for s in fpc if not s.startswith("#")}
    m_preds = {s for s in fpm if not s.startswith("#")}
    img = {m[s] for s in m_preds if s in m}
    c_extra = c_preds - img
    m_missing = {s for s in m_preds if s not in m}
    same = not c_extra and not m_missing
    if r == "CONTRADICTORY" and same:
        return {"type": "negation_polarity", "rule": 1, "rel": r}
    if rule_1b and same:
        flips = _flip_one(C)
        if len(flips) <= 16:
            for F in flips:
                if time.time() > deadline:
                    break
                if _is_equiv(F, M, deadline):
                    return {"type": "negation_polarity", "rule": "1b", "rel": r}
    if r in ("STRONGER", "WEAKER") and c_extra:
        return {"type": "added_condition", "rule": 2, "rel": r}
    if r in ("STRONGER", "WEAKER") and m_missing:
        return {"type": "dropped_condition", "rule": 3, "rel": r}
    if same and quantifier_multiset(C) != quantifier_multiset(Mm):
        return {"type": "quantifier_forall_exists", "rule": 4, "rel": r}
    if same and r == "INCOMPARABLE":
        S = _swap_main_imp(C)
        if S is not None and time.time() < deadline and _is_equiv(S, M, deadline):
            return {"type": "implication_direction_or_only", "rule": 5, "rel": r}
    for S in _arg_swaps(C):
        if time.time() > deadline:
            break
        if _is_equiv(S, M, deadline):
            return {"type": "argument_swap", "rule": 6, "rel": r}
    flags = []
    if quantifier_prefix_order(C) != quantifier_prefix_order(Mm):
        flags.append("scope")
    if connective_multiset(C) != connective_multiset(Mm):
        flags.append("and_or")
    return {"type": "other", "rule": 7, "rel": r, "flags": flags}


__all__ = ["type_error", "TYPES"]
