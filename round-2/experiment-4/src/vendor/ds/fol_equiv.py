"""Lexical-free FOL equivalence up to an arity-preserving bijection of predicates and constants.

L1 labeller. NO lexical information is used: predicate/constant NAMES never matter, only the
arity-grouped bijection. For every candidate mapping:
  1. cheap random-structure refutation in pure Python (sound: a disagreement IS a countermodel);
  2. bounded check by PROPOSITIONAL GROUNDING over domain {0..n-1}, n = 1..4, with z3 Bools per
     ground atom and Int-valued constant choice variables (a SAT answer is a countermodel ->
     sound non-equivalence; no EnumSort, so no sort-naming crashes);
  3. if no countermodel up to n=4: an UNBOUNDED z3 attempt (DeclareSort + quantifiers, 10 s):
     unsat -> equiv_proved, otherwise equiv_bounded.

Statuses: equiv_proved, equiv_bounded, non_equiv, non_equiv_no_bijection, unknown_capped,
unknown_timeout, unparseable.
"""
from __future__ import annotations

import itertools
import math
import random
import time
from collections import defaultdict

import z3

from fol_parse import SYM, normalize_arity_overloads, signature

MAX_MAPPINGS = 5040
BOUND_NS = (1, 2, 3, 4)


# ----------------------------------------------------------------------------- python evaluator
def _eval(n: tuple, interp: dict, consts: dict, env: dict, dom: range, pmap: dict | None) -> bool:
    op = n[0]
    if op == "atom":
        name = pmap.get(n[1], n[1]) if pmap else n[1]
        args = tuple(env[t[1]] if t[0] == "var" else consts[(pmap or {}).get("#" + t[1], t[1])] for t in n[2])
        return args in interp.get(name, ())
    if op == "eq":
        vals = [env[t[1]] if t[0] == "var" else consts[(pmap or {}).get("#" + t[1], t[1])] for t in n[1:]]
        return vals[0] == vals[1]
    if op == "not":
        return not _eval(n[1], interp, consts, env, dom, pmap)
    if op == "and":
        return _eval(n[1], interp, consts, env, dom, pmap) and _eval(n[2], interp, consts, env, dom, pmap)
    if op == "or":
        return _eval(n[1], interp, consts, env, dom, pmap) or _eval(n[2], interp, consts, env, dom, pmap)
    if op == "imp":
        return (not _eval(n[1], interp, consts, env, dom, pmap)) or _eval(n[2], interp, consts, env, dom, pmap)
    if op == "iff":
        return _eval(n[1], interp, consts, env, dom, pmap) == _eval(n[2], interp, consts, env, dom, pmap)
    if op == "xor":
        return _eval(n[1], interp, consts, env, dom, pmap) != _eval(n[2], interp, consts, env, dom, pmap)
    if op == "forall":
        v = n[1]
        old = env.get(v)
        res = True
        for d in dom:
            env[v] = d
            if not _eval(n[2], interp, consts, env, dom, pmap):
                res = False
                break
        env[v] = old
        return res
    if op == "exists":
        v = n[1]
        old = env.get(v)
        res = False
        for d in dom:
            env[v] = d
            if _eval(n[2], interp, consts, env, dom, pmap):
                res = True
                break
        env[v] = old
        return res
    raise ValueError(op)


def random_structures(preds: dict[str, int], consts: set[str], seed: int = 0, per_n: dict | None = None):
    rng = random.Random(seed)
    per_n = per_n or {1: 4, 2: 16, 3: 16}
    out = []
    for n, k in per_n.items():
        dom = range(n)
        for _ in range(k):
            dens = rng.choice([0.2, 0.5, 0.8])
            interp = {p: {t for t in itertools.product(dom, repeat=a) if rng.random() < dens} for p, a in preds.items()}
            cons = {c: rng.randrange(n) for c in consts}
            out.append((dom, interp, cons))
    return out


# ----------------------------------------------------------------------------- z3 grounding
class _Grounder:
    def __init__(self, n: int, pmap: dict | None, cvars: dict):
        self.n, self.pmap, self.cvars = n, pmap or {}, cvars
        self.atoms: dict = {}

    def cname(self, c):
        return self.pmap.get("#" + c, c)

    def bool_atom(self, name: str, args: tuple):
        key = (name, args)
        if key not in self.atoms:
            self.atoms[key] = z3.Bool(f"{name}|{'|'.join(map(str, args))}")
        return self.atoms[key]

    def term_choices(self, t, env):
        if t[0] == "var":
            return [(env[t[1]], None)]
        cv = self.cvars[self.cname(t[1])]
        return [(v, cv == v) for v in range(self.n)]

    def g(self, node, env):
        op = node[0]
        if op == "atom":
            name = self.pmap.get(node[1], node[1])
            choices = [self.term_choices(t, env) for t in node[2]]
            disj = []
            for combo in itertools.product(*choices):
                args = tuple(c[0] for c in combo)
                conds = [c[1] for c in combo if c[1] is not None]
                a = self.bool_atom(name, args)
                disj.append(z3.And(*conds, a) if conds else a)
            return disj[0] if len(disj) == 1 else z3.Or(*disj)
        if op == "eq":
            t1, t2 = node[1], node[2]
            if t1[0] == "var" and t2[0] == "var":
                return z3.BoolVal(env[t1[1]] == env[t2[1]])
            e1 = env[t1[1]] if t1[0] == "var" else self.cvars[self.cname(t1[1])]
            e2 = env[t2[1]] if t2[0] == "var" else self.cvars[self.cname(t2[1])]
            return e1 == e2
        if op == "not":
            return z3.Not(self.g(node[1], env))
        if op == "and":
            return z3.And(self.g(node[1], env), self.g(node[2], env))
        if op == "or":
            return z3.Or(self.g(node[1], env), self.g(node[2], env))
        if op == "imp":
            return z3.Implies(self.g(node[1], env), self.g(node[2], env))
        if op == "iff":
            return self.g(node[1], env) == self.g(node[2], env)
        if op == "xor":
            return z3.Xor(self.g(node[1], env), self.g(node[2], env))
        if op in ("forall", "exists"):
            parts = []
            for d in range(self.n):
                e2 = dict(env)
                e2[node[1]] = d
                parts.append(self.g(node[2], e2))
            return z3.And(*parts) if op == "forall" else z3.Or(*parts)
        raise ValueError(op)


def ground(ast: tuple, n: int, consts: list[str], pmap: dict | None = None, cvars: dict | None = None):
    if cvars is None:
        cvars = {c: z3.Int(f"c#{c}") for c in consts}
    return _Grounder(n, pmap, cvars).g(ast, {}), cvars


def _dom_constraints(cvars: dict, n: int):
    return [z3.And(v >= 0, v < n) for v in cvars.values()]


def bounded_check(F: tuple, G: tuple, consts: list[str], pmap: dict, mode: str, ns=BOUND_NS,
                  timeout_ms: int = 5000, deadline: float | None = None) -> tuple[str, int | None]:
    """mode 'equiv': SAT(F xor G); 'f2g': SAT(F ∧ ¬G); 'g2f': SAT(G ∧ ¬F).
    Returns ('countermodel', n) | ('none', max_n) | ('timeout', n)."""
    for n in ns:
        if deadline is not None and time.time() > deadline:
            return "timeout", n
        f, cv = ground(F, n, consts)
        g, _ = ground(G, n, consts, pmap=pmap, cvars=cv)
        s = z3.Solver()
        s.set("timeout", timeout_ms)
        s.add(*_dom_constraints(cv, n))
        if mode == "equiv":
            s.add(z3.Xor(f, g))
        elif mode == "f2g":
            s.add(f, z3.Not(g))
        else:
            s.add(g, z3.Not(f))
        r = s.check()
        if r == z3.sat:
            return "countermodel", n
        if r == z3.unknown:
            return "timeout", n
    return "none", ns[-1]


def unbounded_equiv(F: tuple, G: tuple, preds: dict[str, int], consts: list[str], pmap: dict,
                    timeout_ms: int = 10000) -> str:
    U = z3.DeclareSort("U")
    funcs = {p: (z3.Function(f"P_{p}", *([U] * a), z3.BoolSort()) if a > 0 else z3.Bool(f"P_{p}"))
             for p, a in preds.items()}
    cs = {c: z3.Const(f"K_{c}", U) for c in consts}

    def tr(node, env, remap):
        op = node[0]
        if op == "atom":
            name = remap.get(node[1], node[1]) if remap else node[1]
            args = [env[t[1]] if t[0] == "var" else cs[(remap or {}).get("#" + t[1], t[1])] for t in node[2]]
            f = funcs[name]
            return f(*args) if args else f
        if op == "eq":
            a = [env[t[1]] if t[0] == "var" else cs[(remap or {}).get("#" + t[1], t[1])] for t in node[1:]]
            return a[0] == a[1]
        if op == "not":
            return z3.Not(tr(node[1], env, remap))
        if op in ("and", "or", "imp", "iff", "xor"):
            a, b = tr(node[1], env, remap), tr(node[2], env, remap)
            return {"and": z3.And, "or": z3.Or, "imp": z3.Implies, "xor": z3.Xor}[op](a, b) if op != "iff" else a == b
        if op in ("forall", "exists"):
            v = z3.Const(f"v_{node[1]}_{id(node)}", U)
            e2 = dict(env)
            e2[node[1]] = v
            body = tr(node[2], e2, remap)
            return z3.ForAll([v], body) if op == "forall" else z3.Exists([v], body)
        raise ValueError(op)
    try:
        f = tr(F, {}, None)
        g = tr(G, {}, pmap)
        s = z3.Solver()
        s.set("timeout", timeout_ms)
        s.add(z3.Not(f == g))
        r = s.check()
        return "unsat" if r == z3.unsat else ("sat" if r == z3.sat else "unknown")
    except z3.Z3Exception:
        return "unknown"


# ----------------------------------------------------------------------------- mappings
def _groups(preds: dict[str, int]) -> dict[int, list[str]]:
    g = defaultdict(list)
    for p, a in preds.items():
        g[a].append(p)
    return {a: sorted(v) for a, v in g.items()}


def arity_profile(preds: dict[str, int], consts) -> tuple:
    g = _groups(preds)
    return tuple(sorted((a, len(v)) for a, v in g.items())) + (("c", len(consts)),)


def enumerate_mappings(cand_preds, cand_consts, gold_preds, gold_consts, fixed: dict | None = None,
                       cap: int = MAX_MAPPINGS, seed: int = 0):
    """Yield dicts gold_name -> cand_name (constants prefixed with '#'). Returns (iterator, capped)."""
    fixed = fixed or {}
    cg = _groups({p: a for p, a in cand_preds.items() if p not in fixed.values()})
    gg = _groups({p: a for p, a in gold_preds.items() if p not in fixed})
    cc = sorted(c for c in cand_consts if "#" + c not in fixed.values())
    gc = sorted(c for c in gold_consts if "#" + c not in fixed)
    blocks = [(gg[a], cg[a]) for a in sorted(gg)] + [(gc, cc)]
    total = math.prod(math.factorial(len(b[0])) for b in blocks)

    def mk(perms):
        m = dict(fixed)
        for (gl, cl), perm in zip(blocks, perms):
            is_c = gl is gc
            for gname, cname in zip(gl, perm):
                if is_c:
                    m["#" + gname] = "#" + cname
                else:
                    m[gname] = cname
        return m

    if total <= cap:
        it = (mk(p) for p in itertools.product(*[itertools.permutations(cl) for _, cl in blocks]))
        return it, False, total
    rng = random.Random(seed)

    def sampled():
        seen = set()
        tries = 0
        while len(seen) < cap and tries < cap * 3:
            tries += 1
            perms = tuple(tuple(rng.sample(cl, len(cl))) for _, cl in blocks)
            if perms in seen:
                continue
            seen.add(perms)
            yield mk(perms)
    return sampled(), True, total


def _pm_for_eval(m: dict) -> dict:
    """Mapping in the evaluator's convention: predicate names map directly; constants '#g'->'c'."""
    out = {}
    for k, v in m.items():
        if k.startswith("#"):
            out[k] = v[1:]
        else:
            out[k] = v
    return out


def _pm_for_z3(m: dict) -> dict:
    return _pm_for_eval(m)


# ----------------------------------------------------------------------------- main API
def equivalence(cand_ast: tuple | None, gold_ast: tuple | None, time_limit: float = 30.0,
                fixed: dict | None = None, want_entailment: bool = True, seed: int = 0) -> dict:
    """L1 status of candidate vs gold, lexical-free. `fixed` pins gold->cand names (used by L2)."""
    t0 = time.time()
    deadline = t0 + time_limit
    res = {"status": None, "mapping": None, "entail_cand_to_gold": None, "entail_gold_to_cand": None,
           "method": None, "max_domain": None, "n_mappings_total": None, "n_mappings_tried": 0,
           "seconds": None}
    if cand_ast is None or gold_ast is None:
        res["status"] = "unparseable"
        res["seconds"] = round(time.time() - t0, 3)
        return res
    C = normalize_arity_overloads(cand_ast)
    G = normalize_arity_overloads(gold_ast)
    cp, cc = signature(C)
    gp, gc = signature(G)
    if fixed is None and arity_profile(cp, cc) != arity_profile(gp, gc):
        res["status"] = "non_equiv_no_bijection"
        res["seconds"] = round(time.time() - t0, 3)
        return res
    if fixed is not None:
        # after substitution the free parts must still match by arity
        cp_free = {p: a for p, a in cp.items() if p not in fixed.values()}
        gp_free = {p: a for p, a in gp.items() if p not in fixed}
        if arity_profile(cp_free, cc) != arity_profile(gp_free, gc):
            res["status"] = "non_equiv_no_bijection"
            res["seconds"] = round(time.time() - t0, 3)
            return res
    maps, capped, total = enumerate_mappings(cp, cc, gp, gc, fixed=fixed, seed=seed)
    res["n_mappings_total"] = total
    structs = random_structures(cp, set(cc), seed=seed)
    cand_vals = [_eval(C, it, cs, {}, dom, None) for dom, it, cs in structs]
    consts_c = sorted(cc)
    best = None  # (score, mapping, f2g_alive, g2f_alive)
    survivors = []
    timed_out = False
    for m in maps:
        if time.time() > deadline:
            timed_out = True
            break
        res["n_mappings_tried"] += 1
        pm = _pm_for_eval(m)
        f2g = g2f = True
        eq_alive = True
        for (dom, it, cs), cv in zip(structs, cand_vals):
            gv = _eval(G, it, cs, {}, dom, pm)
            if cv and not gv:
                f2g = False
            if gv and not cv:
                g2f = False
            if cv != gv:
                eq_alive = False
                if not want_entailment or (not f2g and not g2f):
                    break
        score = int(f2g) + int(g2f)
        if best is None or score > best[0]:
            best = (score, m, f2g, g2f)
        if eq_alive:
            survivors.append(m)
            # bounded z3 check right away (early exit on the first equivalent mapping)
            r, n = bounded_check(C, G, consts_c, _pm_for_z3(m), "equiv", deadline=deadline)
            if r == "timeout":
                timed_out = True
                continue
            if r == "none":
                ub = unbounded_equiv(C, G, {**cp}, consts_c, _pm_for_z3(m),
                                     timeout_ms=int(max(1000, min(10000, (deadline - time.time()) * 1000))))
                res["status"] = "equiv_proved" if ub == "unsat" else "equiv_bounded"
                res["method"] = "unbounded" if ub == "unsat" else "bounded"
                res["max_domain"] = None if ub == "unsat" else BOUND_NS[-1]
                res["mapping"] = m
                res["entail_cand_to_gold"] = True
                res["entail_gold_to_cand"] = True
                res["seconds"] = round(time.time() - t0, 3)
                return res
    # no equivalent mapping found
    if timed_out:
        res["status"] = "unknown_timeout"
    elif capped:
        res["status"] = "unknown_capped"
    else:
        res["status"] = "non_equiv"
    res["method"] = "bounded"
    res["max_domain"] = BOUND_NS[-1]
    if want_entailment and best is not None and time.time() < deadline:
        _, m, f2g, g2f = best
        res["mapping"] = m
        pm = _pm_for_z3(m)
        for key, alive, mode in (("entail_cand_to_gold", f2g, "f2g"), ("entail_gold_to_cand", g2f, "g2f")):
            if not alive:
                res[key] = False
                continue
            r, _ = bounded_check(C, G, consts_c, pm, mode, deadline=deadline)
            res[key] = False if r == "countermodel" else (None if r == "timeout" else True)
    res["seconds"] = round(time.time() - t0, 3)
    return res


def sat_valid_check(ast: tuple, ns=(1, 2, 3), timeout_ms: int = 5000) -> dict:
    """Bounded satisfiability / validity of a single formula (for gold screening)."""
    A = normalize_arity_overloads(ast)
    preds, consts = signature(A)
    consts_l = sorted(consts)
    sat_any = False
    falsifiable_any = False
    for n in ns:
        f, cv = ground(A, n, consts_l)
        s = z3.Solver()
        s.set("timeout", timeout_ms)
        s.add(*_dom_constraints(cv, n))
        s.push()
        s.add(f)
        if s.check() == z3.sat:
            sat_any = True
        s.pop()
        s.add(z3.Not(f))
        if s.check() == z3.sat:
            falsifiable_any = True
        if sat_any and falsifiable_any:
            break
    return {"satisfiable": sat_any, "valid_bounded": not falsifiable_any, "unsat_bounded": not sat_any}
