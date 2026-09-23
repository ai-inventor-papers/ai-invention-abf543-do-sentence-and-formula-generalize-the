"""P2d judged: frozen TVJT* (C3, 3 votes) on 99 held-out audited golds and their 197 solver-verified rewrites.
Paired FA = rewrite C3 < gold C3 − 0.2. Output results/heldout_g2_judged.jsonl."""
from __future__ import annotations

import asyncio
import json
import sys

from loguru import logger

import common
import judge as J
import worlds as WW
from common import DATA, RESULTS, append_jsonl, read_jsonl

OUT = RESULTS / "heldout_g2_judged.jsonl"


async def main() -> None:
    items = [json.loads(l) for l in (DATA / "heldout_g2_items.jsonl").read_text().splitlines()]
    by_key, by_src = WW.load_cache()
    done = {r["item_id"] for r in read_jsonl(OUT)}
    async with J.GeminiBackend(stage_caps={"P2d_g2": 0.3}) as be:
        wc = J.WorldCache(be.name)
        sem = asyncio.Semaphore(12)

        async def sent(its):
            async with sem:
                for t in its:
                    if t["item_id"] in done:
                        continue
                    rec = by_key.get(by_src.get(t["fol"]))
                    ws = [w for w in (rec or {}).get("worlds", []) if w.get("text")]
                    row = {k: t.get(k) for k in ("item_id", "kind", "rw_kind", "gold_id", "sid")}
                    if ws:
                        o = await J.judge_target(be, wc, t["nl"], ws, 3, "P2d_g2", t["item_id"])
                        sc = J.score_tvjt(ws, o["answers"], 3)
                        row.update({"C1": sc["C1"], "C3": sc["C3"], "n_worlds": len(ws), "usd": o["usd"]})
                    append_jsonl(OUT, [row])
        g: dict = {}
        for t in sorted(items, key=lambda x: x["kind"]):   # gold before rewrite within a sentence
            g.setdefault(t["sid"], []).append(t)
        try:
            await asyncio.gather(*[sent(v) for v in g.values()])
        except J.BudgetExceeded as e:
            logger.warning(str(e))
        logger.info(f"P2d done cum ${be.cum:.3f}")


if __name__ == "__main__":
    asyncio.run(main())
