"""LLM-based metrics and probes (S4). All requests go through src/or_client.Client (ledger + hard cap + cache).

B1      cheap judge   : EXACT iter-1 prompt (sha1-checked against Arm B prompts_frozen.json) and request
                        (google/gemini-2.5-flash, T=0, reasoning {max_tokens 0, exclude true}); max_tokens 16 with a
                        max_tokens 48 retry for unparseable numbers (Arm A run_baselines.stage_b1).
B1plus  frontier judge: SAME B1 prompt; google/gemini-2.5-pro (reasoning max_tokens 128, max_tokens 256)
                        -> fallback openai/gpt-5 (effort low) -> openai/gpt-5-mini (medium, 'not frontier').
A1      probe         : Arm A text-side substitution-entailment prompts (built in the Arm A worker), gemini-2.5-flash,
                        reasoning max_tokens 1024, max_tokens 4000, T=0 (Arm A probe_config.json).
B3      round trip    : Arm A B3_PROMPT back-translation (gemini-2.5-flash, reasoning max_tokens 0, max_tokens 200,
                        first line kept); similarity/NLI computed on GPU in src/gpu_b3.py.
B3c     Monty-style   : clause-conformance between sentence and back-translation (RE-IMPLEMENTATION, labelled).
RECALL  gold recall   : asks for the benchmark's reference FOL of a public sentence (contamination probe).
"""
from __future__ import annotations

import asyncio
import json
import random
import re
import time
from pathlib import Path

from loguru import logger

from common import RES, WORK, append_jsonl, read_jsonl, sha1
from or_client import BudgetExceeded, Client

FLASH = "google/gemini-2.5-flash"
B1_PROMPT = ("Sentence: {s}\nFOL: {f}\nGive the probability (0-100) that this FOL is a faithful formalization "
             "of the sentence. Reply with a number only.")
B3_PROMPT = ("Translate this first-order logic formula into one plain English sentence. Read predicate and "
             "constant names as words. Formula: {f}")
B3C_PROMPT = ("List the atomic claims (clauses) of TEXT A, then of TEXT B. For each clause of A say whether B expresses "
              "it; for each clause of B say whether A expresses it. Return JSON {{\"a_clauses\":[...], "
              "\"a_covered\":[bool], \"b_clauses\":[...], \"b_covered\":[bool]}}\n\nTEXT A: {a}\nTEXT B: {b}")
RECALL_PROMPT = ("This sentence is from a public NL-to-FOL benchmark. Write its reference first-order-logic annotation "
                 "exactly as it appears in the dataset.\nSentence: {s}")
PHASE_CAPS = {"B1": 1.0, "B1_retest": 0.05, "A1": 1.9, "B3": 0.4, "B3c": 1.0, "B1plus": 1.8, "RECALL": 0.15}  # tightened: shared key had ~$7 left
FRONTIER_CHAIN = [
    {"model": "google/gemini-2.5-pro", "reasoning": {"max_tokens": 128}, "max_tokens": 256, "frontier": True},
    {"model": "openai/gpt-5", "reasoning": {"effort": "low"}, "max_tokens": 1024, "frontier": True},
    {"model": "openai/gpt-5-mini", "reasoning": {"effort": "medium"}, "max_tokens": 2048, "frontier": False},
]


def first_number(text: str | None):
    """Arm A run_baselines.first_number (clip to [0, 100], /100)."""
    m = re.search(r"-?\d+(?:\.\d+)?", text or "")
    if not m:
        return None
    return min(100.0, max(0.0, float(m.group(0)))) / 100.0


def b1_body(sentence: str, fol: str, max_tokens: int = 16) -> dict:
    return {"model": FLASH, "messages": [{"role": "user", "content": B1_PROMPT.format(s=sentence, f=fol)}],
            "temperature": 0.0, "max_tokens": max_tokens, "reasoning": {"max_tokens": 0, "exclude": True}}


async def _gather(client: Client, bodies: list[dict], tags: list[str]) -> list[dict]:
    async def one(b, t):
        try:
            return await client.chat(b, tag=t)
        except BudgetExceeded as e:
            return {"text": None, "error": f"budget:{e}", "cost_usd": 0.0, "seconds": None, "cached": False}
    return await asyncio.gather(*[one(b, t) for b, t in zip(bodies, tags)])


def _uncached(client: Client, bodies: list[dict]) -> int:
    from or_client import body_key
    return sum(1 for b in bodies if body_key({**b, "usage": {"include": True}}) not in client.cache)


async def _pilot_then_sweep(phase: str, bodies: list[dict], tags: list[str], concurrency: int = 16,
                            n_pilot: int = 20, max_usd_per_call: float | None = None) -> tuple[list[dict], dict]:
    """Pilot n calls -> $/call estimate -> abort if projected spend exceeds the phase cap -> sweep."""
    cap = PHASE_CAPS[phase]
    info = {"phase": phase, "n_requests": len(bodies)}
    async with Client(phase, cap, concurrency=concurrency) as c:
        n_unc = _uncached(c, bodies)
        info["n_unique_bodies"] = len({json.dumps(b, sort_keys=True) for b in bodies})
        info["n_uncached_before"] = n_unc
        pilot_idx = list(range(min(n_pilot, len(bodies))))
        spent0 = c.spent_phase
        t0 = time.time()
        res_p = await _gather(c, [bodies[i] for i in pilot_idx], [tags[i] for i in pilot_idx])
        paid = [r for r in res_p if not r.get("cached") and r.get("text") is not None]
        upc = (sum(r["cost_usd"] for r in paid) / len(paid)) if paid else None
        info["pilot_usd_per_call"] = upc
        info["pilot_seconds"] = round(time.time() - t0, 2)
        n_rem = _uncached(c, bodies)
        est = (upc or 0.0) * n_rem
        info["projected_remaining_usd"] = est
        logger.info(f"[{phase}] pilot $/call={upc} remaining uncached={n_rem} projected ${est:.3f} "
                    f"(phase spent ${c.spent_phase:.3f}, cap ${cap}; total spent ${c.spent_total:.3f})")
        if max_usd_per_call is not None and upc is not None and upc > max_usd_per_call:
            info["aborted"] = f"$/call {upc:.5f} > {max_usd_per_call}"
            return [None] * len(bodies), info
        if c.spent_phase + est > cap or c.spent_total + est > 9.5:
            info["aborted"] = "projected spend exceeds cap"
            logger.error(f"[{phase}] ABORT: projected ${est:.3f} exceeds cap")
            return [None] * len(bodies), info
        res = await _gather(c, bodies, tags)
        info.update(n_paid=c.n_calls, n_cached=c.n_cached, n_failed=c.n_failed,
                    phase_spent_usd=c.spent_phase - spent0 if spent0 is not None else c.spent_phase,
                    phase_spent_total=c.spent_phase, wall_s=round(time.time() - t0, 1))
    return res, info


# ------------------------------------------------------------------------------------------------ B1
def run_b1(items: list[dict], out_file: str, phase: str = "B1") -> dict:
    """items: {key, sentence, fol}. Writes work/<out_file> rows {key, metric=B1, score, covered, usd, seconds, raw}."""
    bodies = [b1_body(it["sentence"], it["fol"] or "") for it in items]
    tags = [it["key"] for it in items]
    res, info = asyncio.run(_pilot_then_sweep(phase, bodies, tags))
    retry = [i for i, r in enumerate(res) if r is not None and first_number(r.get("text")) is None]
    info["n_retry_48"] = len(retry)
    if retry:
        async def _r():
            async with Client(phase, PHASE_CAPS[phase]) as c:
                return await _gather(c, [b1_body(items[i]["sentence"], items[i]["fol"] or "", 48) for i in retry],
                                     [items[i]["key"] + ":retry" for i in retry])
        rr = asyncio.run(_r())
        for i, r in zip(retry, rr):
            if r is not None and first_number(r.get("text")) is not None:
                res[i] = r
    rows = []
    for it, r in zip(items, res):
        v = None if r is None else first_number(r.get("text"))
        rows.append({"key": it["key"], "metric": "B1", "score": 0.5 if v is None else v, "covered": v is not None,
                     "usd": (r or {}).get("cost_usd", 0.0) if not (r or {}).get("cached") else 0.0,
                     "usd_unit": (r or {}).get("cost_usd", 0.0), "seconds": (r or {}).get("seconds"),
                     "raw": ((r or {}).get("text") or "")[:24], "cached": bool((r or {}).get("cached")),
                     "prompt_sha1": sha1(B1_PROMPT.format(s=it["sentence"], f=it["fol"] or "")),
                     "error": (r or {}).get("error", "no_response" if r is None else "")})
    from common import write_jsonl
    write_jsonl(WORK / out_file, rows)
    info["parse_rate"] = sum(r["covered"] for r in rows) / max(1, len(rows))
    logger.info(f"B1 {out_file}: {json.dumps(info)[:600]}")
    return info


def run_b1_retest(items: list[dict], n: int = 300, seed: int = 0) -> dict:
    """Re-call n random UNIQUE B1 prompts sequentially (concurrency 1, cache bypassed). Primary score = first pass."""
    first = {r["key"]: r for r in read_jsonl(WORK / "b1_scores.jsonl")}
    uniq = {}
    for it in items:
        p = B1_PROMPT.format(s=it["sentence"], f=it["fol"] or "")
        if it["key"] in first and first[it["key"]]["covered"] and p not in uniq:
            uniq[p] = it
    keys = sorted(uniq)
    random.Random(seed).shuffle(keys)
    pick = [uniq[k] for k in keys[:n]]
    outp = WORK / "b1_retest.jsonl"
    have = {r["key"] for r in read_jsonl(outp)}
    todo = [it for it in pick if it["key"] not in have]

    async def _run():
        async with Client("B1_retest", PHASE_CAPS["B1_retest"], concurrency=1, cache_name="B1_retest") as c:
            for it in todo:
                try:
                    r = await c.chat(b1_body(it["sentence"], it["fol"] or ""), tag=it["key"], use_cache=False)
                except BudgetExceeded as e:
                    logger.error(f"retest budget stop {e}")
                    break
                append_jsonl(outp, [{"key": it["key"], "score2": first_number(r.get("text")), "raw2": r.get("text")}])
    asyncio.run(_run())
    rows = read_jsonl(outp)
    return {"n": len(rows)}


# ------------------------------------------------------------------------------------------------ A1
def run_a1(prompts: list[dict]) -> dict:
    """prompts: rows of work/a1_prompts.jsonl {sentence, prompts:[{offset, prompt}]}. -> work/a1_raw.jsonl"""
    cfg = json.loads((Path(__file__).resolve().parents[1] / "vendor" / "armA" / "results" / "probe_config.json")
                     .read_text())
    bodies, tags, meta = [], [], []
    for i, p in enumerate(prompts):
        for ch in p["prompts"]:
            bodies.append({"model": cfg["model"], "messages": [{"role": "user", "content": ch["prompt"]}],
                           "temperature": 0.0, "max_tokens": 4000 if cfg["reasoning"].get("max_tokens") else 1200,
                           "reasoning": cfg["reasoning"]})
            tags.append(f"a1:{sha1(p['sentence'])[:10]}:{ch['offset']}")
            meta.append((i, ch["offset"]))
    res, info = asyncio.run(_pilot_then_sweep("A1", bodies, tags, concurrency=12))
    per = {}
    for (i, off), r in zip(meta, res):
        d = per.setdefault(i, {"sentence": prompts[i]["sentence"], "chunks": [], "usd": 0.0, "seconds": 0.0,
                               "failed": 0})
        if r is None or r.get("text") is None:
            d["failed"] += 1
            continue
        d["chunks"].append({"offset": off, "text": r["text"]})
        d["usd"] += r.get("cost_usd", 0.0)
        d["seconds"] += r.get("seconds") or 0.0
    from common import write_jsonl
    write_jsonl(WORK / "a1_raw.jsonl", list(per.values()))
    info["n_sentences_ok"] = sum(1 for d in per.values() if d["chunks"] and not d["failed"])
    logger.info(f"A1: {json.dumps(info)[:600]}")
    return info


# ------------------------------------------------------------------------------------------------ B3 / B3c
def run_b3_back(items: list[dict]) -> dict:
    """items {key, fol}; -> work/b3_back.jsonl {key, back, usd, seconds}"""
    bodies = [{"model": FLASH, "messages": [{"role": "user", "content": B3_PROMPT.format(f=it["fol"] or "")}],
               "temperature": 0.0, "max_tokens": 200, "reasoning": {"max_tokens": 0}} for it in items]
    res, info = asyncio.run(_pilot_then_sweep("B3", bodies, [it["key"] for it in items]))
    rows = []
    for it, r in zip(items, res):
        txt = None if r is None or r.get("text") is None else (r["text"].strip().split("\n")[0].strip() or None)
        rows.append({"key": it["key"], "back": txt, "usd": (r or {}).get("cost_usd", 0.0),
                     "seconds": (r or {}).get("seconds")})
    from common import write_jsonl
    write_jsonl(WORK / "b3_back.jsonl", rows)
    logger.info(f"B3 back: {json.dumps(info)[:500]}")
    return info


def _b3c_score(text: str | None):
    if not text:
        return None, None
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None, None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None, None
    ac, bc = d.get("a_covered"), d.get("b_covered")
    # tolerant reading: a scalar bool is taken to apply to every listed clause (Qwen3 often answers that way)
    if isinstance(ac, bool):
        ac = [ac] * max(1, len(d.get("a_clauses") or []))
    if isinstance(bc, bool):
        bc = [bc] * max(1, len(d.get("b_clauses") or []))
    if not isinstance(ac, list) or not isinstance(bc, list) or not ac or not bc:
        return None, None
    ca = sum(bool(x) for x in ac) / len(ac)
    cb = sum(bool(x) for x in bc) / len(bc)
    hm = 0.0 if ca + cb == 0 else 2 * ca * cb / (ca + cb)
    return hm, {"cov_a": ca, "cov_b": cb, "n_a": len(ac), "n_b": len(bc)}


def run_b3c(items: list[dict]) -> dict:
    """items {key, sentence, back}; -> work/b3c_scores.jsonl"""
    ok = [it for it in items if it.get("back")]
    bodies = [{"model": FLASH, "messages": [{"role": "user", "content": B3C_PROMPT.format(a=it["sentence"], b=it["back"])}],
               "temperature": 0.0, "max_tokens": 800, "reasoning": {"max_tokens": 0}} for it in ok]
    res, info = asyncio.run(_pilot_then_sweep("B3c", bodies, [it["key"] for it in ok]))
    by = {it["key"]: r for it, r in zip(ok, res)}
    rows = []
    for it in items:
        r = by.get(it["key"])
        sc, extra = _b3c_score(None if r is None else r.get("text"))
        rows.append({"key": it["key"], "metric": "B3c", "score": 0.5 if sc is None else sc, "covered": sc is not None,
                     "usd": (r or {}).get("cost_usd", 0.0), "seconds": (r or {}).get("seconds"), "extra": extra})
    from common import write_jsonl
    write_jsonl(WORK / "b3c_scores.jsonl", rows)
    logger.info(f"B3c: {json.dumps(info)[:500]}")
    return info


# ------------------------------------------------------------------------------------------------ B1+
def run_b1plus(items: list[dict], priority_n: int) -> dict:
    """items {key, sentence, fol}; the first priority_n items (panel) are always kept; the rest (contamination slice)
    are subsampled BY SENTENCE if the budget does not fit. Fallback chain FRONTIER_CHAIN."""
    info = {"chain": []}
    chosen = None
    for cfg in FRONTIER_CHAIN:
        body0 = lambda it, cfg=cfg: {"model": cfg["model"], "messages": [{"role": "user", "content": B1_PROMPT.format(
            s=it["sentence"], f=it["fol"] or "")}], "temperature": 0.0, "max_tokens": cfg["max_tokens"],
            "reasoning": cfg["reasoning"]}
        pilot = items[:20]

        async def _p():
            async with Client("B1plus", PHASE_CAPS["B1plus"], concurrency=10) as c:
                return await _gather(c, [body0(it) for it in pilot], [it["key"] for it in pilot])
        rp = asyncio.run(_p())
        paid = [r for r in rp if r.get("text") is not None and not r.get("cached")]
        allr = [r for r in rp if r.get("text") is not None]
        parse = sum(first_number(r["text"]) is not None for r in allr) / max(1, len(allr))
        upc = (sum(r["cost_usd"] for r in paid) / len(paid)) if paid else (
            sum(r["cost_usd"] for r in allr) / len(allr) if allr else None)
        info["chain"].append({"model": cfg["model"], "pilot_usd_per_call": upc, "pilot_parse_rate": parse,
                              "n_ok": len(allr)})
        logger.info(f"B1plus pilot {cfg['model']}: $/call={upc} parse={parse:.2f} ok={len(allr)}/20")
        if upc is not None and upc <= 0.005 and parse >= 0.9 and len(allr) >= 15:
            chosen = (cfg, body0, upc)
            break
    if chosen is None:
        info["skipped"] = "no model in the fallback chain fits $0.005/call with >=90% parseable pilot"
        return info
    cfg, body0, upc = chosen
    info["model"], info["frontier"] = cfg["model"], cfg["frontier"]
    async def _spent():
        async with Client("B1plus", PHASE_CAPS["B1plus"]) as c:
            return c.spent_phase, c
    spent_phase, c0 = asyncio.run(_spent())
    remaining = PHASE_CAPS["B1plus"] - spent_phase - 0.05
    n_aff = int(remaining / max(upc, 1e-9))
    prio, rest = items[:priority_n], items[priority_n:]
    if len(items) > n_aff + 20:
        by_s = {}
        for it in rest:
            by_s.setdefault(it["sid"], []).append(it)
        sids = sorted(by_s)
        random.Random(0).shuffle(sids)
        keep = []
        for s in sids:
            if len(prio) + len(keep) + len(by_s[s]) > n_aff:
                break
            keep += by_s[s]
        info["contamination_subsampled"] = {"n_before": len(rest), "n_after": len(keep)}
        rest = keep
    run = prio + rest
    info["n_affordable"] = n_aff
    bodies = [body0(it) for it in run]

    async def _go():
        async with Client("B1plus", PHASE_CAPS["B1plus"], concurrency=16) as c:
            r = await _gather(c, bodies, [it["key"] for it in run])
            return r, c.n_calls, c.n_cached, c.spent_phase
    res, npaid, ncached, sp = asyncio.run(_go())
    rows = []
    for it, r in zip(run, res):
        v = None if r is None else first_number(r.get("text"))
        rows.append({"key": it["key"], "metric": "B1plus", "score": 0.5 if v is None else v, "covered": v is not None,
                     "usd": (r or {}).get("cost_usd", 0.0), "seconds": (r or {}).get("seconds"),
                     "raw": ((r or {}).get("text") or "")[:24], "model": cfg["model"]})
    from common import write_jsonl
    write_jsonl(WORK / "b1plus_scores.jsonl", rows)
    info.update(n_run=len(run), n_paid=npaid, n_cached=ncached, phase_spent=sp,
                parse_rate=sum(r["covered"] for r in rows) / max(1, len(rows)))
    logger.info(f"B1plus: {json.dumps(info)[:600]}")
    return info


# ------------------------------------------------------------------------------------------------ recall
def run_recall(items: list[dict]) -> dict:
    """items {key, sentence}; -> work/recall.jsonl"""
    bodies = [{"model": FLASH, "messages": [{"role": "user", "content": RECALL_PROMPT.format(s=it["sentence"])}],
               "temperature": 0.0, "max_tokens": 300, "reasoning": {"max_tokens": 0}} for it in items]
    res, info = asyncio.run(_pilot_then_sweep("RECALL", bodies, [it["key"] for it in items]))
    rows = [{"key": it["key"], "text": (r or {}).get("text"), "usd": (r or {}).get("cost_usd", 0.0)}
            for it, r in zip(items, res)]
    from common import write_jsonl
    write_jsonl(WORK / "recall.jsonl", rows)
    return info
