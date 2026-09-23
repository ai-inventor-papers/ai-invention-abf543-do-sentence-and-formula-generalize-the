"""TVJT_iter1 ablation on held-out items: the UNREPAIRED iter-1 protocol — worlds from tvjt.worlds_for(F,
seed=item_id, max_worlds=12, card_variants=False as iter-1 stage_tvjt), the iter-1 'tvjt_v1' prompt (TRUE/FALSE/UNCLEAR),
1 vote, gemini-2.5-flash T=0 reasoning off, max_tokens 300 (+1 format-reminder retry), iter-1 score_answers.

    python stage_iter1.py P|T
"""
from __future__ import annotations

import asyncio
import json
import multiprocessing as mp
import sys
import time
from concurrent.futures import ProcessPoolExecutor

from loguru import logger

import common
import judge as J
from common import DATA, RESULTS, append_jsonl, read_jsonl

WC1 = DATA / "worlds_iter1_heldout.jsonl"
OUT = RESULTS / "heldout_llm_scores.jsonl"


def _w(job):
    import common  # noqa: F401,F811
    import fol_core as fc
    from tvjt import build_prompt, worlds_for
    iid, fol, nl = job
    try:
        F = fc.parse(fol)
        ws = worlds_for(F, iid, max_worlds=12)
        return {"item_id": iid, "worlds": ws, "prompt": build_prompt(nl, F, ws) if ws else None}
    except Exception as e:  # noqa: BLE001
        return {"item_id": iid, "worlds": [], "prompt": None, "err": repr(e)[:120]}


async def main(which: str) -> None:
    from tvjt import parse_answer, score_answers
    tg = [json.loads(l) for l in (DATA / "heldout_targets.jsonl").read_text().splitlines()]
    T = [t for t in tg if t["group"] == "heldout_confirm" and (t["panel"] if which == "P" else t["tercile"] == "top")]
    have = {r["item_id"]: r for r in read_jsonl(WC1)}
    jobs = [(t["item_id"], t["fol_folio"], t["nl"]) for t in T if t["fol_folio"] and t["item_id"] not in have]
    logger.info(f"iter-1 worlds: {len(have)} cached, {len(jobs)} to compute")
    if jobs:
        with ProcessPoolExecutor(4, mp_context=mp.get_context("spawn")) as ex:
            for r in ex.map(_w, jobs, chunksize=8):
                have[r["item_id"]] = r
                append_jsonl(WC1, [r])
    done = {(r["item_id"], r["metric"]) for r in read_jsonl(OUT)}
    ok, msg = J.gemini_available()
    logger.info(msg)
    async with J.GeminiBackend(concurrency=16, stage_caps={"TVJT_iter1": 1.5}) as be:
        sem = asyncio.Semaphore(16)

        async def one(t):
            if (t["item_id"], "TVJT_iter1") in done:
                return
            w = have.get(t["item_id"]) or {}
            row = {"item_id": t["item_id"], "metric": "TVJT_iter1", "score": 0.5, "covered": False}
            if w.get("prompt"):
                async with sem:
                    r = await be.complete(w["prompt"], 300, "TVJT_iter1", t["item_id"])
                    ans = parse_answer(r["text"], len(w["worlds"]))
                    if ans is None:
                        r2 = await be.complete(w["prompt"] + "\nReturn ONLY the JSON object, with every key.", 400,
                                               "TVJT_iter1", t["item_id"] + ":retry")
                        ans = parse_answer(r2["text"], len(w["worlds"]))
                if ans is not None:
                    sc, agrees, et = score_answers(w["worlds"], ans)
                    row.update({"score": sc, "covered": True, "error_type_pred": et, "n_worlds": len(w["worlds"]),
                                "usd": r["usd"]})
            else:
                row["reason"] = w.get("err") or ("unparseable" if not t["fol_folio"] else "no_world")
            append_jsonl(OUT, [row])

        t0 = time.time()
        try:
            await asyncio.gather(*[one(t) for t in T])
        except J.BudgetExceeded as e:
            logger.warning(f"budget stop {e}")
        logger.info(f"TVJT_iter1 {which}: {time.time() - t0:.0f}s cum ${be.cum:.3f}")


if __name__ == "__main__":
    logger.remove()
    logger.add(sys.stdout, level="INFO")
    asyncio.run(main(sys.argv[1]))
