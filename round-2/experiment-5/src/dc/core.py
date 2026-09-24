"""DC contract v1 core: lexical-free alignment (align_pair) and logical relation (pair_relation) of two FOL formulas.

Names of predicates and constants are NEVER read as words: they are opaque symbols. Every map is arity-preserving
and chosen by solver search only; ordering inside each level is deterministic (arity profile, then occurrence
count, then first-occurrence position), and the structural-fingerprint order (DC_fp) is a declared variant.

Pipeline for one pair (A, B) [B is read in A's vocabulary]:
  L1  bijections of equal arity profiles (vendor fol_equiv style, cap 5,040 maps; exhaustive when total <= cap)
  L2  partial injective arity-preserving maps covering >= 50% of B's predicate OCCURRENCES (cap 2,000);
      unmapped B predicates stay fresh symbols (free in every check)
  L3  granularity definitions: <= 2 predicates of one side defined as a conjunction of <= 2 literals over the
      other side's predicates with arity-consistent slot patterns (cap 300 definition sets; both directions)
For each map: a vectorised numpy evaluator refutes entailment directions on (i) solver-found models and
countermodels of A, (ii) models/countermodels of B transported through the map, (iii) seeded random structures
(domains 2 and 3). Directions that survive are decided by vendor fol_equiv.bounded_check (z3 propositional
grounding over domains 1..4, 5 s per call) and then an unbounded z3 entailment check (5 s).
"""
from __future__ import annotations

import itertools
import math
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import z3

_V = Path(__file__).resolve().parents[1] / "vendor" / "ds"
if str(_V) not in sys.path:
    sys.path.insert(0, str(_V))
from fol_equiv import _Grounder, bounded_check  # noqa: E402  (vendor, READ-ONLY copy)
from fol_parse import SYM, normalize_arity_overloads, parse, signature, to_str  # noqa: E402

REL_ORDER = {"EQUIV": 4, "STRONGER": 3, "WEAKER": 3, "COMPATIBLE-INCOMPARABLE": 2, "CONTRADICTORY": 1}
INVERSE = {"STRONGER": "WEAKER", "WEAKER": "STRONGER"}
DEFAULT_LIMITS = {"l1_cap": 5040, "l2_cap": 2000, "l3_cap": 300, "l2_min_cov": 0.5, "l3_max_defs": 2,
                  "l3_max_lits": 2, "domains": (1, 2, 3, 4), "z3_timeout_ms": 5000, "pair_seconds": 20.0,
                  "order": "default", "n_random": 24, "n_models": 6, "max_z3_maps": 40}


# ============================================================================== formula container
def _alpha(ast, env=None, counter=None):
    """alpha-rename bound variables to v0, v1, ... (unique per binder)."""
    env = env or {}
    counter = counter if counter is not None else [0]
    op = ast[0]
    if op in ("forall", "exists"):
        nv = f"v{counter[0]}"
        counter[0] += 1
        return (op, nv, _alpha(ast[2], {**env, ast[1]: nv}, counter))
    if op == "not":
        return ("not", _alpha(ast[1], env, counter))
    if op in SYM:
        return (op, _alpha(ast[1], env, counter), _alpha(ast[2], env, counter))
    if op == "atom":
        return ("atom", ast[1], tuple(("var", env.get(t[1], t[1])) if t[0] == "var" else t for t in ast[2]))
    if op == "eq":
        return ("eq",) + tuple(("var", env.get(t[1], t[1])) if t[0] == "var" else t for t in ast[1:])
    raise ValueError(op)


def walk_atoms(ast, path=(), pol=1, ante=False, out=None):
    """yields (name, args, polarity, in_antecedent, depth, quantified-var co-occurrence) for every atom occurrence."""
    out = [] if out is None else out
    op = ast[0]
    if op in ("forall", "exists"):
        walk_atoms(ast[2], path + (op,), pol, ante, out)
    elif op == "not":
        walk_atoms(ast[1], path + ("not",), -pol, ante, out)
    elif op == "imp":
        walk_atoms(ast[1], path + ("imp_l",), -pol, True, out)
        walk_atoms(ast[2], path + ("imp_r",), pol, ante, out)
    elif op in ("iff", "xor"):
        walk_atoms(ast[1], path + (op,), 0, ante, out)
        walk_atoms(ast[2], path + (op,), 0, ante, out)
    elif op in SYM:
        walk_atoms(ast[1], path + (op,), pol, ante, out)
        walk_atoms(ast[2], path + (op,), pol, ante, out)
    elif op == "atom":
        out.append({"name": ast[1], "args": ast[2], "pol": pol, "ante": ante, "depth": len(path),
                    "negated": path[-1:] == ("not",) if path else False})
    return out


class Formula:
    """Parsed, arity-normalised, alpha-renamed formula plus lexical-free structural statistics."""

    def __init__(self, fol: str):
        self.fol = fol
        pr = parse(fol or "")
        self.ok = pr.ok
        self.error = pr.error
        if not pr.ok:
            return
        self.ast = _alpha(normalize_arity_overloads(pr.ast))
        self.preds, cs = signature(self.ast)
        self.consts = sorted(cs)
        occ = walk_atoms(self.ast)
        self.occ = occ
        self.n_occ = Counter(o["name"] for o in occ)
        first = {}
        for i, o in enumerate(occ):
            first.setdefault(o["name"], i)
        self.first = {p: first.get(p, 0) / max(1, len(occ)) for p in self.preds}
        cfirst = {}
        for i, o in enumerate(occ):
            for t in o["args"]:
                if t[0] == "const":
                    cfirst.setdefault(t[1], i)
        self.cfirst = {c: cfirst.get(c, 0) / max(1, len(occ)) for c in self.consts}
        self.c_occ = Counter(t[1] for o in occ for t in o["args"] if t[0] == "const")
        self.vars = sorted({v for v in _bound_vars(self.ast)}, key=lambda s: int(s[1:]))
        self.K = len(self.vars)
        self.vax = {v: i for i, v in enumerate(self.vars)}
        # structural fingerprint (DC_fp): polarity profile, antecedent share, mean depth, quantified-slot share
        fp = {}
        for p in self.preds:
            os_ = [o for o in occ if o["name"] == p]
            n = max(1, len(os_))
            fp[p] = np.array([sum(o["pol"] > 0 for o in os_) / n, sum(o["pol"] < 0 for o in os_) / n,
                              sum(o["ante"] for o in os_) / n, sum(o["depth"] for o in os_) / n / 10.0,
                              sum(t[0] == "var" for o in os_ for t in o["args"]) / max(1, sum(len(o["args"]) for o in os_)),
                              self.n_occ[p] / max(1, len(occ)), self.first[p]])
        self.fp = fp
        self.n_quant = sum(1 for _ in _quants(self.ast))
        self._models = {}

    def quant_profile(self) -> tuple:
        return tuple(sorted(Counter(q for q in _quants(self.ast)).items()))


def _bound_vars(ast):
    if ast[0] in ("forall", "exists"):
        yield ast[1]
        yield from _bound_vars(ast[2])
    elif ast[0] == "not":
        yield from _bound_vars(ast[1])
    elif ast[0] in SYM:
        yield from _bound_vars(ast[1])
        yield from _bound_vars(ast[2])


def _quants(ast):
    if ast[0] in ("forall", "exists"):
        yield ast[0]
        yield from _quants(ast[2])
    elif ast[0] == "not":
        yield from _quants(ast[1])
    elif ast[0] in SYM:
        yield from _quants(ast[1])
        yield from _quants(ast[2])


# ============================================================================== vectorised evaluator
class Batch:
    """S structures over one domain size n: T[name] bool array (S,)+(n,)*arity; C[const] int array (S,)."""

    def __init__(self, n: int, S: int):
        self.n, self.S = n, S
        self.T: dict[str, np.ndarray] = {}
        self.C: dict[str, np.ndarray] = {}
        self._idx = {}

    def sidx(self, K):
        key = ("s", K)
        if key not in self._idx:
            self._idx[key] = np.arange(self.S).reshape((self.S,) + (1,) * K)
        return self._idx[key]

    def vidx(self, K, j):
        key = ("v", K, j)
        if key not in self._idx:
            shp = [1] * (K + 1)
            shp[j + 1] = self.n
            self._idx[key] = np.arange(self.n).reshape(shp)
        return self._idx[key]


def evaluate(F: Formula, B: Batch, nm: dict | None = None, cm: dict | None = None) -> np.ndarray:
    """Truth value of closed formula F on every structure of batch B. nm/cm rename predicates/constants
    (name -> key in B.T / B.C)."""
    nm = nm or {}
    cm = cm or {}
    K = F.K

    def term(t):
        if t[0] == "var":
            return B.vidx(K, F.vax[t[1]])
        return B.C[cm.get(t[1], t[1])].reshape((B.S,) + (1,) * K)

    def ev(a):
        op = a[0]
        if op == "atom":
            T = B.T[nm.get(a[1], a[1])]
            if not a[2]:
                return T.reshape((B.S,) + (1,) * K)
            return T[(B.sidx(K),) + tuple(term(t) for t in a[2])]
        if op == "eq":
            r = term(a[1]) == term(a[2])
            return np.logical_or(r, np.zeros((B.S,) + (1,) * K, bool))
        if op == "not":
            return ~ev(a[1])
        if op == "and":
            return ev(a[1]) & ev(a[2])
        if op == "or":
            return ev(a[1]) | ev(a[2])
        if op == "imp":
            return (~ev(a[1])) | ev(a[2])
        if op == "iff":
            return ev(a[1]) == ev(a[2])
        if op == "xor":
            return ev(a[1]) != ev(a[2])
        if op in ("forall", "exists"):
            x = ev(a[2])
            ax = 1 + F.vax[a[1]]
            if x.shape[ax] == 1:
                return x
            return x.all(axis=ax, keepdims=True) if op == "forall" else x.any(axis=ax, keepdims=True)
        raise ValueError(op)
    r = ev(F.ast)
    return np.broadcast_to(r, (B.S,) + r.shape[1:]).reshape(B.S, -1)[:, 0]


def random_batch(n: int, S: int, preds: dict, consts, rng: np.random.Generator) -> Batch:
    B = Batch(n, S)
    dens = rng.choice([0.2, 0.5, 0.8], size=S)
    for p, a in preds.items():
        B.T[p] = rng.random((S,) + (n,) * a) < dens.reshape((S,) + (1,) * a)
    for c in consts:
        B.C[c] = rng.integers(0, n, size=S)
    return B


def add_random(B: Batch, preds: dict, consts, rng: np.random.Generator) -> None:
    for p, a in preds.items():
        if p not in B.T:
            B.T[p] = rng.random((B.S,) + (B.n,) * a) < 0.5
    for c in consts:
        if c not in B.C:
            B.C[c] = rng.integers(0, B.n, size=B.S)


def solver_structures(F: Formula, n: int, k: int, positive: bool, seed: int, timeout_ms: int = 3000) -> list[dict]:
    """Up to k models of F (positive) or of ¬F over domain n via vendor grounding; returns [{T:{p:arr}, C:{c:int}}]."""
    cvars = {c: z3.Int(f"c#{c}") for c in F.consts}
    g = _Grounder(n, None, cvars)
    try:
        expr = g.g(F.ast, {})
    except (z3.Z3Exception, RecursionError):
        return []
    s = z3.Solver()
    s.set("timeout", timeout_ms)
    s.set("random_seed", seed)
    for v in cvars.values():
        s.add(v >= 0, v < n)
    s.add(expr if positive else z3.Not(expr))
    out = []
    atoms = list(g.atoms.items())
    rng = random.Random(seed)
    for _ in range(k):
        try:
            r = s.check()
        except z3.Z3Exception:
            break
        if r != z3.sat:
            break
        m = s.model()
        T = {p: np.zeros((n,) * a, bool) for p, a in F.preds.items()}
        vals = []
        for (name, args), b in atoms:
            v = z3.is_true(m.eval(b, model_completion=True))
            vals.append((b, v))
            if name in T and v:
                T[name][args] = True
        C = {c: m.eval(cv, model_completion=True).as_long() for c, cv in cvars.items()}
        out.append({"T": T, "C": C})
        # block a random subset of the assignment for diversity
        if not vals:
            break
        sub = rng.sample(vals, max(1, len(vals) // 3))
        s.add(z3.Or(*[b != z3.BoolVal(v) for b, v in sub]))
    return out


def stack_structs(structs: list[dict], n: int, preds: dict, consts) -> Batch | None:
    if not structs:
        return None
    B = Batch(n, len(structs))
    for p, a in preds.items():
        B.T[p] = np.stack([s["T"][p] if p in s["T"] else np.zeros((n,) * a, bool) for s in structs])
    for c in consts:
        B.C[c] = np.array([s["C"].get(c, 0) for s in structs])
    return B


def formula_structs(F: Formula, k: int, seed: int) -> dict:
    """cached per formula: {n: {"pos": [...], "neg": [...]}} for n in (2, 3)."""
    key = (k, seed)
    if key not in F._models:
        F._models[key] = {n: {"pos": solver_structures(F, n, k, True, seed + n),
                              "neg": solver_structures(F, n, k, False, seed + 10 + n)} for n in (2, 3)}
    return F._models[key]


# ============================================================================== maps
def _blocks(preds: dict) -> dict[int, list[str]]:
    g = defaultdict(list)
    for p, a in preds.items():
        g[a].append(p)
    return g


def _order_key(F: Formula, p: str):
    return (-F.n_occ.get(p, 0), F.first.get(p, 0.0), p)  # name only as the final deterministic tie-break


def _cost(A: Formula, B: Formula, a: str, b: str, order: str) -> float:
    if order == "fp":
        return float(np.abs(A.fp[a] - B.fp[b]).sum())
    return abs(A.n_occ[a] - B.n_occ[b]) / max(A.n_occ[a], B.n_occ[b], 1) + abs(A.first[a] - B.first[b])


def base_assignment(A: Formula, B: Formula, order: str) -> tuple[dict, dict]:
    """per arity block: min-cost (Hungarian) assignment B-pred -> A-pred; also constants."""
    from scipy.optimize import linear_sum_assignment
    ga, gb = _blocks(A.preds), _blocks(B.preds)
    m = {}
    for ar, bl in gb.items():
        al = ga.get(ar, [])
        if not al:
            continue
        bl = sorted(bl, key=lambda p: _order_key(B, p))
        al = sorted(al, key=lambda p: _order_key(A, p))
        cm = np.array([[_cost(A, B, a, b, order) for a in al] for b in bl])
        r, c = linear_sum_assignment(cm)
        for i, j in zip(r, c):
            m[bl[i]] = al[j]
    cmap = {}
    ca = sorted(A.consts, key=lambda c: (-A.c_occ[c], A.cfirst[c], c))
    cb = sorted(B.consts, key=lambda c: (-B.c_occ[c], B.cfirst[c], c))
    for x, y in zip(cb, ca):
        cmap[x] = y
    return m, cmap


def _coverage(B: Formula, m: dict) -> float:
    tot = sum(B.n_occ.values())
    return sum(B.n_occ[b] for b in m) / tot if tot else 1.0


def arity_profile(F: Formula) -> tuple:
    return tuple(sorted(Counter(F.preds.values()).items())) + (("c", len(F.consts)),)


def l1_maps(A: Formula, B: Formula, cap: int, order: str):
    """bijections (B -> A) of equal arity profiles. Exhaustive (sorted by distance from the base assignment) when the
    total is <= cap, otherwise the k-displacement neighbourhoods of the base assignment in increasing k."""
    if arity_profile(A) != arity_profile(B):
        return
    base, cbase = base_assignment(A, B, order)
    gb = _blocks(B.preds)
    blocks = [sorted(bl, key=lambda p: _order_key(B, p)) for _, bl in sorted(gb.items())]
    total = math.prod(math.factorial(len(b)) for b in blocks) * math.factorial(len(B.consts))
    cb = sorted(cbase)
    seen = set()
    n_out = 0

    def emit(m, cm):
        nonlocal n_out
        key = tuple(sorted(m.items())) + tuple(sorted(cm.items()))
        if key in seen:
            return False
        seen.add(key)
        n_out += 1
        return True

    if total <= cap:
        allm = []
        for perms in itertools.product(*[itertools.permutations([base[b] for b in bl]) for bl in blocks]):
            m = {}
            for bl, perm in zip(blocks, perms):
                m.update(dict(zip(bl, perm)))
            d = sum(m[b] != base[b] for b in m)
            allm.append((d, m))
        allm.sort(key=lambda x: x[0])
        cperms = [dict(zip(cb, p)) for p in itertools.permutations([cbase[c] for c in cb])] or [{}]
        cperms.sort(key=lambda cm: sum(cm[c] != cbase[c] for c in cm))
        for d, m in allm:
            for cm in cperms:
                if emit(m, cm):
                    yield m, cm
        return
    # neighbourhoods: transpositions, then 3-cycles, ... within blocks (constants kept at base)
    if emit(dict(base), dict(cbase)):
        yield dict(base), dict(cbase)
    flat = [(bi, b) for bi, bl in enumerate(blocks) for b in bl]
    for k in range(2, 8):
        for combo in itertools.combinations(range(len(flat)), k):
            bis = {flat[i][0] for i in combo}
            if len(bis) != 1:
                continue
            names = [flat[i][1] for i in combo]
            imgs = [base[b] for b in names]
            for perm in itertools.permutations(imgs):
                if any(p == base[b] for p, b in zip(perm, names)):
                    continue  # derangements only (exact k-displacement)
                m = dict(base)
                m.update(dict(zip(names, perm)))
                if emit(m, dict(cbase)):
                    yield m, dict(cbase)
                if n_out >= cap:
                    return


def l2_maps(A: Formula, B: Formula, cap: int, min_cov: float, order: str):
    """partial injective arity-preserving maps B -> A covering >= min_cov of B's predicate occurrences."""
    base, cbase = base_assignment(A, B, order)
    seen = set()
    n = 0

    def ok(m):
        return _coverage(B, m) >= min_cov - 1e-9

    def emit(m, cm):
        nonlocal n
        key = tuple(sorted(m.items())) + tuple(sorted(cm.items()))
        if key in seen or not ok(m):
            return False
        seen.add(key)
        n += 1
        return True

    if emit(dict(base), dict(cbase)):
        yield dict(base), dict(cbase)
    bs = sorted(B.preds, key=lambda p: _order_key(B, p))
    ga = _blocks(A.preds)
    # (i) single re-assignments (swap if the target is used)
    for b in bs:
        for a in sorted(ga.get(B.preds[b], []), key=lambda p: _order_key(A, p)):
            if base.get(b) == a:
                continue
            m = dict(base)
            inv = {v: k for k, v in m.items()}
            if a in inv:
                other = inv[a]
                if b in m:
                    m[other] = m[b]
                else:
                    del m[other]
            m[b] = a
            if emit(m, dict(cbase)):
                yield m, dict(cbase)
            if n >= cap:
                return
    # (ii) drop one / two mapped predicates (they become fresh)
    mapped = [b for b in bs if b in base]
    for k in (1, 2):
        for drop in itertools.combinations(mapped, k):
            m = {b: a for b, a in base.items() if b not in drop}
            if emit(m, dict(cbase)):
                yield m, dict(cbase)
            if n >= cap:
                return
    # (iii) pairs of re-assignments
    singles = []
    for b in bs:
        for a in sorted(ga.get(B.preds[b], []), key=lambda p: _order_key(A, p)):
            if base.get(b) != a:
                singles.append((b, a))
    for (b1, a1), (b2, a2) in itertools.combinations(singles, 2):
        if b1 == b2 or a1 == a2:
            continue
        m = {b: a for b, a in base.items() if a not in (a1, a2)}
        m[b1], m[b2] = a1, a2
        if emit(m, dict(cbase)):
            yield m, dict(cbase)
        if n >= cap:
            return


def l3_defsets(A: Formula, B: Formula, base: dict, cap: int, max_defs: int, max_lits: int):
    """definition sets {b: [(a, slots, False), ...]}: <= max_defs B-predicates, each defined as a conjunction of
    2..max_lits POSITIVE literals over A-predicates that are NOT in the image of the remaining map (A-predicates
    unmatched once the defined B-predicates are removed from the base map), each A-predicate used at most once per
    set. Rationale (fixed before any label, from the T0 toy tests): negated literals would let a definition absorb an
    exception ('Bird := Bird ∧ ¬Penguin'), and literals over still-mapped predicates let it absorb the consequent;
    both manufacture agreement. Positive granularity (TallMan := Tall ∧ Man) is kept; it is formula-only
    indistinguishable from a dropped positive restrictor (documented identifiability limit)."""
    bs = sorted(B.preds, key=lambda p: _order_key(B, p))
    targets = [b for b in bs if b not in base] + [b for b in bs if b in base]
    out = []

    def lits(b, free_a):
        ar = B.preds[b]
        L = []
        for a in free_a:
            ka = A.preds[a]
            if 0 < ka <= ar or (ka == 0 and ar == 0):
                for slots in itertools.permutations(range(ar), ka):
                    L.append((a, slots))
        return L

    def defs_for(b, free_a):
        L = lits(b, free_a)
        res = []
        for k in range(2, max_lits + 1):
            for combo in itertools.combinations(L, k):
                if len({c[0] for c in combo}) < k:
                    continue
                if not set(range(B.preds[b])) <= {s for c in combo for s in c[1]}:
                    continue  # every argument slot of b must be constrained
                res.append([(a, sl, False) for a, sl in combo])
        return res

    for b in targets:
        m = {x: a for x, a in base.items() if x != b}
        free_a = [a for a in sorted(A.preds, key=lambda p: _order_key(A, p)) if a not in set(m.values())]
        for d in defs_for(b, free_a):
            out.append({b: d})
            if len(out) >= cap:
                return out
    if max_defs >= 2:
        for b1, b2 in itertools.combinations(targets, 2):
            m = {x: a for x, a in base.items() if x not in (b1, b2)}
            free_a = [a for a in sorted(A.preds, key=lambda p: _order_key(A, p)) if a not in set(m.values())]
            for d1 in defs_for(b1, free_a):
                used = {x[0] for x in d1}
                for d2 in defs_for(b2, [a for a in free_a if a not in used]):
                    out.append({b1: d1, b2: d2})
                    if len(out) >= cap:
                        return out
    return out


# ============================================================================== AST transforms for z3
def rename_ast(ast, pm: dict, cm: dict, fresh_prefix: str = "~"):
    op = ast[0]
    if op in ("forall", "exists"):
        return (op, "B" + ast[1], rename_ast(ast[2], pm, cm, fresh_prefix))
    if op == "not":
        return ("not", rename_ast(ast[1], pm, cm, fresh_prefix))
    if op in SYM:
        return (op, rename_ast(ast[1], pm, cm, fresh_prefix), rename_ast(ast[2], pm, cm, fresh_prefix))

    def tt(t):
        if t[0] == "var":
            return ("var", "B" + t[1])
        return ("const", cm.get(t[1], fresh_prefix + t[1]))
    if op == "atom":
        return ("atom", pm.get(ast[1], fresh_prefix + ast[1]), tuple(tt(t) for t in ast[2]))
    if op == "eq":
        return ("eq", tt(ast[1]), tt(ast[2]))
    raise ValueError(op)


def substitute_defs(ast, defs: dict):
    """replace atoms of defined B-predicates (already renamed to '~b' or their image) by literal conjunctions.
    defs: {renamed_name: [(a, slots, neg), ...]}"""
    op = ast[0]
    if op in ("forall", "exists"):
        return (op, ast[1], substitute_defs(ast[2], defs))
    if op == "not":
        return ("not", substitute_defs(ast[1], defs))
    if op in SYM:
        return (op, substitute_defs(ast[1], defs), substitute_defs(ast[2], defs))
    if op == "atom" and ast[1] in defs:
        lits = []
        for a, slots, neg in defs[ast[1]]:
            at = ("atom", a, tuple(ast[2][s] for s in slots))
            lits.append(("not", at) if neg else at)
        r = lits[0]
        for l in lits[1:]:
            r = ("and", r, l)
        return r
    return ast


def z3_entails(F, G, preds: dict, consts: list, timeout_ms: int) -> str:
    """unbounded check F ⊨ G over an uninterpreted sort (vendor fol_equiv.unbounded_equiv construction)."""
    U = z3.DeclareSort("U")
    funcs = {p: (z3.Function(f"P_{p}", *([U] * a), z3.BoolSort()) if a > 0 else z3.Bool(f"P_{p}")) for p, a in preds.items()}
    cs = {c: z3.Const(f"K_{c}", U) for c in consts}

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
        if op in ("and", "or", "imp", "iff", "xor"):
            a, b = tr(node[1], env), tr(node[2], env)
            if op == "iff":
                return a == b
            return {"and": z3.And, "or": z3.Or, "imp": z3.Implies, "xor": z3.Xor}[op](a, b)
        if op in ("forall", "exists"):
            v = z3.Const(f"v_{node[1]}_{id(node)}", U)
            body = tr(node[2], {**env, node[1]: v})
            return z3.ForAll([v], body) if op == "forall" else z3.Exists([v], body)
        raise ValueError(op)
    try:
        s = z3.Solver()
        s.set("timeout", timeout_ms)
        s.add(tr(F, {}), z3.Not(tr(G, {})))
        r = s.check()
        return "unsat" if r == z3.unsat else ("sat" if r == z3.sat else "unknown")
    except z3.Z3Exception:
        return "unknown"


def _sig(ast):
    return signature(ast)


# ============================================================================== pair checking
class PairCtx:
    """Structures for one ordered pair (A, B): A-side batches (models/countermodels of A + random, with fresh tensors
    for every B symbol) and B-side batches (models/countermodels of B, with random tensors for A symbols)."""

    def __init__(self, A: Formula, B: Formula, limits: dict, seed: int = 0):
        self.A, self.B, self.L = A, B, limits
        rng = np.random.default_rng(seed)
        fresh_b = {"~" + b: a for b, a in B.preds.items()}
        fresh_bc = ["~" + c for c in B.consts]
        fresh_a = {"~" + a: k for a, k in A.preds.items()}
        fresh_ac = ["~" + c for c in A.consts]
        k = limits["n_models"]
        sa, sb = formula_structs(A, k, seed), formula_structs(B, k, seed + 1)
        self.abatches, self.bbatches = [], []
        for n in (2, 3):
            parts = []
            for kind in ("pos", "neg"):
                bt = stack_structs(sa[n][kind], n, A.preds, A.consts)
                if bt is not None:
                    parts.append(bt)
            rb = random_batch(n, limits["n_random"] // 2, A.preds, A.consts, rng)
            parts.append(rb)
            for bt in parts:
                add_random(bt, fresh_b, fresh_bc, rng)
                self.abatches.append(bt)
            for kind in ("pos", "neg"):
                bt = stack_structs(sb[n][kind], n, B.preds, B.consts)
                if bt is not None:
                    add_random(bt, fresh_a, fresh_ac, rng)
                    self.bbatches.append(bt)
        self.aval = [evaluate(A, bt) for bt in self.abatches]
        self.bval = [evaluate(B, bt) for bt in self.bbatches]
        self.rng = rng

    def filter(self, m: dict, cm: dict, defs: dict | None = None) -> tuple[bool, bool, bool]:
        """(A⊨B alive, B⊨A alive, joint model witnessed) under map m (B->A), constant map cm, optional L3 defs."""
        A, B = self.A, self.B
        nmB = {b: m.get(b, "~" + b) for b in B.preds}
        cmB = {c: cm.get(c, "~" + c) for c in B.consts}
        f2g = g2f = True
        joint = False
        for bt, av in zip(self.abatches, self.aval):
            if defs:
                for b, lits in defs.items():
                    key = "#def:" + b + ":" + repr(lits)
                    if key not in bt.T:
                        ar = B.preds[b]
                        acc = np.ones((bt.S,) + (bt.n,) * ar, bool)
                        for a, slots, neg in lits:
                            Ta = bt.T[a]
                            # place A-literal axes at the given B slots
                            idx = [np.arange(bt.S).reshape((bt.S,) + (1,) * ar)]
                            for s in slots:
                                shp = [1] * (ar + 1)
                                shp[s + 1] = bt.n
                                idx.append(np.arange(bt.n).reshape(shp))
                            v = Ta[tuple(idx)] if slots else Ta.reshape((bt.S,) + (1,) * ar)
                            acc = acc & (~v if neg else v)
                        bt.T[key] = acc
                    nmB[b] = key
            bv = evaluate(B, bt, nmB, cmB)
            if (av & ~bv).any():
                f2g = False
            if (bv & ~av).any():
                g2f = False
            if (av & bv).any():
                joint = True
            if not f2g and not g2f and joint:
                return f2g, g2f, joint
        if not defs:
            inv = {a: b for b, a in m.items()}
            cinv = {a: b for b, a in cm.items()}
            nmA = {a: inv.get(a, "~" + a) for a in A.preds}
            cmA = {c: cinv.get(c, "~" + c) for c in A.consts}
            for bt, bv in zip(self.bbatches, self.bval):
                av = evaluate(A, bt, nmA, cmA)
                if (av & ~bv).any():
                    f2g = False
                if (bv & ~av).any():
                    g2f = False
                if (av & bv).any():
                    joint = True
                if not f2g and not g2f and joint:
                    break
        return f2g, g2f, joint

    def z3_decide(self, m: dict, cm: dict, defs: dict | None, f2g: bool, g2f: bool, joint: bool,
                  deadline: float) -> str:
        A, B, L = self.A, self.B, self.L
        Bp = rename_ast(B.ast, m, cm)
        if defs:
            Bp = substitute_defs(Bp, {m.get(b, "~" + b): lits for b, lits in defs.items()})
        pa, ca = _sig(A.ast)
        pb, cb = _sig(Bp)
        preds = {**pa, **pb}
        consts = sorted(set(ca) | set(cb))
        ns = L["domains"]
        tmo = L["z3_timeout_ms"]
        res = {}
        for key, alive, mode in (("f2g", f2g, "f2g"), ("g2f", g2f, "g2f")):
            if not alive:
                res[key] = False
                continue
            if time.time() > deadline:
                return "UNKNOWN"
            r, _ = bounded_check(A.ast, Bp, consts, {}, mode, ns=ns, timeout_ms=tmo, deadline=deadline)
            if r == "countermodel":
                res[key] = False
            elif r == "timeout":
                return "UNKNOWN"
            else:
                ub = z3_entails(A.ast, Bp, preds, consts, tmo) if mode == "f2g" else z3_entails(Bp, A.ast, preds, consts, tmo)
                res[key] = ub != "sat"
        if res["f2g"] and res["g2f"]:
            return "EQUIV"
        if res["f2g"]:
            return "STRONGER"
        if res["g2f"]:
            return "WEAKER"
        if joint:
            return "COMPATIBLE-INCOMPARABLE"
        # joint satisfiability check (bounded): SAT(A ∧ B') ?
        for n in ns:
            if time.time() > deadline:
                return "UNKNOWN"
            cv = {c: z3.Int(f"c#{c}") for c in consts}
            s = z3.Solver()
            s.set("timeout", tmo)
            try:
                fa = _Grounder(n, None, cv).g(A.ast, {})
                fb = _Grounder(n, None, cv).g(Bp, {})
            except (z3.Z3Exception, RecursionError):
                return "UNKNOWN"
            for v in cv.values():
                s.add(v >= 0, v < n)
            s.add(fa, fb)
            r = s.check()
            if r == z3.sat:
                return "COMPATIBLE-INCOMPARABLE"
            if r == z3.unknown:
                return "UNKNOWN"
        return "CONTRADICTORY"


def _better(r1: str, r2: str | None) -> bool:
    if r2 is None or r2 in ("UNKNOWN",):
        return r1 not in ("UNKNOWN",)
    return REL_ORDER.get(r1, 0) > REL_ORDER.get(r2, 0)


def align_pair(A: Formula, B: Formula, limits: dict | None = None):
    """MEASURES: the lexical-free vocabulary correspondences under which B can be read in A's vocabulary.
    Yields (level, map B->A, const map, defs) in level order L1 -> L2 -> L3 (defs only at L3)."""
    L = {**DEFAULT_LIMITS, **(limits or {})}
    order = L["order"]
    for m, cm in l1_maps(A, B, L["l1_cap"], order):
        yield 1, m, cm, None
    for m, cm in l2_maps(A, B, L["l2_cap"], L["l2_min_cov"], order):
        yield 2, m, cm, None
    base, cbase = base_assignment(A, B, order)
    if _coverage(B, base) < L["l2_min_cov"] - 1e-9:
        return  # L3 builds on an L2-admissible base map; otherwise the pair is UNALIGNABLE
    for d in l3_defsets(A, B, base, L["l3_cap"], L["l3_max_defs"], L["l3_max_lits"]):
        m = {b: a for b, a in base.items() if b not in d}
        yield 3, m, dict(cbase), d


def _search(A: Formula, B: Formula, L: dict, deadline: float, seed: int, levels=(1, 2, 3)) -> dict:
    ctx = PairCtx(A, B, L, seed)
    best = {"relation": None, "level": None, "map": None, "cmap": None, "defs": None}
    best12 = {"relation": None, "level": None, "map": None}
    n_maps = Counter()
    n_z3 = 0
    any_map = False
    all_unknown = True
    timed_out = False
    tried_keys = set()
    for level, m, cm, defs in align_pair(A, B, L):
        if level not in levels:
            continue
        if time.time() > deadline:
            timed_out = True
            break
        any_map = True
        n_maps[level] += 1
        f2g, g2f, joint = ctx.filter(m, cm, defs)
        cand = "EQUIV" if (f2g and g2f) else ("STRONGER" if f2g else ("WEAKER" if g2f else
                                                                    ("COMPATIBLE-INCOMPARABLE" if joint else "CONTRADICTORY?")))
        # only call z3 when the filter outcome could improve on the current best
        opt = {"EQUIV": 4, "STRONGER": 3, "WEAKER": 3, "COMPATIBLE-INCOMPARABLE": 2, "CONTRADICTORY?": 1}[cand]
        if best["relation"] is not None and opt <= REL_ORDER.get(best["relation"], 0):
            all_unknown = False if best["relation"] else all_unknown
            continue
        if cand == "COMPATIBLE-INCOMPARABLE":
            rel = cand  # witnessed joint model and both directions refuted: sound without z3
        else:
            key = (level, tuple(sorted(m.items())), repr(defs), cand)
            if key in tried_keys:
                continue
            tried_keys.add(key)
            if n_z3 >= L["max_z3_maps"]:
                continue
            n_z3 += 1
            rel = ctx.z3_decide(m, cm, defs, f2g, g2f, joint, deadline)
        if rel != "UNKNOWN":
            all_unknown = False
        if level in (1, 2) and _better(rel, best12["relation"]):
            best12 = {"relation": rel, "level": level, "map": dict(m)}
        if _better(rel, best["relation"]):
            best = {"relation": rel, "level": level, "map": dict(m), "cmap": dict(cm),
                    "defs": {k: [list(x) for x in v] for k, v in defs.items()} if defs else None}
            if rel == "EQUIV":
                break
    if not any_map:
        best["relation"] = "UNALIGNABLE"
    elif best["relation"] is None:
        best["relation"] = "UNKNOWN"
    b12 = best12 if best12["relation"] is not None else None
    any12 = n_maps.get(1, 0) + n_maps.get(2, 0) > 0
    best.update(n_maps=dict(n_maps), n_z3=n_z3, timed_out=timed_out,
                relation_l12=(b12["relation"] if b12 else ("UNALIGNABLE" if not any12 and not timed_out else "UNKNOWN")),
                level_l12=b12["level"] if b12 else None, map_l12=b12["map"] if b12 else None)
    return best


def pair_relation(fol_a: str | Formula, fol_b: str | Formula, limits: dict | None = None, seed: int = 0) -> dict:
    """MEASURES: the logical order between A and B read in A's vocabulary under the most informative lexical-free
    alignment: EQUIV / STRONGER (A ⊨ B only) / WEAKER (B ⊨ A only) / COMPATIBLE-INCOMPARABLE / CONTRADICTORY /
    UNALIGNABLE (no arity-preserving map) / UNKNOWN (every map timed out). L3 is tried in both directions."""
    L = {**DEFAULT_LIMITS, **(limits or {})}
    t0 = time.time()
    A = fol_a if isinstance(fol_a, Formula) else Formula(fol_a)
    B = fol_b if isinstance(fol_b, Formula) else Formula(fol_b)
    if not (A.ok and B.ok):
        return {"relation": "UNPARSEABLE", "level": None, "seconds": 0.0}
    deadline = t0 + L["pair_seconds"]
    # L1 + L2 + L3 (B defined over A)
    res = _search(A, B, L, deadline, seed)
    res["direction"] = "B_in_A"
    if res["relation"] != "EQUIV" and time.time() < deadline:
        # L3 reverse: A's predicates defined over B's vocabulary (granularity in the other direction)
        r2 = _search(B, A, L, deadline, seed + 7, levels=(3,))
        if r2["relation"] not in ("UNKNOWN", "UNALIGNABLE", None):
            rel2 = INVERSE.get(r2["relation"], r2["relation"])
            if _better(rel2, res["relation"] if res["relation"] not in ("UNALIGNABLE",) else None):
                r2["relation"] = rel2
                r2["direction"] = "A_in_B"
                r2["n_maps_fwd"] = res.get("n_maps")
                for k in ("relation_l12", "level_l12", "map_l12"):
                    r2[k] = res.get(k)
                res = r2
    res["seconds"] = round(time.time() - t0, 3)
    return res
