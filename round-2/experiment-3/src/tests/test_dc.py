"""Unit tests for the DC library (run: .venv/bin/python -m pytest -q tests/test_dc.py).

Hand cases from the plan, adapted where lexical-free alignment makes the planned case ill-posed
(documented inline): single-letter names such as a/b are read as VARIABLES by the parser, so constants
are written john/mary; a bare reversed implication over two unary predicates is EQUIV under the
predicate swap, so the implication-direction case anchors one role with a binary predicate.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dc import DCConfig, align_pair, derive, directional_consensus, fit_weights, parse_fol, score_group, type_error  # noqa: E402
from dc.align import Caps  # noqa: E402
from dc.relation import converse  # noqa: E402


def R(a, b, L3=False):
    rec = align_pair(parse_fol(a), parse_fol(b))
    return derive(rec, use_L3=L3), rec


def T(a, b, L3=False, rule_1b=True):
    A, B = parse_fol(a), parse_fol(b)
    return type_error(A, B, align_pair(A, B), use_L3=L3, rule_1b=rule_1b)["type"]


def test_renamed_equivalent():
    d, _ = R("all x (Dog(x) -> Barks(x))", "all y (Hund(y) -> Bellt(y))")
    assert d["rel"] == "EQUIV" and d["lvl"] == 1


def test_added_conjunct():
    d, _ = R("∀x (D(x) ∧ Big(x) → B(x))", "∀x (D(x) → B(x))")
    assert d["rel"] == "WEAKER"
    assert T("∀x (D(x) ∧ Big(x) → B(x))", "∀x (D(x) → B(x))") == "added_condition"


def test_dropped_conjunct():
    d, _ = R("∀x (D(x) → B(x))", "∀x (D(x) ∧ Big(x) → B(x))")
    assert d["rel"] == "STRONGER"
    assert T("∀x (D(x) → B(x))", "∀x (D(x) ∧ Big(x) → B(x))") == "dropped_condition"


def test_L3_merges_added_conjunct_known_limit():
    """Lexical-free granularity cannot tell D∧Big (added condition) from a split concept: L3 makes it EQUIV.
    This is the 'search manufactures agreement' failure mode the dev grid must weigh."""
    d, _ = R("∀x (D(x) ∧ Big(x) → B(x))", "∀x (D(x) → B(x))", L3=True)
    assert d["rel"] == "EQUIV" and d["lvl"] == 3


def test_forall_exists():
    assert T("∃x (D(x) ∧ B(x))", "∀x (D(x) → B(x))") == "quantifier_forall_exists"


def test_reversed_implication_anchored():
    d, _ = R("∀x (Dog(x) → Likes(x, rex))", "∀x (Likes(x, rex) → Dog(x))")
    assert d["rel"] == "INCOMPARABLE"
    assert T("∀x (Dog(x) → Likes(x, rex))", "∀x (Likes(x, rex) → Dog(x))") == "implication_direction_or_only"


def test_negation_ground():
    d, _ = R("D(rex) ∧ B(rex)", "D(rex) ∧ ¬B(rex)")
    assert d["rel"] == "CONTRADICTORY"
    assert T("D(rex) ∧ B(rex)", "D(rex) ∧ ¬B(rex)", rule_1b=False) == "negation_polarity"


def test_negation_universal_rule_1b():
    d, _ = R("∀x (D(x) → ¬B(x))", "∀x (D(x) → B(x))")
    assert d["rel"] == "INCOMPARABLE"  # both hold when D is empty
    assert T("∀x (D(x) → ¬B(x))", "∀x (D(x) → B(x))", rule_1b=True) == "negation_polarity"


def test_argument_swap():
    a, b = "Loves(john, mary) ∧ Man(john)", "Loves(mary, john) ∧ Man(john)"
    d, _ = R(a, b)
    assert d["rel"] != "EQUIV"
    assert T(a, b) == "argument_swap"


def test_granularity_split_L3():
    d, rec = R("∀x (TallMan(x) → H(x))", "∀x (Tall(x) ∧ Man(x) → H(x))", L3=True)
    assert d["rel"] == "EQUIV" and d["lvl"] == 3 and rec["L3"].get("via_def")


def test_unalignable():
    # B shares only 1 of 5 symbol occurrences with A's arity structure -> no map covers >= 50%
    rec = align_pair(parse_fol("P(john)"), parse_fol("∀x ∀y (R(x, y) → S(x, y, x)) ∧ T(x, y, y, x)"))
    assert derive(rec, use_L3=False)["rel"] == "UNALIGNABLE"


def _dev_formulas(n=50):
    p = ROOT / "work" / "dev_frame.jsonl"
    if not p.exists():
        return []
    rows = [json.loads(x) for x in p.read_text().splitlines()[:4000] if x.strip()]
    fs = [r["cand"] for r in rows if r.get("parse_ok") and r.get("cand")]
    random.Random(0).shuffle(fs)
    return fs[:n]


def test_idempotence_dev():
    fs = _dev_formulas(50) or ["∀x (D(x) → B(x))"]
    for f in fs:
        A = parse_fol(f)
        if A is None:
            continue
        assert derive(align_pair(A, A, caps=Caps(pair_wall_s=30)), use_L3=False)["rel"] == "EQUIV", f


def test_symmetry_dev():
    fs = _dev_formulas(100)
    rng = random.Random(1)
    n_checked = n_bad = 0
    for i in range(0, min(len(fs) - 1, 100), 2):
        A, B = parse_fol(fs[i]), parse_fol(fs[i + 1])
        if A is None or B is None:
            continue
        r1 = derive(align_pair(A, B), use_L3=False)["rel"]
        r2 = derive(align_pair(B, A), use_L3=False)["rel"]
        if "UNKNOWN" in (r1, r2):
            continue
        n_checked += 1
        n_bad += r1 != converse(r2)
    # strongest-relation search is symmetric up to search caps; allow <= 5% asymmetry from capped search
    assert n_bad <= max(1, 0.05 * n_checked), (n_bad, n_checked)


def test_score_group_hand():
    outs = {s: parse_fol(f) for s, f in {"a": "∀x (D(x) → B(x))", "b": "∀y (P(y) → Q(y))",
                                           "c": "∀x (D(x) ∧ E(x) → B(x))", "d": None}.items()}
    rel = {}
    for s in outs:
        for t in outs:
            if s != t and outs[s] is not None and outs[t] is not None:
                rel[(s, t)] = derive(align_pair(outs[s], outs[t]), use_L3=False)["rel"]
    res = score_group(outs, rel, {"a": 1, "b": 1, "c": 2, "d": 1}, DCConfig(use_L3=False))
    assert abs(res["a"]["score"] - 1 / 3) < 1e-9  # EQUIV to b (w1) of b+c (w1+w2)
    assert abs(res["c"]["score"] - 0.0) < 1e-9 and res["c"]["mode_rep"] in ("a", "b")
    assert res["d"]["score"] == 0.5 and res["d"]["score_DC0"] == 0.0


def test_directional_consensus_api():
    r = directional_consensus("Every dog barks.", "∀x (Dog(x) → Barks(x))",
                              ["∀y (Hund(y) → Bellt(y))", "∀x (Dog(x) ∧ Big(x) → Barks(x))", "garbage((("],
                              cfg=DCConfig(use_L3=False))
    assert r["covered"] and abs(r["score"] - 0.5) < 1e-9 and r["n_peers_unparseable"] == 1


def test_weights_recover_reliability():
    """9 raters with known accuracies; wrong outputs land in one of 4 wrong clusters (so wrong answers can agree).
    With only 3 raters the one-coin model is weakly identified, so the check uses a 9-system panel as in the data."""
    from scipy.stats import spearmanr
    rng = random.Random(0)
    acc = {f"s{i}": a for i, a in enumerate([0.9, 0.85, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2])}
    sents = [{"cls": {s: (0 if rng.random() < a else rng.randint(1, 4)) for s, a in acc.items()}} for _ in range(600)]
    w, info = fit_weights(sents, list(acc))
    rho = spearmanr([acc[s] for s in acc], [info["p"][s] for s in acc]).statistic
    assert rho > 0.9, info
    assert w["s0"] > w["s8"]
