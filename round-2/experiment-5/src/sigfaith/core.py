"""Core machinery of the repaired signature metric (shared by the screen repair, the held-out scoring and the API).

front-end    parse_front(fol): the dataset's tolerant parser (VARLIKE + LaTeX fixes; ASCII/unicode/snake_case)
             -> converted to the iter-1 tuple AST ('all'/'ex', n-ary 'and'/'or', ('v',x)/('c',k) terms)
             -> legacy _fix_arity. The formula side (solver_sig.signature) then runs unchanged.
text sides   T0 = iter-1 rules marker; T1a = gemini probe labels; T1b = probe when m1/m2-consistent in {+,-,0},
             else rule; T1c = rule unless (probe consistent '-' and rule '+'); T2 = T1b with a stronger model deciding
             rule/probe disagreements. a3 relativized coordinates are derived from the chosen concept labels.
scorer       signature_score_full: the iter-1 score.signature_score coordinate loop (verbatim logic) that also
             returns every coordinate, so the polarity-only subscore P (label/swap/rel coordinates only) and the
             decoder features can be computed. Regression-tested against legacy score.signature_score.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEG = ROOT / "legacy_armA" / "src"
if str(LEG) not in sys.path:
    sys.path.insert(0, str(LEG))
SF = Path(__file__).resolve().parent
if str(SF) not in sys.path:
    sys.path.insert(0, str(SF))
import nltk  # noqa: E402
if str(ROOT / "nltk_data") not in nltk.data.path:
    nltk.data.path.insert(0, str(ROOT / "nltk_data"))

import front_parse  # noqa: E402  (dataset parser)
from fol_parse import Parsed, _fix_arity, consts as f_consts, preds as f_preds  # noqa: E402  (legacy)
from score import FLIP, error_type, signature_score  # noqa: E402  (legacy)

PANEL_TYPES = ["added_condition", "dropped_condition", "quantifier_forall_exists", "implication_direction_or_only",
               "negation_polarity", "argument_swap", "conflation", "wrong_split", "connective_and_or",
               "exception_misplaced", "quantifier_scope", "cardinality_numeric", "wrong_constant",
               "syntax_unparseable", "other"]
LEGACY2PANEL = {"swapped_args": "argument_swap", "conflation": "conflation", "dropped_condition": "dropped_condition",
                "added_condition": "added_condition", "wrong_split": "wrong_split",
                "reversed_implication": "implication_direction_or_only", "quantifier": "quantifier_forall_exists",
                "negation_polarity": "negation_polarity", "connective_andor": "connective_and_or", "other": "other",
                "none": "none"}


# ---------------------------------------------------------------- front-end parser
def _conv(n):
    op = n[0]
    if op == "forall":
        return ("all", n[1], _conv(n[2]))
    if op == "exists":
        return ("ex", n[1], _conv(n[2]))
    if op == "not":
        return ("not", _conv(n[1]))
    if op in ("and", "or"):
        parts = []
        for c in (n[1], n[2]):
            cc = _conv(c)
            parts.extend(cc[1] if cc[0] == op else (cc,))
        return (op, tuple(parts))
    if op in ("imp", "iff", "xor"):
        return (op, _conv(n[1]), _conv(n[2]))
    if op == "atom":
        return ("atom", n[1], tuple(("v", t[1]) if t[0] == "var" else ("c", t[1]) for t in n[2]))
    if op == "eq":
        t = lambda x: ("v", x[1]) if x[0] == "var" else ("c", x[1])  # noqa: E731
        return ("eq", t(n[1]), t(n[2]))
    raise ValueError(f"unknown node {op}")


def parse_front(fol: str):
    """Returns (Parsed | None, error_str). Never raises."""
    try:
        r = front_parse.parse(fol or "")
    except Exception as e:  # noqa: BLE001
        return None, f"front_parse crash: {e}"
    if not r.ok or r.ast is None:
        return None, r.error or "unparseable"
    try:
        ast = _conv(r.ast)
        ast, conflict = _fix_arity(ast)
        return Parsed(ast=ast, free_vars=any("closure" in x for x in r.notes), preds=f_preds(ast),
                      consts=sorted(f_consts(ast)), arity_conflict=conflict), ""
    except (ValueError, RecursionError) as e:
        return None, f"convert: {e}"


# ---------------------------------------------------------------- text sides
TEXT_SIDES = ("T0", "T1a", "T1b", "T1c", "T2")


def probe_consistent(per_mod: list | None) -> str | None:
    """The probe label if both specialised copies agree and the label is in {+,-,0}; else None."""
    if not per_mod or len(per_mod) < 2:
        return None
    a, b = per_mod[0], per_mod[1]
    if a == b and a in ("+", "-", "0"):
        return a
    return None


def choose_labels(marker: dict, llm_labels: dict | None, per_mod: dict | None, side: str,
                  strong: dict | None = None) -> dict:
    """Concept polarity labels {cid:int -> label} for text side `side`."""
    out = {}
    for k, rl in marker.items():
        cid = int(k)
        pl = (llm_labels or {}).get(cid, (llm_labels or {}).get(str(cid)))
        pm = (per_mod or {}).get(cid, (per_mod or {}).get(str(cid)))
        pc = probe_consistent(pm)
        if side == "T0" or llm_labels is None:
            out[cid] = rl
        elif side == "T1a":
            out[cid] = pl if pl is not None else "?"
        elif side == "T1b":
            out[cid] = pc if pc is not None else rl
        elif side == "T1c":
            out[cid] = "-" if (pc == "-" and rl == "+") else rl
        elif side == "T2":
            base = pc if pc is not None else rl
            if strong is not None and (cid in strong or str(cid) in strong) and base != rl:
                s = strong.get(cid, strong.get(str(cid)))
                out[cid] = s if s in ("+", "-", "0", "±") else base
            else:
                out[cid] = base
        else:
            raise ValueError(side)
    return out


def a3_rel(coord: list, labels: dict) -> dict:
    rel = {}
    for c, q, kind in coord:
        for (x, y) in ((c, q), (q, c)):
            lx = labels.get(int(x), "+")
            if lx == "?":
                lx = "+"
            if kind == "and":
                rel[(x, y, "out")], rel[(x, y, "in")] = "0", lx
            elif kind == "or":
                rel[(x, y, "in")], rel[(x, y, "out")] = "0", lx
    return rel


def make_T(ex: dict, labels: dict) -> dict:
    return {"labels": dict(labels), "anchors": ex["anchors"], "rel": a3_rel(ex["coord"], labels)}


# ---------------------------------------------------------------- full-coordinate scorer
def signature_score_full(T: dict, S: dict | None, A: dict | None, *, variant: str, parse_ok: bool = True,
                         optional: set | None = None) -> dict:
    """Same result as legacy score.signature_score, plus 'coords' [(w, mismatch, record)], the polarity-only
    subscore 'P' and the legacy + panel-mapped iter-1 error type."""
    res = signature_score(T, S, A, variant=variant, parse_ok=parse_ok, optional=optional)
    if not parse_ok or S is None or A is None:
        res.update(coords=[], P=0.5, P_raw=None)
        return res
    # re-enumerate coordinates exactly as legacy does (copied logic, see score.py)
    labels_T = T.get("labels", {})
    by_c: dict = {}
    for P_, a in A["preds"].items():
        if a["cid"] is not None:
            by_c.setdefault(a["cid"], []).append(P_)
    coords = []
    for cid, tl in labels_T.items():
        cid = int(cid)
        if tl == "?":
            continue
        Ps = by_c.get(cid, [])
        covered_other = any(cid in a["covered"] for a in A["preds"].values()) or cid in A["consts"].values()
        if not Ps:
            if covered_other or (optional and cid in optional):
                continue
            coords.append((1.0, True, {"type": "dropped", "cid": cid, "t": tl}))
            continue
        for P_ in Ps:
            sl = S["labels"].get(P_, "?")
            if sl == "?":
                continue
            if A["preds"][P_]["flip"]:
                sl = FLIP[sl]
            mis_l = (sl != tl) and variant != "A0"
            coords.append((1.0 / len(Ps), mis_l, {"type": "label", "cid": cid, "pred": P_, "t": tl, "s": sl}))
    for P_, a in A["preds"].items():
        sl = S["labels"].get(P_, "?")
        mis = a["cid"] is None or (sl == "0" and variant != "A0")
        coords.append((1.0, mis, {"type": "added" if mis else "pred_ok", "pred": P_, "s": sl,
                                  "why": "unaligned" if a["cid"] is None else ("vacuous" if sl == "0" else "")}))
    for an in (T.get("anchors", []) if variant != "A0" else []):
        Rs = [P_ for P_ in by_c.get(an["verb_cid"], []) if S.get("arity", {}).get(P_, 1) >= 2]
        if not Rs:
            continue
        args = [P_ for P_ in by_c.get(an["arg_cid"], []) if S.get("arity", {}).get(P_, 1) == 1]
        args += [f"c:{k}" for k, cid in A["consts"].items() if cid == an["arg_cid"]]
        if not args:
            continue
        for R in Rs:
            k = S["arity"][R]
            i = an["slot"]
            if i >= k:
                continue
            others = [j for j in range(k) if j != i]
            swap = decided = False
            for ag in args:
                a_i = S.get("anchors", {}).get(f"{R}|{i}|{ag}")
                a_o = [S.get("anchors", {}).get(f"{R}|{j}|{ag}") for j in others]
                if a_i is None and all(x is None for x in a_o):
                    continue
                decided = True
                if (a_i is False) and any(x is True for x in a_o):
                    swap = True
            if decided:
                coords.append((1.0, swap, {"type": "swap" if swap else "slot_ok", "verb": an["verb_cid"], "slot": i,
                                           "R": R}))
    if variant in ("A2", "A3"):
        for (c, q, side), tl in T.get("rel", {}).items():
            if tl == "?":
                continue
            Pc = [P_ for P_ in by_c.get(int(c), []) if S.get("arity", {}).get(P_, 1) == 1]
            Pq = [P_ for P_ in by_c.get(int(q), []) if S.get("arity", {}).get(P_, 1) == 1]
            for pc in Pc:
                for pq in Pq:
                    if pc == pq:
                        continue
                    sl = S.get("rel", {}).get(f"{pc}|{pq}|{side}")
                    if sl is None or sl == "?":
                        continue
                    if A["preds"][pc]["flip"]:
                        sl = FLIP[sl]
                    coords.append((0.5, sl != tl, {"type": "rel" if sl != tl else "rel_ok", "c": c, "q": q,
                                                   "side": side, "t": tl, "s": sl}))
    tot = sum(w for w, _, _ in coords)
    bad = sum(w for w, m, _ in coords if m)
    raw = 1.0 - bad / tot if tot > 0 else None
    assert raw == res["raw_score"] or (raw is not None and res["raw_score"] is not None
                                       and abs(raw - res["raw_score"]) < 1e-12), (raw, res["raw_score"])
    pol = [(w, m) for w, m, r in coords if r["type"] in ("label", "swap", "slot_ok", "rel", "rel_ok")]
    pt = sum(w for w, _ in pol)
    P_raw = (1.0 - sum(w for w, m in pol if m) / pt) if pt > 0 else None
    res.update(coords=coords, P_raw=P_raw, P=(P_raw if P_raw is not None else 0.5),
               legacy_type=res["error_type_pred"], legacy_type_panel=LEGACY2PANEL.get(res["error_type_pred"], "other"))
    return res


def features(res: dict) -> dict:
    """Count features of a scored item (decoder D_lr inputs)."""
    f = {"n_dropped": 0, "n_added_unaligned": 0, "n_added_vacuous": 0, "n_swap": 0, "n_flip_pm": 0, "n_flip_mp": 0,
         "n_pm_nonmono": 0, "n_rel": 0, "n_split": 0, "n_coords": res.get("n_coords", 0) or 0,
         "coverage": res.get("coverage", 0.0) or 0.0, "n_zero_t": 0}
    labs_by_c: dict = {}
    for w, m, r in res.get("coords", []):
        if not m:
            if r["type"] == "label":
                labs_by_c.setdefault(r["cid"], set()).add(r["s"])
            continue
        t = r["type"]
        if t == "dropped":
            f["n_dropped"] += 1
        elif t == "added":
            f["n_added_unaligned" if r.get("why") == "unaligned" else "n_added_vacuous"] += 1
        elif t == "swap":
            f["n_swap"] += 1
        elif t == "rel":
            f["n_rel"] += 1
        elif t == "label":
            labs_by_c.setdefault(r["cid"], set()).add(r["s"])
            if r["t"] == "+" and r["s"] == "-":
                f["n_flip_pm"] += 1
            elif r["t"] == "-" and r["s"] == "+":
                f["n_flip_mp"] += 1
            elif r["s"] == "±" or r["t"] == "±":
                f["n_pm_nonmono"] += 1
            elif r["s"] == "0" or r["t"] == "0":
                f["n_zero_t"] += 1
    f["n_split"] = sum(1 for v in labs_by_c.values() if {"+", "-"} <= v)
    return f


__all__ = ["parse_front", "choose_labels", "make_T", "signature_score_full", "features", "PANEL_TYPES",
           "LEGACY2PANEL", "TEXT_SIDES", "error_type"]
