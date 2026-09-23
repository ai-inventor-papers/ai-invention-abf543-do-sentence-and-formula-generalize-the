"""R1 — canonical, name-blind restricted-quantifier normal form + canonical mutants and worlds.

canon(F) maps logically equivalent surface variants (conjunct reorder, De Morgan, contrapositive, A→B vs ¬A∨B,
¬(A↔B) vs A⊕B, bound-variable names, prenexing) to ONE formula, so that the TVJT world generator
(mutants → z3 distinguishing worlds) sees identical input for equivalent rewrites. Every canonical form is
verified bounded-equivalent (n ≤ 4) to its source; otherwise the source is used and `canon_fallback` is set.

canonical_worlds(F) runs the iter-1 mutation operators on canon(F) with a NAME-BLIND seed and on a
name-normalised copy (predicates → Q1..Qk, constants → k1..km in canonical first-occurrence order), so
predicate renaming (RENAME) yields the same worlds up to the renaming. Worlds are deduplicated by an
isomorphism key and presented in canonical key order.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import sys
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "third_party" / "armB" / "src"))

import z3  # noqa: E402

import fol_core as fc  # noqa: E402
from mutants import OPERATORS, NotPrenexable, make_mutant, prenex, build_prefix  # noqa: E402

def find_world(F, M, prefer: int, nmax: int = 4, timeout_ms: int = 3000) -> dict | None:
    """iter-1 tvjt.find_world with a FIXED Grounder tag. iter-1 tagged every Grounder with a global counter
    (g0, g1, …), so z3 saw differently named atoms on every call and broke ties between equally minimal worlds
    differently (non-deterministic worlds for the same formula). A fixed tag gives identical z3 terms on every
    call and in every process. z3's main context also keeps solver state across calls, which again changes
    tie-breaking with call history, so every call starts from a FRESH main context."""
    z3.z3._main_ctx = None  # fresh context: result depends only on (F, M, prefer)
    z3.set_param("smt.random_seed", 0)
    z3.set_param("sat.random_seed", 0)
    consts = list(dict.fromkeys(fc.constants(F) + fc.constants(M)))
    for una in (True, False):
        start = max(1, len(consts)) if una else 1
        for n in range(start, nmax + 1):
            try:
                g = fc.Grounder(n, consts, una=una, tag="w")
            except ValueError:
                continue
            fF, fM = g.g(F), g.g(M)
            for d in ([prefer, 1 - prefer]):
                opt = z3.Optimize()
                opt.set("timeout", timeout_ms)
                opt.add(*g.side)
                opt.add(z3.And(fF, z3.Not(fM)) if d == 0 else z3.And(z3.Not(fF), fM))
                for key in sorted(g.atoms):
                    opt.add_soft(z3.Not(g.atoms[key]), 1)
                if opt.check() != z3.sat:
                    continue
                mdl = opt.model()
                true_atoms = sorted([list(k) for k, v in g.atoms.items()
                                     if z3.is_true(mdl.eval(v, model_completion=True))], key=lambda x: (x[0], x[1]))
                true_atoms = [[p, list(t)] for p, t in true_atoms]
                cmap = ({c: i for i, c in enumerate(consts)} if una else
                        {c: mdl.eval(v, model_completion=True).as_long() for c, v in g.C.items()})
                w = {"n": n, "una": una, "consts": cmap, "true_atoms": true_atoms, "F_value": d == 0,
                     "M_value": d != 0}
                interp = {"P": {}, "C": cmap}
                for p, t in true_atoms:
                    interp["P"].setdefault(p, set()).add(tuple(t))
                if fc.py_eval(F, interp, n) != w["F_value"] or fc.py_eval(M, interp, n) != w["M_value"]:
                    continue
                return w
    return None

CANON_VERSION = "canon_v2_detworlds"
VARS = ["x", "y", "z", "w", "u", "v", "s", "t"]


# ------------------------------------------------------------------------------------------ helpers
def _is_lit(n) -> bool:
    return n[0] in ("atom", "eq") or (n[0] == "not" and n[1][0] in ("atom", "eq"))


def _neg(n):
    return n[1] if n[0] == "not" else ("not", n)


def _mk(kind, parts):
    """n-ary and/or with flattening; singleton collapses."""
    out = []
    for p in parts:
        if p[0] == kind:
            out.extend(p[1:])
        else:
            out.append(p)
    # drop exact duplicates (idempotence A∧A ≡ A), keep first
    ded = []
    for p in out:
        if p not in ded:
            ded.append(p)
    return ded[0] if len(ded) == 1 else (kind,) + tuple(ded)


def size(n) -> int:
    if n[0] in ("atom", "eq"):
        return 1
    if n[0] in ("forall", "exists"):
        return 1 + size(n[2])
    return 1 + sum(size(a) for a in n[1:])


# ------------------------------------------------------------------------------ 1+2: NNF with ↔/⊕ parity
def nnf(n, positive: bool = True):
    """Negation normal form. ↔/⊕ are kept (no blow-up); negation above them flips ↔↔⊕, and negated
    operands inside them are un-negated with a parity flip, so ¬(A↔B), A⊕B, ¬A↔B map to one form."""
    k = n[0]
    if k in ("atom", "eq"):
        return n if positive else ("not", n)
    if k == "not":
        return nnf(n[1], not positive)
    if k in ("and", "or"):
        kind = k if positive else {"and": "or", "or": "and"}[k]
        return _mk(kind, [nnf(a, positive) for a in n[1:]])
    if k == "imp":  # A→B ≡ ¬A ∨ B ; ¬(A→B) ≡ A ∧ ¬B
        if positive:
            return _mk("or", [nnf(n[1], False), nnf(n[2], True)])
        return _mk("and", [nnf(n[1], True), nnf(n[2], False)])
    if k in ("forall", "exists"):
        q = k if positive else {"forall": "exists", "exists": "forall"}[k]
        return (q, n[1], nnf(n[2], positive))
    if k in ("iff", "xor"):
        par = (k == "xor") ^ (not positive)  # True → xor
        ops = []
        for a in (n[1], n[2]):
            # A⊕B ≡ ¬A↔B: choose each operand's sign canonically (smaller sort key), absorbing it in the parity
            p, q = nnf(a, True), nnf(a, False)
            if _sort_key(sort_tree(restrict(q))) < _sort_key(sort_tree(restrict(p))):
                ops.append(q)
                par = not par
            else:
                ops.append(p)
        return ("xor" if par else "iff", ops[0], ops[1])
    raise ValueError(k)


# ------------------------------------------------------------------ 3: restricted-implication form
def restrict(n):
    """Bottom-up: every disjunction that has negative-literal disjuncts becomes
    (∧ of their positive forms) → (∨ of the rest). All-negative: the consequent is the last ¬literal in
    skeleton order. Conjunction/quantifier structure is otherwise preserved."""
    k = n[0]
    if k in ("atom", "eq"):
        return n
    if k == "not":
        return n  # NNF: only literals are negated
    if k in ("forall", "exists"):
        return (k, n[1], restrict(n[2]))
    if k in ("iff", "xor"):
        return (k, restrict(n[1]), restrict(n[2]))
    if k == "and":
        return _mk("and", [restrict(a) for a in n[1:]])
    if k == "or":
        kids = [restrict(a) for a in n[1:]]
        # a kid that became an implication (inner disjunction) is itself a disjunction: re-flatten
        flat = []
        for c in kids:
            if c[0] == "imp":
                flat.append(("__neg_block", c[1]))
                flat.extend(c[2][1:] if c[2][0] == "or" else [c[2]])
            else:
                flat.append(c)
        negs, rest = [], []
        for c in flat:
            if c[0] == "__neg_block":
                negs.extend(c[1][1:] if c[1][0] == "and" else [c[1]])
            elif c[0] == "not":
                negs.append(c[1])
            else:
                rest.append(c)
        if not negs:
            return _mk("or", rest)
        if not rest:  # all negative: keep the last (skeleton order) as consequent ¬literal
            negs = sorted(negs, key=_sort_key)
            rest = [("not", negs[-1])]
            negs = negs[:-1]
            if not negs:
                return rest[0]
        return ("imp", _mk("and", negs), _mk("or", rest))
    raise ValueError(k)


# ------------------------------------------------------------------------ 5: name-blind sorting
def skel(n) -> str:
    """Name-blind skeleton: predicates → P/arity, constants → c, variables → v."""
    k = n[0]
    if k == "atom":
        return f"P{len(n[2])}(" + ",".join("v" if t[0] == "v" else "c" for t in n[2]) + ")"
    if k == "eq":
        return "EQ(" + ",".join("v" if t[0] == "v" else "c" for t in n[1:]) + ")"
    if k == "not":
        return "~" + skel(n[1])
    if k in ("forall", "exists"):
        return ("A" if k == "forall" else "E") + "." + skel(n[2])
    return k + "[" + ";".join(skel(a) for a in n[1:]) + "]"


def _sort_key(n):
    return (skel(n), fc.to_str(n))


def sort_tree(n):
    k = n[0]
    if k in ("atom", "eq"):
        return n
    if k == "not":
        return ("not", sort_tree(n[1]))
    if k in ("forall", "exists"):
        return (k, n[1], sort_tree(n[2]))
    kids = [sort_tree(a) for a in n[1:]]
    if k in ("and", "or", "iff", "xor"):
        kids = sorted(kids, key=_sort_key)
        if k in ("and", "or"):
            return _mk(k, kids)
        return (k,) + tuple(kids)
    return (k,) + tuple(kids)  # imp: ordered


# ------------------------------------------------------------------------- 6: alpha renaming
def alpha(n):
    names = iter(VARS + [f"x{i}" for i in range(1, 50)])
    mp: dict = {}

    def rec(m, env):
        k = m[0]
        if k == "atom":
            return ("atom", m[1], tuple(("v", env[t[1]]) if t[0] == "v" and t[1] in env else t for t in m[2]))
        if k == "eq":
            return ("eq",) + tuple(("v", env[t[1]]) if t[0] == "v" and t[1] in env else t for t in m[1:])
        if k in ("forall", "exists"):
            nv = next(names)
            return (k, nv, rec(m[2], {**env, m[1]: nv}))
        return (k,) + tuple(rec(a, env) for a in m[1:])
    return rec(n, mp)


def _clean_vacuous(n):
    """Drop quantifiers whose variable does not occur in the body (∀x A ≡ A on non-empty domains)."""
    k = n[0]
    if k in ("atom", "eq"):
        return n
    if k in ("forall", "exists"):
        body = _clean_vacuous(n[2])
        from mutants import free_vars
        return (k, n[1], body) if n[1] in free_vars(body) else body
    return (k,) + tuple(_clean_vacuous(a) for a in n[1:])


# ---------------------------------------------------------------------------------------- canon
@lru_cache(maxsize=100000)
def _canon_cached(fol_str: str) -> tuple:
    F = fc.parse(fol_str)
    return canon_ast(F)


def canon_ast(F) -> tuple:
    """Returns (canonical_ast, info). info: {'fallback': reason|None, 'prenex': bool}."""
    info = {"fallback": None, "prenex": False}
    try:
        G = nnf(F)
        G = restrict(G)
        G = sort_tree(G)
        G = alpha(G)
        try:
            pre, mat = prenex(G)
            G2 = build_prefix(pre, mat)
            info["prenex"] = True
        except (NotPrenexable, ValueError, RecursionError):
            G2 = G
            info["fallback"] = "not_prenexable"
        G2 = _clean_vacuous(G2)
        # re-normalise the matrix after prenexing (pnf may re-introduce ¬ over literals only) and re-sort
        for _ in range(3):
            G3 = alpha(_resort_matrix(G2))
            if G3 == G2:
                break
            G2 = G3
    except (RecursionError, ValueError) as e:
        info["fallback"] = f"error:{e!r}"[:80]
        return F, info
    if size(G2) > 3 * size(F):
        info["fallback"] = "size_guard"
        return F, info
    try:
        r = fc.bounded_equiv(G2, F, nmax=4, timeout_ms=5000)
    except Exception as e:  # noqa: BLE001 - z3 failure → fallback, recorded
        r = f"error:{e!r}"[:60]
    if r != "equiv":
        info["fallback"] = f"verify:{r}"
        return F, info
    return G2, info


def _resort_matrix(G):
    """Sort operands below a quantifier prefix, keeping the prefix order (meaningful)."""
    prefix = []
    m = G
    while m[0] in ("forall", "exists"):
        prefix.append((m[0], m[1]))
        m = m[2]
    m = sort_tree(restrict(nnf(m)))
    return build_prefix(prefix, m)


def canon(fol_str: str) -> str:
    """Canonical FOL string (FOLIO-unicode) of `fol_str`; equivalent surface variants map to one string."""
    G, _ = _canon_cached(fol_str)
    return fc.to_str(G)


def canon_info(fol_str: str) -> dict:
    G, info = _canon_cached(fol_str)
    return {"canon": fc.to_str(G), "skeleton": skel(G), **info,
            "canon_seed": hashlib.sha1(skel(G).encode()).hexdigest()[:16]}


# ------------------------------------------------------------------------- name normalisation
def name_normalise(G) -> tuple:
    """Rename predicates → Q1.., constants → k1.. in canonical pre-order of first occurrence.
    Returns (G_norm, pmap_back, cmap_back)."""
    from mutants import preorder
    pm, cm = {}, {}
    for _, m in preorder(G):
        if m[0] == "atom":
            if m[1] not in pm:
                pm[m[1]] = f"Q{len(pm) + 1}"
            for t in m[2]:
                if t[0] == "c" and t[1] not in cm:
                    cm[t[1]] = f"k{len(cm) + 1}"
        elif m[0] == "eq":
            for t in m[1:]:
                if t[0] == "c" and t[1] not in cm:
                    cm[t[1]] = f"k{len(cm) + 1}"
    Gn = fc.rename(G, pm, cm)
    return Gn, {v: k for k, v in pm.items()}, {v: k for k, v in cm.items()}


# ----------------------------------------------------------------------------- world keys
def world_key(w: dict) -> str:
    """Isomorphism-invariant key: lexicographic minimum over element permutations of
    (sorted true atoms, constant → element map). Uses the predicate/constant names inside w."""
    n = w["n"]
    best = None
    atoms = [(p, tuple(t)) for p, t in w["true_atoms"]]
    consts = sorted(w["consts"].items())
    for perm in itertools.permutations(range(n)):
        a = sorted((p, tuple(perm[e] for e in t)) for p, t in atoms)
        c = [(k, perm[e]) for k, e in consts]
        s = json.dumps([n, a, c])
        if best is None or s < best:
            best = s
    return best


def _map_world_names(w: dict, pback: dict, cback: dict) -> dict:
    out = dict(w)
    out["true_atoms"] = [[pback.get(p, p), list(t)] for p, t in w["true_atoms"]]
    out["consts"] = {cback.get(c, c): e for c, e in w["consts"].items()}
    return out


def canonical_worlds(fol_str: str, max_worlds: int = 12, nmax: int = 4) -> dict:
    """Canonical distinguishing worlds of F. Returns {'canon','canon_seed','fallback','worlds':[...],
    'worlds_norm_keys':[...]} where each world has op, variant, F_value, n, true_atoms (real names), consts,
    key (real-name iso key) and key_norm (name-normalised iso key, for RENAME comparisons)."""
    z3.set_param("smt.random_seed", 0)
    z3.set_param("sat.random_seed", 0)
    G, info = _canon_cached(fol_str)
    seed = hashlib.sha1(skel(G).encode()).hexdigest()[:16]
    Gn, pback, cback = name_normalise(G)
    jobs = []
    for op in OPERATORS:
        if op == "CARD":
            jobs += [("CARD", "two"), ("CARD", "unique")]
        else:
            jobs.append((op, None))
    worlds, seen_mut, seen_key = [], set(), set()
    for op, var in jobs:
        if len(worlds) >= max_worlds:
            break
        m = make_mutant(Gn, op, seed, variant=var)
        if not m.get("kept"):
            continue
        ms = fc.to_str(m["ast"])
        if ms in seen_mut:
            continue
        seen_mut.add(ms)
        w = find_world(Gn, m["ast"], prefer=0, nmax=nmax)
        if w is None:
            continue
        kn = world_key(w)
        if kn in seen_key:
            continue
        seen_key.add(kn)
        wr = _map_world_names(w, pback, cback)
        wr.update({"op": op, "variant": var, "key_norm": kn, "key": world_key(wr),
                   "mutant_fol_norm": ms})
        worlds.append(wr)
    worlds.sort(key=lambda x: x["key_norm"])
    return {"canon": fc.to_str(G), "canon_seed": seed, "fallback": info["fallback"], "worlds": worlds}
