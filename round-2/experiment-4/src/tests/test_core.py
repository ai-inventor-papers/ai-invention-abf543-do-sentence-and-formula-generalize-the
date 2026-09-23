"""T0 unit tests (no API): canonical form, worlds, bridge, weighted AUROC, freeze guard."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import common  # noqa: E402,F401
import canon as K  # noqa: E402
import fol_core as fc  # noqa: E402

SS = json.loads((common.ARMB / "data" / "screen_set.json").read_text())
GOLDS = [s["gold_fol"] for s in SS["sentences"]]


def test_idempotent():
    for g in GOLDS[:50]:
        c = K.canon(g)
        assert K.canon(c) == c


def test_equivalent_to_source():
    for g in GOLDS:
        G, info = K.canon_ast(fc.parse(g))
        assert info["fallback"] is None or info["fallback"] == "not_prenexable"
        assert fc.bounded_equiv(G, fc.parse(g), nmax=4) == "equiv"


def test_implication_forms_share_canon():
    forms = ["∀x (A(x) → B(x))", "∀x (¬B(x) → ¬A(x))", "∀x (¬A(x) ∨ B(x))", "∀x ¬(A(x) ∧ ¬B(x))"]
    assert len({K.canon(f) for f in forms}) == 1


def test_xor_negation_forms():
    assert K.canon("¬(A(c) ↔ B(c))") == K.canon("A(c) ⊕ B(c)") == K.canon("¬A(c) ↔ B(c)")


def test_rename_skeleton_and_seed():
    a = K.canon_info("∀x (Dog(x) → Barks(x))")
    b = K.canon_info("∀x (Hound(x) → Yelps(x))")
    assert a["skeleton"] == b["skeleton"] and a["canon_seed"] == b["canon_seed"]


def test_reorder_identical():
    assert K.canon("∀x ((A(x) ∧ B(x)) → C(x))") == K.canon("∀x ((B(x) ∧ A(x)) → C(x))")


def test_find_world_deterministic():
    f = "∀x (Dog(x) → (Barks(x) ∨ Sleeps(x)))"
    w1, w2 = K.canonical_worlds(f), K.canonical_worlds(f)
    assert [w["true_atoms"] for w in w1["worlds"]] == [w["true_atoms"] for w in w2["worlds"]]


def test_world_key_relabel_invariant():
    w = {"n": 3, "consts": {"a": 0}, "true_atoms": [["P", [1]], ["R", [1, 2]]]}
    w2 = {"n": 3, "consts": {"a": 0}, "true_atoms": [["P", [2]], ["R", [2, 1]]]}
    assert K.world_key(w) == K.world_key(w2)


def test_bridge_roundtrip():
    from bridge import to_folio
    for s in ["forall x (Dog(x) -> Animal(x))", "∀x (dog(x) ^ cute(x) → loved(x))",
              "exists x (Student(x) & ~Lazy(x))", "∀x (Geologist(x, \"Alyssa\") → Expert(x))",
              "ProductOf(G-910, thisBrand)"]:
        a, how = to_folio(s)
        assert a is not None, (s, how)


def test_wauc_matches_sklearn():
    from sklearn.metrics import roc_auc_score
    from analysis2 import wauc
    rng = np.random.default_rng(0)
    y = rng.integers(0, 2, 300)
    s = np.round(rng.random(300), 1)
    w = rng.random(300) + 0.1
    assert abs(wauc(y, s, w) - roc_auc_score(y, s, sample_weight=w)) < 1e-9
    assert abs(wauc(y.astype(float), s, np.ones(300)) - roc_auc_score(y, s)) < 1e-9


def test_label_loader_guard(tmp_path, monkeypatch):
    import labels
    monkeypatch.setattr(labels, "RESULTS", tmp_path)
    with pytest.raises(labels.FreezeViolation):
        labels.check_receipt()
