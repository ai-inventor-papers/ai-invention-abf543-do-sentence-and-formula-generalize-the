#!/usr/bin/env python3
"""S2: candidate generation for the long legal sentences with the FROZEN round-1 prompt, SYSTEMS and extractor v2.

Only change (deviation D4, declared before generation): max_tokens 1024 (gpt-oss-120b 4096) instead of 256 (2048).
Greedy T=0 for 9 systems; T=0.8 samples 1..5 (top_p 1, seed=k) for gpt-4.1-mini and llama-3.1-8b.
Resumable: work/generations.jsonl is appended per call; (sentence_id, system, sample_idx) done-keys are skipped.

Usage: generate_long.py --probe 20      (20 sentences x 9 greedy; logs parse/truncation rate and $/call)
       generate_long.py --full [--no-samples-public]
       generate_long.py --assemble      (-> work/candidates.jsonl incl. the 367 pilot formulas as system='pilot')
"""
from __future__ import annotations

import argparse
import ast
import asyncio
import hashlib
import json
from collections import Counter, defaultdict

from common import RES, SAMPLE_SYSTEMS, VENDOR, WORK, append_jsonl, jdump, jload, read_jsonl, setup_logger, sha1, write_jsonl

logger = setup_logger("generate_long")
from fol_parse import complexity_ast, extract_formula, parse, signature  # noqa: E402  (vendor/ds, extractor v2)
from llm import BudgetExceeded, Client  # noqa: E402

GEN = WORK / "generations.jsonl"
PROMPT = ('Translate the English sentence into ONE first-order logic formula.\n'
          'Syntax: ∀x, ∃x, ¬, ∧, ∨, → (implies), ↔ (iff), ⊕ (exclusive or); predicates written Name(x) or '
          'Name(x, y); constants are names such as john. Choose your own predicate and constant names.\n'
          'Example of the syntax only: "Every bird that is not a penguin can fly." -> '
          '∀x ((Bird(x) ∧ ¬Penguin(x)) → CanFly(x))\n'
          'Output ONLY the formula on a single line, no explanation.\n'
          'Sentence: {sentence}\nFormula:')
PROMPT_SHA1 = hashlib.sha1(PROMPT.encode()).hexdigest()
FROZEN_PROMPT_SHA1 = "afabb41eedb31b3ee96e32419bd8e4abd727f758"  # metadata_prompt_sha1 of every round-1 candidate


def vendor_systems() -> dict:
    src = (VENDOR / "ds" / "generate.py").read_text()
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "SYSTEMS":
            return ast.literal_eval(node.value)
    raise RuntimeError("SYSTEMS not found in vendor generate.py")


SYSTEMS = vendor_systems()
MAX_TOKENS = {"gpt-oss-120b": 4096}
DEFAULT_MAX_TOKENS = 1024


def check_frozen() -> dict:
    vp = (VENDOR / "ds" / "prompts" / "generation_prompt.txt").read_text()
    ok = {"prompt_sha1": PROMPT_SHA1, "frozen_sha1": FROZEN_PROMPT_SHA1, "prompt_matches_frozen": PROMPT_SHA1 == FROZEN_PROMPT_SHA1,
          "prompt_matches_vendor_file": vp == PROMPT, "n_systems": len(SYSTEMS)}
    assert ok["prompt_matches_frozen"] and ok["prompt_matches_vendor_file"], ok
    return ok


def done_keys() -> set:
    return {(r["sentence_id"], r["system"], r["sample_idx"]) for r in read_jsonl(GEN)
            if r.get("raw_output") is not None or r.get("final_failure")}


async def one(client: Client, system: str, sent: dict, sample_idx: int, lock: asyncio.Lock) -> dict:
    model, tier, extra = SYSTEMS[system]
    params = dict(extra)
    params["max_tokens"] = MAX_TOKENS.get(system, DEFAULT_MAX_TOKENS)
    if sample_idx == 0:
        params["temperature"] = 0.0
    else:
        params.update(temperature=0.8, top_p=1.0, seed=sample_idx)
    body = {"model": model, "messages": [{"role": "user", "content": PROMPT.format(sentence=sent["sentence"])}], **params}
    r = await client.chat(body, tag=f"{system}:{sent['sentence_id']}:{sample_idx}")
    raw = r["text"]
    extracted = extract_formula(raw) if raw else ""
    pr = parse(extracted) if extracted else None
    rec = {"sentence_id": sent["sentence_id"], "system": system, "model": model, "tier": tier, "sample_idx": sample_idx,
           "temperature": params["temperature"], "max_tokens": params["max_tokens"], "raw_output": raw,
           "candidate_fol": extracted, "parse_ok": bool(pr and pr.ok),
           "parse_error": (pr.error if pr else ("empty_output" if raw is not None else r.get("error"))),
           "parse_notes": pr.notes if pr else [], "provider": r.get("provider"), "model_returned": r.get("model_returned"),
           "finish_reason": r.get("finish_reason"), "gen_usd": r.get("cost_usd", 0.0), "gen_seconds": r.get("seconds"),
           "usage": r.get("usage"), "reasoning_tokens": r.get("reasoning_tokens"), "api_error": r.get("error"),
           "prompt_sha1": PROMPT_SHA1, "extractor_version": 2, "final_failure": raw is None, "cached": r.get("cached")}
    async with lock:
        append_jsonl(GEN, [rec])
    return rec


async def run_jobs(jobs: list, cap_phase: str = "generation") -> dict:
    lock = asyncio.Lock()
    out = []
    async with Client(cap_phase, concurrency=24) as client:
        tasks = [one(client, *j, lock) for j in jobs]
        for k, fut in enumerate(asyncio.as_completed(tasks)):
            try:
                out.append(await fut)
            except BudgetExceeded as e:
                logger.error(str(e))
                break
            if (k + 1) % 200 == 0:
                logger.info(f"{k + 1}/{len(jobs)} phase ${client.spent_phase:.3f} total ${client.spent_total:.3f}")
        info = {"n_calls": client.n_calls, "n_cached": client.n_cached, "n_failed": client.n_failed,
                "phase_spent": client.spent_phase, "total_spent": client.spent_total}
    return {"rows": out, **info}


def summarize(rows: list[dict]) -> dict:
    by = defaultdict(list)
    for r in rows:
        by[r["system"]].append(r)
    per = {}
    for s, rs in sorted(by.items()):
        per[s] = {"n": len(rs), "parse_rate": sum(r["parse_ok"] for r in rs) / len(rs),
                  "trunc_rate": sum(r.get("finish_reason") == "length" for r in rs) / len(rs),
                  "usd_per_call": sum(r.get("gen_usd") or 0 for r in rs) / len(rs),
                  "fail": sum(bool(r.get("final_failure")) for r in rs)}
    n = max(1, len(rows))
    return {"per_system": per, "parse_rate": sum(r["parse_ok"] for r in rows) / n,
            "trunc_rate": sum(r.get("finish_reason") == "length" for r in rows) / n,
            "usd_per_call": sum(r.get("gen_usd") or 0 for r in rows) / n, "n": len(rows)}


def assemble() -> None:
    """work/candidates.jsonl: greedy + samples + pilot formulas, with parse/complexity features."""
    sents = {s["sentence_id"]: s for s in jload(WORK / "sentences.json")}
    rows = [r for r in read_jsonl(GEN) if r["sentence_id"] in sents]
    last = {}
    for r in rows:  # keep the last record per key (a retry after a failure supersedes it)
        last[(r["sentence_id"], r["system"], r["sample_idx"])] = r
    cands = []
    for (sid, system, k), r in sorted(last.items()):
        cands.append({"cand_id": f"{sid}:{system}:{k}", "sentence_id": sid, "system": system, "sample_idx": k,
                      "fol": r["candidate_fol"], "raw_output": r["raw_output"], "finish_reason": r["finish_reason"],
                      "gen_usd": r["gen_usd"], "provider": r["provider"], "model": r["model"], "frame": "system"})
    # pilot formulas: 367 rows of the user's pilot, pooled across conditions (condition kept as metadata only)
    e2 = jload(VENDOR / "ds" / "work" / "e2_rows.json")
    import re
    def nid(t):
        return sha1(re.sub(r"\s+", " ", t).strip().lower())[:10]
    by_def = defaultdict(list)
    for r in e2:
        by_def[r["definition_id"]].append(r)
    n_unmatched = 0
    for d, rs in sorted(by_def.items()):
        rs = sorted(rs, key=lambda r: r["source_path"])
        for j, r in enumerate(rs):
            sid = nid(r["sentence"]) if r["sentence"] else None
            if sid not in sents:
                n_unmatched += 1
                continue
            cands.append({"cand_id": f"{sid}:pilot:{j}", "sentence_id": sid, "system": "pilot", "sample_idx": j,
                          "fol": r["candidate_fol"], "raw_output": None, "finish_reason": None, "gen_usd": 0.0,
                          "provider": None, "model": "user_pilot_pipeline", "frame": "pilot",
                          "pilot_condition": r["condition"], "pilot_run": r["run"], "pilot_source_path": r["source_path"],
                          "pilot_metric2_inconsistent_rate": r.get("pilot_metric2_inconsistent_rate"),
                          "pilot_metric5_mean_jaccard": r.get("pilot_metric5_mean_jaccard"),
                          "pilot_prolog_valid": r.get("pilot_prolog_valid"), "pilot_definition_id": d,
                          "pilot_parse_ok_vendor_e2": r["parse_ok"]})
    for c in cands:
        pr = parse(c["fol"] or "") if c["fol"] else None
        c["parse_ok"] = bool(pr and pr.ok)
        c["parse_error"] = pr.error if pr else "empty_output"
        if c["parse_ok"]:
            preds, consts = signature(pr.ast)
            cx = complexity_ast(pr.ast)
            c.update(n_preds=len(preds), n_consts=len(consts), n_quant=cx["n_quantifiers"], depth=cx["nesting_depth"],
                     fol_canon=__import__("fol_parse").to_str(pr.ast))
        else:
            c.update(n_preds=None, n_consts=None, n_quant=None, depth=None, fol_canon=None)
    write_jsonl(WORK / "candidates.jsonl", cands)
    cnt = Counter((c["frame"], c["sample_idx"] == 0 if c["frame"] == "system" else True) for c in cands)
    info = {"n_candidates": len(cands), "counts": {f"{a}|{'greedy' if b else 'sample'}": n for (a, b), n in cnt.items()},
            "pilot_unmatched": n_unmatched, "pilot_parse_ok": sum(c["parse_ok"] for c in cands if c["frame"] == "pilot"),
            "greedy_parse_rate": sum(c["parse_ok"] for c in cands if c["frame"] == "system" and c["sample_idx"] == 0) /
            max(1, sum(1 for c in cands if c["frame"] == "system" and c["sample_idx"] == 0))}
    jdump(info, RES / "candidates_report.json")
    logger.info(f"assembled: {info}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", type=int, default=0)
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--no-samples-public", action="store_true")
    ap.add_argument("--assemble", action="store_true")
    a = ap.parse_args()
    frozen = check_frozen()
    logger.info(f"frozen check: {frozen}")
    if a.assemble:
        assemble()
        return
    sents = jload(WORK / "sentences.json")
    dk = done_keys()
    jobs = []
    if a.probe:
        import random
        rng = random.Random(1)
        probe = rng.sample(sents, a.probe)
        for s in probe:
            for sysn in SYSTEMS:
                if (s["sentence_id"], sysn, 0) not in dk:
                    jobs.append((sysn, s, 0))
        res = asyncio.run(run_jobs(jobs))
        allrows = [r for r in read_jsonl(GEN) if r["sentence_id"] in {s["sentence_id"] for s in probe} and r["sample_idx"] == 0]
        summ = summarize(allrows)
        n_full = len(sents) * (9 + 10)
        summ["extrapolated_full_usd"] = summ["usd_per_call"] * n_full
        summ["probe_sentence_ids"] = [s["sentence_id"] for s in probe]
        summ.update({k: v for k, v in res.items() if k != "rows"})
        jdump(summ, RES / "generation_probe.json")
        logger.info(f"probe summary: {json.dumps(summ)[:1500]}")
        return
    if a.full:
        for s in sents:
            for sysn in SYSTEMS:
                if (s["sentence_id"], sysn, 0) not in dk:
                    jobs.append((sysn, s, 0))
        for s in sents:
            if a.no_samples_public and not s["in_ai_act"]:
                continue
            for sysn in SAMPLE_SYSTEMS:
                for k in range(1, 6):
                    if (s["sentence_id"], sysn, k) not in dk:
                        jobs.append((sysn, s, k))
        jobs.sort(key=lambda j: (j[2] > 0, j[0]))
        logger.info(f"jobs {len(jobs)} (greedy {sum(j[2] == 0 for j in jobs)})")
        res = asyncio.run(run_jobs(jobs))
        rows = [r for r in read_jsonl(GEN)]
        summ = summarize([r for r in rows if r["sample_idx"] == 0])
        summ["samples"] = summarize([r for r in rows if r["sample_idx"] > 0])
        summ.update({k: v for k, v in res.items() if k != "rows"})
        jdump(summ, RES / "generation_summary.json")
        logger.info(f"full summary: {json.dumps(summ)[:1500]}")


if __name__ == "__main__":
    main()
