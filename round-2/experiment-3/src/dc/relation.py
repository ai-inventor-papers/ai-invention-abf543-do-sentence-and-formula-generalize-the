"""Solver-decided entailment relation between two formulas that already share one vocabulary.

pair_relation(A, B) answers, for A and B over the SAME predicate/constant names:
  c1 = A |= B ?   c2 = B |= A ?   sat = SAT(A & B) ?
Bounded stage: propositional grounding over domains n = 1..4 (vendor fol_equiv.ground); a model found by z3
is a sound countermodel, so a refuted entailment is refuted for good. Unrefuted entailments go to an
unbounded z3 check (DeclareSort, quantifiers, 5 s). An entailment that survives the bound but is not proved
unboundedly counts as holding and is flagged 'bounded' (as round 1 did).
Relation: c1&c2 -> EQUIV; c1 -> STRONGER (A stronger); c2 -> WEAKER; not sat -> CONTRADICTORY; else INCOMPARABLE.
"""
from __future__ import annotations

import itertools
import random
import sys
import time
from pathlib import Path

import z3

_VENDOR = Path(__file__).resolve().parents[1] / "vendor" / "ds" / "src"
if str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))
from fol_equiv import _eval, ground  # noqa: E402

from .parse import sig  # noqa: E402

BOUND_NS = (1, 2, 3, 4)
RELS = ("EQUIV", "STRONGER", "WEAKER", "INCOMPARABLE", "CONTRADICTORY", "UNALIGNABLE", "UNKNOWN")
RANK = {"EQUIV": 4, "STRONGER": 3, "WEAKER": 3, "INCOMPARABLE": 2, "CONTRADICTORY": 1, "UNKNOWN": 0,
        "UNALIGNABLE": -1}
CONVERSE = {"STRONGER": "WEAKER", "WEAKER": "STRONGER"}


def converse(rel: str) -> str:
    return CONVERSE.get(rel, rel)


def union_sig(A, B) -> tuple[dict[str, int], list[str]]:
    pa, ca = sig(A)
    pb, cb = sig(B)
    preds = dict(pa)
    for p, a in pb.items():
        if p in preds and preds[p] != a:
            raise ValueError(f"arity clash on {p}")
        preds[p] = a
    return preds, sorted(ca | cb)


class Structs:
    """Random finite structures over a vocabulary (vendor random_structures: 4 of size 1, 16 of 2, 16 of 3)."""

    def __init__(self, preds: dict[str, int], consts, seed: int = 0):
        # deterministic: symbols in sorted order (set iteration order depends on the hash seed)
        rng = random.Random(seed)
        preds = dict(sorted(preds.items()))
        consts = sorted(consts)
        self.S = []
        for n, k in ((1, 4), (2, 16), (3, 16)):
            dom = range(n)
            for _ in range(k):
                dens = rng.choice([0.2, 0.5, 0.8])
                interp = {p: {t for t in itertools.product(dom, repeat=a) if rng.random() < dens}
                          for p, a in preds.items()}
                self.S.append((dom, interp, {c: rng.randrange(n) for c in consts}))

    def truth(self, ast) -> tuple:
        return tuple(_eval(ast, it, cs, {}, dom, None) for dom, it, cs in self.S)


def quick_rel(va: tuple, vb: tuple) -> dict:
    """Refutation-only relation from truth vectors on shared random structures (sound for refutations)."""
    f2g = not any(a and not b for a, b in zip(va, vb))
    g2f = not any(b and not a for a, b in zip(va, vb))
    both = any(a and b for a, b in zip(va, vb))
    return {"c1_alive": f2g, "c2_alive": g2f, "sat_seen": both, "eq_alive": f2g and g2f,
            "score": 4 if (f2g and g2f) else 3 if (f2g or g2f) else 2 if both else 1}


def _dom(cv, n):
    return [z3.And(v >= 0, v < n) for v in cv.values()]


def _unbounded(A, B, preds: dict[str, int], consts: list[str], mode: str, timeout_ms: int) -> str:
    """mode 'f2g': validity of A->B; 'g2f': validity of B->A; 'sat': satisfiability of A&B.
    Returns 'proved' (valid / unsat for 'sat'), 'refuted', or 'unknown'."""
    U = z3.DeclareSort("U")
    funcs = {p: (z3.Function(f"P_{p}", *([U] * a), z3.BoolSort()) if a > 0 else z3.Bool(f"P_{p}"))
             for p, a in preds.items()}
    cs = {c: z3.Const(f"K_{c}", U) for c in consts}
    ctr = [0]

    def tr(node, env):
        op = node[0]
        if op == "atom":
            args = [env[t[1]] if t[0] == "var" else cs[t[1]] for t in node[2]]
            f = funcs[node[1]]
            return f(*args) if args else f
        if op == "eq":
            a = [env[t[1]] if t[0] == "var" else cs[t[1]] for t in node[1:]]
            return a[0] == a[1]
        if op == "not":
            return z3.Not(tr(node[1], env))
        if op in ("and", "or", "imp", "xor"):
            return {"and": z3.And, "or": z3.Or, "imp": z3.Implies, "xor": z3.Xor}[op](tr(node[1], env), tr(node[2], env))
        if op == "iff":
            return tr(node[1], env) == tr(node[2], env)
        if op in ("forall", "exists"):
            ctr[0] += 1
            v = z3.Const(f"v_{node[1]}_{ctr[0]}", U)
            e2 = dict(env)
            e2[node[1]] = v
            body = tr(node[2], e2)
            return z3.ForAll([v], body) if op == "forall" else z3.Exists([v], body)
        raise ValueError(op)
    try:
        a, b = tr(A, {}), tr(B, {})
        s = z3.Solver()
        s.set("timeout", timeout_ms)
        if mode == "f2g":
            s.add(z3.Not(z3.Implies(a, b)))
        elif mode == "g2f":
            s.add(z3.Not(z3.Implies(b, a)))
        else:
            s.add(a, b)
        r = s.check()
        if r == z3.unsat:
            return "proved"
        if r == z3.sat:
            return "refuted"
        return "unknown"
    except z3.Z3Exception:
        return "unknown"


def pair_relation(A, B, deadline: float | None = None, need: tuple = ("f2g", "g2f", "sat"),
                  alive: dict | None = None, unbounded_ms: int = 5000, bounded_ms: int = 3000) -> dict:
    """Solver-decided entailment relation of formula A to formula B (shared vocabulary)."""
    t0 = time.time()
    preds, consts = union_sig(A, B)
    alive = alive or {}
    st = {"f2g": alive.get("c1_alive", True), "g2f": alive.get("c2_alive", True),
          # sat: True means "not yet shown satisfiable"; a witness structure shows A&B satisfiable
          "sat": not alive.get("sat_seen", False)}
    sat_shown = alive.get("sat_seen", False)
    timed_out = False
    maxn = {}
    for n in BOUND_NS:
        todo = [m for m in need if st[m]]
        if not todo:
            break
        if deadline is not None and time.time() > deadline:
            timed_out = True
            break
        try:
            fa, cv = ground(A, n, consts)
            fb, _ = ground(B, n, consts, cvars=cv)
        except (z3.Z3Exception, KeyError, RecursionError) as e:  # pragma: no cover - logged by caller
            return {"rel": "UNKNOWN", "error": f"ground:{type(e).__name__}", "seconds": round(time.time() - t0, 3)}
        for m in todo:
            s = z3.Solver()
            s.set("timeout", bounded_ms)
            s.add(*_dom(cv, n))
            if m == "f2g":
                s.add(fa, z3.Not(fb))
            elif m == "g2f":
                s.add(fb, z3.Not(fa))
            else:
                s.add(fa, fb)
            r = s.check()
            if r == z3.sat:
                if m == "sat":
                    sat_shown = True
                st[m] = False  # refuted entailment / satisfiability witnessed
            elif r == z3.unknown:
                timed_out = True
            maxn[m] = n
    method = {}
    c1 = st["f2g"]
    c2 = st["g2f"]
    for m, flag in (("f2g", c1), ("g2f", c2)):
        if m in need and flag:
            u = _unbounded(A, B, preds, consts, m, unbounded_ms)
            if u == "refuted":  # z3 found an infinite/larger countermodel
                if m == "f2g":
                    c1 = False
                else:
                    c2 = False
                method[m] = "unbounded_refuted"
            else:
                method[m] = "unbounded" if u == "proved" else "bounded"
    unsat = (not sat_shown) and ("sat" in need)
    if unsat and st["sat"]:
        u = _unbounded(A, B, preds, consts, "sat", unbounded_ms)
        if u == "refuted":
            unsat = False
            method["sat"] = "unbounded_refuted"
        else:
            method["sat"] = "unbounded" if u == "proved" else "bounded"
    if c1 and c2:
        rel = "EQUIV"
    elif c1:
        rel = "STRONGER"
    elif c2:
        rel = "WEAKER"
    elif unsat:
        rel = "CONTRADICTORY"
    else:
        rel = "INCOMPARABLE"
    bounded_only = any(v == "bounded" for v in method.values())
    if timed_out and rel in ("EQUIV", "STRONGER", "WEAKER", "CONTRADICTORY"):
        # an unfinished bounded stage supports a positive verdict only if z3 proved it unboundedly
        claims = {"EQUIV": ("f2g", "g2f"), "STRONGER": ("f2g",), "WEAKER": ("g2f",), "CONTRADICTORY": ("sat",)}[rel]
        if not all(method.get(c) == "unbounded" for c in claims):
            rel = "UNKNOWN"
    return {"rel": rel, "c1": c1, "c2": c2, "sat": not unsat, "method": method, "bounded_only": bounded_only,
            "timed_out": timed_out, "seconds": round(time.time() - t0, 3)}


__all__ = ["pair_relation", "quick_rel", "Structs", "RELS", "RANK", "converse", "union_sig"]
