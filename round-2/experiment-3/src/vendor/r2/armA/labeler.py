"""Equivalence-up-to-renaming labeler (never reads names for the PRIMARY blind label).

label(cand_ast, gold_ast) ->
  status: equiv | nonequiv | unlabeled
  - arity multiset of predicates or number of constants differs -> nonequiv (no solver work)
  - arity-preserving bijections sigma (per-arity predicate permutations x constant permutations);
    > MAX_BIJ bijections or > 8 predicates -> unlabeled
  - fast reject: 64 random finite structures (sizes 2,3), pure-Python evaluation
  - survivors: exact bounded check  SAT(F_c[sigma] XOR F_g) over all sizes 1..4 (one grounded query)
  - equiv iff some sigma survives; for equiv items an unbounded z3 check (uninterpreted sort,
    10 s timeout) is logged as unsat/sat/unknown.
SECONDARY lexical label (label_lex): equivalence under the single name-similarity-optimal
bijection (character-trigram Jaccard, Hungarian per arity class). This guards against the blind
labeler accepting e.g. a reversed implication ∀x(Bark(x)→Dog(x)) via the swap Dog<->Bark.
"""
from __future__ import annotations

import itertools
import math
import random
import re
import time
from collections import Counter

import numpy as np
import z3
from scipy.optimize import linear_sum_assignment

from fol_parse import consts as f_consts
from fol_parse import preds as f_preds
from fol_parse import rename
from ground import Domain, ground, py_eval, random_structures, sat, var_interp

MAX_BIJ = 5040
N_BOUND = 4


def _trigrams(s: str) -> set:
    s = "#" + re.sub(r"[^a-z0-9]", "", s.lower()) + "#"
    return {s[i:i + 3] for i in range(max(1, len(s) - 2))}


def name_sim(a: str, b: str) -> float:
    A, B = _trigrams(a), _trigrams(b)
    return len(A & B) / max(1, len(A | B))


def bounded_equiv(fa, fb, pa: dict, ca, N: int = N_BOUND, timeout_ms: int = 20000) -> str:
    """fa, fb over the SAME vocabulary (pa: pred->arity, ca: constants). Returns unsat(=equiv)/sat/unknown."""
    D = Domain(N, ca)
    I = var_interp(pa, N)
    return sat(D.axioms + [z3.Xor(ground(fa, D, I), ground(fb, D, I))], timeout_ms)


def _to_z3_unbounded(f, U, P, C, env):
    op = f[0]
    if op == "atom":
        args = [env[a[1]] if a[0] == "v" else C[a[1]] for a in f[2]]
        return P[f[1]](*args) if args else P[f[1]]
    if op == "eq":
        g = lambda t: env[t[1]] if t[0] == "v" else C[t[1]]  # noqa: E731
        return g(f[1]) == g(f[2])
    if op == "not":
        return z3.Not(_to_z3_unbounded(f[1], U, P, C, env))
    if op in ("and", "or"):
        xs = [_to_z3_unbounded(c, U, P, C, env) for c in f[1]]
        return z3.And(xs) if op == "and" else z3.Or(xs)
    a = _to_z3_unbounded(f[1], U, P, C, env) if op in ("imp", "iff", "xor") else None
    if op == "imp":
        return z3.Implies(a, _to_z3_unbounded(f[2], U, P, C, env))
    if op == "iff":
        return a == _to_z3_unbounded(f[2], U, P, C, env)
    if op == "xor":
        return z3.Xor(a, _to_z3_unbounded(f[2], U, P, C, env))
    if op in ("all", "ex"):
        v = z3.Const(f"{f[1]}_{id(f)}_{len(env)}", U)
        body = _to_z3_unbounded(f[2], U, P, C, {**env, f[1]: v})
        return z3.ForAll([v], body) if op == "all" else z3.Exists([v], body)
    raise ValueError(op)


def unbounded_equiv(fa, fb, pa: dict, ca, timeout_ms: int = 10000) -> str:
    U = z3.DeclareSort(f"U{random.randrange(10**9)}")
    P = {p: (z3.Function(f"p_{p}", *([U] * k), z3.BoolSort()) if k else z3.Bool(f"p_{p}")) for p, k in pa.items()}
    C = {c: z3.Const(f"k_{c}", U) for c in ca}
    s = z3.Solver()
    s.set("timeout", timeout_ms)
    s.add(z3.Xor(_to_z3_unbounded(fa, U, P, C, {}), _to_z3_unbounded(fb, U, P, C, {})))
    r = s.check()
    return "unsat" if r == z3.unsat else "sat" if r == z3.sat else "unknown"


def _bijections(pc: dict, pg: dict, cc: list, cg: list):
    by_c, by_g = {}, {}
    for p, k in pc.items():
        by_c.setdefault(k, []).append(p)
    for p, k in pg.items():
        by_g.setdefault(k, []).append(p)
    groups = [(sorted(by_c[k]), sorted(by_g[k])) for k in sorted(by_c)]
    perm_lists = [list(itertools.permutations(g)) for _, g in groups]
    const_perms = list(itertools.permutations(cg))
    for combo in itertools.product(*perm_lists):
        pmap = {}
        for (cs, _), gperm in zip(groups, combo):
            pmap.update(dict(zip(cs, gperm)))
        for cperm in const_perms:
            yield pmap, dict(zip(cc, cperm))


def n_bijections(pc: dict, cc: list) -> int:
    cnt = Counter(pc.values())
    n = 1
    for v in cnt.values():
        n *= math.factorial(v)
    return n * math.factorial(len(cc))


def lexical_bijection(pc: dict, pg: dict, cc: list, cg: list):
    pmap = {}
    for k in set(pc.values()):
        a = sorted(p for p in pc if pc[p] == k)
        b = sorted(p for p in pg if pg[p] == k)
        M = np.array([[name_sim(x, y) for y in b] for x in a])
        r, c = linear_sum_assignment(-M)
        pmap.update({a[i]: b[j] for i, j in zip(r, c)})
    cmap = {}
    if cc:
        M = np.array([[name_sim(x, y) for y in cg] for x in cc])
        r, c = linear_sum_assignment(-M)
        cmap = {cc[i]: cg[j] for i, j in zip(r, c)}
    return pmap, cmap


def label(cand_ast, gold_ast, seed: int = 0, n_samples: int = 64, do_unbounded: bool = True,
          budget_s: float = 30.0) -> dict:
    t0 = time.time()
    pc, pg = f_preds(cand_ast), f_preds(gold_ast)
    cc, cg = sorted(f_consts(cand_ast)), sorted(f_consts(gold_ast))
    out = {"status": None, "bounded_equiv": None, "unbounded_status": None, "bijection": None,
           "status_lex": None, "lex_bijection": None, "lex_is_equiv_bijection": None,
           "n_bij": None, "seconds": None, "reason": ""}
    if sorted(pc.values()) != sorted(pg.values()) or len(cc) != len(cg):
        out.update(status="nonequiv", bounded_equiv=False, status_lex="nonequiv", reason="vocab_shape")
        out["seconds"] = round(time.time() - t0, 3)
        return out
    nb = n_bijections(pc, cc)
    out["n_bij"] = nb
    # lexical secondary label
    lp, lc = lexical_bijection(pc, pg, cc, cg)
    out["lex_bijection"] = {"preds": lp, "consts": lc}
    cand_lex = rename(cand_ast, lp, lc)
    r_lex = bounded_equiv(cand_lex, gold_ast, pg, cg)
    out["status_lex"] = {"unsat": "equiv", "sat": "nonequiv"}.get(r_lex, "unlabeled")
    if nb > MAX_BIJ or len(pc) > 8:
        out.update(status="unlabeled", reason=f"too_many_bijections:{nb}")
        out["seconds"] = round(time.time() - t0, 3)
        return out
    rng = random.Random(seed)
    samples = random_structures(pg, cg, n_samples, rng)
    gold_vals = [py_eval(gold_ast, n, I, C) for n, I, C in samples]
    found = None
    any_unknown = False
    # try the lexical bijection first (cheap win), then all others
    cands = [(lp, lc)] + [b for b in _bijections(pc, pg, cc, cg) if b != (lp, lc)]
    timed_out = False
    for pmap, cmap in cands:
        if time.time() - t0 > budget_s:
            timed_out = True
            break
        ren = rename(cand_ast, pmap, cmap)
        ok = True
        for (n, I, C), gv in zip(samples, gold_vals):
            if py_eval(ren, n, I, C) != gv:
                ok = False
                break
        if not ok:
            continue
        r = bounded_equiv(ren, gold_ast, pg, cg)
        if r == "unsat":
            found = (pmap, cmap, ren)
            break
        if r == "unknown":
            any_unknown = True
    if found:
        out.update(status="equiv", bounded_equiv=True, bijection={"preds": found[0], "consts": found[1]})
        out["lex_is_equiv_bijection"] = (found[0] == lp and found[1] == lc)
        if do_unbounded:
            out["unbounded_status"] = unbounded_equiv(found[2], gold_ast, pg, cg)
    else:
        bad = any_unknown or timed_out
        out.update(status="unlabeled" if bad else "nonequiv", bounded_equiv=False,
                   reason="timeout" if timed_out else "solver_unknown" if any_unknown else "no_bijection")
    out["seconds"] = round(time.time() - t0, 3)
    return out


def identity_equiv(fa, fb, N: int = N_BOUND) -> str:
    """Equivalence with names taken literally (union vocabulary). equiv/nonequiv/unknown."""
    pa = {**f_preds(fa), **f_preds(fb)}
    ca = sorted(f_consts(fa) | f_consts(fb))
    r = bounded_equiv(fa, fb, pa, ca, N)
    return {"unsat": "equiv", "sat": "nonequiv"}.get(r, "unknown")


def satisfiable(f, N: int = 4) -> str:
    D = Domain(N, sorted(f_consts(f)))
    I = var_interp(f_preds(f), N)
    return sat(D.axioms + [ground(f, D, I)], 10000)


if __name__ == "__main__":
    from fol_parse import parse
    g = parse("∀x ((Dog(x) ∧ ¬Trained(x)) → Bark(x))").ast
    for s in ["∀x ((Hound(x) ∧ ¬Taught(x)) → Yap(x))", "∀x (¬Bark(x) → (¬Dog(x) ∨ Trained(x)))",
              "∀x (¬(¬Dog(x) ∨ Trained(x)) → Bark(x))", "∀x ((Dog(x) ∧ Trained(x)) → Bark(x))",
              "∃x (Dog(x) ∧ ¬Trained(x) ∧ Bark(x))", "∀x (Bark(x) → (Dog(x) ∧ ¬Trained(x)))",
              "∀x (Dog(x) → Bark(x))"]:
        print(s, label(parse(s).ast, g))
    g2 = parse("∀x (Dog(x) → Bark(x))").ast
    print("reversed impl vs blind:", label(parse("∀x (Bark(x) → Dog(x))").ast, g2))
