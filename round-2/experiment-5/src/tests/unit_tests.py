#!/usr/bin/env python3
"""T0 unit tests (no API) -> results/unit_tests.json. Every check records expected vs observed; failures are REPORTED,
not hidden (several are genuine identifiability limits of name-blind alignment)."""
from __future__ import annotations

import glob
import hashlib
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "vendor" / "ds"))
from dc.api import error_type, score_from_relations  # noqa: E402
from dc.core import Formula, align_pair, pair_relation  # noqa: E402
from fol_equiv import equivalence  # noqa: E402
from fol_parse import parse  # noqa: E402

R = {"checks": []}


def check(name, expected, observed, note=""):
    ok = expected == observed if not callable(expected) else bool(expected(observed))
    R["checks"].append({"name": name, "expected": expected if not callable(expected) else "predicate", "observed": observed,
                        "pass": ok, "note": note})
    print(("PASS " if ok else "FAIL ") + name, observed, flush=True)


# 1 parser on the pilot formulas
e2 = json.loads((ROOT / "vendor" / "ds" / "work" / "e2_rows.json").read_text())
check("vendor parser parses 289/367 pilot formulas", 289, sum(parse(r["candidate_fol"]).ok for r in e2))
check("parser rejects '⊆' between variables", False, parse("∀x ∀y (Sub(x) → x ⊆ y)").ok)

# 2 calibration rewrites -> EQUIV; drop_conjunct mutants -> STRONGER/WEAKER
cal = json.loads((ROOT / "vendor" / "ds" / "work" / "calibration_set.json").read_text())
rw = [c for c in cal if c["kind"] == "rewrite"]
obs = [pair_relation(c["formula"], c["gold"])["relation"] for c in rw]
check("EQUIV on the 10 calibration equivalent rewrites", 10, sum(o == "EQUIV" for o in obs), f"relations {obs}")
dc_m = [c for c in cal if c["op"] == "drop_conjunct"]
obs = [pair_relation(c["formula"], c["gold"])["relation"] for c in dc_m]
check("drop_conjunct calibration mutants -> STRONGER/WEAKER (not EQUIV)", lambda o: all(x in ("STRONGER", "WEAKER") for x in o), obs,
      "EQUIV here would mean L3 granularity absorbed the dropped conjunct (formula-only identifiability limit)")
neg = [c for c in cal if c["op"] == "negation_flip"]
obs = [pair_relation(c["formula"], c["gold"])["relation"] for c in neg]
check("negation-flip calibration mutants are never EQUIV", lambda o: "EQUIV" not in o, obs,
      "pre-registered relation order ranks COMPATIBLE-INCOMPARABLE above CONTRADICTORY, so a negation flip reads as "
      "INCOMPARABLE whenever another arity-preserving map is jointly satisfiable")
check("CONTRADICTORY on the negation of a satisfiable formula (single map)", "CONTRADICTORY",
      pair_relation("∀x (P(x) ∧ Q(x))", "¬∀x (P(x) ∧ Q(x))")["relation"])
check("UNALIGNABLE on arity-mismatched toy pair", "UNALIGNABLE", pair_relation("P(a) ∧ Q(b)", "∀x ∀y R(x, y)")["relation"])

# 3 name-blind identity-up-to-renaming
rng = random.Random(0)
f = "∀x ((Provider(x) ∧ ¬PublicAuthority(x) ∧ Places(x, m)) → (Obliged(x) ∨ Exempt(x)))"
names = {"Provider": "Qzx", "PublicAuthority": "Wvb", "Places": "Kjh", "Obliged": "Plm", "Exempt": "Rty"}
g = f
for a, b in names.items():
    g = g.replace(a + "(", b + "(")
r = pair_relation(f, g)
inv = {v: k for k, v in names.items()}
check("align_pair finds the renaming map (random names)", True, r["relation"] == "EQUIV" and all(inv[b] == a for b, a in (r["map"] or {}).items()),
      f"map {r['map']}")
first = next(align_pair(Formula(f), Formula(g)))
check("first L1 map proposed by the structural order is the renaming", True, all(inv[b] == a for b, a in first[1].items()), str(first[1]))

# 4 L3 granularity
check("L3: TallMan(x) vs Tall(x) ∧ Man(x) -> EQUIV", "EQUIV", pair_relation("∀x (TallMan(x) → Happy(x))", "∀x ((Tall(x) ∧ Man(x)) → Happy(x))")["relation"])
check("L3 does not absorb a dropped EXCEPTION (negated restrictor)", "WEAKER",
      pair_relation("∀x ((Bird(x) ∧ ¬Penguin(x)) → CanFly(x))", "∀x (Bird(x) → CanFly(x))")["relation"])

# 5 DC synthetic: 4 EQUIV, 1 STRONGER, 1 UNALIGNABLE, weights 1 -> 4/6
sc = score_from_relations(["EQUIV"] * 4 + ["STRONGER", "UNALIGNABLE"], [1.0] * 6)
check("DC synthetic (4 EQUIV, 1 STRONGER, 1 UNALIGNABLE) = 4/6", round(4 / 6, 6), round(sc["score"], 6))
C = "∀x ((Provider(x) ∧ ¬PublicAuthority(x)) → Obliged(x))"
peers = [C.replace("Provider", "Prov"), C, "∀y ((Provider(y) ∧ ¬PublicAuthority(y)) → Obliged(y))",
         "∀x (¬Obliged(x) → (¬Provider(x) ∨ PublicAuthority(x)))", "∀x (Provider(x) → Obliged(x))", "∀x ∀y Rel(x, y)"]
rels = [pair_relation(C, p)["relation"] for p in peers]
sc = score_from_relations(rels, [1.0] * len(rels))
check("DC end-to-end synthetic sentence (4 equivalent, 1 stronger, 1 unalignable)", round(4 / 6, 6), round(sc["score"], 6), f"relations {rels}")

# 6 error types vs the mode
M = Formula("∀x ((Provider(x) ∧ Placed(x) ∧ ¬Public(x)) → Obliged(x))")
tests = {
    "drop negated restrictor (exception) -> dropped_condition": ("∀x ((Provider(x) ∧ Placed(x)) → Obliged(x))", "dropped_condition"),
    "drop positive restrictor -> dropped_condition": ("∀x ((Provider(x) ∧ ¬Public(x)) → Obliged(x))", "dropped_condition"),
    "add conjunct -> added_condition": ("∀x ((Provider(x) ∧ Placed(x) ∧ ¬Public(x) ∧ Large(x)) → Obliged(x))", "added_condition"),
    "forall -> exists -> quantifier_forall_exists": ("∃x ((Provider(x) ∧ Placed(x) ∧ ¬Public(x)) ∧ Obliged(x))", "quantifier_forall_exists"),
    "antecedent/consequent swap -> implication_direction_or_only": ("∀x (Obliged(x) → (Provider(x) ∧ Placed(x) ∧ ¬Public(x)))", "implication_direction_or_only"),
}
for name, (cf, exp) in tests.items():
    Cf = Formula(cf)
    rel = pair_relation(Cf, M)
    et, exc = error_type(Cf, M, rel, c_is_a=True)
    check(f"error_type: {name}", exp, et, f"relation {rel['relation']} level {rel.get('level')} exception_flag {exc}")

# 7 B1 prompt sha1
pf = json.loads((ROOT / "vendor" / "armB" / "prompts_frozen.json").read_text())
from baselines import B1_PROMPT  # noqa: E402
check("B1 prompt equals Arm B prompts_frozen.json", hashlib.sha1(pf["B1_PROMPT"].encode()).hexdigest(), hashlib.sha1(B1_PROMPT.encode()).hexdigest())

# 8 vendor fol_equiv reproduces 5 known L1 labels from heldout_confirm
DS = Path("/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_dataset_1")
d = json.loads(sorted(glob.glob(str(DS / "full_data_out" / "full_data_out_1.json")))[0] and (DS / "full_data_out" / "full_data_out_1.json").read_text())
got = []
for gset in d["datasets"]:
    if gset["dataset"] != "heldout_confirm":
        continue
    for ex in gset["examples"]:
        st = ex.get("metadata_L1_orig_status")
        if st in ("equiv_proved", "non_equiv") and ex.get("metadata_gold_fol_original") and len(got) < 5 and \
                (st == "equiv_proved" or sum(1 for x in got if x[0] == "non_equiv") < 2):
            inp = json.loads(ex["input"])
            r = equivalence(parse(inp["candidate_fol"]).ast, parse(ex["metadata_gold_fol_original"]).ast, time_limit=30.0)
            got.append((st, r["status"]))
del d
check("vendor fol_equiv reproduces 5 heldout_confirm L1 labels", 5, sum(a == b for a, b in got), str(got))

R["n_pass"] = sum(c["pass"] for c in R["checks"])
R["n_checks"] = len(R["checks"])
R["ts"] = time.time()
(ROOT / "results" / "unit_tests.json").write_text(json.dumps(R, indent=1, ensure_ascii=False, default=str))
print(f"{R['n_pass']}/{R['n_checks']} passed")
