#!/usr/bin/env python3
"""LC_granular pair re-check (dataset code ONLY in this interpreter; POST-HOC metric).

For candidate-candidate pairs that Arm B's blind bijection labelled non-equivalent because of vocabulary
(reason vocab_mismatch / no_equiv_map), run the dataset's L2 WordNet-granularity check
vendor/ds/src/fol_granular.granular_equivalence(A, B, time_limit=10) in BOTH directions; the pair is merged
if either direction returns equiv_granular. Gold-free (candidate vs candidate).
in : work/granular_jobs.jsonl {k, a, b}   out: work/granular_cache.jsonl {k, merged, st_ab, st_ba, s}
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("NLTK_DATA", str(ROOT / ".nltk_data"))
sys.path.insert(0, str(ROOT / "vendor" / "ds" / "src"))


def _w(batch):
    import fol_granular as fg
    import fol_parse as dsp
    out = []
    for k, a, b in batch:
        t0 = time.time()
        pa, pb = dsp.parse(a), dsp.parse(b)
        if not (pa.ok and pb.ok):
            out.append({"k": k, "merged": False, "st_ab": "unparseable", "st_ba": "unparseable", "s": 0.0})
            continue
        sts = []
        for x, y in ((pa.ast, pb.ast), (pb.ast, pa.ast)):
            try:
                sts.append(fg.granular_equivalence(x, y, time_limit=10)["status"])
            except Exception as e:  # noqa: BLE001 - recorded
                sts.append(f"error:{type(e).__name__}")
            if sts[-1] == "equiv_granular":
                break
        out.append({"k": k, "merged": "equiv_granular" in sts, "st_ab": sts[0], "st_ba": sts[1] if len(sts) > 1 else None,
                    "s": round(time.time() - t0, 3)})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--cpu_min_cap", type=float, default=40.0)
    a = ap.parse_args()
    cp = ROOT / "work" / "granular_cache.jsonl"
    have = set()
    if cp.exists():
        have = {json.loads(x)["k"] for x in cp.read_text().splitlines() if x.strip()}
    jobs = [json.loads(x) for x in (ROOT / "work" / "granular_jobs.jsonl").read_text().splitlines() if x.strip()]
    todo = [(j["k"], j["a"], j["b"]) for j in jobs if j["k"] not in have]
    print(f"granular: {len(jobs)} jobs, {len(todo)} to do", flush=True)
    B = 10
    batches = [todo[i:i + B] for i in range(0, len(todo), B)]
    t0, cpu = time.time(), 0.0
    with ProcessPoolExecutor(max_workers=a.workers, mp_context=mp.get_context("spawn")) as ex, open(cp, "a") as f:
        futs = [ex.submit(_w, b) for b in batches]
        for i, fu in enumerate(as_completed(futs)):
            try:
                rs = fu.result()
            except Exception as e:  # noqa: BLE001
                print(f"batch failed {e!r}", flush=True)
                continue
            for r in rs:
                cpu += r["s"]
                f.write(json.dumps(r) + "\n")
            if cpu / 60 > a.cpu_min_cap:
                print(f"CPU cap {a.cpu_min_cap} min reached after {i + 1} batches; cancelling rest", flush=True)
                for x in futs:
                    x.cancel()
                break
    print(f"granular done: cpu {cpu / 60:.1f} min wall {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
