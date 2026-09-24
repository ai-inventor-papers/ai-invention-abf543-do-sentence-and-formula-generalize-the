#!/usr/bin/env python3
"""B8 sampling self-consistency, recovered for free from Logic-LM's cross-story duplicates.

Logic-LM re-translated each FOLIO story independently, so a sentence that occurs in k stories has k independent
translations per system. For a real candidate with >= 1 alternative translation, B8 = fraction of the
alternatives that are solver-equivalent to it (blind bijection labeler, the same one used for gold labels;
unparseable alternatives count as disagreement). Candidates with no alternative are uncovered (score 0.5).
Output: results/baseline_b8.jsonl
"""
from __future__ import annotations

import json
import multiprocessing as mp
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).resolve().parent
logger.remove()
logger.add(sys.stdout, level="INFO", format="{time:HH:mm:ss}|{level:<7}|{message}")
logger.add(ROOT / "logs" / "run_selfcons.log", rotation="30 MB", level="DEBUG")


def _worker(args):
    sys.path.insert(0, str(ROOT / "src"))
    from fol_parse import parse
    from labeler import label
    item_id, cand, alts = args
    try:
        ca = parse(cand).ast
    except Exception:  # noqa: BLE001
        return item_id, None, len(alts)
    agree = 0
    for a in alts:
        if a.strip() == cand.strip():
            agree += 1
            continue
        try:
            r = label(parse(a).ast, ca, do_unbounded=False, budget_s=10)
            agree += r["status"] == "equiv"
        except Exception:  # noqa: BLE001
            pass
    return item_id, agree / len(alts), len(alts)


@logger.catch(reraise=True)
def main():
    d = json.loads((ROOT / "data" / "screen_set.json").read_text())
    jobs = [(r["item_id"], r["cand_fol"], r["alt_cands"]) for r in d["real"] if r["alt_cands"]]
    res = {}
    with ProcessPoolExecutor(max_workers=4, mp_context=mp.get_context("spawn")) as ex:
        for fu in as_completed([ex.submit(_worker, j) for j in jobs]):
            iid, v, n = fu.result()
            res[iid] = (v, n)
    rows = []
    for r in d["real"]:
        v, n = res.get(r["item_id"], (None, 0))
        rows.append({"item_id": r["item_id"], "set": "real", "sid": r["sid"], "metric": "B8",
                     "score": 0.5 if v is None else v, "covered": v is not None, "n_alternatives": n, "usd": 0.0})
    with (ROOT / "results" / "baseline_b8.jsonl").open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    logger.info(f"B8: covered {sum(r['covered'] for r in rows)}/{len(rows)}")


if __name__ == "__main__":
    main()
