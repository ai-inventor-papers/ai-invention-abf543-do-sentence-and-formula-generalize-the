"""Unit tests: aligner (R1), polarity-blindness, solver signature hand cases, decoder, budget guard, firewall.
Run: .venv/bin/python -m pytest -q tests/test_align2.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "sigfaith"))
import core  # noqa: E402,F401
import align2  # noqa: E402
import decoder as D  # noqa: E402
import text_sig  # noqa: E402
from fol_parse import parse  # noqa: E402
from solver_sig import signature  # noqa: E402

CFG = {"tau": 0.45, "wn": "wup", "emb": "sentence-transformers/all-MiniLM-L6-v2", "beta": 0.1}


def _al(sent, fol, cfg=CFG):
    ex = text_sig.extract(sent)
    p = parse(fol)
    A = align2.align2(p.preds, p.consts, ex["concepts"], ex["anchors"], cfg)
    span = {c["cid"]: c["span"].lower() for c in ex["concepts"]}
    return A, span, ex


def test_wordnet_teacher_educator():
    A, span, _ = _al("Every teacher is patient.", "∀x (Educator(x) → Patient(x))")
    assert span[A["preds"]["Educator"]["cid"]] == "teacher"


def test_embedding_great_place():
    A, span, ex = _al("Paris is a great place.", "ExcellentLocation(paris)")
    cid = A["preds"]["ExcellentLocation"]["cid"]
    assert cid is not None and span[cid] in ("place", "great")


def test_constant_rex():
    A, span, _ = _al("Rex barks.", "Barks(rex)")
    assert span[A["consts"]["rex"]] == "rex"


def test_arity_term_relation():
    A, span, _ = _al("Every student likes some teacher.", "∀x (Student(x) → ∃y (Teacher(y) ∧ Adores(x, y)))")
    assert span[A["preds"]["Adores"]["cid"]] == "likes"


def test_polarity_blind_sim():
    s1, s2 = "Every dog that is trained barks.", "Every dog that is not trained barks."
    e1, e2 = text_sig.extract(s1), text_sig.extract(s2)
    syms = [("Dog", 1), ("Trained", 1), ("Bark", 1)]
    S1 = align2.sim_matrix(syms, e1["concepts"], e1["anchors"], CFG)[0]
    S2 = align2.sim_matrix(syms, e2["concepts"], e2["anchors"], CFG)[0]
    assert S1.shape == S2.shape and np.allclose(S1, S2)


@pytest.mark.parametrize("fol,expect", [
    ("∀x (Dog(x) → Bark(x))", {"Dog": "-", "Bark": "+"}),
    ("∀x ((Dog(x) ∧ (Loud(x) ∨ ¬Loud(x))) → Bark(x))", {"Dog": "-", "Bark": "+", "Loud": "0"}),
    ("∃x (Dog(x) ∧ Bark(x))", {"Dog": "+", "Bark": "+"}),
    ("¬∃x (Dog(x) ∧ Bark(x))", {"Dog": "-", "Bark": "-"}),
    ("∀x (Person(x) → (Rich(x) ⊕ Poor(x)))", {"Person": "-", "Rich": "±", "Poor": "±"}),
    ("¬Meows(tom) → ¬Cat(tom)", {"Meows": "+", "Cat": "-"}),
    ("∀x (Dog(x) → ¬Cat(x))", {"Dog": "-", "Cat": "-"}),
    ("∀x ((Dog(x) ∨ Cat(x)) → Pet(x))", {"Dog": "-", "Cat": "-", "Pet": "+"}),
    ("∀x (Bird(x) → (Fly(x) ∨ Swim(x)))", {"Bird": "-", "Fly": "+", "Swim": "+"}),
    ("∃x (Cat(x) ∧ ¬Black(x))", {"Cat": "+", "Black": "-"}),
    ("Cat(tom) ↔ Meows(tom)", {"Cat": "±", "Meows": "±"}),
    ("∀x ∀y (Parent(x, y) → Loves(x, y))", {"Parent": "-", "Loves": "+"}),
])
def test_solver_hand(fol, expect):
    assert signature(parse(fol).ast)["labels"] == expect


def test_decoder_rules():
    res = {"coords": [(1.0, True, {"type": "dropped", "cid": 0, "t": "-"})]}
    ev = D.evidence(res)
    assert D.rank_rule(ev, {}, True, True, ["quantifier_scope", "cardinality_numeric"])[0] == "dropped_condition"
    assert D.rank_rule(ev, {}, True, False, ["quantifier_scope", "cardinality_numeric"])[0] == D.NO_CHANGE
    assert D.rank_rule(ev, {}, False, False, [])[0] == "syntax_unparseable"


def test_budget_guard(tmp_path, monkeypatch):
    import llm
    L = llm.Ledger(path=tmp_path / "l.jsonl", cap=0.01)
    L.total = 0.009
    with pytest.raises(llm.BudgetExceeded):
        L.check(0.002)


def test_firewall(tmp_path, monkeypatch):
    import heldout_io
    fz = ROOT / "results" / "frozen_config.json"
    if not fz.exists():
        with pytest.raises(heldout_io.FirewallError):
            heldout_io.load_labels()
    else:
        monkeypatch.setattr(heldout_io, "hash_tree", lambda: {"sigfaith/x.py": "edited"})
        with pytest.raises(heldout_io.FirewallError):
            heldout_io.load_labels()
