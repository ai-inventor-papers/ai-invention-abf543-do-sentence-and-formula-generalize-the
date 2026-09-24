#!/usr/bin/env python3
"""Controlled perturbations with KNOWN error types (mechanism evidence only; never the headline).

For fresh sentences with an audited gold, take one greedy candidate that is solver-EQUIVALENT to the audited gold
(a faithful anchor), apply one operator, keep the mutant only if z3 shows it is NOT equivalent to the anchor (same
vocabulary), put it in the anchor's place among the same 8 peers, and score it with the frozen DC.
  detection      = P(DC(anchor) > DC(mutant)) (ties 0.5), per operator, with a sentence bootstrap CI
  typing         = share of mutants whose DC error type equals the operator's taxonomy type
  VC / L1_uniform contrasts on the same mutants.
Operators: NEG (flip one literal), QUANT (∀x(A→B) <-> ∃x(A∧B), else flip), IMPL_REV (swap the main implication),
DROP (drop one antecedent conjunct), ADD (add a fresh-predicate conjunct to the antecedent), ARG_SWAP (reverse the
arguments of one binary atom), ANDOR (flip the first ∧/∨).
"""
from __future__ import annotations

import json
import random
from collections import Counter, defaultdict

import numpy as np
from loguru import logger

from aframe import load_frame
from common import RES, WORK, assert_frozen, setup_logging
from dc import canon as dcanon
from dc.consensus import DCConfig, score_group
from dc.parse import BIN_OPS, QUANTS, parse_fol
from dc.relation import pair_relation
from dcscore import group_relations
from pairs import load_cache, run as run_pairs
from rewrites import _first
from typing_jobs import run_typing

OP_TYPE = {"NEG": "negation_polarity", "QUANT": "quantifier_forall_exists", "IMPL_REV": "implication_direction_or_only",
           "DROP": "dropped_condition", "ADD": "added_condition", "ARG_SWAP": "argument_swap", "ANDOR": "connective_and_or"}


def _atoms_paths(ast):
    out = []

    def rec(n, path):
        op = n[0]
        if op in QUANTS:
            rec(n[2], path + (2,))
        elif op == "not":
            rec(n[1], path + (1,))
        elif op in BIN_OPS:
            rec(n[1], path + (1,))
            rec(n[2], path + (2,))
        elif op in ("atom", "eq"):
            out.append(path)
    rec(ast, ())
    return out


def _get(n, path):
    for i in path:
        n = n[i]
    return n


def _set(n, path, new):
    if not path:
        return new
    lst = list(n)
    lst[path[0]] = _set(n[path[0]], path[1:], new)
    return tuple(lst)


def m_neg(ast, rng):
    ps = _atoms_paths(ast)
    if not ps:
        return None
    p = rng.choice(ps)
    parent = _get(ast, p[:-1]) if p else None
    if parent is not None and parent[0] == "not":
        return _set(ast, p[:-1], _get(ast, p))
    return _set(ast, p, ("not", _get(ast, p)))


def m_quant(ast, rng):
    def f(n):
        if n[0] == "forall" and n[2][0] == "imp":
            return ("exists", n[1], ("and", n[2][1], n[2][2]))
        if n[0] == "exists" and n[2][0] == "and":
            return ("forall", n[1], ("imp", n[2][1], n[2][2]))
        return None
    r = _first(ast, f)
    if r is not None:
        return r
    return _first(ast, lambda n: ({"forall": "exists", "exists": "forall"}[n[0]], n[1], n[2]) if n[0] in QUANTS else None)


def m_impl_rev(ast, rng):
    return _first(ast, lambda n: ("imp", n[2], n[1]) if n[0] == "imp" else None)


def m_drop(ast, rng):
    def f(n):
        if n[0] == "imp" and n[1][0] == "and":
            keep = n[1][1] if rng.random() < 0.5 else n[1][2]
            return ("imp", keep, n[2])
        return None
    r = _first(ast, f)
    if r is not None:
        return r
    return _first(ast, lambda n: n[1] if n[0] == "and" else None)


def m_add(ast, rng):
    def f(n):
        if n[0] == "imp":
            a = n[1]
            var = next((t for t in _terms(a) if t[0] == "var"), None) or next(iter(_terms(a)), None)
            if var is None:
                return None
            return ("imp", ("and", a, ("atom", "ZzAddedCond", (var,))), n[2])
        return None
    return _first(ast, f)


def _terms(n):
    op = n[0]
    if op in QUANTS:
        return _terms(n[2])
    if op == "not":
        return _terms(n[1])
    if op in BIN_OPS:
        return _terms(n[1]) + _terms(n[2])
    if op == "atom":
        return list(n[2])
    return []


def m_arg_swap(ast, rng):
    ps = [p for p in _atoms_paths(ast) if _get(ast, p)[0] == "atom" and len(_get(ast, p)[2]) >= 2
          and _get(ast, p)[2][0] != _get(ast, p)[2][-1]]
    if not ps:
        return None
    p = rng.choice(ps)
    a = _get(ast, p)
    return _set(ast, p, ("atom", a[1], tuple(reversed(a[2]))))


def m_andor(ast, rng):
    return _first(ast, lambda n: ({"and": "or", "or": "and"}[n[0]], n[1], n[2]) if n[0] in ("and", "or") else None)


OPS = {"NEG": m_neg, "QUANT": m_quant, "IMPL_REV": m_impl_rev, "DROP": m_drop, "ADD": m_add, "ARG_SWAP": m_arg_swap,
       "ANDOR": m_andor}


@logger.catch(reraise=True)
def main() -> None:
    setup_logging("s12c_perturb")
    fz = assert_frozen()
    c = fz["config"]
    cfg = DCConfig(use_L3=c["use_L3"], unalign_in_denominator=c["unalign_in_denominator"], weights=c["weights"],
                   half_caps=c["half_caps"], rule_1b=c["rule_1b"])
    W = json.loads((WORK / "fresh_dc_weights.json").read_text())["weights"]
    rows, _ = load_frame()
    groups = defaultdict(dict)
    for r in rows:
        groups[r["sid"]][r["system"]] = r["canon"]
    rng = random.Random(20260924)
    anchors = {}
    for r in sorted(rows, key=lambda r: (r["sid"], r["system"])):
        if r["S_status"] in ("equiv_proved", "equiv_bounded") and r["parse_ok"] and r["sid"] not in anchors:
            anchors[r["sid"]] = r
    muts = []
    for sid, r in anchors.items():
        A = parse_fol(r["canon"])
        for op, fn in OPS.items():
            try:
                M = fn(A, rng)
            except (IndexError, ValueError, KeyError):
                M = None
            if M is None:
                continue
            mc = dcanon(M)
            if mc == r["canon"]:
                continue
            try:
                rel = pair_relation(parse_fol(mc), A)["rel"]
            except (ValueError, KeyError):
                continue
            if rel in ("EQUIV", "UNKNOWN"):
                continue
            muts.append({"sid": sid, "system": r["system"], "op": op, "canon": mc, "anchor": r["canon"], "rel_to_anchor": rel})
    logger.info(f"anchors {len(anchors)}; verified mutants {len(muts)} {Counter(m['op'] for m in muts)}")
    jobs = [(m["canon"], c2) for m in muts for s, c2 in groups[m["sid"]].items() if c2 and s != m["system"]]
    run_pairs(jobs, workers=12, log=logger.info)
    cache = load_cache()
    res_rows = []
    tjobs = []
    base_cache = {}
    for i, m in enumerate(muts):
        if m["sid"] not in base_cache:
            g = groups[m["sid"]]
            base_cache[m["sid"]] = score_group({k: parse_fol(v) if v else None for k, v in g.items()},
                                               group_relations(g, cache, cfg), W, cfg)
        old = base_cache[m["sid"]][m["system"]]
        g2 = dict(groups[m["sid"]])
        g2[m["system"]] = m["canon"]
        new = score_group({k: parse_fol(v) if v else None for k, v in g2.items()}, group_relations(g2, cache, cfg), W, cfg)[m["system"]]
        res_rows.append((m, old, new))
        if new.get("mode_rep") and not new.get("in_mode"):
            tjobs.append((f"m{i}", m["canon"], g2[new["mode_rep"]]))
    typ = run_typing(tjobs, use_L3=cfg.use_L3)
    key = "type_1b_on" if cfg.rule_1b else "type_1b_off"
    from s05_fresh import vc_scores
    out = {}
    by_op = defaultdict(list)
    for i, (m, old, new) in enumerate(res_rows):
        t = "none" if new.get("in_mode") else typ.get(f"m{i}", {}).get(key, "other")
        by_op[m["op"]].append({"sid": m["sid"], "dc_old": old["score"], "dc_new": new["score"], "type": t,
                               "in_mode_new": new.get("in_mode"), "rel": m["rel_to_anchor"], "canon": m["canon"],
                               "anchor": m["anchor"], "system": m["system"]})
    rngb = np.random.default_rng(0)
    for op, L in by_op.items():
        det = np.array([1.0 if x["dc_old"] > x["dc_new"] else (0.5 if x["dc_old"] == x["dc_new"] else 0.0) for x in L])
        bs = [det[rngb.integers(0, len(det), len(det))].mean() for _ in range(1000)]
        # VC contrast on a subsample (VC is lexical; the mutation keeps names except ADD)
        vc = []
        for x in L[:150]:
            g = {f"{x['sid']}:{s}": c2 for s, c2 in groups[x["sid"]].items()}
            k0 = f"{x['sid']}:{x['system']}"
            a = vc_scores({x["sid"]: g}).get(k0, (0.5, False))[0]
            g[k0] = x["canon"]
            b = vc_scores({x["sid"]: g}).get(k0, (0.5, False))[0]
            vc.append(1.0 if a > b else (0.5 if a == b else 0.0))
        out[op] = {"n": len(L), "expected_type": OP_TYPE[op],
                   "detection_DC": float(det.mean()), "detection_DC_ci95": [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))],
                   "mutant_still_in_mode": float(np.mean([bool(x["in_mode_new"]) for x in L])),
                   "typing_accuracy": float(np.mean([x["type"] == OP_TYPE[op] for x in L])),
                   "type_distribution": dict(Counter(x["type"] for x in L)),
                   "relation_to_anchor": dict(Counter(x["rel"] for x in L)),
                   "detection_VC": float(np.mean(vc)) if vc else None,
                   "mean_DC_anchor": float(np.mean([x["dc_old"] for x in L])), "mean_DC_mutant": float(np.mean([x["dc_new"] for x in L]))}
    (RES / "perturbation_sensitivity.json").write_text(json.dumps({"note": "mechanism evidence only (Thatikonda et al. 2025): "
                                                                   "controlled mutants of solver-verified faithful anchors",
                                                                   "n_anchors": len(anchors), "by_operator": out}, indent=1))
    logger.info(json.dumps(out)[:3000])


if __name__ == "__main__":
    main()
