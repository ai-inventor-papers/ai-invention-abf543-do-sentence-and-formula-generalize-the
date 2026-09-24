#!/usr/bin/env python3
"""Screen Arm B orchestrator: TVJT worlds, instance-consequence NLI and latent-class metrics vs the
B1 fixed-prompt judge and B2 parse rate, on the frozen FOLIO-dev Logic-LM screen.

Stages (each resumable from caches): build -> b1 -> tvjt -> nli -> lc -> analysis -> export
  uv run method.py --stage all            (full 300-sentence screen)
  uv run method.py --stage all --limit 10 (mini run: first 10 screen sentences; writes to runs/mini_10/)
"""
from __future__ import annotations

import argparse
import json
import os
import resource
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("NLTK_DATA", str(ROOT / "nltk_data"))

from loguru import logger  # noqa: E402

logger.remove()
logger.add(sys.stdout, level="INFO", format="{time:HH:mm:ss}|{level:<7}|{message}")
(ROOT / "logs").mkdir(exist_ok=True)
logger.add(str(ROOT / "logs" / "run.log"), rotation="30 MB", level="DEBUG")

# memory guard: container limit 42 GB; this pipeline needs < 12 GB RSS (DeBERTa on GPU, z3 workers)
resource.setrlimit(resource.RLIMIT_AS, (60 * 1024**3, 60 * 1024**3))


def out_dir(limit: int | None) -> Path:
    d = ROOT / ("data" if limit is None else f"runs/mini_{limit}/data")
    d.mkdir(parents=True, exist_ok=True)
    return d


def res_dir(limit: int | None) -> Path:
    d = ROOT / ("results" if limit is None else f"runs/mini_{limit}/results")
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def stage_build(limit: int | None, workers: int) -> None:
    from build_screen import build
    d = out_dir(limit)
    out = build(limit=limit, workers=workers)
    pairs, alt_eq, alt_rows, sup = out.pop("_pairs"), out.pop("_alt_equiv"), out.pop("_alt_rows"), out.pop("_supplement")
    (d / "screen_set.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    for r in alt_rows:
        eqs = alt_eq.get(r["sid"], {}).get(r["system"])
        r["equiv_to_primary"] = None
    # attach equivalence (order preserved per system: alts[:10])
    per = {}
    for r in alt_rows:
        per.setdefault((r["sid"], r["system"]), []).append(r)
    for (sid, s), rows in per.items():
        eqs = alt_eq.get(sid, {}).get(s) or []
        for i, r in enumerate(rows):
            r["equiv_to_primary"] = eqs[i] if i < len(eqs) else None
    write_jsonl(d / "alt_candidates.jsonl", alt_rows)
    write_jsonl(d / "blindspot_supplement.jsonl", sup)
    (d / "candidate_pairs.json").write_text(json.dumps(pairs, indent=1))
    logger.info(f"build stage wrote {d}/screen_set.json fingerprint={out['fingerprint']}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="all")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    stages = ["build", "b1", "tvjt", "nli", "lc", "tvjt_nv", "analysis", "export"] if args.stage == "all" else args.stage.split(",")
    t0 = time.time()
    for st in stages:
        ts = time.time()
        logger.info(f"=== stage {st} (limit={args.limit}) ===")
        if st == "build":
            stage_build(args.limit, args.workers)
        else:
            import stages as S
            getattr(S, f"stage_{st}")(args.limit, args.workers)
        logger.info(f"=== stage {st} done in {time.time() - ts:.1f}s ===")
    logger.info(f"all done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    logger.catch(reraise=True)(main)()
