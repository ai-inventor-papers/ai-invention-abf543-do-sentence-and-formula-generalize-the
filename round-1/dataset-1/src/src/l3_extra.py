#!/usr/bin/env python3
"""L3 extension: N extra blinded 3-member adjudications drawn uniformly at random (seed 1) from the
TOP-tercile non-equivalent strata, excluding already-adjudicated items. Merged into
work/l3_results.json (design stratum 'extra_top|<stratum>'); assemble.py re-weights all L3 items by
post-stratification on the current frame, so the within-stratum random draw keeps estimates unbiased."""
import argparse
import asyncio
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import l3_adjudicate as L  # noqa: E402
from or_client import BudgetExceeded, Client  # noqa: E402
from panel import ADJ_TMPL, cached_call, load_cache  # noqa: E402
from collections import Counter  # noqa: E402


async def amain(a):
    cur = json.loads((ROOT / "work" / "l3_results.json").read_text())
    done = set(cur["results"])
    pool = []
    for x in L.build_frame():
        if x["l1"] in L.EQUIV or x["l2"] == "equiv_granular" or x["tercile"] != "top" or x["item_id"] in done:
            continue
        x["stratum"] = f"nonequiv|{x['corpus']}|{x['tier']}|{x['tercile']}"
        pool.append(x)
    rng = random.Random(1)
    pool.sort(key=lambda x: x["item_id"])
    take = rng.sample(pool, min(a.n, len(pool)))
    for x in take:
        x["gold_is_A"] = rng.random() < 0.5
        x["stratum"] = "extra_top|" + x["stratum"]
        x["weight"] = None
    cache = load_cache()
    async with Client("l3_adjudication_extra", phase_cap=a.cap, concurrency=24) as client:
        async def one(x):
            A, B = (x["gold"], x["candidate_fol"]) if x["gold_is_A"] else (x["candidate_fol"], x["gold"])
            key = f"l3|{x['item_id']}|{int(x['gold_is_A'])}"
            recs = await asyncio.gather(*[cached_call(client, cache, key, L.CFG[m], ADJ_TMPL.format(sentence=x["sentence"], a=A, b=B), m)
                                          for m in ("M1", "M2", "M3")])
            votes = {m: L.parse_vote(r, x["gold_is_A"]) for m, r in zip(("M1", "M2", "M3"), recs)}
            cf = [v["cand_faithful"] for v in votes.values() if v and v["cand_faithful"] is not None]
            c = Counter(cf)
            maj = True if c[True] > len(cf) / 2 else (False if c[False] > len(cf) / 2 else None)
            un = [v["primary_error"] for v in votes.values() if v and v["cand_faithful"] is False]
            x.update({"L3_votes": votes, "L3_majority": maj,
                      "L3_primary_error": Counter(un).most_common(1)[0][0] if (maj is False and un) else ("none" if maj else None),
                      "L3_dissent": sorted(m for m, v in votes.items() if v and maj is not None and v["cand_faithful"] is not None and v["cand_faithful"] != maj)})
            cur["results"][x["item_id"]] = x
        try:
            await asyncio.gather(*[one(x) for x in take])
        except BudgetExceeded as e:
            print("budget stop", e)
        print(f"extra L3 spend ${client.spent_phase:.3f}; total ${client.spent_total:.3f}; added {len(take)}")
    cur["extra_top"] = {"n": len(take), "seed": 1, "pool": len(pool)}
    (ROOT / "work" / "l3_results.json").write_text(json.dumps(cur, ensure_ascii=False, indent=1))

ap = argparse.ArgumentParser()
ap.add_argument("--n", type=int, default=150)
ap.add_argument("--cap", type=float, default=0.85)
asyncio.run(ap.parse_args() and amain(ap.parse_args()))
