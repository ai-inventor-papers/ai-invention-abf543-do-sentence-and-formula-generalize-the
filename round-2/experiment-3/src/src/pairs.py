#!/usr/bin/env python3
"""Config-agnostic DC relation cache: align_pair for unordered pairs of canonical formula strings.

Jobs are (a, b) canonical strings; the cache key is sha1(min||max) and the record's relations are stated for
a = min(a, b) relative to b = max(a, b) (the converse is derived on lookup). Identical strings are EQUIV at L1
by definition (k_found 0) and are not solved. Spawn ProcessPool, batches of 25, resumable, per-pair wall 20 s.
Usage (CLI): pairs.py JOBS.jsonl [--workers 12] [--limit_s 0]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CACHE = ROOT / "work" / "pair_cache.jsonl"


def pkey(a: str, b: str) -> tuple[str, str, str]:
    x, y = (a, b) if a <= b else (b, a)
    return hashlib.sha1((x + "||" + y).encode("utf-8")).hexdigest(), x, y


def _compact(r):
    if r is None:
        return None
    return {k: r.get(k) for k in ("rel", "lvl", "k_found", "n_unmapped", "map", "via_def", "n_candidates",
                                  "bounded_only", "best_k", "n_tried")}


def _worker(batch):
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (6 * 1024 ** 3, 6 * 1024 ** 3))
    from dc.align import align_pair
    from dc.parse import parse_fol
    out = []
    for k, a, b in batch:
        t0 = time.time()
        try:
            A, B = parse_fol(a), parse_fol(b)
            if A is None or B is None:
                out.append({"k": k, "error": "unparseable", "s": 0.0})
                continue
            rec = align_pair(A, B)
            out.append({"k": k, "L1": _compact(rec["L1"]), "L2": _compact(rec["L2"]), "L3": _compact(rec["L3"]),
                        "timed_out": rec["timed_out"], "n_preds": rec["n_preds"], "s": round(time.time() - t0, 3)})
        except (MemoryError, RecursionError, ValueError, KeyError, IndexError) as e:
            out.append({"k": k, "error": f"{type(e).__name__}:{str(e)[:80]}", "s": round(time.time() - t0, 3)})
    return out


def load_cache() -> dict:
    have = {}
    if CACHE.exists():
        with open(CACHE, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        r = json.loads(line)
                        have[r["k"]] = r
                    except json.JSONDecodeError:
                        continue
    return have


def run(jobs: list[tuple[str, str]], workers: int = 12, limit_s: float = 0.0, log=print) -> dict:
    """Compute missing pairs. jobs = [(a, b)] canonical strings. Returns the stats dict."""
    have = load_cache()
    todo, seen = [], set()
    n_same = 0
    for a, b in jobs:
        k, x, y = pkey(a, b)
        if k in seen or k in have:
            continue
        seen.add(k)
        if x == y:
            n_same += 1
            have[k] = {"k": k, "L1": {"rel": "EQUIV", "lvl": 1, "k_found": 0, "n_unmapped": 0, "map": None},
                       "L2": None, "L3": None, "timed_out": False, "same_string": True, "s": 0.0}
            with open(CACHE, "a", encoding="utf-8") as f:
                f.write(json.dumps(have[k]) + "\n")
            continue
        todo.append((k, x, y))
    log(f"pairs: {len(jobs)} jobs, {len(seen)} new unique ({n_same} identical strings), {len(todo)} to solve")
    if not todo:
        return {"n_solved": 0}
    # longest formulas first spreads the heavy tail across workers
    todo.sort(key=lambda t: -(len(t[1]) + len(t[2])))
    B = 25
    batches = [todo[i:i + B] for i in range(0, len(todo), B)]
    t0 = time.time()
    n_done = 0
    secs = []
    with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn")) as ex, \
            open(CACHE, "a", encoding="utf-8") as f:
        futs = [ex.submit(_worker, b) for b in batches]
        for fu in as_completed(futs):
            try:
                rs = fu.result()
            except Exception as e:  # noqa: BLE001 - a crashed batch is logged and recomputed on resume
                log(f"batch failed: {e!r}")
                continue
            for r in rs:
                f.write(json.dumps(r) + "\n")
                secs.append(r.get("s", 0.0))
            f.flush()
            n_done += len(rs)
            if n_done % 1000 < B:
                el = time.time() - t0
                log(f"pairs {n_done}/{len(todo)} {el:.0f}s ({n_done / max(el, 1e-9):.1f}/s)")
            if limit_s and time.time() - t0 > limit_s:
                log("time limit reached; cancelling (resumable)")
                for x in futs:
                    x.cancel()
                break
    import numpy as np
    st = {"n_solved": n_done, "wall_s": round(time.time() - t0, 1),
          "mean_s": float(np.mean(secs)) if secs else None, "p95_s": float(np.percentile(secs, 95)) if secs else None,
          "max_s": float(np.max(secs)) if secs else None}
    log(f"pairs done: {st}")
    return st


def lookup(cache: dict, a: str, b: str):
    """(record, flipped): flipped=True when a is the SECOND element of the stored pair."""
    k, x, y = pkey(a, b)
    return cache.get(k), (a != x)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("jobs")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--limit_s", type=float, default=0.0)
    ap.add_argument("--n", type=int, default=0)
    a = ap.parse_args()
    js = [json.loads(x) for x in Path(a.jobs).read_text().splitlines() if x.strip()]
    if a.n:
        js = js[: a.n]
    print(json.dumps(run([(j["a"], j["b"]) for j in js], a.workers, a.limit_s)), flush=True)
