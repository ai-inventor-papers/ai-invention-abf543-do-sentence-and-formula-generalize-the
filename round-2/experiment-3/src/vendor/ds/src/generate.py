#!/usr/bin/env python3
"""STEP 4: candidate generation by 9 NL->FOL systems under ONE frozen gold-free prompt.

Greedy (T=0, sample_idx 0) for all 9 systems; k=5 samples at T=0.8 (sample_idx 1..5) for
gpt-4.1-mini and llama-3.1-8b. Resumable: raw/generations/<system>.jsonl is appended per call and
existing (sentence_id, sample_idx) keys are skipped.

Usage: generate.py --limit 20 [--no-samples] [--systems a,b]
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from fol_parse import extract_formula, parse  # noqa: E402
from or_client import BudgetExceeded, Client  # noqa: E402

GEN_DIR = ROOT / "raw" / "generations"
GEN_DIR.mkdir(parents=True, exist_ok=True)
PROMPT_PATH = ROOT / "prompts" / "generation_prompt.txt"
PROMPT = ('Translate the English sentence into ONE first-order logic formula.\n'
          'Syntax: ∀x, ∃x, ¬, ∧, ∨, → (implies), ↔ (iff), ⊕ (exclusive or); predicates written Name(x) or '
          'Name(x, y); constants are names such as john. Choose your own predicate and constant names.\n'
          'Example of the syntax only: "Every bird that is not a penguin can fly." -> '
          '∀x ((Bird(x) ∧ ¬Penguin(x)) → CanFly(x))\n'
          'Output ONLY the formula on a single line, no explanation.\n'
          'Sentence: {sentence}\nFormula:')
PROMPT_SHA1 = hashlib.sha1(PROMPT.encode()).hexdigest()

# system name -> (model id, tier, extra params)
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

logger.remove()
logger.add(sys.stdout, level="INFO", format="{time:HH:mm:ss}|{level:<7}|{message}")
logger.add(ROOT / "logs" / "generate.log", rotation="30 MB", level="DEBUG")


def done_keys(system: str) -> set:
    p = GEN_DIR / f"{system}.jsonl"
    keys = set()
    if p.exists():
        for line in p.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("raw_output") is not None or r.get("final_failure"):
                    keys.add((r["sentence_id"], r["sample_idx"]))
    return keys


async def one(client: Client, system: str, sent: dict, sample_idx: int, lock: asyncio.Lock) -> None:
    model, tier, extra = SYSTEMS[system]
    params = dict(extra)
    params["max_tokens"] = MAX_TOKENS.get(system, 256)
    if sample_idx == 0:
        params["temperature"] = 0.0
    else:
        params["temperature"] = 0.8
        params["top_p"] = 1.0
        params["seed"] = sample_idx
    msgs = [{"role": "user", "content": PROMPT.format(sentence=sent["sentence"])}]
    r = await client.chat(model, msgs, tag=f"{system}:{sent['sentence_id']}:{sample_idx}", **params)
    raw = r["text"]
    extracted = extract_formula(raw) if raw else ""
    pr = parse(extracted) if extracted else None
    rec = {"sentence_id": sent["sentence_id"], "system": system, "model": model, "tier": tier,
           "sample_idx": sample_idx, "temperature": params["temperature"], "raw_output": raw,
           "reasoning_present": bool(r.get("reasoning")), "candidate_fol": extracted,
           "parse_ok": bool(pr and pr.ok), "parse_error": (pr.error if pr else ("empty_output" if raw is not None else r["error"])),
           "parse_notes": pr.notes if pr else [], "provider": r["provider"], "model_returned": r["model_returned"],
           "finish_reason": r["finish_reason"], "gen_usd": r["cost_usd"], "gen_seconds": r["seconds"],
           "usage": r["usage"], "api_error": r["error"], "prompt_sha1": PROMPT_SHA1,
           "final_failure": raw is None}
    async with lock:
        with open(GEN_DIR / f"{system}.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


@logger.catch(reraise=True)
async def amain(args) -> None:
    PROMPT_PATH.parent.mkdir(exist_ok=True)
    PROMPT_PATH.write_text(PROMPT)
    sents = json.loads((ROOT / "work" / "heldout_sentences.json").read_text())
    order = sorted(sents, key=lambda s: ({"top": 0, "middle": 1, "bottom": 2}[s["complexity_tercile"]], s["sentence_id"]))
    greedy_sents = sorted(sents, key=lambda s: s["sentence_id"])[: args.limit] if args.limit else sents
    samp_sents = order[: args.sample_limit] if args.sample_limit else order
    if args.limit:
        samp_sents = [s for s in samp_sents if s in greedy_sents]
    systems = args.systems.split(",") if args.systems else list(SYSTEMS)
    jobs = []
    for sysname in systems:
        dk = done_keys(sysname)
        for s in greedy_sents:
            if (s["sentence_id"], 0) not in dk:
                jobs.append((sysname, s, 0))
        if sysname in SAMPLED and not args.no_samples:
            for s in samp_sents:
                for k in range(1, 6):
                    if (s["sentence_id"], k) not in dk:
                        jobs.append((sysname, s, k))
    # greedy first, then samples
    jobs.sort(key=lambda j: (j[2] > 0, j[0]))
    logger.info(f"jobs: {len(jobs)} (greedy {sum(j[2] == 0 for j in jobs)})")
    lock = asyncio.Lock()
    async with Client("generation", phase_cap=args.cap, concurrency=args.concurrency) as client:
        tasks = [one(client, *j, lock) for j in jobs]
        done = 0
        for fut in asyncio.as_completed(tasks):
            try:
                await fut
            except BudgetExceeded as e:
                logger.error(str(e))
                break
            done += 1
            if done % 250 == 0:
                logger.info(f"{done}/{len(jobs)} spent phase ${client.spent_phase:.3f} total ${client.spent_total:.3f}")
        logger.info(f"generation finished: calls={client.n_calls} phase ${client.spent_phase:.3f} total ${client.spent_total:.3f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sample-limit", type=int, default=0)
    ap.add_argument("--no-samples", action="store_true")
    ap.add_argument("--systems", default="")
    ap.add_argument("--cap", type=float, default=2.0)
    ap.add_argument("--concurrency", type=int, default=12)
    asyncio.run(amain(ap.parse_args()))
