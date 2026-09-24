"""Reusable, task-agnostic gold-free NL→FOL faithfulness metrics taking (text, fol).

    from metrics_api import tvjt_score, instance_nli_score, latent_class_scores, parse_ok

tvjt_score(text, fol) -> dict
    MEASURES: agreement between the candidate's truth value and an LLM's judgement of the SENTENCE's truth value
    on small finite worlds that z3 builds to separate the candidate from each of its own typed mutants
    (negation, quantifier, implication direction, dropped/added condition, argument swap, and/or, scope,
    concept merge, cardinality). The LLM never sees the formula. 1.0 = the sentence behaves like the candidate
    on every distinguishing world; error_type = operator family whose worlds disagree most. Requires
    OPENROUTER_API_KEY (google/gemini-2.5-flash, T=0, no reasoning); ~1 call per formula.

instance_nli_score(text, fol) -> dict
    MEASURES: mean agreement (binary entailed-vs-not) between an NLI cross-encoder's reading of
    SENTENCE + instance facts ⇒ hypothesis and the candidate's solver-derived consequence labels
    (E/C/N) for ground literals and templated quantified hypotheses about named individuals. Zero LLM calls.

latent_class_scores(fols_by_system) -> dict
    MEASURES: posterior probability (one-coin latent-class EM with an all-wrong state) that each system's
    candidate for the SAME sentence belongs to the correct equivalence class, estimated only from which
    systems' outputs are solver-equivalent (blind predicate bijection). Needs >= 2 parseable candidates per
    sentence and many sentences to fit; for a single sentence it falls back to agreement share (MAJ).
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("NLTK_DATA", str(ROOT / "nltk_data"))

import fol_core as fc  # noqa: E402


def parse_ok(fol: str) -> dict:
    """B2 baseline: does the formula parse in the FOLIO unicode dialect (closed, first-order, no function terms)?"""
    ast, err = fc.try_parse(fol)
    return {"score": float(ast is not None), "error_class": err}


def tvjt_score(text: str, fol: str, seed_key: str = "api") -> dict:
    from llm import LLM
    from tvjt import build_prompt, parse_answer, score_answers, worlds_for
    F, err = fc.try_parse(fol)
    if F is None:
        return {"score": 0.5, "covered": False, "reason": f"unparseable:{err}"}
    worlds = worlds_for(F, seed_key)
    if not worlds:
        return {"score": 0.5, "covered": False, "reason": "no_world"}
    prompt = build_prompt(text, F, worlds)

    async def run():
        async with LLM(concurrency=1) as L:
            return await L.call([{"role": "user", "content": prompt}], stage="api_TVJT", item_id=seed_key)
    r = asyncio.run(run())
    ans = parse_answer(r["text"], len(worlds))
    if ans is None:
        return {"score": 0.5, "covered": False, "reason": "malformed"}
    sc, agrees, et = score_answers(worlds, ans)
    return {"score": sc, "covered": True, "error_type": et, "agrees": agrees, "ops": [w["op"] for w in worlds],
            "usd": r["cost"]}


_NLI = {}


def instance_nli_score(text: str, fol: str, seed_key: str = "api") -> dict:
    from instance_nli import agree_scores, error_type, process_target
    from stages import deberta_probs
    F, err = fc.try_parse(fol)
    if F is None:
        return {"score": 0.5, "covered": False, "reason": f"unparseable:{err}"}
    c = process_target(F, text, seed_key)
    if len(c["labels"]) < 3:
        return {"score": 0.5, "covered": False, "reason": "few_hypotheses"}
    pr = deberta_probs(c["texts"])
    sb, s3 = agree_scores(c["labels"], pr)
    return {"score": sb, "score_3way": s3, "covered": True,
            "error_type": error_type(c["labels"], c["pairs"], pr, c["mutant_labels"]),
            "pairs": list(zip(c["texts"], c["labels"]))}


def latent_class_scores(fols_by_system: dict[str, str]) -> dict:
    """Single-sentence use: agreement share (MAJ). For the EM fit over a corpus see latent_class.run_latent_class."""
    asts = {s: fc.try_parse(f)[0] for s, f in fols_by_system.items()}
    ok = [s for s, a in asts.items() if a is not None]
    out = {}
    for s in fols_by_system:
        if asts[s] is None or len(ok) < 2:
            out[s] = {"score": 0.5 if asts[s] is not None else 0.0, "covered": False}
            continue
        agree = sum(1 for t in ok if t != s and fc.find_bijections(asts[s], asts[t])["label"] == "equiv")
        out[s] = {"score": agree / (len(ok) - 1), "covered": True}
    return out


if __name__ == "__main__":
    print(parse_ok("∀x (Dog(x) → Bark(x))"))
    print(latent_class_scores({"a": "∀x (Dog(x) → Bark(x))", "b": "∀x (Canine(x) → Barks(x))", "c": "∃x (Dog(x) ∧ Bark(x))"}))
