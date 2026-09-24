"""Family-disjoint LLM panel: prompts, member configs, JSON parsing, resumable cached calls.

Members share NO model family with any of the 9 generators (Meta, Qwen, Mistral, OpenAI, Google,
DeepSeek, Microsoft) nor with the gemini judge baseline:
  M1 Anthropic claude-sonnet-4.5 (non-thinking, T=0)   fallback claude-haiku-4.5
  M2 xAI grok (grok-4-fast is no longer listed on OpenRouter -> grok-4.3, reasoning low)
  M3 Zhipu glm-4.6 (reasoning low)                     fallback moonshotai/kimi-k2-thinking
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from or_client import Client  # noqa: E402

CACHE = ROOT / "work" / "panel_cache.jsonl"
PROMPTS = ROOT / "prompts"

MEMBERS = {
    "M1": {"model": "anthropic/claude-sonnet-4.5", "params": {"temperature": 0.0, "max_tokens": 900}},
    "M2": {"model": "x-ai/grok-4.3", "params": {"temperature": 0.0, "max_tokens": 4000, "reasoning": {"effort": "low"}}},
    "M3": {"model": "z-ai/glm-4.6", "params": {"temperature": 0.0, "max_tokens": 4000, "reasoning": {"effort": "low"}}},
}
FALLBACKS = {
    "M1": {"model": "anthropic/claude-haiku-4.5", "params": {"temperature": 0.0, "max_tokens": 900}},
    "M2": {"model": "x-ai/grok-4.20", "params": {"temperature": 0.0, "max_tokens": 4000, "reasoning": {"effort": "low"}}},
    "M3": {"model": "moonshotai/kimi-k2-thinking", "params": {"temperature": 0.0, "max_tokens": 4000}},
}

ERROR_TYPES = {
    "negation_polarity": "a negation is missing, added, or misplaced",
    "quantifier_forall_exists": "universal used where existential is meant, or vice versa",
    "implication_direction_or_only": "implication reversed, or 'only if'/'only' mishandled",
    "dropped_condition": "a condition, restriction or conjunct stated in the sentence is missing",
    "added_condition": "a condition or claim not stated in the sentence is added",
    "argument_swap": "arguments of a relation are in the wrong order/roles",
    "conflation": "two distinct concepts/entities are merged into one predicate or constant",
    "wrong_split": "one concept is split into parts that change the meaning",
    "connective_and_or": "conjunction used for disjunction or vice versa (incl. exclusive-or vs inclusive-or)",
    "exception_misplaced": "an 'unless/except' exception is attached to the wrong part or inverted",
    "quantifier_scope": "wrong scope/order of quantifiers or of negation relative to a quantifier",
    "cardinality_numeric": "counting, 'at least/at most/exactly/more than one', or numbers mishandled",
    "wrong_constant": "a named individual is replaced by the wrong constant, or a constant used for a general term",
    "syntax_unparseable": "the formula is not well-formed first-order logic",
    "other": "any other meaning difference",
    "none": "no error",
}
TAXONOMY_TXT = "\n".join(f"- {k}: {v}" for k, v in ERROR_TYPES.items())

STANDARD = (
    "Judging standard: a formula is FAITHFUL if it has the same truth conditions as the sentence under a reasonable "
    "reading of the sentence. Different predicate or constant names, different granularity (e.g. one predicate "
    "TallMan(x) versus Tall(x) ∧ Man(x)), and logically equivalent rewrites are all acceptable. If the sentence is "
    "ambiguous, a formula is faithful if it matches ANY defensible reading. Information the sentence states must not "
    "be dropped; information it does not state must not be added. Judge only meaning, not style.")

SYNTAX = "Notation: ∀ ∃ quantifiers; ¬ not; ∧ and; ∨ inclusive or; → implies; ↔ iff; ⊕ exclusive or."

GOLD_AUDIT_TMPL = (
    "You are auditing a first-order logic (FOL) formalization of an English sentence.\n\n"
    "Sentence: {sentence}\nFormula: {formula}\n\n" + SYNTAX + "\n" + STANDARD + "\n\n"
    "Error types (use exactly these names):\n" + TAXONOMY_TXT + "\n\n"
    "Return ONLY a JSON object, no other text:\n"
    '{{"faithful": "yes" or "no", "sentence_ambiguous": "yes" or "no", "error_types": [list of error type names, '
    '["none"] if faithful], "primary_error": "<one error type name>", "explanation": "<at most 40 words>", '
    '"corrected_fol": "<if faithful is no: a faithful formula in the same notation on one line, reusing the '
    'formula\'s predicate and constant names where possible; otherwise empty string>"}}')

ADJ_TMPL = (
    "Two first-order logic (FOL) formalizations of the same English sentence are shown. They come from different "
    "sources; neither is known to be correct. Judge EACH formula independently against the sentence.\n\n"
    "Sentence: {sentence}\nFormula A: {a}\nFormula B: {b}\n\n" + SYNTAX + "\n" + STANDARD + "\n\n"
    "Error types (use exactly these names):\n" + TAXONOMY_TXT + "\n\n"
    "Also say whether A and B mean the same thing (same truth conditions, allowing renamed predicates).\n"
    "Return ONLY a JSON object, no other text:\n"
    '{{"A": {{"faithful": "yes" or "no", "error_types": [...], "primary_error": "<name>"}}, '
    '"B": {{"faithful": "yes" or "no", "error_types": [...], "primary_error": "<name>"}}, '
    '"sentence_ambiguous": "yes" or "no", "same_meaning": "yes" or "no"}}')


def save_prompts() -> None:
    PROMPTS.mkdir(exist_ok=True)
    (PROMPTS / "gold_audit.txt").write_text(GOLD_AUDIT_TMPL)
    (PROMPTS / "adjudication.txt").write_text(ADJ_TMPL)


def parse_json(text: str | None) -> dict | None:
    if not text:
        return None
    t = re.sub(r"```(json)?", "", text)
    starts = [m.start() for m in re.finditer(r"\{", t)]
    for s in starts:
        depth = 0
        for j in range(s, len(t)):
            if t[j] == "{":
                depth += 1
            elif t[j] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(t[s:j + 1])
                    except json.JSONDecodeError:
                        break
    return None


def yn(v) -> bool | None:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        v = v.strip().lower()
        if v in ("yes", "true", "y"):
            return True
        if v in ("no", "false", "n"):
            return False
    return None


def norm_errs(v) -> list[str]:
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, list):
        return []
    out = []
    for e in v:
        e = str(e).strip().lower().replace(" ", "_").replace("-", "_")
        out.append(e if e in ERROR_TYPES else "other")
    return out


def load_cache() -> dict:
    c = {}
    if CACHE.exists():
        for line in CACHE.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("parsed") is not None:
                    c[r["key"]] = r
    return c


_cache_lock = asyncio.Lock()


async def cached_call(client: Client, cache: dict, key: str, member_cfg: dict, prompt: str, member: str) -> dict:
    full_key = f"{member}|{member_cfg['model']}|{key}"
    if full_key in cache:
        return cache[full_key]
    parsed = None
    r = None
    for attempt in range(2):
        r = await client.chat(member_cfg["model"], [{"role": "user", "content": prompt}], tag=full_key[:120],
                              **member_cfg["params"])
        parsed = parse_json(r["text"])
        if parsed is not None:
            break
    rec = {"key": full_key, "member": member, "model": member_cfg["model"], "parsed": parsed,
           "raw": (r["text"] or "")[:3000] if r else "", "cost_usd": r["cost_usd"] if r else 0,
           "provider": r["provider"] if r else None, "error": r["error"] if r else "no call"}
    async with _cache_lock:
        with open(CACHE, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    if parsed is not None:
        cache[full_key] = rec
    return rec
