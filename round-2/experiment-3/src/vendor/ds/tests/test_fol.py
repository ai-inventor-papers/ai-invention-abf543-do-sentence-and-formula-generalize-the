"""Unit tests: 15 hand formulas (parse -> print -> parse round trip) + equivalence sanity."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pytest
from fol_parse import parse, to_str, extract_formula
from fol_equiv import equivalence, sat_valid_check

HAND = [
    "∀x (Bird(x) ∧ ¬Penguin(x) → CanFly(x))",
    "∃x (Dog(x) ∧ Loves(john, x))",
    "∀x ∀y (Parent(x, y) → Older(x, y))",
    "forall x (Student(x) -> exists y (Course(y) & Takes(x, y)))",
    "∀x,y (Friend(x, y) ↔ Friend(y, x))",
    "∀x y (R(x,y) → ¬R(y,x))",
    "is_competitive(Legend) ⊕ has_athletic_build(Legend)",
    "~(Rain | Snow) => Dry",
    "∀x (Gemstone(x) → ((Diamond(x) ∧ ¬(Ruby(x) ∨ Emerald(x))) ∨ (Ruby(x) ∧ ¬(Diamond(x) ∨ Emerald(x)))))",
    "∀x. (Human(x) → Mortal(x))",
    "∀x (P(x) xor Q(x))",
    "∃x ∃y (Likes(x, y) ∧ x ≠ y)",
    "¬∀x (Swan(x) → White(x))",
    "∀x Bird(x) ∧ ¬Penguin(x) → CanFly(x)",
    "```\nFormula: ∀x (Cat(x) → Mammal(x)).\n```",
]


@pytest.mark.parametrize("s", HAND)
def test_roundtrip(s):
    r = parse(extract_formula(s))
    assert r.ok, (s, r.error)
    r2 = parse(to_str(r.ast))
    assert r2.ok and r2.ast == r.ast, (to_str(r.ast), r2.error)


def test_wide_scope_repair():
    a = parse("∀x Bird(x) ∧ ¬Penguin(x) → CanFly(x)").ast
    b = parse("∀x (Bird(x) ∧ ¬Penguin(x) → CanFly(x))").ast
    assert a == b


def test_function_terms_rejected():
    assert not parse("∀x (P(f(x)))").ok
    assert not parse("oh ⊆ r").ok


EQ = [  # (cand, gold, expected equivalent?)
    ("∀x (A(x) → B(x))", "∀y (¬Q(y) → ¬P(y))", True),          # contrapositive + renaming
    ("¬(A(c) ∧ B(c))", "¬P(d) ∨ ¬Q(d)", True),                   # De Morgan + const renaming
    ("∀x (A(x) → B(x))", "∀x (B(x) → A(x))", False),             # needs bijection A<->B -> equiv under swap!
    ("∀x (A(x) → B(x))", "∃x (A(x) ∧ B(x))", False),
    ("∀x (Dog(x) → ∃y Loves(x, y))", "∃y ∀x (Dog(x) → Loves(x, y))", False),  # scope
    ("∀x (A(x) ∧ B(x) → C(x))", "∀x (A(x) → (B(x) → C(x)))", True),
    ("Loves(john, mary)", "Loves(mary, john)", True),            # constants swap under bijection
    ("Loves(john, mary) ∧ Tall(john)", "Loves(mary, john) ∧ Tall(john)", False),
    ("∀x (A(x) → B(x))", "∀x (A(x) ∨ B(x))", False),
]


@pytest.mark.parametrize("c,g,exp", EQ)
def test_equivalence(c, g, exp):
    r = equivalence(parse(c).ast, parse(g).ast, time_limit=20)
    if exp:
        assert r["status"] in ("equiv_proved", "equiv_bounded"), r
    else:
        # the implication-reversal case IS equivalent under the A<->B swap: bijection labels are strict only up to renaming
        if c == "∀x (A(x) → B(x))" and g == "∀x (B(x) → A(x))":
            assert r["status"] in ("equiv_proved", "equiv_bounded")
        else:
            assert r["status"] == "non_equiv", r


def test_no_bijection():
    r = equivalence(parse("∀x (A(x) → B(x))").ast, parse("∀x (A(x) ∧ C(x) → B(x))").ast)
    assert r["status"] == "non_equiv_no_bijection"


def test_entailment_hint():
    r = equivalence(parse("∀x (A(x) ∧ C(x) → B(x))").ast, parse("∀x (P(x) ∧ R(x) → Q(x) ∧ S(x))").ast)
    assert r["status"] in ("non_equiv_no_bijection",)
    r = equivalence(parse("∀x (A(x) → B(x) ∧ C(x))").ast, parse("∀x (A(x) → B(x) ∨ C(x))").ast)
    assert r["status"] == "non_equiv" and r["entail_cand_to_gold"] is True and r["entail_gold_to_cand"] is False


def test_sat_valid():
    assert sat_valid_check(parse("P(a) ∧ ¬P(a)").ast)["unsat_bounded"]
    assert sat_valid_check(parse("∀x (P(x) ∨ ¬P(x))").ast)["valid_bounded"]
    v = sat_valid_check(parse("∀x (P(x) → Q(x))").ast)
    assert v["satisfiable"] and not v["valid_bounded"]
