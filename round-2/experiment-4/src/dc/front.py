"""Front end: canonical parse of a candidate FOL string.

canon(fol) = to_str(parse(fol)) with the DATASET's tolerant parser (vendor/ds/fol_parse, exactly the normalisation
gen_art_experiment_3 applied before scoring), then parsed into the Arm-B AST (vendor/armB/fol_core) that the whole DC
engine works on. Measures nothing; returns the AST + signature or UNPARSEABLE (never dropped: callers count it).
"""
from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "vendor" / "armB", ROOT / "vendor" / "ds"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import fol_core as fc  # noqa: E402
import fol_parse as dsp  # noqa: E402


@lru_cache(maxsize=200000)
def canon_str(fol: str) -> str | None:
    """Dataset-parser canonical string, or None if the dataset parser rejects it."""
    if not fol or not fol.strip():
        return None
    try:
        pr = dsp.parse(fol)
    except (RecursionError, ValueError):
        return None
    if not pr.ok:
        return None
    return dsp.to_str(pr.ast)


@lru_cache(maxsize=200000)
def canon(fol: str) -> dict:
    """{'ok', 'canon', 'ast', 'preds', 'consts', 'err'}; canon string preferred, raw string as fallback (as exp3)."""
    c = canon_str(fol)
    for s in ([c] if c else []) + [fol]:
        if not s:
            continue
        ast, err = fc.try_parse(s)
        if ast is not None:
            return {"ok": True, "canon": fc.to_str(ast), "ast": ast, "preds": fc.predicates(ast),
                    "consts": fc.constants(ast), "err": None}
    return {"ok": False, "canon": c or (fol or ""), "ast": None, "preds": {}, "consts": [], "err": "unparseable"}


def parse_canon(s: str):
    """Parse a string that is already in Arm-B canonical form (fc.to_str output)."""
    ast, _ = fc.try_parse(s)
    return ast
