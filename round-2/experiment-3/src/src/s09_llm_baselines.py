#!/usr/bin/env python3
"""STEP 9: frozen LLM baselines on the fresh set (prompts / requests copied verbatim from round 2).

  b1     B1 cheap judge: gemini-2.5-flash, T=0, reasoning {max_tokens 0, exclude}, max_tokens 16 (+48 retry), on
         ALL fresh greedy rows (unparseable rows too: the prompt takes the string)      -> work/b1_fresh.jsonl
  b3     B3 round trip: flash back-translation (B3_PROMPT, max_tokens 200, first line) -> DeBERTa-v3-large NLI (min of
         both directions) + MiniLM cosine (vendor/r2/src/gpu_b3.score_b3)            -> work/b3_fresh.jsonl
         Items: --scope panel (the L3 items; plan fallback F2(2)) or all
  tj     TJ typed judge (frozen round-2 exp-5 prompt, flash, thinking off) on the L3 items -> work/tj_fresh.jsonl
  b1plus B1plus frontier judge: gemini-2.5-pro (reasoning max_tokens 128, max_tokens 256), same B1 prompt, on a
         seeded subset of L3 items (--n)                                                -> work/b1plus_fresh.jsonl
  retest B1 test-retest on 100 rows (sequential, cache bypass)                           -> work/b1_retest_fresh.jsonl
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import random
import re

from loguru import logger

from common import ROOT, WORK, read_jsonl, setup_logging, sha1, write_jsonl
from orc import BudgetExceeded, Client

FLASH = "google/gemini-2.5-flash"
B1_PROMPT = ("Sentence: {s}\nFOL: {f}\nGive the probability (0-100) that this FOL is a faithful formalization "
             "of the sentence. Reply with a number only.")
B3_PROMPT = ("Translate this first-order logic formula into one plain English sentence. Read predicate and "
             "constant names as words. Formula: {f}")
TAX = "\n".join(l for l in (ROOT / "vendor" / "ds" / "prompts" / "adjudication.txt").read_text().splitlines()
                if l.startswith("- ") and ":" in l and not l.startswith("- none"))
TJ_PROMPT = ("Sentence: {s}\nFOL: {f}\n\nNotation: ∀ ∃ quantifiers; ¬ not; ∧ and; ∨ inclusive or; → implies; ↔ iff; "
             "⊕ exclusive or. Different predicate names, different granularity and logically equivalent rewrites are "
             "acceptable; judge meaning only.\nIs the FOL a faithful formalization of the sentence? If not, choose the "
             "ONE primary error type from this list, and optionally a second:\n{tax}\n\nAnswer JSON only: "
             "{{\"faithful\": true|false, \"primary\": \"<type>\"|null, \"secondary\": \"<type>\"|null, "
             "\"p_faithful\": <0-100>}}")
FR = WORK / "fresh_frame.jsonl"


def first_number(text):
    m = re.search(r"-?\d+(?:\.\d+)?", text or "")
    if not m:
        return None
    return min(100.0, max(0.0, float(m.group(0)))) / 100.0


def b1_body(s, f, max_tokens=16, model=FLASH, reasoning=None):
    return {"model": model, "messages": [{"role": "user", "content": B1_PROMPT.format(s=s, f=f)}], "temperature": 0.0,
            "max_tokens": max_tokens, "reasoning": reasoning if reasoning is not None else {"max_tokens": 0, "exclude": True}}


async def gather(phase, cap, bodies, tags, conc=24, use_cache=True):
    async with Client(phase, phase_cap=cap, concurrency=conc, cache_name=phase) as c:
        async def one(b, t):
            try:
                return await c.chat(b, tag=t, use_cache=use_cache)
            except BudgetExceeded as e:
                logger.error(str(e))
                return None
        res = await asyncio.gather(*[one(b, t) for b, t in zip(bodies, tags)])
        logger.info(f"{phase}: calls {c.n_calls} cached {c.n_cached} failed {c.n_failed} phase ${c.spent_phase:.4f} "
                    f"total ${c.spent_total:.4f}")
        return res


def l3_items():
    l3 = json.loads((WORK / "l3_fresh.json").read_text())["results"]
    fr = {r["item_id"]: r for r in read_jsonl(FR)}
    return [fr[k] for k in sorted(l3)]


def cmd_b1(cap):
    rows = [r for r in read_jsonl(FR) if r["fold"] == "fresh_greedy"]
    bodies = [b1_body(r["sentence"], r["cand"] or "") for r in rows]
    res = asyncio.run(gather("B1", cap, bodies, [r["item_id"] for r in rows]))
    retry = [i for i, r in enumerate(res) if r is not None and r.get("text") is not None and first_number(r["text"]) is None]
    if retry:
        rr = asyncio.run(gather("B1", cap, [b1_body(rows[i]["sentence"], rows[i]["cand"] or "", 48) for i in retry],
                                [rows[i]["item_id"] + ":retry" for i in retry]))
        for i, r in zip(retry, rr):
            if r is not None and first_number(r.get("text")) is not None:
                res[i] = r
    out = []
    for r, x in zip(rows, res):
        v = None if x is None else first_number(x.get("text"))
        out.append({"item_id": r["item_id"], "B1": 0.5 if v is None else v, "covered": v is not None,
                    "usd": (x or {}).get("cost_usd", 0.0), "seconds": (x or {}).get("seconds"),
                    "raw": ((x or {}).get("text") or "")[:24], "prompt_sha1": sha1(B1_PROMPT.format(s=r["sentence"], f=r["cand"] or ""))})
    write_jsonl(WORK / "b1_fresh.jsonl", out)
    logger.info(f"B1 fresh {len(out)} covered {sum(o['covered'] for o in out)}; retries {len(retry)}")


def cmd_b3(cap, scope):
    rows = l3_items() if scope == "panel" else [r for r in read_jsonl(FR) if r["fold"] == "fresh_greedy"]
    bodies = [{"model": FLASH, "messages": [{"role": "user", "content": B3_PROMPT.format(f=r["cand"] or "")}],
               "temperature": 0.0, "max_tokens": 200, "reasoning": {"max_tokens": 0}} for r in rows]
    res = asyncio.run(gather("B3", cap, bodies, [r["item_id"] for r in rows]))
    items = []
    for r, x in zip(rows, res):
        txt = None if x is None or x.get("text") is None else (x["text"].strip().split("\n")[0].strip() or None)
        items.append({"key": r["item_id"], "sentence": r["sentence"], "back": txt, "usd": (x or {}).get("cost_usd", 0.0)})
    spec = importlib.util.spec_from_file_location("gpu_b3", ROOT / "vendor" / "r2" / "src" / "gpu_b3.py")
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)
    import torch
    if torch.cuda.is_available():
        torch.cuda.set_per_process_memory_fraction(0.6)
    sc = g.score_b3(items)
    by = {}
    for s in sc:
        by.setdefault(s["key"], {})[s["metric"]] = (s["score"], s["covered"])
    out = []
    for it in items:
        d = by.get(it["key"], {})
        out.append({"item_id": it["key"], "back": it["back"], "usd": it["usd"],
                    "B3cos": d.get("B3cos", (0.5, False))[0], "B3nli": d.get("B3nli", (0.5, False))[0],
                    "covered": d.get("B3nli", (0.5, False))[1]})
    write_jsonl(WORK / "b3_fresh.jsonl", out)
    logger.info(f"B3 fresh {len(out)}; example {json.dumps(out[0])[:300]}")


def parse_tj(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return {"parse_ok": False}
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"parse_ok": False}
    f = d.get("faithful")
    if isinstance(f, str):
        f = f.strip().lower() in ("true", "yes")
    pf = d.get("p_faithful")
    try:
        pf = float(pf) / 100.0 if pf is not None else None
    except (TypeError, ValueError):
        pf = None
    if pf is None and f is not None:
        pf = 1.0 if f else 0.0
    return {"parse_ok": True, "faithful": f, "primary": d.get("primary"), "secondary": d.get("secondary"), "p_faithful": pf}


def cmd_tj(cap):
    rows = l3_items()
    bodies = [{"model": FLASH, "messages": [{"role": "user", "content": TJ_PROMPT.format(s=r["sentence"], f=r["cand"] or "", tax=TAX)}],
               "reasoning": {"max_tokens": 0}, "max_tokens": 200} for r in rows]
    res = asyncio.run(gather("TJ", cap, bodies, [r["item_id"] for r in rows]))
    out = [{"item_id": r["item_id"], **(parse_tj(x.get("text")) if x else {"parse_ok": False}),
            "usd": (x or {}).get("cost_usd", 0.0)} for r, x in zip(rows, res)]
    write_jsonl(WORK / "tj_fresh.jsonl", out)
    logger.info(f"TJ fresh {len(out)} parsed {sum(o['parse_ok'] for o in out)}")


def cmd_b1plus(cap, n):
    rows = l3_items()
    rng = random.Random(11)
    rng.shuffle(rows)
    rows = rows[:n]
    bodies = [b1_body(r["sentence"], r["cand"] or "", 256, "google/gemini-2.5-pro", {"max_tokens": 128}) for r in rows]
    res = asyncio.run(gather("B1plus", cap, bodies, [r["item_id"] for r in rows], conc=12))
    out = []
    for r, x in zip(rows, res):
        v = None if x is None else first_number(x.get("text"))
        out.append({"item_id": r["item_id"], "B1plus": 0.5 if v is None else v, "covered": v is not None,
                    "usd": (x or {}).get("cost_usd", 0.0), "raw": ((x or {}).get("text") or "")[:40]})
    write_jsonl(WORK / "b1plus_fresh.jsonl", out)
    logger.info(f"B1plus fresh {len(out)} covered {sum(o['covered'] for o in out)}")


def cmd_retest(cap, n=100):
    rows = [r for r in read_jsonl(FR) if r["fold"] == "fresh_greedy"]
    rng = random.Random(3)
    rows = rng.sample(rows, n)
    res = asyncio.run(gather("B1_retest", cap, [b1_body(r["sentence"], r["cand"] or "") for r in rows],
                             [r["item_id"] for r in rows], conc=1, use_cache=False))
    first = {x["item_id"]: x["B1"] for x in read_jsonl(WORK / "b1_fresh.jsonl")}
    out = [{"item_id": r["item_id"], "B1_first": first.get(r["item_id"]), "B1_retest": first_number((x or {}).get("text"))}
           for r, x in zip(rows, res)]
    write_jsonl(WORK / "b1_retest_fresh.jsonl", out)


if __name__ == "__main__":
    setup_logging("s09_llm_baselines")
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["b1", "b3", "tj", "b1plus", "retest"])
    ap.add_argument("--cap", type=float, default=0.3)
    ap.add_argument("--scope", default="panel")
    ap.add_argument("--n", type=int, default=150)
    a = ap.parse_args()
    {"b1": lambda: cmd_b1(a.cap), "b3": lambda: cmd_b3(a.cap, a.scope), "tj": lambda: cmd_tj(a.cap),
     "b1plus": lambda: cmd_b1plus(a.cap, a.n), "retest": lambda: cmd_retest(a.cap)}[a.cmd]()
