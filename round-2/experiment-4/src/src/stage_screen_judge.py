"""Phase-1 screen evaluation of the repaired judge protocol (gemini-2.5-flash, tvjt_v2_conf, 3 votes, canonical
worlds): C1/C2/C3 on the 833 real candidates, 300 golds and 499 rewrites (screen labels only), plus P1b test-retest
on 150 random screen targets in a separate cache namespace. Output: results/screen_repair_scores.jsonl.

Run AFTER the freeze (the gemini key was unavailable before it): this measures what the pre-declared freeze
rule would have seen; it does not change the frozen configuration.
"""
from __future__ import annotations

import asyncio
import json
import random
import sys
import time

from loguru import logger

import common
import judge as J
import worlds as WW
from common import RESULTS, append_jsonl, read_jsonl

OUT = RESULTS / "screen_repair_scores.jsonl"


def targets() -> list[dict]:
    ss = json.loads((common.ARMB / "data" / "screen_set.json").read_text())
    sent = {s["sid"]: s for s in ss["sentences"]}
    T = [{"item_id": f"{s['sid']}:gold", "kind": "gold", "sid": s["sid"], "nl": s["nl"], "fol": s["gold_fol"]}
         for s in ss["sentences"]]
    T += [{"item_id": r["item_id"], "kind": "real", "sid": r["sid"], "nl": sent[r["sid"]]["nl"], "fol": r["fol"],
           "parse_ok": r.get("parse_ok")} for r in ss["real_items"]]
    T += [{"item_id": r["item_id"], "kind": "rewrite", "rw_kind": r["kind"], "sid": r["sid"],
           "nl": sent[r["sid"]]["nl"], "fol": r["fol"]} for r in ss["rewrites"]]
    return T


async def main(retest_n: int = 150) -> None:
    ok, msg = J.gemini_available()
    logger.info(msg)
    if not ok:
        raise J.JudgeUnavailable(msg)
    T = targets()
    by_key, by_src = WW.load_cache()
    done = {(r["item_id"], r["ns"]) for r in read_jsonl(OUT)}
    rng = random.Random(0)
    retest = set(rng.sample([t["item_id"] for t in T if t["kind"] == "real"], retest_n))
    async with J.GeminiBackend(stage_caps={"P1_screen": 1.6, "P1b_retest": 0.15}) as be:
        caches = {"main": J.WorldCache(be.name), "retest": J.WorldCache(be.name, "retest")}
        sem = asyncio.Semaphore(12)
        t0 = time.time()

        async def one(t, ns):
            if (t["item_id"], ns) in done:
                return
            rec = by_key.get(by_src.get(t["fol"]))
            ws = [w for w in (rec or {}).get("worlds", []) if w.get("text")]
            row = {"item_id": t["item_id"], "kind": t["kind"], "rw_kind": t.get("rw_kind"), "sid": t["sid"], "ns": ns}
            if not ws:
                row.update({"covered": False, "C1": None, "C2": None, "C3": None})
            else:
                votes = 3 if ns == "main" else 1
                o = await J.judge_target(be, caches[ns], t["nl"], ws, votes,
                                         "P1_screen" if ns == "main" else "P1b_retest", t["item_id"])
                sc = J.score_tvjt(ws, o["answers"], votes)
                row.update({"covered": sc["C3"] is not None, "C1": sc["C1"], "C2": sc["C2"], "C3": sc["C3"],
                            "n_worlds": sc["n_worlds"], "error_type_pred": sc["error_type"],
                            "per_world_agree": sc["per_world_agree"], "ops": [w["op"] for w in ws],
                            "answers_v0": o["answers"].get(0), "malformed": o["malformed"], "usd": o["usd"]})
            append_jsonl(OUT, [row])

        async def by_sentence(items):
            async with sem:
                for t, ns in items:
                    try:
                        await one(t, ns)
                    except J.BudgetExceeded as e:
                        logger.warning(f"budget stop {e}")
                        return

        groups: dict[str, list] = {}
        order = {"real": 0, "gold": 1, "rewrite": 2}
        for t in sorted(T, key=lambda x: order[x["kind"]]):
            groups.setdefault(t["sid"], []).append((t, "main"))
        await asyncio.gather(*[by_sentence(v) for v in groups.values()])
        logger.info(f"main done {time.time() - t0:.0f}s cum ${be.cum:.3f}")
        rt = [(t, "retest") for t in T if t["item_id"] in retest]
        await asyncio.gather(*[by_sentence([x]) for x in rt])
        logger.info(f"retest done cum ${be.cum:.3f}")


if __name__ == "__main__":
    logger.remove()
    logger.add(sys.stdout, level="INFO")
    asyncio.run(main())
