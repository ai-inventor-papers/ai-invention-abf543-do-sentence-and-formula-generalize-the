#!/usr/bin/env python3
"""Build work/frame.jsonl (heldout_confirm + contamination rows) and work/canon.jsonl (every candidate/gold string ->
DC canonical form or UNPARSEABLE)."""
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from loguru import logger
from dc.common import WORK, load_frame, wj, sha1
from dc.front import canon

logger.remove(); logger.add(sys.stdout, level="INFO", format="{time:HH:mm:ss}|{level:<7}|{message}")
logger.add(str(Path(__file__).resolve().parents[1] / "logs" / "prep.log"), level="DEBUG")


@logger.catch(reraise=True)
def main():
    t0 = time.time()
    rows = load_frame()
    logger.info(f"frame rows {len(rows)} in {time.time()-t0:.1f}s")
    strings = set()
    for r in rows:
        for k in ("candidate_fol", "gold_fol_original", "gold_fol_audited", "candidate_fol_original", "gold_fol_renamed"):
            if r.get(k):
                strings.add(r[k])
    out = []
    for s in sorted(strings):
        c = canon(s)
        out.append({"h": sha1(s), "raw": s, "ok": c["ok"], "canon": c["canon"] if c["ok"] else None,
                    "n_preds": len(c["preds"]), "n_consts": len(c["consts"])})
    wj(WORK / "canon.jsonl", out)
    logger.info(f"canon: {len(out)} strings, ok {sum(o['ok'] for o in out)} in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
