"""FOL core: tokenizer, parser (FOLIO/Logic-LM unicode syntax), AST utilities, pure-Python finite-model
evaluation, finite-domain grounding into z3 (bounded equivalence / world search), unbounded z3 check,
and blind (arity-preserving bijection) + trigram-anchored equivalence labelling.

AST (hashable tuples, picklable):
  ('atom', name, (t1, ..., tk))        terms are ('v', name) or ('c', name)
  ('eq', t1, t2)
  ('not', A)
  ('and', A1, ..., An) / ('or', A1, ..., An)     n-ary, flattened
  ('imp', A, B) / ('iff', A, B) / ('xor', A, B)
  ('forall', var, A) / ('exists', var, A)
Precedence (as in the GEN_HYPO prototype): ↔ ⊕ (1) < → (2, right-assoc) < ∨ (3) < ∧ (4) < ¬, ∀, ∃.
A quantifier binds a parenthesised group or the next unary formula.
"""
from __future__ import annotations

import itertools
import random
import re
import time
from functools import lru_cache
from typing import Any

import numpy as np
import z3

# ----------------------------------------------------------------------------------------- parsing
_CTR = itertools.count()  # global suffix: fixes the prototype's EnumSort-name-by-hash crash


class ParseError(ValueError):
    def __init__(self, cls: str, msg: str):
        super().__init__(f"{cls}: {msg}")
        self.cls = cls


VAR_NAMES = set("xyzwuvst") | {"x1", "x2", "x3", "y1", "y2", "z1", "z2"}
_REPL = [("<->", "↔"), ("<=>", "↔"), ("->", "→"), ("=>", "→"), ("!=", "≠"), ("&", "∧"), ("|", "∨"),
         ("~", "¬"), ("Ǝ", "∃"), ("⇒", "→"), ("⇔", "↔"), ("≡", "↔"), ("⊻", "⊕"), ("∨", "∨")]
TOK = re.compile(r"\s*(∀|∃|¬|∧|∨|→|↔|⊕|≠|=|\(|\)|,|[^\W\d][\w'’]*|\d[\w.]*)")
NON_FOL = set("∈∉⊆⊂≤≥<>{}[]$\"+*/")


def normalize(s: str) -> str:
    s = s.strip()
    for a, b in _REPL:
        s = s.replace(a, b)
    s = re.sub(r"\bforall\s+([a-z])\b", r"∀\1", s)
    s = re.sub(r"\bexists\s+([a-z])\b", r"∃\1", s)
    s = s.rstrip(" .;")
    return s


def tokenize(s: str) -> list[str]:
    out, pos = [], 0
    while pos < len(s):
        if s[pos].isspace():
            pos += 1
            continue
        m = TOK.match(s, pos)
        if not m:
            ch = s[pos]
            raise ParseError("non_FOL" if ch in NON_FOL else "tokenize", f"cannot tokenize at {s[pos:pos+15]!r}")
        out.append(m.group(1))
        pos = m.end()
    return out


BIN = {"↔": ("iff", 1), "⊕": ("xor", 1), "→": ("imp", 2), "∨": ("or", 3), "∧": ("and", 4)}


class _Parser:
    def __init__(self, toks: list[str]):
        self.t, self.i = toks, 0

    def peek(self) -> str | None:
        return self.t[self.i] if self.i < len(self.t) else None

    def eat(self, x: str | None = None) -> str:
        tok = self.peek()
        if tok is None:
            raise ParseError("structure", f"unexpected end, expected {x}")
        if x is not None and tok != x:
            raise ParseError("structure", f"expected {x} got {tok}")
        self.i += 1
        return tok

    def parse(self, minp: int = 1):
        lhs = self.unary()
        while self.peek() in BIN and BIN[self.peek()][1] >= minp:
            op = self.eat()
            kind, p = BIN[op]
            rhs = self.parse(p if op == "→" else p + 1)
            lhs = (kind, lhs, rhs)
        return lhs

    def unary(self):
        tok = self.peek()
        if tok in ("∀", "∃"):
            self.eat()
            v = self.eat()
            if not re.fullmatch(r"[a-z][a-z0-9]*", v):
                raise ParseError("structure", f"bad quantified variable {v}")
            return ("forall" if tok == "∀" else "exists", v, self.unary())
        if tok == "¬":
            self.eat()
            return ("not", self.unary())
        if tok == "(":
            self.eat("(")
            n = self.parse()
            self.eat(")")
            return n
        return self.atom()

    def term(self) -> str:
        tok = self.eat()
        if not re.fullmatch(r"[\w.'’]+", tok):
            raise ParseError("structure", f"bad term {tok}")
        if self.peek() == "(":
            raise ParseError("function_term", f"function term {tok}(...)")
        return tok

    def atom(self):
        tok = self.peek()
        if tok is None or not re.fullmatch(r"[\w.'’]+", tok):
            raise ParseError("structure", f"expected atom got {tok}")
        name = self.eat()
        if self.peek() == "(":
            self.eat("(")
            args = []
            if self.peek() == ")":
                self.eat(")")
                return ("atomraw", name, ())
            while True:
                args.append(self.term())
                if self.peek() == ",":
                    self.eat(",")
                    continue
                self.eat(")")
                break
            node = ("atomraw", name, tuple(args))
        else:
            node = ("termraw", name)
        if self.peek() in ("=", "≠"):
            op = self.eat()
            rhs = self.term()
            if node[0] != "termraw":
                raise ParseError("non_FOL", "function term in equality")
            eq = ("eqraw", node[1], rhs)
            return ("not", eq) if op == "≠" else eq
        if node[0] == "termraw":
            return ("atomraw", name, ())  # propositional atom
        return node


def _resolve(n, bound: frozenset):
    k = n[0]
    if k == "atomraw":
        return ("atom", n[1], tuple(("v", a) if a in bound else ("c", a) for a in n[2]))
    if k == "eqraw":
        return ("eq", ("v", n[1]) if n[1] in bound else ("c", n[1]), ("v", n[2]) if n[2] in bound else ("c", n[2]))
    if k in ("forall", "exists"):
        return (k, n[1], _resolve(n[2], bound | {n[1]}))
    if k == "not":
        return ("not", _resolve(n[1], bound))
    return (k,) + tuple(_resolve(a, bound) for a in n[1:])


def flatten(n):
    k = n[0]
    if k in ("and", "or"):
        out = []
        for a in n[1:]:
            a = flatten(a)
            if a[0] == k:
                out.extend(a[1:])
            else:
                out.append(a)
        return (k,) + tuple(out)
    if k in ("atom", "eq"):
        return n
    if k in ("forall", "exists"):
        return (k, n[1], flatten(n[2]))
    return (k,) + tuple(flatten(a) for a in n[1:])


@lru_cache(maxsize=200000)
def parse(fol: str):
    s = normalize(fol)
    if not s:
        raise ParseError("structure", "empty")
    toks = tokenize(s)
    p = _Parser(toks)
    raw = p.parse()
    if p.i != len(toks):
        raise ParseError("structure", f"trailing tokens {toks[p.i:p.i+5]}")
    ast = flatten(_resolve(raw, frozenset()))
    fv = [c for c in constants(ast) if c in VAR_NAMES]
    if fv:
        raise ParseError("free_var", f"free variables {fv}")
    sig = predicates(ast, strict=False)
    if sig is None:
        raise ParseError("structure", "predicate used with inconsistent arity")
    return ast


def try_parse(fol: str):
    try:
        return parse(fol), None
    except ParseError as e:
        return None, e.cls
    except RecursionError:
        return None, "structure"


# ----------------------------------------------------------------------------------------- AST utils
def predicates(n, strict: bool = True) -> dict[str, int] | None:
    acc: dict[str, int] = {}
    ok = [True]

    def rec(m):
        if m[0] == "atom":
            if m[1] in acc and acc[m[1]] != len(m[2]):
                ok[0] = False
            acc[m[1]] = len(m[2])
        elif m[0] == "eq":
            return
        elif m[0] in ("forall", "exists"):
            rec(m[2])
        else:
            for a in m[1:]:
                rec(a)
    rec(n)
    if not ok[0]:
        if strict:
            raise ParseError("structure", "inconsistent arity")
        return None
    return acc


def constants(n) -> list[str]:
    acc: list[str] = []

    def rec(m):
        if m[0] == "atom":
            for t in m[2]:
                if t[0] == "c" and t[1] not in acc:
                    acc.append(t[1])
        elif m[0] == "eq":
            for t in m[1:]:
                if t[0] == "c" and t[1] not in acc:
                    acc.append(t[1])
        elif m[0] in ("forall", "exists"):
            rec(m[2])
        else:
            for a in m[1:]:
                rec(a)
    rec(n)
    return acc


def depth(n) -> int:
    if n[0] in ("atom", "eq"):
        return 1
    if n[0] in ("forall", "exists"):
        return 1 + depth(n[2])
    return 1 + max(depth(a) for a in n[1:])


def count_ops(n, kinds: set[str]) -> int:
    c = 1 if n[0] in kinds else 0
    if n[0] in ("atom", "eq"):
        return c
    if n[0] in ("forall", "exists"):
        return c + count_ops(n[2], kinds)
    return c + sum(count_ops(a, kinds) for a in n[1:])


def has_equality(n) -> bool:
    return count_ops(n, {"eq"}) > 0


def to_str(n) -> str:
    k = n[0]
    if k == "atom":
        return f"{n[1]}({', '.join(t[1] for t in n[2])})" if n[2] else n[1]
    if k == "eq":
        return f"{n[1][1]} = {n[2][1]}"
    if k == "not":
        a = n[1]
        if a[0] == "eq":
            return f"{a[1][1]} ≠ {a[2][1]}"
        return "¬" + (to_str(a) if a[0] in ("atom", "not", "forall", "exists") else f"({to_str(a)})")
    if k in ("forall", "exists"):
        body = n[2]
        q = "∀" if k == "forall" else "∃"
        if body[0] in ("forall", "exists"):
            return f"{q}{n[1]} {to_str(body)}"
        return f"{q}{n[1]} ({to_str(body)})"
    sym = {"and": " ∧ ", "or": " ∨ ", "imp": " → ", "iff": " ↔ ", "xor": " ⊕ "}[k]

    def wrap(a):
        return to_str(a) if a[0] in ("atom", "eq", "not", "forall", "exists") else f"({to_str(a)})"
    return sym.join(wrap(a) for a in n[1:])


def rename(n, pmap: dict[str, str], cmap: dict[str, str]):
    k = n[0]
    if k == "atom":
        return ("atom", pmap.get(n[1], n[1]), tuple(("c", cmap.get(t[1], t[1])) if t[0] == "c" else t for t in n[2]))
    if k == "eq":
        return ("eq",) + tuple(("c", cmap.get(t[1], t[1])) if t[0] == "c" else t for t in n[1:])
    if k in ("forall", "exists"):
        return (k, n[1], rename(n[2], pmap, cmap))
    return (k,) + tuple(rename(a, pmap, cmap) for a in n[1:])


# ------------------------------------------------------------------------------ pure-python evaluation
def py_eval(n, interp: dict, dom: int, env: dict | None = None) -> bool:
    """interp: {'P': {pred: set(tuples)}, 'C': {const: int}}; domain = range(dom)."""
    env = env or {}
    k = n[0]
    if k == "atom":
        tup = tuple(env[t[1]] if t[0] == "v" else interp["C"][t[1]] for t in n[2])
        return tup in interp["P"].get(n[1], ())
    if k == "eq":
        a, b = (env[t[1]] if t[0] == "v" else interp["C"][t[1]] for t in n[1:])
        return a == b
    if k == "not":
        return not py_eval(n[1], interp, dom, env)
    if k == "and":
        return all(py_eval(a, interp, dom, env) for a in n[1:])
    if k == "or":
        return any(py_eval(a, interp, dom, env) for a in n[1:])
    if k == "imp":
        return (not py_eval(n[1], interp, dom, env)) or py_eval(n[2], interp, dom, env)
    if k == "iff":
        return py_eval(n[1], interp, dom, env) == py_eval(n[2], interp, dom, env)
    if k == "xor":
        return py_eval(n[1], interp, dom, env) != py_eval(n[2], interp, dom, env)
    if k == "forall":
        return all(py_eval(n[2], interp, dom, {**env, n[1]: d}) for d in range(dom))
    if k == "exists":
        return any(py_eval(n[2], interp, dom, {**env, n[1]: d}) for d in range(dom))
    raise ValueError(k)


def random_interps(preds: dict[str, int], consts: list[str], n_interp: int, seed: int, sizes=(2, 3)) -> list:
    rng = random.Random(seed)
    out = []
    for i in range(n_interp):
        dom = sizes[i % len(sizes)]
        P = {}
        for p, k in preds.items():
            P[p] = {t for t in itertools.product(range(dom), repeat=k) if rng.random() < 0.5}
        C = {c: rng.randrange(dom) for c in consts}
        out.append(({"P": P, "C": C}, dom))
    return out


# ------------------------------------------------------------------------------ finite grounding (z3)
class Grounder:
    """Ground formulas over domain {0..n-1}. Predicate atoms -> z3 Bools shared by name+tuple.
    Constants: fixed ints (una=True: distinct elements 0..k-1) or z3 Int vars in [0,n) (no UNA)."""

    def __init__(self, n: int, consts: list[str], una: bool, tag: str = ""):
        self.n = n
        self.tag = tag or f"g{next(_CTR)}"
        self.atoms: dict[tuple, z3.BoolRef] = {}
        self.side: list = []
        if una:
            if len(consts) > n:
                raise ValueError("too many constants for UNA domain")
            self.C: dict[str, Any] = {c: i for i, c in enumerate(consts)}
        else:
            self.C = {}
            for c in consts:
                v = z3.Int(f"{self.tag}_c_{c}")
                self.C[c] = v
                self.side.append(z3.And(v >= 0, v < n))

    def const(self, c: str):
        if c not in self.C:  # constant not declared up-front (no-UNA mode only)
            v = z3.Int(f"{self.tag}_c_{c}")
            self.C[c] = v
            self.side.append(z3.And(v >= 0, v < self.n))
        return self.C[c]

    def atom(self, p: str, tup: tuple[int, ...]) -> z3.BoolRef:
        key = (p, tup)
        if key not in self.atoms:
            self.atoms[key] = z3.Bool(f"{self.tag}|{p}|{','.join(map(str, tup))}")
        return self.atoms[key]

    def g(self, f, env: dict | None = None):
        env = env or {}
        k = f[0]
        if k == "atom":
            vals = [env[t[1]] if t[0] == "v" else self.const(t[1]) for t in f[2]]
            if all(isinstance(v, int) for v in vals):
                return self.atom(f[1], tuple(vals))
            choices = [[(v, None)] if isinstance(v, int) else [(d, v == d) for d in range(self.n)] for v in vals]
            disj = []
            for combo in itertools.product(*choices):
                conds = [c for _, c in combo if c is not None]
                disj.append(z3.And(*conds, self.atom(f[1], tuple(d for d, _ in combo))))
            return z3.Or(*disj)
        if k == "eq":
            a, b = (env[t[1]] if t[0] == "v" else self.const(t[1]) for t in f[1:])
            if isinstance(a, int) and isinstance(b, int):
                return z3.BoolVal(a == b)
            return a == b
        if k == "not":
            return z3.Not(self.g(f[1], env))
        if k == "and":
            return z3.And(*[self.g(a, env) for a in f[1:]])
        if k == "or":
            return z3.Or(*[self.g(a, env) for a in f[1:]])
        if k == "imp":
            return z3.Implies(self.g(f[1], env), self.g(f[2], env))
        if k == "iff":
            return self.g(f[1], env) == self.g(f[2], env)
        if k == "xor":
            return z3.Xor(self.g(f[1], env), self.g(f[2], env))
        if k == "forall":
            return z3.And(*[self.g(f[2], {**env, f[1]: d}) for d in range(self.n)])
        if k == "exists":
            return z3.Or(*[self.g(f[2], {**env, f[1]: d}) for d in range(self.n)])
        raise ValueError(k)


def _check(constraints: list, timeout_ms: int) -> z3.CheckSatResult:
    s = z3.Solver()
    s.set("timeout", timeout_ms)
    s.add(*constraints)
    return s.check()


def satisfiable(f, nmax: int = 4, timeout_ms: int = 5000) -> str:
    """'sat' if F has a model with domain size <= nmax, 'unsat' if none, 'unknown' on timeout."""
    cs = constants(f)
    unk = False
    for n in range(1, nmax + 1):
        g = Grounder(n, cs, una=False)
        r = _check([g.g(f)] + g.side, timeout_ms)
        if r == z3.sat:
            return "sat"
        if r == z3.unknown:
            unk = True
    return "unknown" if unk else "unsat"


def bounded_equiv(f, g, nmax: int = 4, timeout_ms: int = 5000) -> str:
    """'equiv' | 'nonequiv' | 'unknown' over all domains of size 1..nmax (constants may co-refer)."""
    cs = list(dict.fromkeys(constants(f) + constants(g)))
    unk = False
    for n in range(1, nmax + 1):
        gr = Grounder(n, cs, una=False)
        r = _check([z3.Xor(gr.g(f), gr.g(g))] + gr.side, timeout_ms)
        if r == z3.sat:
            return "nonequiv"
        if r == z3.unknown:
            unk = True
    return "unknown" if unk else "equiv"


def equiv_under_map(F, G, pmap: dict, cmap: dict, nmax: int = 4, timeout_ms: int = 5000) -> str:
    return bounded_equiv(rename(F, pmap, cmap), G, nmax=nmax, timeout_ms=timeout_ms)


def unbounded_equiv(F, G, timeout_ms: int = 5000) -> str:
    """Uninterpreted-sort check sat(F xor G): unsat -> equiv (valid), sat -> nonequiv, else unknown."""
    D = z3.DeclareSort(f"U{next(_CTR)}")
    preds = {**predicates(F), **predicates(G)}
    P = {p: (z3.Function(f"{p}_{next(_CTR)}", *([D] * k), z3.BoolSort()) if k else z3.Bool(f"{p}_{next(_CTR)}"))
         for p, k in preds.items()}
    C = {c: z3.Const(f"c_{c}_{next(_CTR)}", D) for c in set(constants(F)) | set(constants(G))}

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
    r = _check([z3.Xor(tz(F, {}), tz(G, {}))], timeout_ms)
    if r == z3.unsat:
        return "equiv"
    if r == z3.sat:
        return "nonequiv"
    return "unknown"


# ------------------------------------------------------------------------------ bijection labelling
def _arity_classes(preds: dict[str, int]) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    for p, k in sorted(preds.items()):
        out.setdefault(k, []).append(p)
    return out


def _truth_vector(f, interps) -> tuple:
    return tuple(py_eval(f, it, d) for it, d in interps)


def find_bijections(F, G, cap: int = 5040, n_fp: int = 64, max_preds: int = 8, wall_s: float = 30.0,
                    max_equiv: int = 5, nmax: int = 4, timeout_ms: int = 5000) -> dict:
    """Blind label: is there an arity-preserving bijection of predicates (and a bijection of constants)
    under which candidate F is bounded-equivalent (domains 1..nmax) to gold G?"""
    t0 = time.time()
    pF, pG = predicates(F), predicates(G)
    cF, cG = constants(F), constants(G)
    aF, aG = _arity_classes(pF), _arity_classes(pG)
    if sorted(pF.values()) != sorted(pG.values()) or len(cF) != len(cG):
        return {"label": "nonequiv", "reason": "vocab_mismatch", "map": None, "n_equiv_maps": 0, "n_maps": 0}
    if len(pF) > max_preds:
        return {"label": "unlabeled", "reason": "too_many_preds", "map": None, "n_equiv_maps": 0, "n_maps": 0}
    per_class = [list(itertools.permutations(aG[k])) for k in sorted(aF)]
    n_maps = 1
    for pc in per_class:
        n_maps *= len(pc)
    n_cmaps = 1
    for i in range(2, len(cG) + 1):
        n_cmaps *= i
    total = n_maps * n_cmaps
    if total > cap:
        return {"label": "unlabeled", "reason": "too_many_maps", "map": None, "n_equiv_maps": 0, "n_maps": total}
    interps = random_interps(pG, cG, n_fp, seed=12345)
    vG = _truth_vector(G, interps)
    keysF = [aF[k] for k in sorted(aF)]
    survivors = []
    for combo in itertools.product(*per_class):
        pmap = {}
        for srcs, tgts in zip(keysF, combo):
            pmap.update(dict(zip(srcs, tgts)))
        for cperm in itertools.permutations(cG):
            cmap = dict(zip(cF, cperm))
            RF = rename(F, pmap, cmap)
            if _truth_vector(RF, interps) == vG:
                survivors.append((pmap, cmap))
        if time.time() - t0 > wall_s:
            return {"label": "unlabeled", "reason": "timeout", "map": None, "n_equiv_maps": 0, "n_maps": total}
    first, n_eq, unk = None, 0, False
    for pmap, cmap in survivors:
        r = equiv_under_map(F, G, pmap, cmap, nmax=nmax, timeout_ms=timeout_ms)
        if r == "equiv":
            n_eq += 1
            if first is None:
                first = (pmap, cmap)
            if n_eq >= max_equiv:
                break
        elif r == "unknown":
            unk = True
        if time.time() - t0 > wall_s:
            break
    if first is not None:
        return {"label": "equiv", "reason": "bijection", "map": {"P": first[0], "C": first[1]},
                "n_equiv_maps": n_eq, "n_maps": total, "n_survivors": len(survivors)}
    if unk or time.time() - t0 > wall_s:
        return {"label": "unlabeled", "reason": "solver_unknown", "map": None, "n_equiv_maps": 0, "n_maps": total}
    return {"label": "nonequiv", "reason": "no_equiv_map", "map": None, "n_equiv_maps": 0, "n_maps": total,
            "n_survivors": len(survivors)}


def _trigrams(s: str) -> set[str]:
    s = f"  {s.lower()} "
    return {s[i:i + 3] for i in range(len(s) - 2)}


def _hungarian(src: list[str], tgt: list[str]) -> dict[str, str]:
    from scipy.optimize import linear_sum_assignment
    if not src:
        return {}
    cost = np.zeros((len(src), len(tgt)))
    for i, a in enumerate(src):
        ta = _trigrams(a)
        for j, b in enumerate(tgt):
            tb = _trigrams(b)
            cost[i, j] = 1 - len(ta & tb) / max(1, len(ta | tb))
    r, c = linear_sum_assignment(cost)
    return {src[i]: tgt[j] for i, j in zip(r, c)}


def trigram_map(F, G) -> tuple[dict, dict] | None:
    pF, pG = predicates(F), predicates(G)
    cF, cG = constants(F), constants(G)
    if sorted(pF.values()) != sorted(pG.values()) or len(cF) != len(cG):
        return None
    aF, aG = _arity_classes(pF), _arity_classes(pG)
    pmap = {}
    for k in aF:
        pmap.update(_hungarian(aF[k], aG[k]))
    return pmap, _hungarian(cF, cG)


def label_trigram(F, G, nmax: int = 4, timeout_ms: int = 5000) -> dict:
    m = trigram_map(F, G)
    if m is None:
        return {"label": "nonequiv", "reason": "vocab_mismatch", "map": None}
    r = equiv_under_map(F, G, m[0], m[1], nmax=nmax, timeout_ms=timeout_ms)
    return {"label": {"equiv": "equiv", "nonequiv": "nonequiv"}.get(r, "unlabeled"), "reason": "trigram",
            "map": {"P": m[0], "C": m[1]}}
