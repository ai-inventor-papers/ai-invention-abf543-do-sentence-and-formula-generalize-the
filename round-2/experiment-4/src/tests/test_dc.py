"""T0 unit tests for the DC engine (hand formulas). Documented blind spots are asserted AS blind spots."""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import dc.common  # noqa: E402,F401  (env: NLTK_DATA, thread caps)
from dc import best_relation  # noqa: E402
from dc.align import align_pair  # noqa: E402
from dc.core import directional_consensus  # noqa: E402
from dc.front import canon, parse_canon  # noqa: E402
from dc.pairs import compute_record, oriented  # noqa: E402
import fol_core as fc  # noqa: E402


def rel(a, b):
    return best_relation(canon(a)["canon"], canon(b)["canon"])


HAND = ["∀x (Dog(x) → Bark(x))", "∃x (Cat(x) ∧ ¬Black(x))", "Likes(john, mary)", "∀x ∀y (Parent(x, y) → Loves(x, y))",
        "¬∃x (Fish(x) ∧ Fly(x))", "∀x ((Student(x) ∧ Tall(x)) → ∃y (Book(y) ∧ Reads(x, y)))", "Happy(anna) ∨ Sad(anna)",
        "∀x (Bird(x) → (Fly(x) ⊕ Penguin(x)))", "∃x (Teacher(x) ∧ ∀y (Student(y) → Knows(x, y)))",
        "∀x (Employee(x) ↔ (Paid(x) ∧ Works(x)))"]


def test_rename_invariance():
    for f in HAND:
        A = parse_canon(canon(f)["canon"])
        pm = {p: f"Q{i}zz" for i, p in enumerate(sorted(fc.predicates(A)))}
        cm = {c: f"k{i}q" for i, c in enumerate(fc.constants(A))}
        B = fc.rename(A, pm, cm)
        r = best_relation(fc.to_str(A), fc.to_str(B))
        assert r["rel"] == "EQUIV" and r["rel_L1"] == "EQUIV", (f, r["rel"])


def test_added_restrictor_direction_and_L3_blind_spot():
    r = rel("∀x (Dog(x) → Bark(x))", "∀x ((Dog(x) ∧ Brown(x)) → Bark(x))")
    assert r["rel_L2"] == "STRONGER"          # the unrestricted rule entails the restricted one
    assert r["rel_L3"] == "EQUIV"             # DOCUMENTED blind spot: Dog__s := Dog ∧ Brown absorbs the restrictor


def test_quant_flip():
    assert rel("∀x Bark(x)", "∃x Bark(x)")["rel"] == "STRONGER"
    assert rel("∃x Bark(x)", "∀x Bark(x)")["rel"] == "WEAKER"


def test_neg_contradictory():
    assert rel("Bark(rex)", "¬Bark(rex)")["rel"] == "CONTRADICTORY"


def test_L3_granular_equiv():
    r = rel("∀x (BrownDog(x) → Bark(x))", "∀x ((Brown(x) ∧ Dog(x)) → Bark(x))")
    assert r["rel_L2"] != "EQUIV" and r["rel_L3"] == "EQUIV" and r["level"] == 3


def test_automorphism_blind_spot():
    r = rel("∀x (A(x) → B(x))", "∀x (B(x) → A(x))")
    assert r["rel_L1"] == "EQUIV"             # lexical-free alignment swaps A and B
    assert r["rel_lex"] != "EQUIV"            # the lexically anchored map does not


def test_unalignable():
    assert rel("∀x (A(x) → B(x))", "∀x ∀y (R(x, y) → S(x, y))")["rel"] == "UNALIGNABLE"


def test_dc_half_with_few_covered_peers():
    r = directional_consensus("s", "∀x (A(x) → B(x))", ["∀x ∀y (R(x, y) → S(x, y))", None, ""])
    assert r["score"] == 0.5 and not r["covered"]
    r = directional_consensus("s", None, ["∀x (A(x) → B(x))", "∀x (C(x) → D(x))"])
    assert r["score"] == 0.5 and not r["covered"]


def test_cache_orientation_flip():
    a, b = canon("∀x Bark(x)")["canon"], canon("∃x Bark(x)")["canon"]
    rec = compute_record(a, b)
    assert oriented(rec, a == rec["lo"])["rel"] == "STRONGER"
    assert oriented(rec, b == rec["lo"])["rel"] == "WEAKER"
    with tempfile.TemporaryDirectory() as d:
        from dc.common import PairStore
        st = PairStore(Path(d) / "p.jsonl")
        st.d[rec["k"]] = rec
        assert st.get(a, b)["rel"] == "STRONGER" and st.get(b, a)["rel"] == "WEAKER"


def test_name_independent_map_ordering():
    f1 = parse_canon(canon("∀x ((Student(x) ∧ Tall(x)) → ∃y (Book(y) ∧ Reads(x, y)))")["canon"])
    f2 = parse_canon(canon("∀x (Tall(x) → ∃y (Reads(x, y)))")["canon"])
    L1 = align_pair(f1, f2)
    pm = {"Student": "Zq1", "Tall": "Aa2", "Book": "Mm3", "Reads": "Bb4"}
    L2 = align_pair(fc.rename(f1, pm, {}), fc.rename(f2, pm, {}))
    assert [(x["level"], x["agree"]) for x in L1] == [(x["level"], x["agree"]) for x in L2]
    inv = {v: k for k, v in pm.items()}
    ren = [sorted((k[0], inv.get(k[1], k[1]), inv.get(v, v) if v else None) for k, v in x["map"].items()) for x in L2]
    assert [sorted((k[0], k[1], v) for k, v in x["map"].items()) for x in L1] == ren


def test_toy_dc_five_peers():
    fol = "∀x (Dog(x) → Animal(x)) ∧ Dog(rex)"
    peers = ["∀x (Canine(x) → Beast(x)) ∧ Canine(fido)", "Dog(rex) ∧ ∀y (Dog(y) → Animal(y))",
             "∀z (D(z) → A(z)) ∧ D(rover)", "Animal(rex) ∧ Dog(rex)", "∀x ∀y (Likes(x, y) → Knows(x, y))"]
    r = directional_consensus("s", fol, peers)
    rels = [p["rel"] for p in r["per_peer"]]
    assert rels == ["EQUIV", "EQUIV", "EQUIV", "STRONGER", "UNALIGNABLE"], rels
    assert abs(r["score"] - 0.6) < 1e-9 and r["error_type"] == "none"


def test_toy_dropped_type():
    # a dropped RELATION cannot be absorbed by unary granularity definitions -> typed 'dropped'
    mode = ["∃x ∃y (Dog(x) ∧ Owns(x, y) ∧ Cat(y))", "∃y ∃x (Cat(x) ∧ Owns(y, x) ∧ Dog(y))",
            "∃x ∃y (Canine(x) ∧ Has(x, y) ∧ Feline(y))"]
    cand = "∃x ∃y (Dog(x) ∧ Cat(y))"
    r = directional_consensus("s", cand, mode)
    assert r["score"] == 0.0 and r["rel_to_mode"] == "WEAKER" and r["error_type"] == "dropped_condition", r
    # a dropped UNARY conjunct is absorbed at L3 (DOCUMENTED blind spot) but not at L2
    mode2 = ["∃x (Dog(x) ∧ Brown(x) ∧ Bark(x))", "∃y (Brown(y) ∧ Dog(y) ∧ Bark(y))", "∃x (Canine(x) ∧ Tan(x) ∧ Woof(x))"]
    cand2 = "∃x (Dog(x) ∧ Bark(x))"
    assert directional_consensus("s", cand2, mode2, rel_key="rel_L2", with_type=False)["score"] == 0.0
    assert directional_consensus("s", cand2, mode2, rel_key="rel_L3", with_type=False)["score"] == 1.0
