"""Syntax bridge: held-out candidates (ASCII ^, LaTeX, snake_case, …) → fol_core AST (FOLIO-unicode)."""
from __future__ import annotations

import importlib.util
import re

import common  # noqa: F401  (paths)
import fol_core as fc

_spec = importlib.util.spec_from_file_location("ds_fol_parse", common.ROOT / "third_party" / "ds" / "fol_parse.py")
ds = importlib.util.module_from_spec(_spec)
import sys as _sys
_sys.modules["ds_fol_parse"] = ds
_spec.loader.exec_module(ds)


def _cname(c: str) -> str:
    """Constants with quotes/hyphens/spaces → identifier ('G-910' → 'G_910', '"Dr. Y H"' → 'Dr_Y_H')."""
    s = re.sub(r"\W+", "_", c.strip('"')).strip("_") or "c0"
    return s if not s[0].isdigit() else "n" + s


def _vname(v: str) -> str:
    return v if re.fullmatch(r"[a-z][a-z0-9]*", v) else "v" + re.sub(r"\W", "", v).lower()


def _term(t):
    return ("v", _vname(t[1])) if t[0] == "var" else ("c", _cname(t[1]))


def _conv(n):
    k = n[0]
    if k == "atom":
        return ("atom", n[1], tuple(_term(t) for t in n[2]))
    if k == "eq":
        return ("eq",) + tuple(_term(t) for t in n[1:])
    if k in ("forall", "exists"):
        return (k, _vname(n[1]), _conv(n[2]))
    if k == "not":
        return ("not", _conv(n[1]))
    return (k,) + tuple(_conv(a) for a in n[1:])


def to_folio(fol_str: str):
    """Returns (ast|None, how) with how in {'direct','bridged','unparseable:<reason>'}."""
    ast, err = fc.try_parse(fol_str)
    if ast is not None:
        return ast, "direct"
    try:
        r = ds.parse(fol_str)
    except Exception as e:  # noqa: BLE001 - tolerant parser failure → unparseable, counted
        return None, f"unparseable:ds_exception:{type(e).__name__}"
    if not r.ok:
        return None, f"unparseable:{err}"
    try:
        a = fc.flatten(_conv(ds.normalize_arity_overloads(r.ast)))
    except Exception as e:  # noqa: BLE001
        return None, f"unparseable:convert:{type(e).__name__}"
    if fc.predicates(a, strict=False) is None:
        return None, "unparseable:arity"
    # round-trip through the FOLIO printer/parser so downstream code sees a canonical fol_core AST
    s = fc.to_str(a)
    b, err2 = fc.try_parse(s)
    if b is None:
        return None, f"unparseable:roundtrip:{err2}"
    return b, "bridged"


def to_folio_str(fol_str: str) -> tuple[str | None, str]:
    a, how = to_folio(fol_str)
    return (fc.to_str(a) if a is not None else None), how
