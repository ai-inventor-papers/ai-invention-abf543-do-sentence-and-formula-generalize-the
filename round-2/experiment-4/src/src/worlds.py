"""Canonical worlds (R1) for many formulas, in parallel, with a persistent cache (data/worlds_canon.jsonl).

Cache key = sha1(to_str(canon(F))): identical canonical forms across systems/rewrites share worlds.
Each cached record holds the canonical form, seed, fallback flag, the worlds (with iso keys) and a
sentence-independent verbalisation per world (predicates of F ∪ predicates true in that world).
"""
from __future__ import annotations

import json
import multiprocessing as mp
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

from loguru import logger

import common
from common import DATA, append_jsonl, read_jsonl, sha1

WCACHE = DATA / "worlds_canon.jsonl"


def verbalize(F, w: dict) -> str:
    import fol_core as fc
    from tvjt import verbalize_world
    preds = dict(fc.predicates(F))
    for p, t in w["true_atoms"]:
        preds.setdefault(p, len(t))
    return verbalize_world(w, preds)[0]


def _worker(fol_str: str) -> dict:
    import common  # noqa: F401,F811
    import fol_core as fc
    import canon as K
    t0 = time.time()
    try:
        info = K.canon_info(fol_str)
        cw = K.canonical_worlds(fol_str)
        G = fc.parse(info["canon"]) if info["fallback"] is None else fc.parse(fol_str)
        for w in cw["worlds"]:
            try:
                w["text"] = verbalize(G, w)
            except Exception as e:  # noqa: BLE001 - verbaliser failure → world dropped later, counted
                w["text"] = None
                w["verb_err"] = repr(e)[:120]
        return {"key": sha1(info["canon"]), "canon": info["canon"], "skeleton": info["skeleton"],
                "canon_seed": info["canon_seed"], "fallback": info["fallback"], "worlds": cw["worlds"],
                "cpu_s": round(time.time() - t0, 3), "err": None}
    except Exception as e:  # noqa: BLE001 - z3/parse failure → uncovered target, counted
        return {"key": None, "fol": fol_str, "worlds": [], "cpu_s": round(time.time() - t0, 3),
                "err": f"{type(e).__name__}:{e}"[:200]}


def load_cache() -> tuple[dict, dict]:
    """(by canonical key, by source fol string → canonical key)."""
    by_key, by_src = {}, {}
    for r in read_jsonl(WCACHE):
        if r.get("key") and "worlds" in r:   # alias lines carry only {key, sources}: never let them overwrite
            by_key[r["key"]] = r
        for s in r.get("sources", []):
            by_src[s] = r.get("key")
    return by_key, by_src


def compute(fol_strs: list[str], workers: int = 4, log_every: int = 100) -> dict[str, dict]:
    """fol string (FOLIO-unicode, parseable) → world record. Resumable."""
    import canon as K
    by_key, by_src = load_cache()
    out, todo_src = {}, []
    for s in dict.fromkeys(fol_strs):
        if s in by_src and (by_src[s] in by_key or by_src[s] is None):
            out[s] = by_key.get(by_src[s]) or {"worlds": [], "err": "cached_error"}
            continue
        try:
            k = sha1(K.canon(s))
        except Exception:  # noqa: BLE001
            k = None
        if k in by_key:
            out[s] = by_key[k]
            append_jsonl(WCACHE, [{"key": k, "sources": [s], "alias": True}])
        else:
            todo_src.append(s)
    # group sources by canonical key so each canonical form is solved once
    groups: dict[str, list[str]] = {}
    for s in todo_src:
        try:
            k = sha1(K.canon(s))
        except Exception:  # noqa: BLE001
            k = "err:" + s
        groups.setdefault(k, []).append(s)
    reps = [v[0] for v in groups.values()]
    logger.info(f"worlds: {len(out)} cached, {len(reps)} canonical forms to solve ({len(todo_src)} sources)")
    if reps:
        t0 = time.time()
        ctx = mp.get_context("spawn")
        with ProcessPoolExecutor(max_workers=workers, mp_context=ctx) as ex:
            futs = {ex.submit(_worker, s): s for s in reps}
            for i, fu in enumerate(as_completed(futs)):
                s = futs[fu]
                try:
                    r = fu.result(timeout=900)
                except Exception as e:  # noqa: BLE001
                    r = {"key": None, "worlds": [], "err": f"worker:{e!r}"[:200]}
                srcs = groups.get(sha1(r["canon"]) if r.get("canon") else "err:" + s, [s])
                if s not in srcs:
                    srcs = [s]
                r["sources"] = srcs
                if r.get("key"):
                    by_key[r["key"]] = r
                append_jsonl(WCACHE, [r])
                for s2 in srcs:
                    out[s2] = r
                if (i + 1) % log_every == 0:
                    logger.info(f"  worlds {i + 1}/{len(reps)} ({time.time() - t0:.0f}s)")
    return out
