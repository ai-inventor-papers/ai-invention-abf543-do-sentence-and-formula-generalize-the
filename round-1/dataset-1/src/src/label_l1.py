#!/usr/bin/env python3
"""STEP 5: L1 (lexical-free solver equivalence) + L2 (granularity-aware, lexical) labels.

Checks every needed (candidate, gold) pair once; results are cached in work/l1_cache.jsonl keyed by
sha1(candidate text + '\\x00' + gold text). Greedy candidates are labelled before samples.

Stages:
  orig     : held-out candidates vs gold_fol_original + screen candidates vs original screen gold
  audited  : the same vs gold_fol_audited (needs work/audit_results.json)
Usage: label_l1.py --stage orig|audited [--limit N]
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

from loguru import logger

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
CACHE = ROOT / "work" / "l1_cache.jsonl"
GEN_DIR = ROOT / "raw" / "generations"

logger.remove()
logger.add(sys.stdout, level="INFO", format="{time:HH:mm:ss}|{level:<7}|{message}")
logger.add(ROOT / "logs" / "label_l1.log", rotation="30 MB", level="DEBUG")


def pair_key(cand: str, gold: str) -> str:
    return hashlib.sha1((cand + "\x00" + gold).encode("utf-8")).hexdigest()


def load_cache() -> dict:
    out = {}
    if CACHE.exists():
        for line in CACHE.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                out[r["key"]] = r
    return out


def worker(job: tuple) -> dict:
    key, cand, gold, do_l2 = job
    import resource
    try:
        resource.setrlimit(resource.RLIMIT_AS, (6 * 1024 ** 3, 6 * 1024 ** 3))
    except (ValueError, OSError):
        pass
    sys.path.insert(0, str(ROOT / "src"))
    from fol_equiv import equivalence
    from fol_granular import granular_equivalence
    from fol_parse import parse
    t0 = time.time()
    pc, pg = parse(cand), parse(gold)
    out = {"key": key}
    if not pg.ok:
        out.update({"status": "gold_unparseable"})
        return out
    if not pc.ok:
        out.update({"status": "unparseable", "parse_error": pc.error[:200]})
        return out
    try:
        r = equivalence(pc.ast, pg.ast, time_limit=30.0)
    except (MemoryError, RecursionError, Exception) as e:  # noqa: BLE001 - recorded as unknown
        r = {"status": "unknown_timeout", "error": f"{type(e).__name__}: {str(e)[:150]}"}
    m = r.get("mapping")
    out.update({"status": r["status"], "mapping": {k: v for k, v in m.items()} if m else None,
                "entail_cand_to_gold": r.get("entail_cand_to_gold"), "entail_gold_to_cand": r.get("entail_gold_to_cand"),
                "method": r.get("method"), "max_domain": r.get("max_domain"), "n_mappings_total": r.get("n_mappings_total"),
                "n_mappings_tried": r.get("n_mappings_tried"), "error": r.get("error")})
    if do_l2 and r["status"] not in ("equiv_proved", "equiv_bounded"):
        try:
            g = granular_equivalence(pc.ast, pg.ast, time_limit=20.0)
        except (MemoryError, RecursionError, Exception) as e:  # noqa: BLE001
            g = {"status": "not_applicable", "definitions": {}, "error": str(e)[:150]}
        out.update({"L2_status": g["status"], "L2_definitions": g.get("definitions", {})})
    out["seconds"] = round(time.time() - t0, 3)
    return out


def load_generations() -> list[dict]:
    rows = []
    for f in sorted(GEN_DIR.glob("*.jsonl")):
        seen = set()
        for line in f.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                k = (r["sentence_id"], r["sample_idx"])
                if k in seen:
                    continue
                seen.add(k)
                rows.append(r)
    return rows


def audited_gold_map() -> dict:
    """sentence key -> (gold_fol_audited or None, gold_source)."""
    held = json.loads((ROOT / "work" / "heldout_sentences.json").read_text())
    screen = json.loads((ROOT / "work" / "screen_sentences.json").read_text())
    aud = json.loads((ROOT / "work" / "audit_results.json").read_text())["results"]
    out = {}
    for s in held:
        a = aud.get(f"heldout:{s['sentence_id']}")
        if s.get("gold_fol_paper"):
            out[f"heldout:{s['sentence_id']}"] = (s["gold_fol_paper"], "paper_corrected")
        elif s["corpus"] == "proverqa":
            if a and a["gold_faithful_final"] is False:
                out[f"heldout:{s['sentence_id']}"] = (a.get("correction"), "panel_corrected" if a.get("correction") else "panel_flagged_uncorrected")
            else:
                out[f"heldout:{s['sentence_id']}"] = (s["gold_fol_original"], "synthetic_clean" if not a else "original")
        elif a is None or a["gold_faithful_final"] is None:
            out[f"heldout:{s['sentence_id']}"] = (s["gold_fol_original"], "original_unaudited")
        elif a["gold_faithful_final"]:
            out[f"heldout:{s['sentence_id']}"] = (s["gold_fol_original"], "original")
        else:
            out[f"heldout:{s['sentence_id']}"] = (a.get("correction"), "panel_corrected" if a.get("correction") else "panel_flagged_uncorrected")
    for s in screen:
        a = aud.get(f"screen:{s['sentence_id']}")
        if a is None or a["gold_faithful_final"] is None:
            out[f"screen:{s['sentence_id']}"] = (s["gold_fol_original"], "original_unaudited")
        elif a["gold_faithful_final"]:
            out[f"screen:{s['sentence_id']}"] = (s["gold_fol_original"], "original")
        else:
            out[f"screen:{s['sentence_id']}"] = (a.get("correction"), "panel_corrected" if a.get("correction") else "panel_flagged_uncorrected")
    return out


def needed_jobs(stage: str, limit: int) -> list[tuple]:
    held = {s["sentence_id"]: s for s in json.loads((ROOT / "work" / "heldout_sentences.json").read_text())}
    screen = json.loads((ROOT / "work" / "screen_sentences.json").read_text())
    gens = load_generations()
    gmap = audited_gold_map() if stage == "audited" else None
    jobs = []
    for r in gens:
        s = held.get(r["sentence_id"])
        if s is None or not r.get("candidate_fol"):
            continue
        gold = s["gold_fol_original"] if stage == "orig" else (gmap[f"heldout:{s['sentence_id']}"][0])
        if not gold:
            continue
        jobs.append((r["sample_idx"] > 0, pair_key(r["candidate_fol"], gold), r["candidate_fol"], gold, r["sample_idx"] == 0))
    for s in screen:
        gold = s["gold_fol_original"] if stage == "orig" else gmap[f"screen:{s['sentence_id']}"][0]
        if not gold:
            continue
        for sysname, c in s["candidates"].items():
            jobs.append((False, pair_key(c["candidate_fol"], gold), c["candidate_fol"], gold, True))
    jobs.sort(key=lambda j: j[0])
    uniq, seen = [], set()
    for _, k, c, g, l2 in jobs:
        if k in seen:
            continue
        seen.add(k)
        uniq.append((k, c, g, l2))
    return uniq[:limit] if limit else uniq


@logger.catch(reraise=True)
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["orig", "audited"], required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    cache = load_cache()
    jobs = [j for j in needed_jobs(args.stage, args.limit) if j[0] not in cache]
    logger.info(f"stage={args.stage}: {len(jobs)} uncached pair checks")
    t0 = time.time()
    done = 0
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=mp.get_context("spawn")) as pool, \
            open(CACHE, "a", encoding="utf-8") as fh:
        futs = {pool.submit(worker, j): j for j in jobs}
        for fut in as_completed(futs):
            j = futs[fut]
            try:
                r = fut.result()
            except Exception as e:  # noqa: BLE001 - a crashed worker is recorded as unknown
                logger.error(f"worker crashed on {j[0]}: {e!r}")
                r = {"key": j[0], "status": "unknown_timeout", "error": f"worker crash: {e!r}"[:200]}
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            done += 1
            if done % 500 == 0:
                fh.flush()
                el = time.time() - t0
                logger.info(f"{done}/{len(jobs)} {el:.0f}s ({el / done:.3f}s/pair)")
    logger.info(f"stage {args.stage} done: {done} checks in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
