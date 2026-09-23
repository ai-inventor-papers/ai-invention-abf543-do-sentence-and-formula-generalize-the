"""Typed mutation operators (known error types) and meaning-preserving rewrites over fol_core ASTs.

Every operator enumerates its applicable sites in pre-order; sites are tried in a seeded order
(rng = Random(sha1(seed_key + op))) and the first site whose mutant is NOT bounded-equivalent (n<=4)
to the source under the identity map is kept. Rewrites are kept only if bounded-equivalent.
"""
from __future__ import annotations

import os as _os
from pathlib import Path as _Path

_os.environ.setdefault("NLTK_DATA", str(_Path(__file__).resolve().parents[1] / "nltk_data"))

import hashlib
import random
import re
from typing import Callable, Iterator

from fol_core import bounded_equiv, constants, predicates, rename, to_str

OPERATORS = ["NEG", "QUANT", "IMPL_REV", "DROP_CONJ", "ADD_CONJ", "ARG_SWAP", "AND_OR", "SCOPE_SWAP", "MERGE", "CARD"]
OP_FAMILY = {"NEG": "negation/polarity", "QUANT": "quantifier", "SCOPE_SWAP": "quantifier-scope",
             "CARD": "quantifier-cardinality", "IMPL_REV": "implication-direction", "DROP_CONJ": "dropped-condition",
             "ADD_CONJ": "added-condition", "ARG_SWAP": "swapped-arguments", "AND_OR": "connective",
             "MERGE": "conflated-concepts"}
REWRITES = ["RENAME", "REORDER", "CONTRAPOSITIVE", "DEMORGAN", "PRENEX"]


def rng_for(key: str, op: str) -> random.Random:
    return random.Random(int(hashlib.sha1(f"{key}|{op}".encode()).hexdigest()[:12], 16))


# ----------------------------------------------------------------------------------------- tree nav
def children(n) -> list:
    if n[0] in ("atom", "eq"):
        return []
    if n[0] in ("forall", "exists"):
        return [n[2]]
    return list(n[1:])


def preorder(n, path=()) -> Iterator[tuple[tuple, tuple]]:
    yield path, n
    for i, c in enumerate(children(n)):
        yield from preorder(c, path + (i,))


def get(n, path):
    for i in path:
        n = children(n)[i]
    return n


def replace(n, path, new):
    if not path:
        return new
    i = path[0]
    if n[0] in ("forall", "exists"):
        return (n[0], n[1], replace(n[2], path[1:], new))
    kids = list(n[1:])
    kids[i] = replace(kids[i], path[1:], new)
    return (n[0],) + tuple(kids)


def neg(x):
    return x[1] if x[0] == "not" else ("not", x)


def mk_and(parts):
    parts = [p for q in parts for p in (q[1:] if q[0] == "and" else (q,))]
    return parts[0] if len(parts) == 1 else ("and",) + tuple(parts)


def all_vars(n) -> set[str]:
    out = set()
    for _, m in preorder(n):
        if m[0] in ("forall", "exists"):
            out.add(m[1])
        elif m[0] == "atom":
            out.update(t[1] for t in m[2] if t[0] == "v")
        elif m[0] == "eq":
            out.update(t[1] for t in m[1:] if t[0] == "v")
    return out


def fresh_var(used: set[str]) -> str:
    for v in ["y", "z", "w", "u", "v", "t", "s"] + [f"x{i}" for i in range(1, 50)]:
        if v not in used:
            return v
    raise ValueError("no fresh var")


def subst_var(n, old: str, new: str):
    """Replace free occurrences of variable old by variable new."""
    k = n[0]
    if k == "atom":
        return ("atom", n[1], tuple(("v", new) if t == ("v", old) else t for t in n[2]))
    if k == "eq":
        return ("eq",) + tuple(("v", new) if t == ("v", old) else t for t in n[1:])
    if k in ("forall", "exists"):
        if n[1] == old:
            return n
        return (k, n[1], subst_var(n[2], old, new))
    return (k,) + tuple(subst_var(a, old, new) for a in n[1:])


def free_vars(n, bound=frozenset()) -> set[str]:
    k = n[0]
    if k == "atom":
        return {t[1] for t in n[2] if t[0] == "v" and t[1] not in bound}
    if k == "eq":
        return {t[1] for t in n[1:] if t[0] == "v" and t[1] not in bound}
    if k in ("forall", "exists"):
        return free_vars(n[2], bound | {n[1]})
    out = set()
    for a in n[1:]:
        out |= free_vars(a, bound)
    return out


def has_quant(n) -> bool:
    return any(m[0] in ("forall", "exists") for _, m in preorder(n))


# ----------------------------------------------------------------------------------------- prenex
class NotPrenexable(Exception):
    pass


def pnf(n, used: set[str]) -> tuple[list, tuple]:
    k = n[0]
    if k in ("atom", "eq"):
        return [], n
    if k == "not":
        p, m = pnf(n[1], used)
        return [("exists" if q == "forall" else "forall", v) for q, v in p], neg(m)
    if k in ("forall", "exists"):
        v, body = n[1], n[2]
        if v in used:
            nv = fresh_var(used | all_vars(n))
            body = subst_var(body, v, nv)
            v = nv
        used.add(v)
        p, m = pnf(body, used)
        return [(k, v)] + p, m
    if k in ("and", "or"):
        pre, mats = [], []
        for a in n[1:]:
            p, m = pnf(a, used)
            pre += p
            mats.append(m)
        return pre, (k,) + tuple(mats)
    if k == "imp":
        p1, m1 = pnf(("not", n[1]), used)
        p2, m2 = pnf(n[2], used)
        return p1 + p2, ("imp", neg(m1) if True else m1, m2)
    if k in ("iff", "xor"):
        if has_quant(n):
            raise NotPrenexable(k)
        return [], n
    raise ValueError(k)


def build_prefix(prefix, matrix):
    out = matrix
    for q, v in reversed(prefix):
        out = (q, v, out)
    return out


def prenex(n):
    p, m = pnf(n, set())
    return p, m


# ----------------------------------------------------------------------------------------- operators
def _op_neg(F, rng):
    sites = []
    for path, m in preorder(F):
        if m[0] == "atom":
            if path and get(F, path[:-1])[0] == "not":
                sites.append(replace(F, path[:-1], m))
            else:
                sites.append(replace(F, path, ("not", m)))
    return sites


def _op_quant(F, rng):
    sites = []
    for path, m in preorder(F):
        if m[0] == "forall":
            b = m[2]
            nb = mk_and([b[1], b[2]]) if b[0] == "imp" else b
            sites.append(replace(F, path, ("exists", m[1], nb)))
        elif m[0] == "exists":
            b = m[2]
            if b[0] == "and":
                rest = b[2] if len(b) == 3 else ("and",) + b[2:]
                nb = ("imp", b[1], rest)
            else:
                nb = b
            sites.append(replace(F, path, ("forall", m[1], nb)))
    return sites


def _op_impl_rev(F, rng):
    return [replace(F, p, ("imp", m[2], m[1])) for p, m in preorder(F) if m[0] == "imp"]


def _restrictor_paths(F) -> list[tuple]:
    """Paths of restrictor positions: antecedents of → and the first conjunct under ∃."""
    out = []
    for p, m in preorder(F):
        if m[0] == "imp":
            out.append(p + (0,))
        elif m[0] == "exists" and m[2][0] == "and":
            out.append(p + (0, 0))
    return out


def _op_drop_conj(F, rng):
    restr = set()
    for rp in _restrictor_paths(F):
        restr.add(rp)
    ands = [(p, m) for p, m in preorder(F) if m[0] == "and"]
    # restrictor-side and-nodes first (the antecedent itself is an ∧, or ∃-body ∧)
    ands.sort(key=lambda pm: 0 if (pm[0] in restr or any(pm[0][:len(r)] == r for r in restr)) else 1)
    sites = []
    for p, m in ands:
        idx = list(range(len(m) - 1))
        rng.shuffle(idx)
        for i in idx:
            rest = [c for j, c in enumerate(m[1:]) if j != i]
            sites.append(replace(F, p, rest[0] if len(rest) == 1 else ("and",) + tuple(rest)))
    return sites


def _op_add_conj(F, rng):
    sites = []
    preds = predicates(F)
    name = "NewCond"
    while name in preds:
        name += "X"
    for p, m in preorder(F):
        if m[0] in ("forall", "exists"):
            v, b = m[1], m[2]
            if b[0] == "imp" and v in free_vars(b[1]):
                sites.append(replace(F, p + (0, 0), mk_and([b[1], ("atom", name, (("v", v),))])))
            elif m[0] == "exists":
                sites.append(replace(F, p + (0,), mk_and([b, ("atom", name, (("v", v),))])))
    if not sites:
        cs = constants(F)
        new = ("atom", name, (("c", cs[0]),)) if cs else ("atom", name, ())
        sites.append(mk_and([F, new]))
    return sites


def _swap_consts(F, a, b):
    return rename(rename(rename(F, {}, {a: "__tmp__"}), {}, {b: a}), {}, {"__tmp__": b})


def _op_arg_swap(F, rng):
    sites = []
    for p, m in preorder(F):
        if m[0] == "atom" and len(m[2]) == 2 and m[2][0] != m[2][1]:
            sites.append(replace(F, p, ("atom", m[1], (m[2][1], m[2][0]))))
    if not sites:
        cs = constants(F)
        for i in range(len(cs)):
            for j in range(i + 1, len(cs)):
                sites.append(_swap_consts(F, cs[i], cs[j]))
    return sites


def _op_and_or(F, rng):
    return [replace(F, p, ({"and": "or", "or": "and"}[m[0]],) + m[1:]) for p, m in preorder(F) if m[0] in ("and", "or")]


def _op_scope_swap(F, rng):
    sites = []
    for p, m in preorder(F):  # directly nested, different kinds
        if m[0] in ("forall", "exists") and m[2][0] in ("forall", "exists") and m[2][0] != m[0]:
            inner = m[2]
            sites.append(replace(F, p, (inner[0], inner[1], (m[0], m[1], inner[2]))))
    if sites:
        return sites
    try:
        pre, mat = prenex(F)
    except NotPrenexable:
        return []
    for i in range(len(pre) - 1):
        if pre[i][0] != pre[i + 1][0]:
            q = list(pre)
            q[i], q[i + 1] = q[i + 1], q[i]
            sites.append(build_prefix(q, mat))
    return sites


def _op_merge(F, rng):
    sites = []
    preds = predicates(F)
    for p, m in preorder(F):
        if m[0] != "and":
            continue
        un = [(i, c) for i, c in enumerate(m[1:]) if c[0] == "atom" and len(c[2]) == 1]
        for a in range(len(un)):
            for b in range(a + 1, len(un)):
                (i, A), (j, B) = un[a], un[b]
                if A[1] == B[1] or A[2] != B[2]:
                    continue
                name = A[1] + B[1]
                while name in preds:
                    name += "X"

                def merge_all(n, P=A[1], Q=B[1], NAME=name):
                    if n[0] == "and":
                        kids = [merge_all(c) for c in n[1:]]
                        un2 = {}
                        for idx, c in enumerate(kids):
                            if c[0] == "atom" and len(c[2]) == 1 and c[1] in (P, Q):
                                un2.setdefault(c[2], {})[c[1]] = idx
                        drop, repl = set(), {}
                        for t, d in un2.items():
                            if P in d and Q in d:
                                repl[d[P]] = ("atom", NAME, t)
                                drop.add(d[Q])
                        kids = [repl.get(idx, c) for idx, c in enumerate(kids) if idx not in drop]
                        return kids[0] if len(kids) == 1 else ("and",) + tuple(kids)
                    if n[0] in ("atom", "eq"):
                        return n
                    if n[0] in ("forall", "exists"):
                        return (n[0], n[1], merge_all(n[2]))
                    return (n[0],) + tuple(merge_all(c) for c in n[1:])
                sites.append(merge_all(F))
    return sites


def _op_card(F, rng, variant: str | None = None):
    sites = []
    for p, m in preorder(F):
        if m[0] != "exists":
            continue
        x, phi = m[1], m[2]
        y = fresh_var(all_vars(F))
        var = variant or rng.choice(["two", "unique"])
        if var == "two":
            new = ("exists", x, ("exists", y, mk_and([("not", ("eq", ("v", x), ("v", y))), phi, subst_var(phi, x, y)])))
        else:
            new = ("exists", x, mk_and([phi, ("forall", y, ("imp", subst_var(phi, x, y), ("eq", ("v", y), ("v", x))))]))
        sites.append(replace(F, p, new))
    return sites


OP_FUNCS: dict[str, Callable] = {"NEG": _op_neg, "QUANT": _op_quant, "IMPL_REV": _op_impl_rev,
                                 "DROP_CONJ": _op_drop_conj, "ADD_CONJ": _op_add_conj, "ARG_SWAP": _op_arg_swap,
                                 "AND_OR": _op_and_or, "SCOPE_SWAP": _op_scope_swap, "MERGE": _op_merge,
                                 "CARD": _op_card}


def make_mutant(F, op: str, seed_key: str, variant: str | None = None, max_tries: int = 6,
                timeout_ms: int = 3000) -> dict:
    """Returns {'op','applicable','kept','fol','ast'}; the kept mutant is non-equivalent to F (identity map, n<=4)."""
    rng = rng_for(seed_key, op + (variant or ""))
    try:
        sites = OP_FUNCS[op](F, rng, variant) if op == "CARD" else OP_FUNCS[op](F, rng)
    except (NotPrenexable, ValueError, RecursionError):
        sites = []
    sites = [s for s in dict.fromkeys(sites) if s != F]
    if not sites:
        return {"op": op, "applicable": False, "kept": False}
    order = list(range(len(sites)))
    rng.shuffle(order)
    for i in order[:max_tries]:
        r = bounded_equiv(sites[i], F, nmax=4, timeout_ms=timeout_ms)
        if r == "nonequiv":
            return {"op": op, "applicable": True, "kept": True, "ast": sites[i], "fol": to_str(sites[i]),
                    "variant": variant}
    return {"op": op, "applicable": True, "kept": False}


def all_mutants(F, seed_key: str, ops=OPERATORS) -> list[dict]:
    return [make_mutant(F, op, seed_key) for op in ops]


# ----------------------------------------------------------------------------------------- rewrites
_WN = None


def _wordnet():
    global _WN
    if _WN is None:
        try:
            from nltk.corpus import wordnet as wn
            wn.synsets("dog")
            _WN = wn
        except LookupError:
            _WN = False
    return _WN


def _split_words(name: str) -> list[str]:
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name.replace("_", " "))
    return [w.lower() for w in s.split() if w]


def synonym_name(name: str, taken: set[str], k: int) -> str:
    wn = _wordnet()
    words = _split_words(name)
    if wn and words:
        for i, w in enumerate(words):
            for syn in wn.synsets(w):
                for lem in syn.lemma_names():
                    lem = lem.lower()
                    if lem != w and lem.isalpha() and lem not in words:
                        new_words = words[:i] + [lem] + words[i + 1:]
                        cand = "".join(x.capitalize() for x in new_words)
                        if cand not in taken:
                            return cand
    cand = f"Pred_{k}"
    while cand in taken:
        cand += "b"
    return cand


def _rw_rename(F, rng):
    preds = predicates(F)
    taken = set(preds)
    pmap = {}
    for k, p in enumerate(sorted(preds)):
        new = synonym_name(p, taken, k)
        taken.add(new)
        pmap[p] = new
    cmap = {c: f"{c}_r" if not c[0].isupper() else f"{c}R" for c in constants(F)}
    return [(rename(F, pmap, cmap), {"P": pmap, "C": cmap})]


def _rw_reorder(F, rng):
    out = []
    for p, m in preorder(F):
        if m[0] in ("and", "or"):
            kids = list(m[1:])
            new = kids[::-1]
            out.append((replace(F, p, (m[0],) + tuple(new)), None))
        elif m[0] in ("iff", "xor"):
            out.append((replace(F, p, (m[0], m[2], m[1])), None))
    return out


def _rw_contra(F, rng):
    out = []
    paths = [()] if F[0] == "imp" else []
    for p, m in preorder(F):
        if m[0] == "forall" and m[2][0] == "imp":
            paths.append(p + (0,))
    for p in paths:
        m = get(F, p)
        if m[0] == "imp":
            out.append((replace(F, p, ("imp", neg(m[2]), neg(m[1]))), None))
    return out


def _rw_demorgan(F, rng):
    out = []
    for p, m in preorder(F):
        if m[0] == "not" and m[1][0] in ("and", "or"):
            inner = m[1]
            out.append((replace(F, p, ({"and": "or", "or": "and"}[inner[0]],) + tuple(neg(c) for c in inner[1:])), None))
    if not out:
        for p, m in preorder(F):
            if m[0] in ("and", "or"):
                out.append((replace(F, p, ("not", ({"and": "or", "or": "and"}[m[0]],) + tuple(neg(c) for c in m[1:]))), None))
    return out


def _rw_prenex(F, rng):
    try:
        pre, mat = prenex(F)
    except NotPrenexable:
        return []
    new = build_prefix(pre, mat)
    return [(new, None)] if new != F else []


RW_FUNCS = {"RENAME": _rw_rename, "REORDER": _rw_reorder, "CONTRAPOSITIVE": _rw_contra, "DEMORGAN": _rw_demorgan,
            "PRENEX": _rw_prenex}


def make_rewrites(F, seed_key: str, k: int = 2, timeout_ms: int = 3000) -> list[dict]:
    rng = rng_for(seed_key, "REWRITE")
    kinds = list(REWRITES)
    rng.shuffle(kinds)
    out = []
    for kind in kinds:
        if len(out) >= k:
            break
        try:
            cands = RW_FUNCS[kind](F, rng)
        except (NotPrenexable, ValueError, RecursionError):
            cands = []
        cands = [c for c in cands if c[0] != F]
        if not cands:
            continue
        new, m = cands[rng.randrange(len(cands))]
        if kind == "RENAME":
            inv_p = {v: k2 for k2, v in m["P"].items()}
            inv_c = {v: k2 for k2, v in m["C"].items()}
            chk = bounded_equiv(rename(new, inv_p, inv_c), F, nmax=4, timeout_ms=timeout_ms)
        else:
            chk = bounded_equiv(new, F, nmax=4, timeout_ms=timeout_ms)
        if chk == "equiv":
            out.append({"kind": kind, "ast": new, "fol": to_str(new), "map": m})
    return out
