"""Parsing, renaming and structural fingerprints for the DC library.

Uses the dataset's tolerant FOL parser (vendor/ds/src/fol_parse.py, read-only copy) so that every
system's dialect (unicode, ASCII, LaTeX, snake_case) is read the same way the labels were built.
AST convention (vendor): ("atom", name, (terms)), terms ("var", v) | ("const", c); ("eq", t1, t2);
("not", f); (op, f, g) for op in and/or/imp/iff/xor; ("forall"|"exists", v, body).
"""
from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

_VENDOR = Path(__file__).resolve().parents[1] / "vendor" / "ds" / "src"
if str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))

from fol_parse import SYM, normalize_arity_overloads, parse as _vparse, signature, to_str  # noqa: E402

BIN_OPS = ("and", "or", "imp", "iff", "xor")
QUANTS = ("forall", "exists")


@lru_cache(maxsize=200_000)
def parse_fol(s: str | None):
    """Parsed, arity-normalised AST of a formula string, or None if it does not parse."""
    if not s or not isinstance(s, str):
        return None
    try:
        r = _vparse(s)
    except (ValueError, RecursionError, IndexError, KeyError, TypeError):
        return None
    if not r.ok or r.ast is None:
        return None
    return normalize_arity_overloads(r.ast)


def canon(ast) -> str:
    """Canonical printed form (vendor printer)."""
    return to_str(ast)


def sig(ast) -> tuple[dict[str, int], set[str]]:
    """({predicate: arity}, {constants}); equality is not a predicate."""
    return signature(ast)


def rename(ast, pmap: dict[str, str], cmap: dict[str, str]):
    """Rename predicates by pmap and constants by cmap (names absent from the maps are kept)."""
    op = ast[0]
    if op in QUANTS:
        return (op, ast[1], rename(ast[2], pmap, cmap))
    if op == "not":
        return ("not", rename(ast[1], pmap, cmap))
    if op in BIN_OPS:
        return (op, rename(ast[1], pmap, cmap), rename(ast[2], pmap, cmap))
    if op == "atom":
        terms = tuple(("const", cmap.get(t[1], t[1])) if t[0] == "const" else t for t in ast[2])
        return ("atom", pmap.get(ast[1], ast[1]), terms)
    if op == "eq":
        return ("eq",) + tuple(("const", cmap.get(t[1], t[1])) if t[0] == "const" else t for t in ast[1:])
    raise ValueError(op)


def fingerprint(ast) -> dict[str, tuple]:
    """Structural fingerprint of every predicate ('P') and constant ('#c') symbol of a formula:
    (arity, #occurrences, #positive-polarity occ., #negative-polarity occ., #occ. in an implication
    antecedent, min quantifier depth, #co-argument constants). Names are never used."""
    acc: dict[str, list] = {}

    def bump(key, arity, pol, ante, depth, nconst):
        r = acc.setdefault(key, [arity, 0, 0, 0, 0, 99, 0])
        r[1] += 1
        if pol > 0:
            r[2] += 1
        elif pol < 0:
            r[3] += 1
        else:
            r[2] += 1
            r[3] += 1
        r[4] += int(ante)
        r[5] = min(r[5], depth)
        r[6] += nconst

    def walk(n, pol, ante, depth):
        op = n[0]
        if op in QUANTS:
            walk(n[2], pol, ante, depth + 1)
        elif op == "not":
            walk(n[1], -pol, ante, depth)
        elif op in ("and", "or"):
            walk(n[1], pol, ante, depth)
            walk(n[2], pol, ante, depth)
        elif op == "imp":
            walk(n[1], -pol, True, depth)
            walk(n[2], pol, ante, depth)
        elif op in ("iff", "xor"):
            walk(n[1], 0, ante, depth)
            walk(n[2], 0, ante, depth)
        elif op == "atom":
            nconst = sum(t[0] == "const" for t in n[2])
            bump(n[1], len(n[2]), pol, ante, depth, nconst)
            for t in n[2]:
                if t[0] == "const":
                    bump("#" + t[1], 0, pol, ante, depth, 0)
        elif op == "eq":
            for t in n[1:]:
                if t[0] == "const":
                    bump("#" + t[1], 0, pol, ante, depth, 0)
    walk(ast, 1, False, 0)
    return {k: tuple(v) for k, v in acc.items()}


def fp_distance(a: tuple, b: tuple) -> float:
    """L1 distance between two fingerprints (arity mismatch is infinite)."""
    if a[0] != b[0]:
        return float("inf")
    return sum(abs(x - y) for x, y in zip(a[1:], b[1:]))


def quantifier_multiset(ast) -> tuple:
    out = []

    def walk(n):
        op = n[0]
        if op in QUANTS:
            out.append(op)
            walk(n[2])
        elif op == "not":
            walk(n[1])
        elif op in BIN_OPS:
            walk(n[1])
            walk(n[2])
    walk(ast)
    return tuple(sorted(out))


def quantifier_prefix_order(ast) -> tuple:
    out = []

    def walk(n):
        op = n[0]
        if op in QUANTS:
            out.append(op)
            walk(n[2])
        elif op == "not":
            walk(n[1])
        elif op in BIN_OPS:
            walk(n[1])
            walk(n[2])
    walk(ast)
    return tuple(out)


def connective_multiset(ast) -> tuple:
    out = []

    def walk(n):
        op = n[0]
        if op in QUANTS:
            walk(n[2])
        elif op == "not":
            walk(n[1])
        elif op in BIN_OPS:
            out.append(op)
            walk(n[1])
            walk(n[2])
    walk(ast)
    return tuple(sorted(out))


def n_atoms(ast) -> int:
    op = ast[0]
    if op in QUANTS:
        return n_atoms(ast[2])
    if op == "not":
        return n_atoms(ast[1])
    if op in BIN_OPS:
        return n_atoms(ast[1]) + n_atoms(ast[2])
    return 1


__all__ = ["parse_fol", "canon", "sig", "rename", "fingerprint", "fp_distance", "quantifier_multiset",
           "quantifier_prefix_order", "connective_multiset", "n_atoms", "SYM", "BIN_OPS", "QUANTS"]
