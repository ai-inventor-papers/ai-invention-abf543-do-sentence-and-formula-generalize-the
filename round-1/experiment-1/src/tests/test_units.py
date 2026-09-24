"""T0 unit tests (testing plan): parser, sig_abs, anchors, sig_rel, labeler, rules marker, aligner.
Run: NLTK_DATA=.nltk_data .venv/bin/python -m pytest -q tests/test_units.py   (or plain python)"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from align import align  # noqa: E402
from fol_parse import parse  # noqa: E402
from labeler import identity_equiv, label  # noqa: E402
from solver_sig import signature  # noqa: E402

GOLD = "∀x ((Dog(x) ∧ ¬Trained(x)) → Bark(x))"


def test_a_parser_folio_gold_rate():
    rows = [json.loads(l) for l in (ROOT / "data/raw/folio-validation.jsonl").read_text().splitlines() if l.strip()]
    fols = [f for r in rows for f in r["premises-FOL"]] + [r["conclusion-FOL"] for r in rows]
    ok = 0
    for f in fols:
        try:
            parse(f)
            ok += 1
        except Exception:  # noqa: BLE001
            pass
    assert ok / len(fols) >= 0.95, ok / len(fols)


def test_b_sig_abs_table():
    s = signature(parse(GOLD).ast)["labels"]
    assert s == {"Dog": "-", "Trained": "+", "Bark": "+"}
    assert signature(parse("∀x (¬Bark(x) → (¬Dog(x) ∨ Trained(x)))").ast)["labels"] == s
    assert signature(parse("∀x ((Dog(x) ∧ (Loud(x) ∨ ¬Loud(x))) → Bark(x))").ast)["labels"]["Loud"] == "0"
    assert signature(parse("∀x (Person(x) → (Rich(x) ⊕ Poor(x)))").ast)["labels"]["Rich"] == "±"
    a = signature(parse("∀x (Student(x) → ∃y (Book(y) ∧ Reads(x, y)))").ast)["anchors"]
    b = signature(parse("∀x (Student(x) → ∃y (Book(y) ∧ Reads(y, x)))").ast)["anchors"]
    assert a["Reads|0|Student"] and b["Reads|1|Student"] and a != b


def test_c_sig_rel_separates_andor_and_exceptions():
    def diff(g, c):
        x, y = signature(parse(g).ast)["rel"], signature(parse(c).ast)["rel"]
        return sum(1 for k in x if x[k] != y.get(k))
    assert diff("∀x ((Dog(x) ∨ Cat(x)) → Pet(x))", "∀x ((Dog(x) ∧ Cat(x)) → Pet(x))") >= 6
    assert diff("∀x ((Dog(x) ∧ ¬Trained(x)) → Bark(x)) ∧ ∀x ((Dog(x) ∧ Trained(x)) → Sit(x))",
                "∀x ((Dog(x) ∧ Trained(x)) → Bark(x)) ∧ ∀x ((Dog(x) ∧ ¬Trained(x)) → Sit(x))") >= 6
    assert diff(GOLD, "∀x (¬Bark(x) → (¬Dog(x) ∨ Trained(x)))") == 0


def test_d_labeler():
    g = parse(GOLD).ast
    for eq in ["∀x ((Hound(x) ∧ ¬Taught(x)) → Yap(x))", "∀x (¬Bark(x) → (¬Dog(x) ∨ Trained(x)))",
               "∀x (¬(¬Dog(x) ∨ Trained(x)) → Bark(x))"]:
        assert label(parse(eq).ast, g)["status"] == "equiv"
    for ne in ["∀x ((Dog(x) ∧ Trained(x)) → Bark(x))", "∃x (Dog(x) ∧ ¬Trained(x) ∧ Bark(x))", "∀x (Dog(x) → Bark(x))"]:
        assert label(parse(ne).ast, g)["status"] == "nonequiv"
    signature(g)
    signature(g)  # profiling the same formula twice must not crash (unique names)
    assert identity_equiv(g, g) == "equiv"


def test_e_rules_marker():
    import text_sig
    ex = text_sig.extract("No student who smokes is healthy.")
    labs = {c["span"]: ex["marker"][c["cid"]] for c in ex["concepts"]}
    assert labs == {"student": "-", "smokes": "-", "healthy": "-"}
    ex = text_sig.extract("Tom is not a cat unless he meows.")  # must not crash on 'unless'
    assert {c["span"]: ex["marker"][c["cid"]] for c in ex["concepts"] if not c["is_const"]} == {"cat": "-", "meows": "+"}


def test_f_aligner_compound_head():
    import text_sig
    ex = text_sig.extract("All dogs that are not trained bark.")
    A = align({"UntrainedDog": 1, "Bark": 1}, [], ex["concepts"])
    dog = [c["cid"] for c in ex["concepts"] if c["head_lemma"] == "dog"][0]
    assert A["preds"]["UntrainedDog"]["cid"] == dog


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS", name)
