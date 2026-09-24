#!/usr/bin/env python3
"""STEP 2: candidate generation for the fresh set with the FROZEN round-1 prompt, systems and decoding
(vendor/ds/src/generate.py, copied verbatim for PROMPT / SYSTEMS / params; only the HTTP client differs:
src/or_client.py with ledger ./cost_ledger.jsonl and the run proxy URL).

Greedy (T=0, sample_idx 0) for 9 systems; 5 samples (T=0.8, top_p 1, seed=idx, idx 1..5) for gpt-4.1-mini and
llama-3.1-8b. Unparseable outputs are KEPT (parse_ok=false). Resumable (work/generations/<system>.jsonl).
Usage: s02_generate.py [--limit N] [--no-samples] [--cap 1.0]
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time

from loguru import logger

from common import RES, WORK, read_jsonl, setup_logging
from fol_parse import extract_formula, parse
from orc import BudgetExceeded, Client

GEN_DIR = WORK / "generations"
GEN_DIR.mkdir(parents=True, exist_ok=True)
PROMPT = ('Translate the English sentence into ONE first-order logic formula.\n'
          'Syntax: ∀x, ∃x, ¬, ∧, ∨, → (implies), ↔ (iff), ⊕ (exclusive or); predicates written Name(x) or '
          'Name(x, y); constants are names such as john. Choose your own predicate and constant names.\n'
          'Example of the syntax only: "Every bird that is not a penguin can fly." -> '
          '∀x ((Bird(x) ∧ ¬Penguin(x)) → CanFly(x))\n'
          'Output ONLY the formula on a single line, no explanation.\n'
          'Sentence: {sentence}\nFormula:')
PROMPT_SHA1 = hashlib.sha1(PROMPT.encode()).hexdigest()
ROUND1_PROMPT_SHA1 = "afabb41eedb31b3ee96e32419bd8e4abd727f758"
SYSTEMS = {
    "llama-3.1-8b": ("meta-llama/llama-3.1-8b-instruct", "required", {}),
    "qwen-2.5-7b": ("qwen/qwen-2.5-7b-instruct", "required", {}),
    "mistral-small-3.2-24b": ("mistralai/mistral-small-3.2-24b-instruct", "required", {}),
    "gpt-4.1-mini": ("openai/gpt-4.1-mini", "required", {}),
    "gemini-2.5-flash": ("google/gemini-2.5-flash", "required", {"reasoning": {"max_tokens": 0}}),
    "deepseek-v3.1": ("deepseek/deepseek-chat-v3.1", "required", {"reasoning": {"enabled": False}}),
    "gemma-3-27b": ("google/gemma-3-27b-it", "extra", {}),
    "phi-4": ("microsoft/phi-4", "extra", {}),
    "gpt-oss-120b": ("openai/gpt-oss-120b", "extra", {"reasoning": {"effort": "low"}}),
}
SAMPLED = ("gpt-4.1-mini", "llama-3.1-8b")
MAX_TOKENS = {"gpt-oss-120b": 2048}


def done_keys(system: str) -> set:
    keys = set()
    for r in read_jsonl(GEN_DIR / f"{system}.jsonl"):
        if r.get("raw_output") is not None or r.get("final_failure"):
            keys.add((r["sid"], r["sample_idx"]))
    return keys


async def one(client: Client, system: str, sent: dict, idx: int, lock: asyncio.Lock) -> None:
    model, tier, extra = SYSTEMS[system]
    body = {"model": model, "messages": [{"role": "user", "content": PROMPT.format(sentence=sent["sentence"])}],
            **extra, "max_tokens": MAX_TOKENS.get(system, 256)}
    if idx == 0:
        body["temperature"] = 0.0
    else:
        body.update({"temperature": 0.8, "top_p": 1.0, "seed": idx})
    r = await client.chat(body, tag=f"{system}:{sent['sid']}:{idx}")
    raw = r["text"]
    ext = extract_formula(raw) if raw else ""
    pr = parse(ext) if ext else None
    rec = {"sid": sent["sid"], "system": system, "model": model, "tier": tier, "sample_idx": idx,
           "temperature": body["temperature"], "raw_output": raw, "candidate_fol": ext,
           "parse_ok": bool(pr and pr.ok), "parse_error": (pr.error if pr else ("empty_output" if raw is not None else r["error"])),
           "parse_notes": pr.notes if pr else [], "provider": r["provider"], "finish_reason": r["finish_reason"],
           "gen_usd": r["cost_usd"], "gen_seconds": r["seconds"], "api_error": r["error"], "prompt_sha1": PROMPT_SHA1,
           "extractor_version": 2, "final_failure": raw is None, "cached": r.get("cached", False)}
    async with lock:
        with open(GEN_DIR / f"{system}.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


@logger.catch(reraise=True)
async def amain(a) -> None:
    assert PROMPT_SHA1 == ROUND1_PROMPT_SHA1, "generation prompt differs from round 1"
    sents = json.loads((RES / "fresh_sentences.json").read_text())
    if a.limit:
        sents = sents[: a.limit]
    jobs = []
    for sysn in SYSTEMS:
        dk = done_keys(sysn)
        for s in sents:
            if (s["sid"], 0) not in dk:
                jobs.append((sysn, s, 0))
            if sysn in SAMPLED and not a.no_samples:
                for k in range(1, 6):
                    if (s["sid"], k) not in dk:
                        jobs.append((sysn, s, k))
    jobs.sort(key=lambda j: (j[2] > 0, j[0]))
    logger.info(f"generation jobs: {len(jobs)} (greedy {sum(j[2] == 0 for j in jobs)})")
    lock = asyncio.Lock()
    t0 = time.time()
    async with Client("generation", phase_cap=a.cap, concurrency=a.concurrency, cache_name="generation") as client:
        tasks = [asyncio.create_task(one(client, *j, lock)) for j in jobs]
        done = 0
        for fut in asyncio.as_completed(tasks):
            try:
                await fut
            except BudgetExceeded as e:
                logger.error(str(e))
                for t in tasks:
                    t.cancel()
                break
            done += 1
            if done % 500 == 0:
                logger.info(f"{done}/{len(jobs)} {time.time() - t0:.0f}s spent phase ${client.spent_phase:.3f}")
        logger.info(f"generation done: calls {client.n_calls} failed {client.n_failed} "
                    f"phase ${client.spent_phase:.4f} total ${client.spent_total:.4f} in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    setup_logging("s02_generate")
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-samples", action="store_true")
    ap.add_argument("--cap", type=float, default=1.0)
    ap.add_argument("--concurrency", type=int, default=24)
    asyncio.run(amain(ap.parse_args()))
