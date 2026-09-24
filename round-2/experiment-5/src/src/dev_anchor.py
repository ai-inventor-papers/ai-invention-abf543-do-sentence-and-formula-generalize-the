#!/usr/bin/env python3
"""DEV ANCHOR (no API): default DC on the round-1 heldout_confirm group (700 sentences x 9 greedy peers).

frame   : work/dev_frame.jsonl (one row per greedy candidate, label_source / panel3 label / L3 sampling weight)
l1      : vendor fol_equiv.equivalence on every within-sentence greedy pair -> work/dev_l1_pairs.jsonl (LC_maj/DS_bin)
auroc   : weighted AUROC of DC / DC_noL3 / DS_dc / LC_maj / DS_bin on the panel3 items with sentence-clustered CI
"""
from __future__ import annotations

import argparse
import glob
import json
import multiprocessing as mp
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from common import DS_DIR, RES, VENDOR, WORK, append_jsonl, jdump, read_jsonl, setup_logger, sha1, write_jsonl

logger = setup_logger("dev_anchor")
from fol_parse import parse, to_str  # noqa: E402


def build_frame() -> None:
    rows = []
    for f in sorted(glob.glob(str(DS_DIR / "full_data_out" / "full_data_out_*.json"))):
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        for g in d["datasets"]:
            if g["dataset"] != "heldout_confirm":
                continue
            for ex in g["examples"]:
                inp = json.loads(ex["input"])
                pr = parse(inp.get("candidate_fol") or "")
                rows.append({"cand_id": ex["metadata_item_id"], "sentence_id": ex["metadata_sentence_id"],
                             "system": ex["metadata_system"], "sample_idx": ex["metadata_sample_idx"], "frame": "system",
                             "parse_ok": pr.ok, "fol_canon": to_str(pr.ast) if pr.ok else None,
                             "sentence": inp.get("sentence"), "fol": inp.get("candidate_fol"), "output": ex["output"],
                             "label_source": ex.get("metadata_label_source"),
                             "w": ex.get("metadata_L3_sampling_weight"), "corpus": ex.get("metadata_corpus"),
                             "tercile": ex.get("metadata_complexity_tercile")})
        del d
    write_jsonl(WORK / "dev_frame.jsonl", rows)
    n3 = sum(1 for r in rows if r["label_source"] == "panel3")
    logger.info(f"dev frame {len(rows)} rows, {len({r['sentence_id'] for r in rows})} sentences, panel3 {n3}")
    sids = sorted({r["sentence_id"] for r in rows if r["label_source"] == "panel3"})
    Path(WORK / "dev_panel3_sids.json").write_text(json.dumps(sids))


def _l1(args):
    sys.path.insert(0, str(VENDOR / "ds"))
    from fol_equiv import equivalence
    k, a, b = args
    r = equivalence(parse(a).ast, parse(b).ast, time_limit=6.0, want_entailment=False)
    return k, r["status"]


def l1(workers: int) -> None:
    rows = read_jsonl(WORK / "dev_frame.jsonl")
    by = defaultdict(list)
    for r in rows:
        if r["parse_ok"]:
            by[r["sentence_id"]].append(r)
    out = WORK / "dev_l1_pairs.jsonl"
    done = {r["key"] for r in read_jsonl(out)}
    jobs = []
    for cs in by.values():
        for i in range(len(cs)):
            for j in range(i + 1, len(cs)):
                a, b = sorted([cs[i]["fol_canon"], cs[j]["fol_canon"]])
                k = sha1(a + "␞" + b)
                if a != b and k not in done:
                    done.add(k)
                    jobs.append((k, a, b))
    logger.info(f"dev L1 jobs {len(jobs)}")
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn")) as ex:
        buf = []
        for k, st in ex.map(_l1, jobs, chunksize=16):
            buf.append({"key": k, "status": st})
            if len(buf) >= 500:
                append_jsonl(out, buf)
                buf = []
        append_jsonl(out, buf)
    logger.info(f"dev L1 done {time.time() - t0:.0f}s")


def auroc() -> None:
    import numpy as np
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from stats_ext import StratBoot, ci, wauc
    frame = {r["cand_id"]: r for r in read_jsonl(WORK / "dev_frame.jsonl")}
    sc = read_jsonl(WORK / "dc_scores_dev.jsonl")
    rows = [(s, frame[s["cand_id"]]) for s in sc if frame[s["cand_id"]]["label_source"] == "panel3"
            and frame[s["cand_id"]]["output"] in ("faithful", "unfaithful")]
    y = np.array([f["output"] == "faithful" for _, f in rows], float)
    w = np.array([f["w"] or 1.0 for _, f in rows], float)
    sids = np.array([f["sentence_id"] for _, f in rows])
    strata = {f["sentence_id"]: f.get("corpus") or "NA" for _, f in rows}
    boot = StratBoot(sids, strata, n=1000, seed=0)
    res = {"n_items": len(rows), "n_sentences": len(set(sids)), "weighted_faithful_share": float((w * y).sum() / w.sum())}
    for m in ("DC", "DC_noL3", "DC_unw", "DS_dc", "LC_maj", "DS_bin"):
        s = np.array([(r.get(m) if r.get(m) is not None else 0.5) for r, _ in rows], float)
        res[m] = {"auroc_w": wauc(y, s, w), "ci95": ci(wauc(y[i], s[i], w[i]) for i in boot),
                  "coverage": float(np.mean([bool(r.get(m + "_cov")) for r, _ in rows]))}
    res["reference_round2"] = {"DS": 0.787, "LC": 0.756, "tolerance": 0.05}
    res["within_tolerance_of_DS_or_LC"] = bool(min(abs(res["DC"]["auroc_w"] - 0.787), abs(res["DC"]["auroc_w"] - 0.756)) <= 0.05)
    jdump(res, RES / "dev_anchor.json")
    logger.info(f"dev anchor: {json.dumps(res)[:1200]}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args()
    {"frame": build_frame, "l1": lambda: l1(a.workers), "auroc": auroc}[a.cmd]()


if __name__ == "__main__":
    main()
