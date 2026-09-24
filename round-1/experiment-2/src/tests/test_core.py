"""T0 unit tests: parser, equivalence, py_eval vs z3, verbalizer, world finder, consequence labeller."""
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("NLTK_DATA", str(ROOT / "nltk_data"))

import z3  # noqa: E402

import fol_core as fc  # noqa: E402
from instance_nli import A1, A2, build_items, label_pairs  # noqa: E402
from mutants import OPERATORS, make_mutant, make_rewrites  # noqa: E402
from tvjt import find_world  # noqa: E402
from verbalize import const_name, fact  # noqa: E402

PROTO = ["∀x ((Dog(x) ∧ ¬Trained(x)) → Bark(x))", "∀x (¬Bark(x) → (¬Dog(x) ∨ Trained(x)))",
         "∀x ((Dog(x) ∧ Trained(x)) → Bark(x))", "∃x (Dog(x) ∧ ¬Trained(x) ∧ Bark(x))",
         "∀x (Bark(x) → (Dog(x) ∧ ¬Trained(x)))", "∀x (Dog(x) → Bark(x))",
         "∀x ((Dog(x) ∧ ¬Trained(x) ∧ (Loud(x) ∨ ¬Loud(x))) → Bark(x))",
         "∀x (Student(x) → ∃y (Book(y) ∧ Reads(x, y)))", "∀x (Student(x) → ∃y (Book(y) ∧ Reads(y, x)))",
         "∃y (Book(y) ∧ ∀x (Student(x) → Reads(x, y)))", "∀x (Person(x) → (Rich(x) ⊕ Poor(x)))",
         "¬Meows(tom) → ¬Cat(tom)"]
PROBES = [("∀x ((Dog(x) ∨ Cat(x)) → Pet(x))", "∀x ((Dog(x) ∧ Cat(x)) → Pet(x))"),
          ("∀x (Dog(x) → (Bark(x) ∧ Bite(x)))", "∀x (Dog(x) → (Bark(x) ∨ Bite(x)))"),
          ("∀x ((Dog(x) ∧ ¬Trained(x)) → Bark(x)) ∧ ∀x ((Dog(x) ∧ Trained(x)) → Sit(x))",
           "∀x ((Dog(x) ∧ Trained(x)) → Bark(x)) ∧ ∀x ((Dog(x) ∧ ¬Trained(x)) → Sit(x))"),
          ("∀x ((Provider(x) ∧ ¬Sme(x)) → Register(x)) ∧ ∀x ((Provider(x) ∧ Sme(x)) → Notify(x))",
           "∀x ((Provider(x) ∧ ¬Sme(x)) → Register(x)) ∧ ∀x ((Provider(x) ∧ ¬Sme(x)) → Notify(x))"),
          ("∀x (Deployer(x) ↔ (Person(x) ∧ UsesSystem(x)))", "∀x ((Person(x) ∧ UsesSystem(x)) → Deployer(x))"),
          ("∀x (Person(x) → (Rich(x) ⊕ Poor(x)))", "∀x (Person(x) → (Rich(x) ∨ Poor(x)))"),
          ("Cat(tom) ∧ ¬Meows(ann)", "Cat(ann) ∧ ¬Meows(tom)")]


def test_parser_roundtrip_and_enum_bug():
    for f in PROTO + [x for p in PROBES for x in p]:
        a = fc.parse(f)
        b = fc.parse(fc.to_str(a))
        assert fc.bounded_equiv(a, b) == "equiv"
        # parse/solve twice: the prototype crashed on the 2nd EnumSort with the same name
        assert fc.satisfiable(a) in ("sat", "unsat")
        assert fc.satisfiable(fc.parse(f)) in ("sat", "unsat")


def test_equivalences():
    g = fc.parse(PROTO[0])
    assert fc.bounded_equiv(g, g) == "equiv"
    assert fc.bounded_equiv(g, fc.parse(PROTO[1])) == "equiv"
    assert fc.unbounded_equiv(g, fc.parse(PROTO[1])) == "equiv"
    rw = [r for r in make_rewrites(g, "t", k=5) if r["kind"] == "RENAME"]
    assert rw and fc.find_bijections(rw[0]["ast"], g)["label"] == "equiv"
    for op in OPERATORS:
        m = make_mutant(g, op, "t")
        if m["kept"]:
            assert fc.bounded_equiv(m["ast"], g) == "nonequiv"


def test_reversed_implication_documented():
    a, b = fc.parse("∀x (Bark(x) → Dog(x))"), fc.parse("∀x (Dog(x) → Bark(x))")
    assert fc.find_bijections(a, b)["label"] == "equiv"      # blind label passes it (known flaw)
    assert fc.label_trigram(a, b)["label"] == "nonequiv"     # trigram-anchored label catches it


def test_py_eval_matches_z3():
    rng = random.Random(0)
    for f in (PROTO + [x for p in PROBES for x in p])[:20]:
        ast = fc.parse(f)
        preds, consts = fc.predicates(ast), fc.constants(ast)
        for interp, dom in fc.random_interps(preds, consts, 10, seed=rng.randrange(10**6)):
            g = fc.Grounder(dom, consts, una=False)
            fz = g.g(ast)
            s = z3.Solver()
            for (p, tup), v in g.atoms.items():
                s.add(v if tup in interp["P"].get(p, set()) else z3.Not(v))
            for c, v in g.C.items():
                s.add(v == interp["C"][c])
            s.add(fz)
            assert (s.check() == z3.sat) == fc.py_eval(ast, interp, dom)


def test_verbalizer():
    exp = {("Bark", ("Alex",)): "Alex barks", ("Trained", ("Alex",)): "Alex is trained",
           ("ParentOf", ("Alex", "Blair")): "Alex is parent of Blair",
           ("LocatedIn", ("Alex", "Blair")): "Alex is located in Blair",
           ("WildTurkey", ("Alex",)): "Alex is a wild turkey", ("Write", ("Alex", "Blair")): "Alex writes Blair",
           ("Dog", ("Alex",)): "Alex is a dog", ("Student", ("Alex",)): "Alex is a student",
           ("Perform", ("Alex",)): "Alex performs", ("Young", ("Alex",)): "Alex is young",
           ("Wrote", ("Alex", "Blair")): "Alex wrote Blair", ("Employee", ("Alex",)): "Alex is an employee",
           ("Meows", ("Alex",)): "Alex meows", ("Schedule", ("Alex", "Blair")): "Alex schedules Blair"}
    for (p, args), s in exp.items():
        assert fact(p, list(args)) == s, (p, fact(p, list(args)), s)
    assert fact("Bark", ["Alex"], False) == "Alex does not bark"
    assert fact("Meows", ["Alex"], False) == "Alex does not meow"
    assert const_name("symphonyNo9") == "Symphony No 9"


def test_world_finder():
    F = fc.parse(PROTO[0])
    M = make_mutant(F, "NEG", "t")["ast"]
    w = find_world(F, M, prefer=0)
    interp = {"P": {}, "C": w["consts"]}
    for p, t in w["true_atoms"]:
        interp["P"].setdefault(p, set()).add(tuple(t))
    assert fc.py_eval(F, interp, w["n"]) != fc.py_eval(M, interp, w["n"])
    assert fc.py_eval(F, interp, w["n"]) == w["F_value"]


def test_consequence_labeller_scope_visibility():
    F = fc.parse("∀x (Student(x) → ∃y (Book(y) ∧ Reads(x, y)))")
    S = fc.parse("∃y (Book(y) ∧ ∀x (Student(x) → Reads(x, y)))")
    items = build_items(F, "t")
    P = ((("Student", A1, True), ("Student", A2, True)))
    items["premises"] = [P]
    q1 = ("Q1", ("exists", "y", ("and", ("atom", "Book", (("v", "y"),)), ("atom", "Reads", (("c", A1), ("v", "y"))),
                                 ("atom", "Reads", (("c", A2), ("v", "y"))))), ("Reads", "Book"))
    ex = ("Q2x", ("exists", "y", ("atom", "Reads", (("c", A1), ("v", "y")))), ())
    items["hyps"] = [q1, ex]
    lf = label_pairs(F, items, pairs=[(0, 0), (0, 1)])["labels"]
    assert lf[(0, 0)] == "N" and lf[(0, 1)] == "E"
    ls = label_pairs(S, items, pairs=[(0, 0)])["labels"]
    assert ls[(0, 0)] == "E"
