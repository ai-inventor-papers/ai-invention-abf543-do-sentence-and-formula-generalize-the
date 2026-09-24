"""Quick toy-pair sanity check of dc.core.pair_relation (prints relation, level, timing, map)."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dc.core import pair_relation  # noqa: E402

CASES = [
    ("∀x ((Bird(x) ∧ ¬Penguin(x)) → CanFly(x))", "∀y ((Zz(y) ∧ ¬Qq(y)) → Rr(y))", "EQUIV"),
    ("∀x (TallMan(x) → Happy(x))", "∀x ((Tall(x) ∧ Man(x)) → Happy(x))", "EQUIV"),
    ("∀x ((Tall(x) ∧ Man(x)) → Happy(x))", "∀x (TallMan(x) → Happy(x))", "EQUIV"),
    ("∀x ((Bird(x) ∧ ¬Penguin(x)) → CanFly(x))", "∀x (Bird(x) → CanFly(x))", "WEAKER"),
    ("∀x (P(x) → Q(x))", "¬∀x (P(x) → Q(x))", "CONTRADICTORY"),
    ("P(a)", "∀x ∀y R(x, y)", "UNALIGNABLE"),
    ("∀x (P(x) → Q(x))", "∀x (Q(x) → P(x))", None),
    ("∀x (P(x) → Q(x))", "∃x (P(x) ∧ Q(x))", None),
]

if __name__ == "__main__":
    for a, b, exp in CASES:
        t = time.time()
        r = pair_relation(a, b)
        print(f"{r['relation']:26s} exp={exp} L{r.get('level')} {time.time() - t:.2f}s maps={r.get('n_maps')} "
              f"z3={r.get('n_z3')} map={r.get('map')} defs={r.get('defs')}", flush=True)
