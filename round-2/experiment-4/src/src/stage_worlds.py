"""Stage: canonical worlds for screen targets (golds, real candidates, rewrites) and held-out targets."""
from __future__ import annotations

import json
import sys

from loguru import logger

import common
import worlds as W


def screen_fols() -> list[str]:
    import fol_core as fc
    ss = json.loads((common.ARMB / "data" / "screen_set.json").read_text())
    fols = [s["gold_fol"] for s in ss["sentences"]]
    fols += [r["fol"] for r in ss["real_items"] if r.get("parse_ok")]
    fols += [r["fol"] for r in ss["rewrites"]]
    return [f for f in fols if fc.try_parse(f)[0] is not None]


def heldout_fols() -> list[str]:
    tg = [json.loads(l) for l in (common.DATA / "heldout_targets.jsonl").read_text().splitlines()]
    ids = {t["original_item_id"] for t in tg if t["group"] == "contamination"}
    keep = [t for t in tg if t["group"] == "contamination" or t["panel"] or t["tercile"] == "top" or t["item_id"] in ids]
    # priority order P → Ccon → T so partial runs still cover the primary set
    keep.sort(key=lambda t: (0 if t["panel"] else 1 if (t["group"] == "contamination" or t["item_id"] in ids) else 2))
    return [t["fol_folio"] for t in keep if t.get("fol_folio")]


if __name__ == "__main__":
    logger.remove()
    logger.add(sys.stdout, level="INFO")
    logger.add(common.ROOT / "logs" / "stage_worlds.log", level="DEBUG", rotation="20 MB")
    which = sys.argv[1]
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    fols = screen_fols() if which == "screen" else heldout_fols()
    logger.info(f"{which}: {len(fols)} formulas")
    res = W.compute(fols, workers=workers)
    logger.info(f"done {len(res)}; errors {sum(1 for r in res.values() if r.get('err'))}")
