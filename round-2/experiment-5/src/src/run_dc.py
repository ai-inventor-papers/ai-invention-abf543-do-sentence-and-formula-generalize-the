#!/usr/bin/env python3
"""S3 compute: all DC pair relations per sentence, one subprocess per sentence (RLIMIT_CPU / RLIMIT_AS), 6 at a time.

Pairs per sentence (dedup by canonical formula pair; identical canonical strings are EQUIV at no cost):
  peer pairs   : all unordered pairs among parseable {9 greedy systems + pilot formulas}
  lone pairs   : greedy vs its own 5 T=0.8 samples (gpt-4.1-mini, llama-3.1-8b)   [DC_lone / B8]
Usage: run_dc.py --set legal --limit 10 | --set legal | --set dev [--sids file]
Outputs work/dc_pairs/<set>/<sid>.jsonl and results/dc_timing_<set>.json.
"""
from __future__ import annotations

import argparse
import json
import os
import resource
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

from common import ROOT, RES, WORK, jdump, jload, read_jsonl, setup_logger, sha1

logger = setup_logger("run_dc")
from fol_parse import parse, to_str  # noqa: E402

LIMITS = {"l1_cap": 5040, "l2_cap": 2000, "l3_cap": 300, "l2_min_cov": 0.5, "l3_max_defs": 2, "l3_max_lits": 2,
          "domains": [1, 2, 3, 4], "z3_timeout_ms": 5000, "pair_seconds": 20.0, "order": "default",
          "n_random": 24, "n_models": 6, "max_z3_maps": 40}
BIG_RULE = {"pair_seconds": 10.0, "domains": [1, 2, 3]}  # runtime-only rule (pre-declared), applied if needed


def canon(fol: str) -> str | None:
    pr = parse(fol or "")
    return to_str(pr.ast) if pr.ok else None


def pair_key(a: str, b: str) -> tuple[str, str, str]:
    x, y = sorted([a, b])
    return sha1(x + "␞" + y), x, y


def build_legal_tasks(order: str = "default") -> dict:
    cands = read_jsonl(WORK / "candidates.jsonl")
    by = defaultdict(list)
    for c in cands:
        by[c["sentence_id"]].append(c)
    tasks = {}
    for sid, cs in by.items():
        peers = [c for c in cs if c["parse_ok"] and (c["frame"] == "pilot" or c["sample_idx"] == 0)]
        pairs = {}
        for i in range(len(peers)):
            for j in range(i + 1, len(peers)):
                a, b = peers[i]["fol_canon"], peers[j]["fol_canon"]
                if a == b:
                    continue
                k, x, y = pair_key(a, b)
                kind = "greedy" if peers[i]["frame"] == peers[j]["frame"] == "system" else "pilot"
                if k not in pairs or kind == "greedy":
                    pairs[k] = {"key": k, "a": x, "b": y, "kind": kind}
        for c in cs:
            if c["frame"] == "system" and c["sample_idx"] == 0 and c["parse_ok"]:
                for s in cs:
                    if s["system"] == c["system"] and s["sample_idx"] > 0 and s["parse_ok"] and s["fol_canon"] != c["fol_canon"]:
                        k, x, y = pair_key(c["fol_canon"], s["fol_canon"])
                        pairs.setdefault(k, {"key": k, "a": x, "b": y, "kind": "lone"})
        order_kind = {"greedy": 0, "pilot": 1, "lone": 2}
        tasks[sid] = sorted(pairs.values(), key=lambda p: (order_kind[p["kind"]], p["key"]))
    return tasks


def build_dev_tasks(sids: set | None) -> dict:
    rows = read_jsonl(WORK / "dev_frame.jsonl")
    by = defaultdict(list)
    for r in rows:
        by[r["sentence_id"]].append(r)
    tasks = {}
    for sid, cs in by.items():
        if sids is not None and sid not in sids:
            continue
        peers = [c for c in cs if c["fol_canon"]]
        pairs = {}
        for i in range(len(peers)):
            for j in range(i + 1, len(peers)):
                a, b = peers[i]["fol_canon"], peers[j]["fol_canon"]
                if a == b:
                    continue
                k, x, y = pair_key(a, b)
                pairs[k] = {"key": k, "a": x, "b": y, "kind": "greedy"}
        tasks[sid] = sorted(pairs.values(), key=lambda p: p["key"])
    return tasks


def _limit(cpu_s: int, ram_gb: float):
    def f():
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s + 5))
        b = int(ram_gb * 1024 ** 3)
        resource.setrlimit(resource.RLIMIT_AS, (b, b))
    return f


def run(tasks: dict, set_name: str, budget_s: float, workers: int, big_rule: dict | None, limits: dict) -> dict:
    tdir = WORK / "dc_tasks" / set_name
    odir = WORK / "dc_pairs" / set_name
    tdir.mkdir(parents=True, exist_ok=True)
    odir.mkdir(parents=True, exist_ok=True)
    queue = sorted(tasks, key=lambda s: -len(tasks[s]))  # longest first
    running: dict[str, tuple[subprocess.Popen, float]] = {}
    t0 = time.time()
    stats = {}
    py = str(ROOT / ".venv" / "bin" / "python")
    while queue or running:
        while queue and len(running) < workers:
            sid = queue.pop(0)
            out = odir / f"{sid}.jsonl"
            done = {r["key"] for r in read_jsonl(out)}
            todo = [p for p in tasks[sid] if p["key"] not in done]
            if not todo:
                continue
            tf = tdir / f"{sid}.json"
            tf.write_text(json.dumps({"sid": sid, "budget_s": budget_s, "limits": limits, "big_rule": big_rule,
                                      "pairs": todo}, ensure_ascii=False))
            p = subprocess.Popen([py, "-m", "dc.worker", str(tf), str(out)], cwd=str(ROOT),
                                 stdout=subprocess.DEVNULL, stderr=open(odir / f"{sid}.err", "w"),
                                 preexec_fn=_limit(int(budget_s * 1.5 + 60), 6.0))
            running[sid] = (p, time.time())
        time.sleep(0.5)
        for sid in list(running):
            p, ts = running[sid]
            if p.poll() is not None:
                stats[sid] = {"wall_s": round(time.time() - ts, 1), "rc": p.returncode, "n_pairs": len(tasks[sid])}
                del running[sid]
            elif time.time() - ts > budget_s * 1.6 + 90:
                p.kill()
                stats[sid] = {"wall_s": round(time.time() - ts, 1), "rc": "killed", "n_pairs": len(tasks[sid])}
                del running[sid]
        if int(time.time() - t0) % 60 == 0:
            logger.info(f"[{set_name}] done {len(stats)}/{len(tasks)} running {len(running)} elapsed {time.time() - t0:.0f}s")
    # fill missing pairs as UNKNOWN (killed workers)
    n_missing = 0
    for sid, prs in tasks.items():
        out = odir / f"{sid}.jsonl"
        done = {r["key"] for r in read_jsonl(out)}
        miss = [p for p in prs if p["key"] not in done]
        if miss:
            n_missing += len(miss)
            with open(out, "a", encoding="utf-8") as f:
                for p in miss:
                    f.write(json.dumps({"key": p["key"], "relation": "UNKNOWN", "reason": "worker_killed",
                                        "kind": p["kind"], "seconds": None}) + "\n")
    return {"wall_s": round(time.time() - t0, 1), "per_sentence": stats, "n_missing_marked_unknown": n_missing}


def timing_report(tasks: dict, set_name: str) -> dict:
    odir = WORK / "dc_pairs" / set_name
    import numpy as np
    recs = []
    for sid in tasks:
        recs += read_jsonl(odir / f"{sid}.jsonl")
    secs = [r["seconds"] for r in recs if r.get("seconds") is not None]
    by_rel = defaultdict(int)
    by_lvl = defaultdict(int)
    for r in recs:
        by_rel[r["relation"]] += 1
        by_lvl[str(r.get("level"))] += 1
    np_bins = defaultdict(list)
    for r in recs:
        if r.get("seconds") is not None and r.get("n_preds_a") is not None:
            m = max(r["n_preds_a"], r["n_preds_b"])
            np_bins["<=6" if m <= 6 else ("7-12" if m <= 12 else ">12")].append(r["seconds"])
    return {"n_pairs": len(recs), "sec_mean": float(np.mean(secs)) if secs else None,
            "sec_p90": float(np.percentile(secs, 90)) if secs else None, "sec_total": float(sum(secs)),
            "relations": dict(by_rel), "levels": dict(by_lvl),
            "sec_by_npreds": {k: {"n": len(v), "mean": float(np.mean(v))} for k, v in np_bins.items()}}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="legal")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sids", default="")
    ap.add_argument("--budget", type=float, default=300.0)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--big-rule", action="store_true")
    ap.add_argument("--order", default="default")
    a = ap.parse_args()
    limits = dict(LIMITS, order=a.order)
    set_name = a.set if a.order == "default" else f"{a.set}_{a.order}"
    if a.set == "legal":
        tasks = build_legal_tasks()
    else:
        sids = set(json.loads(Path(a.sids).read_text())) if a.sids else None
        tasks = build_dev_tasks(sids)
    if a.limit:
        sents = jload(WORK / "sentences.json") if a.set == "legal" else None
        keys = sorted(tasks)
        if sents:
            import random
            rng = random.Random(3)
            bins = defaultdict(list)
            for s in sents:
                if s["sentence_id"] in tasks:
                    bins[s["marker_bin"]].append(s["sentence_id"])
            keys = []
            for b in ("B0", "B1", "B2"):
                keys += rng.sample(sorted(bins[b]), min(3, len(bins[b])))
            keys += [s["sentence_id"] for s in sents if s["act"] == "SARA-IRC" and s["sentence_id"] in tasks][:1]
            keys += [s["sentence_id"] for s in sents if s["in_ai_act"] and s["sentence_id"] in tasks][:2]
        tasks = {k: tasks[k] for k in keys[: a.limit + 3]}
    n_pairs = sum(len(v) for v in tasks.values())
    logger.info(f"[{set_name}] sentences {len(tasks)} pairs {n_pairs} workers {a.workers} budget {a.budget}s")
    info = run(tasks, set_name, a.budget, a.workers, BIG_RULE if a.big_rule else None, limits)
    rep = timing_report(tasks, set_name)
    rep.update({k: v for k, v in info.items() if k != "per_sentence"}, n_sentences=len(tasks), limits=limits,
               big_rule=BIG_RULE if a.big_rule else None)
    rep["per_sentence"] = info["per_sentence"]
    tag = f"{set_name}{'_limit' + str(a.limit) if a.limit else ''}"
    jdump(rep, RES / f"dc_timing_{tag}.json")
    logger.info(f"[{set_name}] {json.dumps({k: v for k, v in rep.items() if k != 'per_sentence'})[:1500]}")


if __name__ == "__main__":
    main()
