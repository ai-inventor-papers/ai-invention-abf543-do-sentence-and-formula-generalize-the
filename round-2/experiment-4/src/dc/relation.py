"""pair_relation: the logical relation between A and B once B's vocabulary is mapped into A's.

Measures: EQUIV (A⊨B and B⊨A) | STRONGER (A⊨B only) | WEAKER (B⊨A only) | CONTRADICTORY (A∧B unsat) |
COMPATIBLE (none of these) | UNKNOWN (solver timeout on a check that could change the verdict).
Checks: (1) fingerprint refutation on 64 finite structures (sound); (2) unbounded z3 over an uninterpreted sort
(unsat => proved; sat => refuted); (3) on unknown, propositional grounding over domains 1..3 (a countermodel refutes,
none => entailment kept with method='bounded').
"""
from __future__ import annotations

import itertools
import time

import numpy as np
import z3

from . import front  # noqa: F401  (sets sys.path for fol_core)
import fol_core as fc  # noqa: E402

_CTR = itertools.count()
Z3_MS = 3000
BOUND_N = 3


def _z3_formula(F):
    D = z3.DeclareSort(f"U{next(_CTR)}")
    preds = fc.predicates(F, strict=False) or {}
    P = {p: (z3.Function(f"{p}_{next(_CTR)}", *([D] * k), z3.BoolSort()) if k else z3.Bool(f"{p}_{next(_CTR)}"))
         for p, k in preds.items()}
    C = {c: z3.Const(f"c_{c}_{next(_CTR)}", D) for c in fc.constants(F)}

    def tz(f, env):
        k = f[0]
        if k == "atom":
            fn = P[f[1]]
            if not f[2]:
                return fn
            return fn(*[env[t[1]] if t[0] == "v" else C[t[1]] for t in f[2]])
        if k == "eq":
            a, b = (env[t[1]] if t[0] == "v" else C[t[1]] for t in f[1:])
            return a == b
        if k in ("forall", "exists"):
            v = z3.Const(f"v_{f[1]}_{next(_CTR)}", D)
            body = tz(f[2], {**env, f[1]: v})
            return z3.ForAll([v], body) if k == "forall" else z3.Exists([v], body)
        a = [tz(x, env) for x in f[1:]]
        if k == "not":
            return z3.Not(a[0])
        if k == "and":
            return z3.And(*a)
        if k == "or":
            return z3.Or(*a)
        if k == "imp":
            return z3.Implies(a[0], a[1])
        if k == "iff":
            return a[0] == a[1]
        if k == "xor":
            return z3.Xor(a[0], a[1])
        raise ValueError(k)
    return tz(F, {})


def sat_check(F, timeout_ms: int = Z3_MS, deadline: float | None = None) -> tuple[str, str]:
    """('sat'|'unsat'|'unknown', method). Unbounded first, bounded (n<=3) fallback on unknown."""
    if deadline is not None:
        rem = int((deadline - time.time()) * 1000)
        if rem <= 50:
            return "unknown", "deadline"
        timeout_ms = max(50, min(timeout_ms, rem))
    try:
        s = z3.Solver()
        s.set("timeout", timeout_ms)
        s.add(_z3_formula(F))
        r = s.check()
    except (z3.Z3Exception, RecursionError, KeyError, ValueError):
        r = z3.unknown
    if r == z3.unsat:
        return "unsat", "unbounded"
    if r == z3.sat:
        return "sat", "unbounded"
    if deadline is not None and time.time() > deadline:
        return "unknown", "deadline"
    try:
        b = fc.satisfiable(F, nmax=BOUND_N, timeout_ms=min(timeout_ms, 2000))
    except (z3.Z3Exception, RecursionError, ValueError):
        b = "unknown"
    if b == "sat":
        return "sat", "bounded"
    if b == "unsat":
        return "unsat", "bounded"
    return "unknown", "timeout"


RANK = {"EQUIV": 4, "STRONGER": 3, "WEAKER": 3, "COMPATIBLE": 2, "CONTRADICTORY": 1, "UNKNOWN": 0,
        "UNALIGNABLE": -1}
FLIP = {"STRONGER": "WEAKER", "WEAKER": "STRONGER"}


def flip(rel: str) -> str:
    return FLIP.get(rel, rel)


def possible(vA: np.ndarray, vB: np.ndarray) -> dict:
    """Relations still possible given the fingerprints (anything refuted here is refuted soundly)."""
    ab = not bool(np.any(vA & ~vB))   # A |= B not refuted
    ba = not bool(np.any(vB & ~vA))
    joint = bool(np.any(vA & vB))     # A ∧ B has a model
    return {"ab": ab, "ba": ba, "joint_sat": joint}


def pair_relation(A, B, vA: np.ndarray | None = None, vB: np.ndarray | None = None,
                  deadline: float | None = None) -> dict:
    """Relation of A to B (same vocabulary: B already mapped). Returns
    {rel, entail_ab, entail_ba, sat_joint, method, n_solver_calls}."""
    if vA is None or vB is None:
        from .fp import slotmap, truth_vector
        ps, cs = slotmap(A, B)
        vA, vB = truth_vector(A, ps, cs), truth_vector(B, ps, cs)
    pos = possible(vA, vB)
    methods, n_calls, unk = [], 0, False
    ent = {}
    for key, (X, Y) in (("ab", (A, B)), ("ba", (B, A))):
        if not pos[key]:
            ent[key] = False
            continue
        n_calls += 1
        r, m = sat_check(("and", X, ("not", Y)), deadline=deadline)
        if r == "unsat":
            ent[key] = True
            methods.append(m)
        elif r == "sat":
            ent[key] = False
        else:
            ent[key] = None
            unk = True
    joint = None
    if pos["joint_sat"]:
        joint = True
    elif not (ent.get("ab") and ent.get("ba")):
        n_calls += 1
        r, m = sat_check(("and", A, B), deadline=deadline)
        joint = {"sat": True, "unsat": False}.get(r)
        if joint is None:
            unk = True
    if ent["ab"] and ent["ba"]:
        rel = "EQUIV"
    elif ent["ab"] and ent["ba"] is False:
        rel = "STRONGER"
    elif ent["ba"] and ent["ab"] is False:
        rel = "WEAKER"
    elif ent["ab"] is None or ent["ba"] is None:
        # an undecided entailment could still yield EQUIV/STRONGER/WEAKER
        rel = "UNKNOWN" if not (ent["ab"] or ent["ba"]) else ("STRONGER" if ent["ab"] else "WEAKER")
    elif joint is False:
        rel = "CONTRADICTORY"
    elif joint is None:
        rel = "UNKNOWN"
    else:
        rel = "COMPATIBLE"
    method = "bounded" if "bounded" in methods else ("unbounded" if methods else "fingerprint")
    return {"rel": rel, "entail_ab": ent["ab"], "entail_ba": ent["ba"], "sat_joint": joint, "method": method,
            "n_solver_calls": n_calls, "had_unknown": unk}
