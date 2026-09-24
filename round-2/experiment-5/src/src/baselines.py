#!/usr/bin/env python3
"""S4 baselines on the SAME candidates.

  b1      B1 cheap judge: exact round-1/2 prompt + request (gemini-2.5-flash, T=0, reasoning max_tokens 0 exclude,
          max_tokens 16, retry 48) on ALL greedy + pilot candidates incl. unparseable ones      -> work/b1.jsonl
  b1plus  B1plus frontier judge (FRONTIER_CHAIN: gemini-2.5-pro reasoning 128 / max_tokens 256 ...) on the panel sample
  b3      B3 round trip: flash back-translation (B3_PROMPT) on the panel sample, then GPU DeBERTa-v3-large NLI (min of
          both directions) and MiniLM cosine vs the sentence (vendor gpu_b3.score_b3)       -> work/b3.jsonl
  struct  B2 parse, B7 structural metrics (arity_self, arity_doc, joint-load conflict, cross-run Jaccard), and the
          vocabulary-conformity control VC (NAME-based on purpose)                            -> work/struct.jsonl
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import random
import re
import sys
import time
from collections import Counter, defaultdict

from common import RES, ROOT, SEED, VENDOR, WORK, jdump, jload, read_jsonl, setup_logger, sha1, write_jsonl

logger = setup_logger("baselines")
from llm import BudgetExceeded, Client, gather_bodies, ledger_total  # noqa: E402

# ---- exact vendor strings (vendor/iter2/llm_stages.py), sha1-checked against Arm B prompts_frozen.json
FLASH = "google/gemini-2.5-flash"
B1_PROMPT = ("Sentence: {s}\nFOL: {f}\nGive the probability (0-100) that this FOL is a faithful formalization "
             "of the sentence. Reply with a number only.")
B3_PROMPT = ("Translate this first-order logic formula into one plain English sentence. Read predicate and "
             "constant names as words. Formula: {f}")
FRONTIER_CHAIN = [
    {"model": "google/gemini-2.5-pro", "reasoning": {"max_tokens": 128}, "max_tokens": 256, "frontier": True},
    {"model": "openai/gpt-5", "reasoning": {"effort": "low"}, "max_tokens": 1024, "frontier": True},
    {"model": "openai/gpt-5-mini", "reasoning": {"effort": "medium"}, "max_tokens": 2048, "frontier": False},
]


def check_frozen() -> dict:
    pf = jload(VENDOR / "armB" / "prompts_frozen.json")
    src = (VENDOR / "iter2" / "llm_stages.py").read_text()
    ok = {"B1_matches_prompts_frozen": pf["B1_PROMPT"] == B1_PROMPT,
          "B1_sha1": hashlib.sha1(B1_PROMPT.encode()).hexdigest(),
          "B1_in_vendor_llm_stages": 'B1_PROMPT = ("Sentence: {s}\\nFOL: {f}\\nGive the probability (0-100) that this FOL is a faithful formalization "' in src,
          "B3_in_vendor_llm_stages": '"constant names as words. Formula: {f}")' in src}
    assert ok["B1_matches_prompts_frozen"], ok
    return ok


def first_number(text):
    m = re.search(r"-?\d+(?:\.\d+)?", text or "")
    if not m:
        return None
    return min(100.0, max(0.0, float(m.group(0)))) / 100.0


def b1_body(sentence: str, fol: str, max_tokens: int = 16) -> dict:
    return {"model": FLASH, "messages": [{"role": "user", "content": B1_PROMPT.format(s=sentence, f=fol)}],
            "temperature": 0.0, "max_tokens": max_tokens, "reasoning": {"max_tokens": 0, "exclude": True}}


def cand_items(ids: list[str] | None = None) -> list[dict]:
    sents = {s["sentence_id"]: s for s in jload(WORK / "sentences.json")}
    out = []
    for c in read_jsonl(WORK / "candidates.jsonl"):
        if not (c["frame"] == "pilot" or c["sample_idx"] == 0):
            continue
        if ids is not None and c["cand_id"] not in ids:
            continue
        f = c["fol"] if c["fol"] else (c.get("raw_output") or "")
        out.append({"key": c["cand_id"], "sentence": sents[c["sentence_id"]]["sentence"], "fol": f, "sid": c["sentence_id"]})
    return out


async def _pilot_sweep(phase: str, bodies: list[dict], tags: list[str], cap: float, concurrency: int = 16,
                       n_pilot: int = 20) -> tuple[list, dict]:
    info = {"phase": phase, "n": len(bodies)}
    async with Client(phase, phase_cap=cap, concurrency=concurrency) as c:
        t0 = time.time()
        rp = await gather_bodies(c, bodies[:n_pilot], tags[:n_pilot])
        paid = [r for r in rp if r.get("text") is not None and not r.get("cached")]
        upc = sum(r["cost_usd"] for r in paid) / len(paid) if paid else 0.0
        from llm import body_key
        n_unc = sum(1 for b in bodies if body_key({**b, "usage": {"include": True}}) not in c.cache)
        est = upc * n_unc
        info.update(pilot_usd_per_call=upc, n_uncached=n_unc, projected_usd=est, spent_phase_before=c.spent_phase)
        logger.info(f"[{phase}] $/call {upc:.6f} uncached {n_unc} projected ${est:.3f} cap ${cap}")
        if c.spent_phase + est > cap:
            info["aborted"] = "projection exceeds cap"
            return [None] * len(bodies), info
        res = await gather_bodies(c, bodies, tags)
        info.update(wall_s=round(time.time() - t0, 1), phase_spent=c.spent_phase, n_paid=c.n_calls, n_cached=c.n_cached,
                    n_failed=c.n_failed)
    return res, info


def run_b1() -> None:
    items = cand_items()
    bodies = [b1_body(it["sentence"], it["fol"]) for it in items]
    res, info = asyncio.run(_pilot_sweep("B1", bodies, [it["key"] for it in items], 0.15, concurrency=24))
    retry = [i for i, r in enumerate(res) if r is not None and first_number(r.get("text")) is None]
    info["n_retry_48"] = len(retry)
    if retry:
        async def _r():
            async with Client("B1", phase_cap=0.15) as c:
                return await gather_bodies(c, [b1_body(items[i]["sentence"], items[i]["fol"], 48) for i in retry],
                                           [items[i]["key"] + ":r48" for i in retry])
        for i, r in zip(retry, asyncio.run(_r())):
            if r is not None and first_number(r.get("text")) is not None:
                res[i] = r
    rows = []
    for it, r in zip(items, res):
        v = None if r is None else first_number(r.get("text"))
        rows.append({"key": it["key"], "B1": 0.5 if v is None else v, "B1_cov": v is not None,
                     "B1_usd": (r or {}).get("cost_usd", 0.0), "B1_sec": (r or {}).get("seconds"),
                     "B1_raw": ((r or {}).get("text") or "")[:24]})
    write_jsonl(WORK / "b1.jsonl", rows)
    info["coverage"] = sum(r["B1_cov"] for r in rows) / len(rows)
    info["frozen"] = check_frozen()
    jdump(info, RES / "b1_info.json")
    logger.info(f"B1 {info}")


def sample_ids() -> list[str]:
    return [s["item_id"] for s in jload(WORK / "panel_sample.json")["items"]]


def run_b1plus() -> None:
    samp = jload(WORK / "panel_sample.json")["items"]
    ids = [s["item_id"] for s in samp]
    items = {it["key"]: it for it in cand_items(set(ids))}
    items = [items[i] for i in ids]
    info = {"chain": []}
    chosen = None
    for cfg in FRONTIER_CHAIN:
        def mk(it, cfg=cfg):
            return {"model": cfg["model"], "messages": [{"role": "user", "content": B1_PROMPT.format(s=it["sentence"], f=it["fol"])}],
                    "temperature": 0.0, "max_tokens": cfg["max_tokens"], "reasoning": cfg["reasoning"]}

        async def _p():
            async with Client("B1plus", phase_cap=1.3, concurrency=10) as c:
                return await gather_bodies(c, [mk(it) for it in items[:20]], [it["key"] for it in items[:20]])
        rp = asyncio.run(_p())
        allr = [r for r in rp if r.get("text") is not None]
        paid = [r for r in allr if not r.get("cached")]
        upc = sum(r["cost_usd"] for r in (paid or allr)) / max(1, len(paid or allr))
        parse = sum(first_number(r["text"]) is not None for r in allr) / max(1, len(allr))
        info["chain"].append({"model": cfg["model"], "usd_per_call": upc, "parse_rate": parse, "n_ok": len(allr)})
        logger.info(f"B1plus pilot {cfg['model']} $/call {upc:.5f} parse {parse:.2f}")
        if parse >= 0.9 and len(allr) >= 15:
            chosen = (cfg, mk, upc)
            break
    if chosen is None:
        info["skipped"] = "no frontier model parseable"
        jdump(info, RES / "b1plus_info.json")
        return
    cfg, mk, upc = chosen
    spent = ledger_total("B1plus")
    n_aff = int((1.3 - spent - 0.03) / max(upc, 1e-9))
    run = items
    if n_aff < len(items):  # stratified subset (frame x marker bin), seeded
        info["subsampled"] = {"n_affordable": n_aff, "n_items": len(items)}
        n_target = min(n_aff, 400)
        rng = random.Random(SEED + 9)
        by = defaultdict(list)
        smeta = {s["item_id"]: s for s in samp}
        for it in items:
            by[(smeta[it["key"]]["frame"], smeta[it["key"]]["marker_bin"])].append(it)
        run = []
        for k in sorted(by):
            v = by[k]
            run += rng.sample(v, max(1, round(n_target * len(v) / len(items))))
        run = items[:20] + [it for it in run if it not in items[:20]]
    async def _go():
        async with Client("B1plus", phase_cap=1.3, concurrency=16) as c:
            return await gather_bodies(c, [mk(it) for it in run], [it["key"] for it in run])
    res = asyncio.run(_go())
    rows = []
    for it, r in zip(run, res):
        v = None if r is None else first_number(r.get("text"))
        rows.append({"key": it["key"], "B1plus": 0.5 if v is None else v, "B1plus_cov": v is not None,
                     "B1plus_usd": (r or {}).get("cost_usd", 0.0), "B1plus_sec": (r or {}).get("seconds"),
                     "B1plus_model": cfg["model"]})
    write_jsonl(WORK / "b1plus.jsonl", rows)
    info.update(model=cfg["model"], frontier=cfg["frontier"], n_run=len(run), coverage=sum(r["B1plus_cov"] for r in rows) / len(rows),
                phase_spent=ledger_total("B1plus"))
    jdump(info, RES / "b1plus_info.json")
    logger.info(f"B1plus {info}")


def run_b3() -> None:
    ids = sample_ids()
    items = {it["key"]: it for it in cand_items(set(ids))}
    items = [items[i] for i in ids]
    bodies = [{"model": FLASH, "messages": [{"role": "user", "content": B3_PROMPT.format(f=it["fol"])}],
               "temperature": 0.0, "max_tokens": 200, "reasoning": {"max_tokens": 0}} for it in items]
    res, info = asyncio.run(_pilot_sweep("B3", bodies, [it["key"] for it in items], 0.25))
    for it, r in zip(items, res):
        txt = None if r is None or not r.get("text") else (r["text"].strip().split("\n")[0].strip() or None)
        it["back"] = txt
        it["B3_usd"] = (r or {}).get("cost_usd", 0.0)
    sys.path.insert(0, str(VENDOR / "iter2"))
    import torch
    torch.cuda.set_per_process_memory_fraction(0.6)
    from gpu_b3 import score_b3
    scored = score_b3(items)
    by = defaultdict(dict)
    for r in scored:
        by[r["key"]][r["metric"]] = r
    rows = []
    for it in items:
        d = by[it["key"]]
        rows.append({"key": it["key"], "back": it["back"], "B3_usd": it["B3_usd"],
                     "B3nli": d["B3nli"]["score"], "B3nli_cov": d["B3nli"]["covered"],
                     "B3cos": d["B3cos"]["score"], "B3cos_cov": d["B3cos"]["covered"],
                     "B3_gpu_sec": d["B3nli"]["seconds"], "nli_model": d["B3nli"]["nli_model"]})
    write_jsonl(WORK / "b3.jsonl", rows)
    jdump(info, RES / "b3_info.json")
    logger.info(f"B3 {info}")


# ------------------------------------------------------------------------------------------------ structural + VC
def split_name(n: str) -> tuple:
    s = n.replace("_", " ").replace("-", " ")
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)
    out = []
    for w in s.lower().split():
        if len(w) > 4 and w.endswith("ies"):
            w = w[:-3] + "y"
        elif len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.append(w)
    return tuple(out)


def _joint_job(args):
    import z3
    sys.path.insert(0, str(VENDOR / "ds"))
    sys.path.insert(0, str(ROOT))
    from dc.core import z3_entails  # noqa: F401
    from fol_parse import normalize_arity_overloads, parse, signature
    key, fol, others = args
    asts = [normalize_arity_overloads(parse(f).ast) for f in [fol] + others]
    preds, consts = {}, set()
    for a in asts:
        p, c = signature(a)
        for k, v in p.items():
            preds[f"{k}/{v}"] = v
        consts |= c
    U = z3.DeclareSort("U")
    funcs = {p: (z3.Function("P_" + p.replace("/", "_"), *([U] * a), z3.BoolSort()) if a > 0 else z3.Bool("P_" + p.replace("/", "_"))) for p, a in preds.items()}
    cs = {c: z3.Const(f"K_{c}", U) for c in consts}

    def tr(n, env):
        op = n[0]
        if op == "atom":
            f = funcs[f"{n[1]}/{len(n[2])}"]
            args_ = [env[t[1]] if t[0] == "var" else cs[t[1]] for t in n[2]]
            return f(*args_) if args_ else f
        if op == "eq":
            a_ = [env[t[1]] if t[0] == "var" else cs[t[1]] for t in n[1:]]
            return a_[0] == a_[1]
        if op == "not":
            return z3.Not(tr(n[1], env))
        if op in ("and", "or", "imp", "iff", "xor"):
            x, y = tr(n[1], env), tr(n[2], env)
            return x == y if op == "iff" else {"and": z3.And, "or": z3.Or, "imp": z3.Implies, "xor": z3.Xor}[op](x, y)
        v = z3.Const(f"v_{n[1]}_{id(n)}", U)
        b = tr(n[2], {**env, n[1]: v})
        return z3.ForAll([v], b) if op == "forall" else z3.Exists([v], b)
    try:
        s = z3.Solver()
        s.set("timeout", 3000)
        for a in asts:
            s.add(tr(a, {}))
        r = s.check()
        return key, ("conflict" if r == z3.unsat else ("ok" if r == z3.sat else "unknown"))
    except (z3.Z3Exception, KeyError, RecursionError):
        return key, "unknown"


def run_struct(workers: int = 6) -> None:
    import multiprocessing as mp
    from concurrent.futures import ProcessPoolExecutor
    sys.path.insert(0, str(VENDOR / "ds"))
    from fol_parse import parse, signature
    sents = {s["sentence_id"]: s for s in jload(WORK / "sentences.json")}
    cands = read_jsonl(WORK / "candidates.jsonl")
    info = {}
    sig = {}
    for c in cands:
        if c["parse_ok"]:
            ast = parse(c["fol"]).ast
            raw = {}
            clash = False

            def walk(n):
                nonlocal clash
                if n[0] in ("forall", "exists"):
                    walk(n[2])
                elif n[0] == "not":
                    walk(n[1])
                elif n[0] in ("and", "or", "imp", "iff", "xor"):
                    walk(n[1]); walk(n[2])
                elif n[0] == "atom":
                    if n[1] in raw and raw[n[1]] != len(n[2]):
                        clash = True
                    raw.setdefault(n[1], len(n[2]))
            walk(ast)
            sig[c["cand_id"]] = {"preds": raw, "arity_clash": clash}
    # document = act (source document) x system; pilot = one 'system'
    doc = defaultdict(list)
    for c in cands:
        if c["parse_ok"] and (c["frame"] == "pilot" or c["sample_idx"] == 0):
            doc[(sents[c["sentence_id"]]["act"], c["system"])].append(c)
    arity_doc = {}
    for k, cs in doc.items():
        ar = defaultdict(set)
        for c in cs:
            for p, a in sig[c["cand_id"]]["preds"].items():
                ar[p].add(a)
        bad = {p for p, s in ar.items() if len(s) > 1}
        for c in cs:
            arity_doc[c["cand_id"]] = not (set(sig[c["cand_id"]]["preds"]) & bad)
    # joint load: candidate + the same system's other formulas of the same document sharing a predicate name
    jobs = []
    for k, cs in doc.items():
        for c in cs:
            ps = set(sig[c["cand_id"]]["preds"])
            oth = [d["fol"] for d in cs if d["cand_id"] != c["cand_id"] and ps & set(sig[d["cand_id"]]["preds"])]
            if oth:
                jobs.append((c["cand_id"], c["fol"], oth[:40]))
    t0 = time.time()
    joint = {}
    with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn")) as ex:
        for k, st in ex.map(_joint_job, jobs, chunksize=4):
            joint[k] = st
    info["joint_seconds"] = round(time.time() - t0, 1)
    info["joint_counts"] = dict(Counter(joint.values()))
    # VC peers = DC peers (other systems' greedy outputs; pilot rows: the 9 systems)
    by = defaultdict(list)
    for c in cands:
        by[c["sentence_id"]].append(c)
    rows = []
    for c in cands:
        if not (c["frame"] == "pilot" or c["sample_idx"] == 0):
            continue
        r = {"key": c["cand_id"], "B2": float(c["parse_ok"])}
        if c["parse_ok"]:
            s = sig[c["cand_id"]]
            r["B7_arity_self"] = int(not s["arity_clash"])
            r["B7_arity_doc"] = int(arity_doc.get(c["cand_id"], True))
            r["B7_joint"] = int(joint.get(c["cand_id"], "ok") != "conflict")
            r["B7"] = float(r["B7_arity_self"] and r["B7_arity_doc"] and r["B7_joint"])
            peers = [d for d in by[c["sentence_id"]] if d["frame"] == "system" and d["sample_idx"] == 0 and d["parse_ok"]
                     and (c["frame"] == "pilot" or d["system"] != c["system"])]
            mine = {split_name(p) for p in s["preds"]}
            prof = tuple(sorted(Counter(s["preds"].values()).items()))
            if peers:
                jac = []
                same = 0
                for d in peers:
                    ps = sig[d["cand_id"]]["preds"]
                    th = {split_name(p) for p in ps}
                    jac.append(len(mine & th) / max(1, len(mine | th)))
                    same += tuple(sorted(Counter(ps.values()).items())) == prof
                r["VC"] = 0.5 * sum(jac) / len(jac) + 0.5 * same / len(peers)
                r["VC_cov"] = 1
            else:
                r["VC"], r["VC_cov"] = 0.5, 0
            # cross-run Jaccard (user's metric5 style): greedy vs own samples (2 systems)
            samp = [d for d in by[c["sentence_id"]] if d["system"] == c["system"] and d["frame"] == "system" and d["sample_idx"] > 0]
            if c["frame"] == "system" and samp:
                js = []
                for d in samp:
                    th = set(sig[d["cand_id"]]["preds"]) if d["parse_ok"] else set()
                    js.append(len(set(s["preds"]) & th) / max(1, len(set(s["preds"]) | th)))
                r["B7_jacc"] = sum(js) / len(js)
        else:
            r.update(B7_arity_self=0, B7_arity_doc=0, B7_joint=0, B7=0.0, VC=0.5, VC_cov=0)
            if c["frame"] == "system" and any(d["system"] == c["system"] and d["sample_idx"] > 0 for d in by[c["sentence_id"]]):
                r["B7_jacc"] = 0.0
        if c["frame"] == "pilot":
            r["pilot_metric5"] = c.get("pilot_metric5_mean_jaccard")
            r["pilot_metric2"] = c.get("pilot_metric2_inconsistent_rate")
            r["pilot_prolog_valid"] = c.get("pilot_prolog_valid")
        rows.append(r)
    write_jsonl(WORK / "struct.jsonl", rows)
    info["n"] = len(rows)
    jdump(info, RES / "struct_info.json")
    logger.info(f"struct {info}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    if a.cmd == "b1":
        run_b1()
    elif a.cmd == "b1plus":
        run_b1plus()
    elif a.cmd == "b3":
        run_b3()
    elif a.cmd == "struct":
        run_struct(a.workers)
    elif a.cmd == "check":
        print(check_frozen())


if __name__ == "__main__":
    main()
