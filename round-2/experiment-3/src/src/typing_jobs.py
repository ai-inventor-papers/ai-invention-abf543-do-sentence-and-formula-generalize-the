"""Parallel DC error typing: type_error(C, M) for (candidate, modal representative) canonical-string pairs."""
from __future__ import annotations

import multiprocessing as mp
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _w(batch, use_L3):
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (6 * 1024 ** 3, 6 * 1024 ** 3))
    from dc.align import align_pair
    from dc.errtype import type_error
    from dc.parse import parse_fol
    out = []
    for key, c, m in batch:
        t0 = time.time()
        try:
            C, M = parse_fol(c), parse_fol(m)
            rec = align_pair(C, M, use_L3=use_L3)
            on = type_error(C, M, rec, use_L3=use_L3, rule_1b=True)
            off = on if on.get("rule") != "1b" else type_error(C, M, rec, use_L3=use_L3, rule_1b=False)
            out.append({"key": key, "type_1b_on": on["type"], "type_1b_off": off["type"], "rule_on": str(on.get("rule")),
                        "rel": on.get("rel"), "flags": on.get("flags", []), "s": round(time.time() - t0, 3)})
        except (MemoryError, RecursionError, ValueError, KeyError, IndexError) as e:
            out.append({"key": key, "type_1b_on": "other", "type_1b_off": "other", "error": repr(e)[:100]})
    return out


def run_typing(jobs: list[tuple[str, str, str]], use_L3: bool, workers: int = 12) -> dict:
    B = 10
    batches = [jobs[i:i + B] for i in range(0, len(jobs), B)]
    res = {}
    with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn")) as ex:
        futs = [ex.submit(_w, b, use_L3) for b in batches]
        for fu in as_completed(futs):
            for r in fu.result():
                res[r["key"]] = r
    return res
