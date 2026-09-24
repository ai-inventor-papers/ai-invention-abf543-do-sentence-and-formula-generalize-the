#!/usr/bin/env python3
"""M0 pair jobs: all within-sentence peer pairs among parseable greedy outputs (C(9,2) per sentence) + gold (original
and audited) vs every output. Resumable (work/pairs_dc.jsonl). Usage: m0_pairs.py [n_sentences] [workers]"""
import sys, time, random
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from loguru import logger
from dc.common import WORK, LOGS, load_frame, rj, detect_cpus, PairStore

logger.remove(); logger.add(sys.stdout, level="INFO", format="{time:HH:mm:ss}|{level:<7}|{message}")
logger.add(str(LOGS / "m0_pairs.log"), level="DEBUG")


def jobs(n_sent=None):
    rows = [r for r in load_frame() if r["fold"] == "heldout_confirm"]
    can = {c["raw"]: c for c in rj(WORK / "canon.jsonl")}
    by = defaultdict(list)
    for r in rows:
        by[r["sentence_id"]].append(r)
    sids = sorted(by)
    if n_sent:
        random.Random(0).shuffle(sids)
        sids = sorted(sids[:n_sent])
    out = []
    for sid in sids:
        cs = [can[r["candidate_fol"]]["canon"] for r in by[sid] if r.get("candidate_fol") and can.get(r["candidate_fol"], {}).get("ok")]
        for i in range(len(cs)):
            for j in range(i + 1, len(cs)):
                out.append((cs[i], cs[j]))
        g0 = by[sid][0]
        for gk in ("gold_fol_original", "gold_fol_audited"):
            g = g0.get(gk)
            if g and can.get(g, {}).get("ok"):
                for c in cs:
                    out.append((can[g]["canon"], c))
    return sids, out


@logger.catch(reraise=True)
def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1] != "all" else None
    w = int(sys.argv[2]) if len(sys.argv) > 2 else max(1, detect_cpus() - 1)
    sids, pj = jobs(n)
    logger.info(f"{len(sids)} sentences, {len(pj)} pair jobs, workers={w}")
    st = PairStore()
    t0 = time.time()
    info = st.compute(pj, workers=w, log=logger.info)
    logger.info(f"done {info} wall {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
