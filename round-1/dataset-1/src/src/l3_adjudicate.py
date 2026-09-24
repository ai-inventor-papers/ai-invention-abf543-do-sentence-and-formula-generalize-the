#!/usr/bin/env python3
"""STEP 8: L3 full 3-member blinded A/B adjudication of 300 stratified greedy candidates.

Sampling frame: greedy, parseable held-out candidates whose sentence has an audited gold.
  - 250 L1_audited NON-equivalent (non_equiv / non_equiv_no_bijection / unknown_*), of which every
    L2 equiv_granular item up to 40 is forced (own stratum); the rest stratified by
    corpus(3) x system tier(2) x tercile(3) with the top tercile oversampled 1.5x;
  - 50 L1_audited EQUIVALENT (equiv_proved / equiv_bounded), stratified by corpus.
L3_sampling_weight = N_stratum / n_stratum (inverse inclusion probability).
Gold and candidate are shown as Formula A / Formula B in seeded random order; the panel is not told
which is the reference nor any system name. All 3 members vote on every item.
Writes work/l3_results.json.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from label_l1 import audited_gold_map, load_cache as load_l1, load_generations, pair_key  # noqa: E402
from or_client import BudgetExceeded, Client  # noqa: E402
from panel import ADJ_TMPL, cached_call, load_cache, norm_errs, yn  # noqa: E402

logger.remove()
logger.add(sys.stdout, level="INFO", format="{time:HH:mm:ss}|{level:<7}|{message}")
logger.add(ROOT / "logs" / "l3.log", rotation="30 MB", level="DEBUG")
CFG = json.loads((ROOT / "work" / "panel_config.json").read_text())["members"]
EQUIV = ("equiv_proved", "equiv_bounded")


def allocate(pop: dict, n: int, boost: dict) -> dict:
    w = {h: len(v) * boost.get(h, 1.0) for h, v in pop.items() if v}
    tot = sum(w.values())
    alloc = {h: max(1, round(n * w[h] / tot)) for h in w}
    alloc = {h: min(a, len(pop[h])) for h, a in alloc.items()}
    # fix rounding to hit n exactly
    order = sorted(w, key=lambda h: -w[h])
    i = 0
    while sum(alloc.values()) < n and any(alloc[h] < len(pop[h]) for h in order):
        h = order[i % len(order)]
        if alloc[h] < len(pop[h]):
            alloc[h] += 1
        i += 1
    while sum(alloc.values()) > n:
        h = max(alloc, key=lambda k: alloc[k] - 1 if alloc[k] > 1 else -1)
        alloc[h] -= 1
    return alloc


def build_frame() -> list[dict]:
    """Greedy, parseable held-out candidates with an audited gold and an L1_audited result."""
    held = {s["sentence_id"]: s for s in json.loads((ROOT / "work" / "heldout_sentences.json").read_text())}
    gmap = audited_gold_map()
    l1 = load_l1()
    frame = []
    for r in load_generations():
        if r["sample_idx"] != 0 or not r["parse_ok"]:
            continue
        s = held[r["sentence_id"]]
        gold, src = gmap[f"heldout:{s['sentence_id']}"]
        if not gold:
            continue
        res = l1.get(pair_key(r["candidate_fol"], gold))
        if res is None or res["status"] in ("gold_unparseable", "unparseable"):
            continue
        frame.append({"item_id": f"{s['sentence_id']}:{r['system']}:0", "sentence_id": s["sentence_id"], "system": r["system"],
                      "tier": r["tier"], "corpus": s["corpus"], "tercile": s["complexity_tercile"], "sentence": s["sentence"],
                      "candidate_fol": r["candidate_fol"], "gold": gold, "gold_source": src, "l1": res["status"],
                      "l2": res.get("L2_status")})
    return frame


def build_sample(n_non: int, n_eq: int, max_gran: int, seed: int = 0) -> list[dict]:
    frame = build_frame()
    rng = random.Random(seed)
    frame.sort(key=lambda x: x["item_id"])
    non = [x for x in frame if x["l1"] not in EQUIV]
    eq = [x for x in frame if x["l1"] in EQUIV]
    gran = [x for x in non if x["l2"] == "equiv_granular"]
    rest = [x for x in non if x["l2"] != "equiv_granular"]
    chosen = []
    g_take = rng.sample(gran, min(max_gran, len(gran)))
    for x in g_take:
        x["stratum"] = "nonequiv|l2_granular"
        x["weight"] = len(gran) / len(g_take)
    chosen += g_take
    pop = defaultdict(list)
    for x in rest:
        pop[f"nonequiv|{x['corpus']}|{x['tier']}|{x['tercile']}"].append(x)
    boost = {h: 1.5 for h in pop if h.endswith("|top")}
    alloc = allocate(pop, n_non - len(g_take), boost)
    for h, k in alloc.items():
        take = rng.sample(pop[h], k)
        for x in take:
            x["stratum"] = h
            x["weight"] = len(pop[h]) / k
        chosen += take
    pop_e = defaultdict(list)
    for x in eq:
        pop_e[f"equiv|{x['corpus']}"].append(x)
    alloc_e = allocate(pop_e, n_eq, {})
    for h, k in alloc_e.items():
        take = rng.sample(pop_e[h], k)
        for x in take:
            x["stratum"] = h
            x["weight"] = len(pop_e[h]) / k
        chosen += take
    for x in chosen:
        x["gold_is_A"] = rng.random() < 0.5
    frame_counts = {"frame_total": len(frame), "frame_nonequiv": len(non), "frame_equiv": len(eq),
                    "frame_l2_granular": len(gran)}
    return chosen, frame_counts


def parse_vote(rec: dict, gold_is_a: bool) -> dict | None:
    p = rec.get("parsed")
    if not p:
        return None
    gk, ck = ("A", "B") if gold_is_a else ("B", "A")
    c = p.get(ck) or {}
    g = p.get(gk) or {}
    return {"cand_faithful": yn(c.get("faithful")), "gold_faithful": yn(g.get("faithful")),
            "error_types": norm_errs(c.get("error_types")), "primary_error": (norm_errs(c.get("primary_error")) or ["other"])[0],
            "ambiguous": yn(p.get("sentence_ambiguous")), "same_meaning": yn(p.get("same_meaning")), "model": rec["model"]}


@logger.catch(reraise=True)
async def amain(args) -> None:
    items, frame_counts = build_sample(args.n_non, args.n_eq, args.max_gran)
    if args.limit:
        items = items[: args.limit]
    logger.info(f"L3 sample {len(items)}: {Counter(x['stratum'].split('|')[0] for x in items)} frame={frame_counts}")
    cache = load_cache()
    out = {}
    async with Client("l3_adjudication", phase_cap=args.cap, concurrency=args.concurrency) as client:
        async def one(x):
            a, b = (x["gold"], x["candidate_fol"]) if x["gold_is_A"] else (x["candidate_fol"], x["gold"])
            prompt = ADJ_TMPL.format(sentence=x["sentence"], a=a, b=b)
            key = f"l3|{x['item_id']}|{int(x['gold_is_A'])}"
            recs = await asyncio.gather(*[cached_call(client, cache, key, CFG[m], prompt, m) for m in ("M1", "M2", "M3")])
            votes = {m: parse_vote(r, x["gold_is_A"]) for m, r in zip(("M1", "M2", "M3"), recs)}
            cf = [v["cand_faithful"] for v in votes.values() if v and v["cand_faithful"] is not None]
            cnt = Counter(cf)
            maj = None
            if cnt[True] > len(cf) / 2:
                maj = True
            elif cnt[False] > len(cf) / 2:
                maj = False
            un = [v["primary_error"] for v in votes.values() if v and v["cand_faithful"] is False]
            pe = Counter(un).most_common(1)[0][0] if (maj is False and un) else ("none" if maj else None)
            x2 = dict(x)
            x2.update({"L3_votes": votes, "L3_majority": maj, "L3_primary_error": pe,
                       "L3_dissent": sorted(m for m, v in votes.items() if v and maj is not None and v["cand_faithful"] is not None and v["cand_faithful"] != maj)})
            out[x["item_id"]] = x2
        try:
            await asyncio.gather(*[one(x) for x in items])
        except BudgetExceeded as e:
            logger.error(f"budget stop: {e}")
        logger.info(f"L3 spend ${client.spent_phase:.3f}; total ${client.spent_total:.3f}")
    maj = Counter(str(v["L3_majority"]) for v in out.values())
    logger.info(f"L3 majority counts {dict(maj)}")
    (ROOT / "work" / "l3_results.json").write_text(json.dumps({"frame_counts": frame_counts, "results": out},
                                                              ensure_ascii=False, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-non", type=int, default=250)
    ap.add_argument("--n-eq", type=int, default=50)
    ap.add_argument("--max-gran", type=int, default=40)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--cap", type=float, default=3.0)
    ap.add_argument("--concurrency", type=int, default=24)
    asyncio.run(amain(ap.parse_args()))
