#!/usr/bin/env python3
"""Solver signatures for every held-out / transfer formula (label-free; uses load_inputs only).

Formulas: 6,300 heldout_confirm greedy candidates, the 700 held-out ORIGINAL golds, the 360 screen golds
(screen_l4 gold_fol_original) and the transfer_unlabeled formulas. Front-end = dataset parser (VARLIKE + LaTeX
fixes) converted to the iter-1 AST. Signature = legacy solver_sig.signature(ast, N=3, timeout_ms=5000, with_rel=True).
Pre-registered fallback for heavy formulas: N=2 when the formula has > 12 predicates or > 6 quantifiers; a hard
per-formula wall clock of 120 s (SIGALRM) -> 'timeout' (the item is then uncovered, score 0.5, and counted).
Writes results/heldout_formula_sigs.json {fol_string: signature | {error}} (resumable, checkpointed).
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import signal
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "sigfaith"))
logger.remove()
logger.add(sys.stdout, level="INFO", format="{time:HH:mm:ss}|{level:<7}|{message}")
logger.add(ROOT / "logs" / "phase2_sigs.log", rotation="30 MB", level="DEBUG")
OUT = ROOT / "results" / "heldout_formula_sigs.json"


class _Alarm(Exception):
    pass


def _handler(signum, frame):
    raise _Alarm()


def worker(fol: str):
    sys.path.insert(0, str(ROOT / "sigfaith"))
    import core
    from fol_parse import n_quant
    from solver_sig import signature
    signal.signal(signal.SIGALRM, _handler)
    p, err = core.parse_front(fol)
    if p is None:
        return fol, {"error": f"unparseable: {err}"}
    N = 2 if (len(p.preds) > 12 or n_quant(p.ast) > 6) else 3
    t0 = time.time()
    signal.alarm(120)
    try:
        s = signature(p.ast, N=N, timeout_ms=5000, with_rel=True, rel_max_unary=8)
        s["N_used"] = N
        return fol, s
    except _Alarm:
        return fol, {"error": "timeout_120s", "N_used": N, "seconds": round(time.time() - t0, 1)}
    except Exception as e:  # noqa: BLE001
        return fol, {"error": f"{type(e).__name__}: {e}"}
    finally:
        signal.alarm(0)


def all_formulas() -> list[str]:
    import heldout_io
    rows = heldout_io.load_inputs(with_design=False)
    fols = [r["candidate_fol"] for r in rows] + [r["gold_fol_original"] for r in rows]
    for l in (ROOT / "data" / "screen_l4.jsonl").read_text().splitlines():
        fols.append(json.loads(l)["gold_fol_original"])
    for l in (ROOT / "data" / "transfer_inputs.jsonl").read_text().splitlines():
        fols.append(json.loads(l)["candidate_fol"])
    return sorted({f for f in fols if f})


@logger.catch(reraise=True)
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--extra", default=None, help="jsonl file with a 'fol' field to add")
    a = ap.parse_args()
    fols = all_formulas()
    if a.extra:
        fols = sorted(set(fols) | {json.loads(l)["fol"] for l in Path(a.extra).read_text().splitlines()})
    cache = json.loads(OUT.read_text()) if OUT.exists() else {}
    todo = [f for f in fols if f not in cache]
    if a.limit:
        todo = todo[: a.limit]
    logger.info(f"{len(fols)} distinct formulas; {len(todo)} to compute with {a.workers} workers")
    t0 = time.time()
    done = 0
    with ProcessPoolExecutor(max_workers=a.workers, mp_context=mp.get_context("spawn")) as ex:
        futs = [ex.submit(worker, f) for f in todo]
        for fu in as_completed(futs):
            try:
                f, s = fu.result()
                cache[f] = s
            except Exception as e:  # noqa: BLE001
                logger.error(f"worker failed: {e}")
            done += 1
            if done % 250 == 0:
                OUT.write_text(json.dumps(cache, ensure_ascii=False))
                el = time.time() - t0
                logger.info(f"{done}/{len(todo)} in {el:.0f}s ({el / done:.2f}s/formula); ETA {(len(todo) - done) * el / done / 60:.1f} min")
    OUT.write_text(json.dumps(cache, ensure_ascii=False))
    errs = {}
    for v in cache.values():
        if "error" in v:
            k = v["error"].split(":")[0]
            errs[k] = errs.get(k, 0) + 1
    logger.info(f"done {len(todo)} in {time.time() - t0:.0f}s; errors {errs}")


if __name__ == "__main__":
    main()
