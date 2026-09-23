"""Reusable metric API (iter 2).

canon(fol_str) -> str
    Canonical, name-blind restricted-quantifier normal form (FOLIO-unicode). Logically equivalent surface
    variants (conjunct order, De Morgan, contrapositive, A→B vs ¬A∨B, ¬(A↔B) vs A⊕B, variable names, prenex)
    map to one string; verified bounded-equivalent (domains 1..4) to the input, else the input is returned.

distinguishing_worlds(fol_str) -> list[dict]
    The canonical TVJT worlds of F: for each of F's typed mutants M (NEG, QUANT, IMPL_REV, DROP_CONJ, ADD_CONJ,
    ARG_SWAP, AND_OR, SCOPE_SWAP, MERGE, CARD two/unique) a minimal finite world (n ≤ 4) where F and M disagree,
    found by a deterministic z3 optimisation, deduplicated by isomorphism, with a verbalisation ('text').
    Each world carries F_value = truth of F in the world and op = the mutant family it separates.

tvjt_score(text, fol, backend='gemini', votes=3) -> dict
    What it measures: how often the SENTENCE's judged truth value (asked of an LLM that never sees F) agrees with
    F's truth value in F's distinguishing worlds. C3 (frozen) = mean over worlds of the judged probability that
    the sentence has F's truth value; C1 = vote-0 binary agreement; error_type = the mutant family whose worlds
    disagree most (a guess at the error type of F). Requires the judge (OPENROUTER_API_KEY for gemini).
"""
from __future__ import annotations

import asyncio

import common  # noqa: F401
import canon as K
import judge as J
from worlds import verbalize


def canon(fol_str: str) -> str:
    return K.canon(fol_str)


def distinguishing_worlds(fol_str: str) -> list[dict]:
    import fol_core as fc
    cw = K.canonical_worlds(fol_str)
    G = fc.parse(cw["canon"])
    for w in cw["worlds"]:
        w["text"] = verbalize(G, w)
    return cw["worlds"]


def tvjt_score(text: str, fol: str, backend: str = "gemini", votes: int = 3) -> dict:
    ws = [w for w in distinguishing_worlds(fol) if w.get("text")]
    if not ws:
        return {"score": 0.5, "covered": False, "error_type": None, "worlds": [], "usd": 0.0}

    async def go():
        be = J.GeminiBackend() if backend == "gemini" else J.LocalBackend(backend)
        async with be:
            wc = J.WorldCache(be.name, "api")
            return await J.judge_target(be, wc, text, ws, votes, "TVJT_api", "api")
    o = asyncio.run(go())
    s = J.score_tvjt(ws, o["answers"], votes)
    return {"score": s["C3"] if s["C3"] is not None else 0.5, "covered": s["C3"] is not None,
            "C1": s["C1"], "C2": s["C2"], "error_type": s["error_type"], "worlds": ws,
            "agrees": s["per_world_agree"], "usd": o["usd"]}
