"""Exact finite-model grounding of FOL ASTs into propositional z3 formulas.

A grounding with bound N covers EVERY domain size 1..N in one propositional query: element 0 is
always active, element i>0 is active iff act_i (with act_i -> act_{i-1} to break symmetry);
quantifiers range over active elements only; each constant is a one-hot choice over active elements.
This replaces EnumSort (one query per size, name clashes) with a single SAT call per check.

Interpretations are dicts pred_name -> callable(tuple_of_element_indices) -> z3 BoolRef, so the
same formula can be grounded under substituted predicates (P', P restricted to A(x_i), ...).
Also provides a pure-Python evaluator on explicit finite structures (for fast random filtering).
"""
from __future__ import annotations

import itertools
import random

import z3

_ctr = itertools.count()


def fresh(prefix: str) -> str:
    return f"{prefix}_{next(_ctr)}"


class Domain:
    """Active-element bookkeeping + one-hot constants for bound N."""

    def __init__(self, N: int, const_names, tag: str | None = None):
        self.N = N
        tag = tag or fresh("d")
        self.act = [z3.BoolVal(True)] + [z3.Bool(f"{tag}_act{i}") for i in range(1, N)]
        self.cons = {}
        self.axioms = [z3.Implies(self.act[i], self.act[i - 1]) for i in range(2, N)]
        for c in sorted(const_names):
            vs = [z3.Bool(f"{tag}_c_{c}_{i}") for i in range(N)]
            self.cons[c] = vs
            self.axioms.append(z3.PbEq([(v, 1) for v in vs], 1))
            self.axioms += [z3.Implies(vs[i], self.act[i]) for i in range(N)]

    def add_const(self, c: str, tag: str | None = None):
        if c in self.cons:
            return
        tag = tag or fresh("cx")
        vs = [z3.Bool(f"{tag}_c_{c}_{i}") for i in range(self.N)]
        self.cons[c] = vs
        self.axioms.append(z3.PbEq([(v, 1) for v in vs], 1))
        self.axioms += [z3.Implies(vs[i], self.act[i]) for i in range(self.N)]


def var_interp(pred_arity: dict, N: int, tag: str | None = None) -> dict:
    """Fresh propositional variables for each predicate tuple."""
    tag = tag or fresh("I")
    out = {}
    for p, k in pred_arity.items():
        table = {t: z3.Bool(f"{tag}_{p}_{'_'.join(map(str, t))}") for t in itertools.product(range(N), repeat=k)}
        out[p] = (lambda tb: (lambda t: tb[t]))(table)
        out[p].table = table  # type: ignore[attr-defined]
    return out


def ground(f, D: Domain, I: dict, env: dict | None = None):
    env = env or {}
    op = f[0]
    N = D.N
    if op == "atom":
        args = f[2]
        pf = I[f[1]]
        slots = []
        for a in args:
            if a[0] == "v":
                slots.append([(env[a[1]], None)])
            else:
                slots.append([(i, D.cons[a[1]][i]) for i in range(N)])
        disj = []
        for combo in itertools.product(*slots):
            idx = tuple(c[0] for c in combo)
            guards = [c[1] for c in combo if c[1] is not None]
            lit = pf(idx)
            disj.append(z3.And(guards + [lit]) if guards else lit)
        return disj[0] if len(disj) == 1 else z3.Or(disj)
    if op == "eq":
        a, b = f[1], f[2]
        if a[0] == "v" and b[0] == "v":
            return z3.BoolVal(env[a[1]] == env[b[1]])
        if a[0] == "v":
            return D.cons[b[1]][env[a[1]]]
        if b[0] == "v":
            return D.cons[a[1]][env[b[1]]]
        return z3.Or([z3.And(D.cons[a[1]][i], D.cons[b[1]][i]) for i in range(N)])
    if op == "not":
        return z3.Not(ground(f[1], D, I, env))
    if op == "and":
        return z3.And([ground(c, D, I, env) for c in f[1]])
    if op == "or":
        return z3.Or([ground(c, D, I, env) for c in f[1]])
    if op == "imp":
        return z3.Implies(ground(f[1], D, I, env), ground(f[2], D, I, env))
    if op == "iff":
        return ground(f[1], D, I, env) == ground(f[2], D, I, env)
    if op == "xor":
        return z3.Xor(ground(f[1], D, I, env), ground(f[2], D, I, env))
    if op in ("all", "ex"):
        v = f[1]
        parts = []
        for i in range(N):
            body = ground(f[2], D, I, {**env, v: i})
            if op == "all":
                parts.append(body if i == 0 else z3.Implies(D.act[i], body))
            else:
                parts.append(body if i == 0 else z3.And(D.act[i], body))
        return z3.And(parts) if op == "all" else z3.Or(parts)
    raise ValueError(op)


def sat(constraints, timeout_ms: int = 5000):
    s = z3.Solver()
    s.set("timeout", timeout_ms)
    s.add(*constraints)
    r = s.check()
    return "sat" if r == z3.sat else "unsat" if r == z3.unsat else "unknown"


# ---------------------------------------------------------------- python evaluator
def py_eval(f, n: int, I: dict, C: dict, env: dict | None = None) -> bool:
    """I: pred -> set of tuples; C: const -> element."""
    env = env or {}
    op = f[0]
    if op == "atom":
        t = tuple(env[a[1]] if a[0] == "v" else C[a[1]] for a in f[2])
        return t in I[f[1]]
    if op == "eq":
        va = env[f[1][1]] if f[1][0] == "v" else C[f[1][1]]
        vb = env[f[2][1]] if f[2][0] == "v" else C[f[2][1]]
        return va == vb
    if op == "not":
        return not py_eval(f[1], n, I, C, env)
    if op == "and":
        return all(py_eval(c, n, I, C, env) for c in f[1])
    if op == "or":
        return any(py_eval(c, n, I, C, env) for c in f[1])
    if op == "imp":
        return (not py_eval(f[1], n, I, C, env)) or py_eval(f[2], n, I, C, env)
    if op == "iff":
        return py_eval(f[1], n, I, C, env) == py_eval(f[2], n, I, C, env)
    if op == "xor":
        return py_eval(f[1], n, I, C, env) != py_eval(f[2], n, I, C, env)
    if op == "all":
        return all(py_eval(f[2], n, I, C, {**env, f[1]: i}) for i in range(n))
    if op == "ex":
        return any(py_eval(f[2], n, I, C, {**env, f[1]: i}) for i in range(n))
    raise ValueError(op)


def random_structures(pred_arity: dict, const_names, k: int, rng: random.Random, sizes=(2, 3)):
    out = []
    for j in range(k):
        n = sizes[j % len(sizes)]
        I = {}
        for p, a in pred_arity.items():
            dens = rng.choice((0.3, 0.5, 0.7))
            I[p] = {t for t in itertools.product(range(n), repeat=a) if rng.random() < dens}
        C = {c: rng.randrange(n) for c in const_names}
        out.append((n, I, C))
    return out
