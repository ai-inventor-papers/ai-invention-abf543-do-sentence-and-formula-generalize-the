#!/usr/bin/env python3
"""Cross-implementation agreement (builds_on o): the sibling DC implementation of this run
(run_ujABDGgoK_5Q iter_2 gen_art_experiment_3/dc, READ-ONLY, appeared after this artifact's DC was implemented) is run
on 500 random dev-anchor pairs (and 300 random legal pairs); exact agreement of relation labels and Spearman of the
ordinal relation rank vs this artifact's dc/ results.  -> results/cross_impl.json
The sibling package is imported in separate worker processes (both packages are called 'dc')."""
from __future__ import annotations

import json
import multiprocessing as mp
import random
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from common import RES, WORK, jdump, read_jsonl, setup_logger

logger = setup_logger("crossimpl")
SIB = Path("../../../experiment-3/src")
RANK = {"EQUIV": 4, "STRONGER": 3, "WEAKER": 3, "COMPATIBLE-INCOMPARABLE": 2, "INCOMPARABLE": 2, "CONTRADICTORY": 1,
        "UNKNOWN": 0, "UNALIGNABLE": -1}


def _job(args):
    import time
    sys.path.insert(0, str(SIB))
    for m in [k for k in sys.modules if k == "dc" or k.startswith("dc.")]:
        del sys.modules[m]
    import dc as sdc  # sibling package
    key, a, b = args
    t = time.time()
    try:
        A, B = sdc.parse_fol(a), sdc.parse_fol(b)
        rec = sdc.align_pair(A, B)
        r = sdc.derive(rec)
        return key, r["rel"], r.get("lvl"), round(time.time() - t, 3)
    except Exception as e:  # noqa: BLE001 - sibling code errors are recorded as UNKNOWN
        return key, f"ERROR:{type(e).__name__}", None, round(time.time() - t, 3)


def run(set_name: str, n: int, workers: int) -> dict:
    tasks = {}
    for f in (WORK / "dc_tasks" / set_name).glob("*.json"):
        for p in json.loads(f.read_text())["pairs"]:
            tasks[p["key"]] = p
    mine = {}
    for f in (WORK / "dc_pairs" / set_name).glob("*.jsonl"):
        for r in read_jsonl(f):
            if r["key"] in tasks and r.get("reason") != "worker_killed":
                mine[r["key"]] = r
    keys = sorted(mine)
    rng = random.Random(0)
    pick = rng.sample(keys, min(n, len(keys)))
    jobs = [(k, tasks[k]["a"], tasks[k]["b"]) for k in pick]
    out = []
    with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn")) as ex:
        for k, rel, lvl, sec in ex.map(_job, jobs, chunksize=4):
            out.append({"key": k, "sibling": rel, "sibling_level": lvl, "sibling_sec": sec, "mine": mine[k]["relation"],
                        "mine_level": mine[k].get("level")})
    norm = lambda r: "INCOMPARABLE" if r == "COMPATIBLE-INCOMPARABLE" else r  # noqa: E731
    valid = [o for o in out if not str(o["sibling"]).startswith("ERROR")]
    exact = sum(norm(o["mine"]) == norm(o["sibling"]) for o in valid) / max(1, len(valid))
    eq_agree = sum((o["mine"] == "EQUIV") == (o["sibling"] == "EQUIV") for o in valid) / max(1, len(valid))
    from scipy.stats import spearmanr
    rho = spearmanr([RANK.get(o["mine"], 0) for o in valid], [RANK.get(o["sibling"], 0) for o in valid]).statistic if len(valid) > 3 else None
    from collections import Counter
    conf = Counter((norm(o["mine"]), norm(o["sibling"])) for o in valid)
    return {"n": len(out), "n_valid": len(valid), "exact_agreement": exact, "equiv_vs_not_agreement": eq_agree,
            "spearman_rank": rho, "confusion_mine_x_sibling": {f"{a}|{b}": c for (a, b), c in sorted(conf.items())},
            "n_sibling_errors": len(out) - len(valid)}


def main() -> None:
    res = {"sibling_path": str(SIB / "dc"), "note": "sibling implementation appeared after this artifact's dc/ was written and "
           "frozen; it is compared, not substituted"}
    res["dev"] = run("dev", 500, 5)
    logger.info(f"dev: {json.dumps(res['dev'])[:500]}")
    res["legal"] = run("legal", 300, 5)
    logger.info(f"legal: {json.dumps(res['legal'])[:500]}")
    jdump(res, RES / "cross_impl.json")


if __name__ == "__main__":
    main()
