"""Shared screen-side helpers: splits, item loading, cached legacy-parse + signatures, scoring under an aligner.

SCREEN split (pre-registered, no labels): sentences sorted by sha1(sid); first 150 = SCREEN_DEV, rest SCREEN_TEST.
Mutants, rewrites and real candidates follow their sentence.
"""
from __future__ import annotations

import hashlib
import json
import sys
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "sigfaith"))
sys.path.insert(0, str(ROOT / "legacy_armA" / "src"))

import core  # noqa: E402
from align import align as legacy_align  # noqa: E402
from align import is_optional  # noqa: E402
from fol_parse import ParseError, parse  # noqa: E402

SCREEN = ROOT / "data" / "screen_set.json"
TSIG = ROOT / "legacy_armA" / "text_sigs.json"
FSIG = ROOT / "legacy_armA" / "formula_sigs.json"
EXTRA_SIG = ROOT / "results" / "extra_formula_sigs.json"


@lru_cache(maxsize=1)
def screen() -> dict:
    return json.loads(SCREEN.read_text())


@lru_cache(maxsize=1)
def tsigs() -> dict:
    return json.loads(TSIG.read_text())


@lru_cache(maxsize=1)
def fsigs() -> dict:
    d = json.loads(FSIG.read_text())
    if EXTRA_SIG.exists():
        d.update(json.loads(EXTRA_SIG.read_text()))
    return d


def splits() -> tuple[list[str], list[str]]:
    sids = sorted((s["sid"] for s in screen()["sentences"]), key=lambda s: hashlib.sha1(s.encode()).hexdigest())
    return sids[:150], sids[150:]


def ex_of(sid: str) -> dict:
    ts = tsigs()[sid]
    return {"concepts": ts["concepts"], "anchors": ts["anchors"], "coord": [tuple(c) for c in ts["coord"]],
            "marker": {int(k): v for k, v in ts["marker"].items()}}


def T_of(sid: str, side: str = "T0", strong: dict | None = None) -> dict:
    ts = tsigs()[sid]
    ex = ex_of(sid)
    labels = core.choose_labels(ex["marker"], {int(k): v for k, v in ts["llm_labels"].items()},
                                {int(k): v for k, v in ts["llm_per_mod"].items()}, side, strong)
    return core.make_T(ex, labels)


def items(sids: set, kinds=("gold", "real", "mutant", "rewrite")) -> list[dict]:
    d = screen()
    S = {s["sid"]: s for s in d["sentences"]}
    out = []
    if "gold" in kinds:
        out += [{"item_id": f"{sid}:gold", "set": "gold", "sid": sid, "fol": S[sid]["gold_fol"], "parse_ok": True}
                for sid in sids]
    if "real" in kinds:
        out += [{"item_id": r["item_id"], "set": "real", "sid": r["sid"], "fol": r["cand_fol"], "parse_ok": r["parse_ok"],
                 "y_bij": r["correct"]} for r in d["real"] if r["sid"] in sids]
    if "mutant" in kinds:
        out += [{"item_id": m["mid"], "set": "mutant", "sid": m["sid"], "fol": m["fol"], "parse_ok": True,
                 "operator": m["operator"]} for m in d["mutants"] if m["sid"] in sids]
    if "rewrite" in kinds:
        out += [{"item_id": r["rid"], "set": "rewrite", "sid": r["sid"], "fol": r["fol"], "parse_ok": True,
                 "kind": r["kind"]} for r in d["rewrites"] if r["sid"] in sids]
    return out


@lru_cache(maxsize=100000)
def lparse(fol: str):
    try:
        return parse(fol)
    except (ParseError, RecursionError):
        return None


def score_item(it: dict, aligner, side: str = "T0", variant: str = "A3", T: dict | None = None) -> dict:
    """aligner: callable(preds, consts, concepts, anchors) -> A, or 'legacy'."""
    sid = it["sid"]
    ex = it.get("ex") or ex_of(sid)
    T = T or T_of(sid, side)
    optional = {c["cid"] for c in ex["concepts"] if is_optional(c)}
    p = lparse(it["fol"]) if it.get("parse_ok", True) else None
    S = fsigs().get(it["fol"]) if p is not None else None
    if S is not None and "error" in S:
        S = None
    if p is None or S is None:
        r = core.signature_score_full(T, None, None, variant=variant, parse_ok=False)
        r.update(A=None, parse_ok=False)
        return r
    if aligner == "legacy":
        A = legacy_align(p.preds, p.consts, ex["concepts"])
    else:
        A = aligner(p.preds, p.consts, ex["concepts"], ex["anchors"])
    r = core.signature_score_full(T, S, A, variant=variant, parse_ok=True, optional=optional)
    r.update(A=A, parse_ok=True, consts=p.consts)
    return r


def auroc(y, s, w=None) -> float | None:
    from sklearn.metrics import roc_auc_score
    import numpy as np
    y = np.asarray(y)
    if len(set(y.tolist())) < 2:
        return None
    return float(roc_auc_score(y, s, sample_weight=w))
