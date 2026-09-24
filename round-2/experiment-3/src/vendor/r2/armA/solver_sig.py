"""Formula side of the monotonicity signature (A1/A2/A3 share it).

sig_abs  : per predicate P, label in {+, -, 0, ±, ?} from two SAT checks over all finite structures
           of size 1..N (exact propositional grounding, see ground.py):
             UP-violation   SAT( P ⊆ P'  ∧  F(P)  ∧ ¬F(P') )
             DOWN-violation SAT( P ⊆ P'  ∧  F(P') ∧ ¬F(P) )
           '+' only UP holds, '-' only DOWN holds, '0' both (F does not depend on P),
           '±' neither (non-monotone), '?' solver unknown/timeout.
anchors  : for k-ary R (k>=2), slot i and each unary A (or constant c):
             anchored(R,i,A) iff  F ↔ F[R ↦ λx̄. R(x̄) ∧ A(x_i)]  is valid on sizes 1..N.
sig_rel  : relativized label of unary P w.r.t. unary Q (or 'x=c'), side in {in, out}: the same
           UP/DOWN test when P' ⊇ P may differ from P only on elements inside Q (in) / outside Q (out).
All three are semantic properties of F: invariant under logical equivalence and renaming.
"""
from __future__ import annotations

import itertools
import time

import z3

from fol_parse import consts as f_consts
from fol_parse import preds as f_preds
from ground import Domain, ground, sat, var_interp

LAB = {(True, False): "+", (False, True): "-", (True, True): "0", (False, False): "±"}


def _label(up: str, down: str) -> str:
    if up == "unknown" or down == "unknown":
        return "?"
    return LAB[(up == "unsat", down == "unsat")]


def signature(ast, N: int = 3, timeout_ms: int = 5000, with_rel: bool = True,
              rel_max_unary: int = 8) -> dict:
    t0 = time.time()
    P = f_preds(ast)
    C = sorted(f_consts(ast))
    D = Domain(N, C)
    I = var_interp(P, N)
    F1 = ground(ast, D, I)
    ax = list(D.axioms)
    n_unknown = 0
    n_queries = 0

    labels = {}
    for p, k in P.items():
        J = var_interp({p: k}, N)
        I2 = dict(I)
        I2[p] = J[p]
        tuples = list(itertools.product(range(N), repeat=k))
        sub = z3.And([z3.Implies(I[p](t), J[p](t)) for t in tuples]) if tuples else z3.BoolVal(True)
        F2 = ground(ast, D, I2)
        up = sat(ax + [sub, F1, z3.Not(F2)], timeout_ms)
        down = sat(ax + [sub, F2, z3.Not(F1)], timeout_ms)
        n_queries += 2
        labels[p] = _label(up, down)
        n_unknown += labels[p] == "?"

    unary = [p for p, k in P.items() if k == 1]
    anchors = {}
    for r, k in P.items():
        if k < 2:
            continue
        for i in range(k):
            restrictors = [(a, (lambda a_: (lambda t, i_=i: I[a_]((t[i_],))))(a)) for a in unary]
            restrictors += [(f"c:{c}", (lambda c_: (lambda t, i_=i: D.cons[c_][t[i_]]))(c)) for c in C]
            for name, fn in restrictors:
                I2 = dict(I)
                I2[r] = (lambda fn_: (lambda t: z3.And(I[r](t), fn_(t))))(fn)
                F2 = ground(ast, D, I2)
                res = sat(ax + [F1 != F2], timeout_ms)
                n_queries += 1
                if res == "unknown":
                    n_unknown += 1
                    anchors[f"{r}|{i}|{name}"] = None
                else:
                    anchors[f"{r}|{i}|{name}"] = res == "unsat"

    rel = {}
    if with_rel:
        regions = [(q, (lambda q_: (lambda e: I[q_]((e,))))(q)) for q in unary[:rel_max_unary]]
        regions += [(f"c:{c}", (lambda c_: (lambda e: D.cons[c_][e]))(c)) for c in C]
        for p in unary[:rel_max_unary]:
            J = var_interp({p: 1}, N)
            I2 = dict(I)
            I2[p] = J[p]
            F2 = ground(ast, D, I2)
            sub = z3.And([z3.Implies(I[p]((e,)), J[p]((e,))) for e in range(N)])
            for q, qfn in regions:
                if q == p:
                    continue
                for side in ("in", "out"):
                    reg = z3.And([z3.Implies(I[p]((e,)) != J[p]((e,)), qfn(e) if side == "in" else z3.Not(qfn(e)))
                                  for e in range(N)])
                    up = sat(ax + [sub, reg, F1, z3.Not(F2)], timeout_ms)
                    down = sat(ax + [sub, reg, F2, z3.Not(F1)], timeout_ms)
                    n_queries += 2
                    lab = _label(up, down)
                    n_unknown += lab == "?"
                    rel[f"{p}|{q}|{side}"] = lab
    return {"labels": labels, "anchors": anchors, "rel": rel, "arity": dict(P), "n_unknown": n_unknown,
            "n_queries": n_queries, "seconds": round(time.time() - t0, 3), "N": N}


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
    from fol_parse import parse
    cases = {
        "gold": "∀x ((Dog(x) ∧ ¬Trained(x)) → Bark(x))",
        "contrapositive": "∀x (¬Bark(x) → (¬Dog(x) ∨ Trained(x)))",
        "vacuous": "∀x ((Dog(x) ∧ ¬Trained(x) ∧ (Loud(x) ∨ ¬Loud(x))) → Bark(x))",
        "xor": "∀x (Person(x) → (Rich(x) ⊕ Poor(x)))",
        "reads": "∀x (Student(x) → ∃y (Book(y) ∧ Reads(x, y)))",
        "reads swap": "∀x (Student(x) → ∃y (Book(y) ∧ Reads(y, x)))",
        "const": "¬Meows(tom) → ¬Cat(tom)",
    }
    for k, f in cases.items():
        s = signature(parse(f).ast)
        print(k, s["labels"], {a: v for a, v in s["anchors"].items() if v}, s["seconds"], s["n_queries"])
    pairs = {
        "and/or restrictor": ("∀x ((Dog(x) ∨ Cat(x)) → Pet(x))", "∀x ((Dog(x) ∧ Cat(x)) → Pet(x))"),
        "and/or scope": ("∀x (Dog(x) → (Bark(x) ∧ Bite(x)))", "∀x (Dog(x) → (Bark(x) ∨ Bite(x)))"),
        "exception swap": ("∀x ((Dog(x) ∧ ¬Trained(x)) → Bark(x)) ∧ ∀x ((Dog(x) ∧ Trained(x)) → Sit(x))",
                           "∀x ((Dog(x) ∧ Trained(x)) → Bark(x)) ∧ ∀x ((Dog(x) ∧ ¬Trained(x)) → Sit(x))"),
        "contrapositive": ("∀x ((Dog(x) ∧ ¬Trained(x)) → Bark(x))", "∀x (¬Bark(x) → (¬Dog(x) ∨ Trained(x)))"),
    }
    for k, (g, c) in pairs.items():
        a, b = signature(parse(g).ast)["rel"], signature(parse(c).ast)["rel"]
        d = {x: (a[x], b.get(x)) for x in a if a[x] != b.get(x)}
        print(k, len(d), "of", len(a), d)
