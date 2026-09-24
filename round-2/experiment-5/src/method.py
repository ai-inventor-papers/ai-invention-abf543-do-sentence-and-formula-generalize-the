#!/usr/bin/env python3
"""Directional consensus (DC) on long, exception-heavy legal definitions — reusable API + full pipeline.

REUSABLE FUNCTIONS (text, fol) / sets of such pairs   [dc/ package, contract v1]
  align_pair(A, B, limits)
      MEASURES: the lexical-free vocabulary correspondences under which formula B can be read in A's vocabulary
      (L1 arity-preserving bijections; L2 partial maps covering >= 50% of B's predicate occurrences, unmapped
      symbols fresh; L3 granularity definitions: a predicate = conjunction of 2 positive literals over the other
      side's unmatched predicates). Names are never read as words.
  pair_relation(A, B, limits)
      MEASURES: the logical order between A and B under the most informative alignment: EQUIV / STRONGER / WEAKER /
      COMPATIBLE-INCOMPARABLE / CONTRADICTORY / UNALIGNABLE / UNKNOWN (z3 grounding over domains 1..4 + unbounded z3).
  directional_consensus(text, fol, peers, weights)
      MEASURES: the reliability-weighted share of peers (other systems' formalizations of the SAME text) that are
      logically equivalent to the candidate under lexical-free alignment; `text` is provenance only (text-blind).
      Returns score, coverage, strength profile; error_type(C, mode, rel) names the error relative to the modal peer.
  ds_weights(obs, systems)
      MEASURES: one-coin Dawid-Skene reliability of each system from which outputs agree (no labels).

PIPELINE (python method.py --stages all). Stages (all resumable; LLM calls cached in work/llm_cache.jsonl):
  sentences   S1 build the 158-sentence legal set                       src/build_sentences.py
  generate    S2 9 systems greedy + 2x5 samples (frozen prompt)           src/generate_long.py --probe 20 / --full / --assemble
  l1          vendor L1 equivalence for sampling strata / LC_maj           src/panel_nogold.py l1
  panel       S5 smoke, calibration gate, sample, adjudication             src/panel_nogold.py smoke|calibrate|sample|run
  dc          S3 DC pairs (default + DC_fp) and FREEZE                     src/run_dc.py; src/dc_score.py --freeze
  baselines   S4 B1, B1plus, B3 (API -> local substitute), B7/VC, DC+arb  src/baselines.py; src/local_judge.py
  extra       invariance, shuffled-peer placebo, dev anchor, cross-impl   src/extra_dc.py; src/dev_anchor.py; src/crossimpl.py
  analysis    S6 X1-X5 + secondary; T5 re-derivation                     src/analysis.py; audit_rederive.py
  export      S7 scores.jsonl, method_out.json                            src/export.py
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from dc.api import align_pair, directional_consensus, ds_weights, error_type, pair_relation, score_from_relations  # noqa: E402,F401
from dc.core import Formula  # noqa: E402,F401

PY = str(ROOT / ".venv" / "bin" / "python")
STAGES = [
    ("sentences", [["build_sentences.py"]]),
    ("generate", [["generate_long.py", "--probe", "20"], ["generate_long.py", "--full"], ["generate_long.py", "--assemble"]]),
    ("l1", [["panel_nogold.py", "l1"]]),
    ("panel", [["panel_nogold.py", "smoke"], ["panel_nogold.py", "calibrate"], ["panel_nogold.py", "sample"],
               ["panel_nogold.py", "run", "--pilot-cost"], ["panel_nogold.py", "run"]]),
    ("dc", [["run_dc.py", "--set", "legal", "--limit", "10"], ["run_dc.py", "--set", "legal"],
            ["run_dc.py", "--set", "legal", "--order", "fp", "--workers", "5"], ["dc_score.py", "--set", "legal", "--freeze"]]),
    ("baselines", [["baselines.py", "b1"], ["baselines.py", "b1plus"], ["baselines.py", "b3"], ["local_judge.py", "b3"],
                   ["baselines.py", "struct"], ["local_judge.py", "arb"]]),
    ("extra", [["dev_anchor.py", "frame"], ["dev_anchor.py", "l1"], ["run_dc.py", "--set", "dev", "--workers", "5", "--budget", "120"],
               ["dc_score.py", "--set", "dev"], ["dev_anchor.py", "auroc"], ["extra_dc.py", "invariance"], ["extra_dc.py", "placebo"],
               ["crossimpl.py"], ["alignment_audit.py"]]),
    ("analysis", [["deviations.py"], ["analysis.py"]]),
    ("export", [["export.py"]]),
]


def demo() -> None:
    text = "'provider' means a natural or legal person, other than a public authority, that places an AI system on the market."
    cand = "∀x (Provider(x) ↔ ((NaturalPerson(x) ∨ LegalPerson(x)) ∧ ¬PublicAuthority(x) ∧ ∃y (AISystem(y) ∧ PlacesOnMarket(x, y))))"
    peers = ["∀p (Prov(p) ↔ ((Natural(p) ∨ Legal(p)) ∧ ¬PubAuth(p) ∧ ∃s (AISys(s) ∧ Places(p, s))))",
             "∀x (Provider(x) ↔ ((NaturalPerson(x) ∨ LegalPerson(x)) ∧ ∃y (AISystem(y) ∧ PlacesOnMarket(x, y))))",
             "∀x (Provider(x) → ((NaturalPerson(x) ∨ LegalPerson(x)) ∧ ¬PublicAuthority(x) ∧ ∃y (AISystem(y) ∧ PlacesOnMarket(x, y))))"]
    r = directional_consensus(text, cand, peers)
    print({k: r[k] for k in ("score", "coverage", "n_covered", "strength_profile", "relation_counts")})
    for p in peers:
        rel = pair_relation(cand, p)
        print(rel["relation"], "level", rel.get("level"), "map", rel.get("map"))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stages", default="", help="comma list of stage names or 'all'")
    ap.add_argument("--demo", action="store_true", help="score a toy legal definition against 3 peers (no API)")
    a = ap.parse_args()
    if a.demo or not a.stages:
        demo()
        return
    names = [s for s, _ in STAGES] if a.stages == "all" else a.stages.split(",")
    for name, cmds in STAGES:
        if name not in names:
            continue
        for cmd in cmds:
            print(f"=== {name}: {' '.join(cmd)}", flush=True)
            r = subprocess.run([PY, *cmd], cwd=ROOT / "src")
            if r.returncode != 0:
                raise RuntimeError(f"stage {name} step {cmd} failed ({r.returncode})")


if __name__ == "__main__":
    main()
