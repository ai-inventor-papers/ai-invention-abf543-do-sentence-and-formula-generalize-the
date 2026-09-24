#!/usr/bin/env python3
"""Monotonicity-signature faithfulness metrics for NL->FOL (Arm A of the iter-1 screen) — reusable API + pipeline.

REUSABLE FUNCTIONS (text, fol) -> dict
  signature_faithfulness(text, fol, variant="A3")
      A3 (zero-LLM): per-concept polarity of the TEXT from a rule-based monotonicity calculus over a spaCy
      parse, compared with the solver-computed monotonicity signature of the FORMULA (for each predicate P:
      is F upward/downward monotone in P over all finite models of size 1..3; exact SAT on a grounding),
      via a lexical aligner. Score = 1 - weighted fraction of mismatching coordinates:
        concept polarity mismatches, dropped text concepts, added/vacuous formula predicates, swapped role
        anchors (relation slot i anchored to the wrong argument), relativized coordination coordinates.
      Returns a score in [0,1] (0.5 if uncovered), a predicted error type, and the mismatch list.
      variant="A1": the text polarity comes from substitution-entailment questions to an LLM
      (google/gemini-2.5-flash, thinking budget 1024; needs OPENROUTER_API_KEY; ~$0.0025 per sentence).
  alignment_only(text, fol)   A0 ablation: dropped/added coordinates only (no polarity, no anchors)
  concept_coverage(text, fol) Ccov control: fraction of text content concepts covered by formula symbols

WHAT THE SCORE MEASURES: agreement between (a) which content words of the sentence occur in upward vs
downward-entailing positions (restrictor/antecedent/negated vs scope/consequent), which argument slot each
role word fills, and which words are represented at all, and (b) the same properties computed exactly
from the formula. It is invariant (by construction) under logical equivalence, conjunct reordering,
contrapositive, De Morgan, prenexing; it is NOT invariant under predicate renaming that breaks the lexical
alignment, and it is blind (pre-registered) to quantifier-scope swaps, cardinality and (for A1) and/or swaps.

PIPELINE (python method.py --stages all): reproduces every artifact of the screen:
  build_screen_set -> run_sigs -> run_text(pilot, probe, b6) -> run_baselines(b1, b1_mutants, b3, b4)
  -> run_selfcons -> run_metrics -> analyze   (LLM calls are cached in results/llm_cache; $ cap 5.80)
"""
from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

logger.remove()
logger.add(sys.stdout, level="INFO", format="{time:HH:mm:ss}|{level:<7}|{message}")
(ROOT / "logs").mkdir(exist_ok=True)
logger.add(ROOT / "logs" / "method.log", rotation="30 MB", level="DEBUG")


def _text_side(text: str, variant: str) -> tuple[dict, dict]:
    import text_sig
    ex = text_sig.extract(text)
    if variant == "A3" or variant in ("A0", "Ccov"):
        a3_rel = {}
        for c, q, kind in ex["coord"]:
            for (x, y) in ((c, q), (q, c)):
                lx = ex["marker"].get(x, "+")
                if kind == "and":
                    a3_rel[(x, y, "out")], a3_rel[(x, y, "in")] = "0", lx
                elif kind == "or":
                    a3_rel[(x, y, "in")], a3_rel[(x, y, "out")] = "0", lx
        return ex, {"labels": dict(ex["marker"]), "anchors": ex["anchors"], "rel": a3_rel}
    import llm
    qs = text_sig.probe_questions(ex, with_rel=(variant == "A2"))
    prompt = text_sig.render_prompt(qs)
    res = asyncio.run(llm.run_batch([dict(model="google/gemini-2.5-flash",
                                          messages=[{"role": "user", "content": prompt}], purpose="api_probe",
                                          reasoning={"max_tokens": 1024}, max_tokens=4000)]))[0]
    if isinstance(res, Exception):
        raise res
    T = text_sig.labels_from_answers(ex, qs, text_sig.parse_answers(res[0]))
    return ex, {"labels": T["concept_labels"], "anchors": ex["anchors"],
                "rel": T["rel_labels"] if variant == "A2" else {}}


def signature_faithfulness(text: str, fol: str, variant: str = "A3") -> dict:
    """Gold-free faithfulness score of `fol` for `text`. variant in {A1, A2, A3, A0, Ccov}."""
    from align import align, is_optional
    from fol_parse import ParseError, parse
    from score import signature_score
    from solver_sig import signature
    ex, T = _text_side(text, variant)
    try:
        p = parse(fol)
    except (ParseError, RecursionError) as e:
        return {"score": 0.5, "covered": False, "error": f"unparseable: {e}", "error_type_pred": "other"}
    S = signature(p.ast, N=3, timeout_ms=5000, with_rel=True)
    A = align(p.preds, p.consts, ex["concepts"])
    if variant == "Ccov":
        return {"score": A["coverage"], "covered": True, "coverage": A["coverage"], "alignment": A}
    optional = {c["cid"] for c in ex["concepts"] if is_optional(c)}
    res = signature_score(T, S, A, variant=variant, optional=optional)
    res.update(text_labels={c["span"]: T["labels"].get(c["cid"]) for c in ex["concepts"]},
               formula_labels=S["labels"], alignment={k: v["cid"] for k, v in A["preds"].items()})
    return res


def alignment_only(text: str, fol: str) -> dict:
    return signature_faithfulness(text, fol, variant="A0")


def concept_coverage(text: str, fol: str) -> dict:
    return signature_faithfulness(text, fol, variant="Ccov")


STAGES = [
    ("build_screen_set", ["build_screen_set.py", "--n_sent", "300"]),
    ("run_sigs", ["run_sigs.py"]),
    ("text_pilot", ["run_text.py", "--stage", "pilot"]),
    ("text_probe", ["run_text.py", "--stage", "probe"]),
    ("b6", ["run_text.py", "--stage", "b6"]),
    ("b1", ["run_baselines.py", "--stage", "b1", "--sets", "real,gold,rewrite"]),
    ("b1_mutants", ["run_baselines.py", "--stage", "b1_mutants"]),
    ("b3", ["run_baselines.py", "--stage", "b3"]),
    ("b4_real_gold", ["run_baselines.py", "--stage", "b4", "--sets", "real,gold"]),
    ("b4_mut_rew", ["run_baselines.py", "--stage", "b4", "--sets", "mutant,rewrite", "--n_mut_per_op", "20",
                    "--n_rew", "120"]),
    ("selfcons", ["run_selfcons.py"]),
    ("metrics", ["run_metrics.py"]),
    ("analyze", ["analyze.py"]),
]


@logger.catch(reraise=True)
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stages", default="all", help="comma list of stage names or 'all'")
    ap.add_argument("--demo", action="store_true", help="score a few (text, fol) pairs with the zero-LLM A3 API")
    a = ap.parse_args()
    if a.demo:
        demo = [("All dogs that are not trained bark.", "∀x ((Dog(x) ∧ ¬Trained(x)) → Bark(x))"),
                ("All dogs that are not trained bark.", "∀x (¬Bark(x) → (¬Dog(x) ∨ Trained(x)))"),
                ("All dogs that are not trained bark.", "∀x ((Dog(x) ∧ Trained(x)) → Bark(x))"),
                ("All dogs that are not trained bark.", "∀x (Bark(x) → (Dog(x) ∧ ¬Trained(x)))"),
                ("No student who smokes is healthy.", "∀x ((Student(x) ∧ Smoke(x)) → ¬Healthy(x))"),
                ("No student who smokes is healthy.", "∃x (Student(x) ∧ Smoke(x) ∧ ¬Healthy(x))")]
        for t, f in demo:
            r = signature_faithfulness(t, f, "A3")
            logger.info(f"{t} | {f} -> score={r['score']:.3f} type={r['error_type_pred']} text={r['text_labels']} "
                        f"formula={r['formula_labels']}")
        return
    names = [s for s, _ in STAGES] if a.stages == "all" else a.stages.split(",")
    for name, cmd in STAGES:
        if name not in names:
            continue
        logger.info(f"=== stage {name}: {' '.join(cmd)}")
        r = subprocess.run([sys.executable, *cmd], cwd=ROOT)
        if r.returncode != 0:
            raise RuntimeError(f"stage {name} failed with exit code {r.returncode}")
    logger.info("pipeline complete: see results/method_out.json and method_out.json")


if __name__ == "__main__":
    main()
