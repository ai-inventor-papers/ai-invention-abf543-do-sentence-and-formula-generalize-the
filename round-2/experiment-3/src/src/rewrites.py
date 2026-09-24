"""Meaning-preserving rewrites on the DC AST (for the invariance test). Each rewrite is verified by z3 afterwards.

SYN_RENAME   : every predicate whose name has a WordNet synonym for one of its tokens gets that token replaced
               (bijective renaming; names stay distinct)
RAND_RENAME  : every predicate and constant renamed to an opaque random token (bijective)
CONTRAPOS    : the first implication A -> B becomes ¬B -> ¬A
DEMORGAN     : the first ¬(A ∧ B) / ¬(A ∨ B) is pushed inward; else the first A ∧ B becomes ¬(¬A ∨ ¬B)
REORDER      : the first ∧ / ∨ node has its operands swapped
"""
from __future__ import annotations

import random
import re

from dc.parse import BIN_OPS, QUANTS, rename, sig

KINDS = ["SYN_RENAME", "RAND_RENAME", "CONTRAPOS", "DEMORGAN", "REORDER"]
_TOK = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|\d+")


def _first(ast, pred):
    """Rewrite the first node (pre-order) satisfying pred(node) -> new node or None."""
    done = [False]

    def rec(n):
        if done[0]:
            return n
        r = pred(n)
        if r is not None:
            done[0] = True
            return r
        op = n[0]
        if op in QUANTS:
            return (op, n[1], rec(n[2]))
        if op == "not":
            return ("not", rec(n[1]))
        if op in BIN_OPS:
            a = rec(n[1])
            return (op, a, rec(n[2]))
        return n
    out = rec(ast)
    return out if done[0] else None


def contrapos(ast):
    return _first(ast, lambda n: ("imp", ("not", n[2]), ("not", n[1])) if n[0] == "imp" else None)


def demorgan(ast):
    def f(n):
        if n[0] == "not" and n[1][0] in ("and", "or"):
            o = "or" if n[1][0] == "and" else "and"
            return (o, ("not", n[1][1]), ("not", n[1][2]))
        return None
    r = _first(ast, f)
    if r is not None:
        return r
    return _first(ast, lambda n: ("not", ("or", ("not", n[1]), ("not", n[2]))) if n[0] == "and" else None)


def reorder(ast):
    return _first(ast, lambda n: (n[0], n[2], n[1]) if n[0] in ("and", "or") else None)


def _synonym(tok: str, wn) -> str | None:
    t = tok.lower()
    if len(t) < 3:
        return None
    for ss in wn.synsets(t):
        for l in ss.lemma_names():
            l = l.replace("-", "_")
            if l.lower() != t and l.isascii() and "_" not in l and l.isalpha():
                return l
    return None


def syn_rename(ast, wn):
    preds, _ = sig(ast)
    used = set(preds)
    pmap = {}
    for p in preds:
        base = p.split("/")[0]
        toks = []
        for part in base.split("_"):
            toks += _TOK.findall(part) or [part]
        for i, t in enumerate(toks):
            s = _synonym(t, wn)
            if s:
                new = "".join(x[:1].upper() + x[1:] for x in (toks[:i] + [s] + toks[i + 1:]))
                if new not in used and new != p:
                    pmap[p] = new
                    used.add(new)
                    break
    if not pmap:
        return None
    return rename(ast, pmap, {})


def rand_rename(ast, rng: random.Random):
    preds, consts = sig(ast)
    names = set()

    def fresh(prefix):
        while True:
            s = prefix + "".join(rng.choice("bcdfghjklmnpqrstvwxz") for _ in range(6))
            if s not in names:
                names.add(s)
                return s
    pmap = {p: fresh("Q") for p in preds}
    cmap = {c: fresh("k") for c in consts}
    return rename(ast, pmap, cmap)


def rewrite(ast, kind: str, rng: random.Random, wn=None):
    if kind == "SYN_RENAME":
        return syn_rename(ast, wn)
    if kind == "RAND_RENAME":
        return rand_rename(ast, rng)
    if kind == "CONTRAPOS":
        return contrapos(ast)
    if kind == "DEMORGAN":
        return demorgan(ast)
    if kind == "REORDER":
        return reorder(ast)
    raise ValueError(kind)
