#!/usr/bin/env python3
"""Secondary DC runs (no API, same frozen limits):
  invariance  100 parseable greedy candidates x meaning-preserving rewrites (random predicate RENAME, operand REORDER of
              every ∧/∨, top-level CONTRAPOSITIVE); DC recomputed against the same peers and weights.
              False alarm = |ΔDC| > 0.05, by rewrite kind.  -> results/invariance.json
  placebo     DC with peers shuffled across sentences (each sentence's candidates scored against another sentence's
              greedy outputs); AUROC vs the panel label is computed in analysis.py  -> work/placebo_scores.jsonl
"""
from __future__ import annotations

import argparse
import random
from collections import Counter, defaultdict

import numpy as np

from common import RES, SEED, WORK, jdump, jload, read_jsonl, setup_logger, write_jsonl

logger = setup_logger("extra_dc")
from fol_parse import SYM, parse, to_str  # noqa: E402
from run_dc import LIMITS, pair_key, run  # noqa: E402


def rename(ast, pm):
    op = ast[0]
    if op in ("forall", "exists"):
        return (op, ast[1], rename(ast[2], pm))
    if op == "not":
        return ("not", rename(ast[1], pm))
    if op in SYM:
        return (op, rename(ast[1], pm), rename(ast[2], pm))
    if op == "atom":
        return ("atom", pm.get(ast[1], ast[1]), ast[2])
    return ast


def reorder(ast):
    op = ast[0]
    if op in ("forall", "exists"):
        return (op, ast[1], reorder(ast[2]))
    if op == "not":
        return ("not", reorder(ast[1]))
    if op in ("and", "or"):
        return (op, reorder(ast[2]), reorder(ast[1]))
    if op in SYM:
        return (op, reorder(ast[1]), reorder(ast[2]))
    return ast


def contrapositive(ast):
    if ast[0] in ("forall", "exists"):
        inner = contrapositive(ast[2])
        return None if inner is None else (ast[0], ast[1], inner)
    if ast[0] == "imp":
        return ("imp", ("not", ast[2]), ("not", ast[1]))
    return None


def _peers(cands):
    by = defaultdict(list)
    for c in cands:
        by[c["sentence_id"]].append(c)
    return by


def invariance(workers: int) -> None:
    cfg = jload(RES / "dc_config.json")
    W = cfg["ds_weights"]["w"]
    cands = read_jsonl(WORK / "candidates.jsonl")
    dc = {r["cand_id"]: r for r in read_jsonl(RES / "dc_scores_frozen.jsonl")}
    by = _peers(cands)
    pool = sorted([c for c in cands if c["frame"] == "system" and c["sample_idx"] == 0 and c["parse_ok"]
                   and dc.get(c["cand_id"], {}).get("DC_cov")], key=lambda c: c["cand_id"])
    rng = random.Random(SEED + 11)
    pick = rng.sample(pool, min(100, len(pool)))
    tasks = defaultdict(dict)
    plan = []
    for c in pick:
        ast = parse(c["fol"]).ast
        preds = sorted({o for o in _atoms(ast)})
        pm = {p: "Q" + "".join(rng.choice("bcdfghjklmnpqrstvwxz") for _ in range(6)) + str(i) for i, p in enumerate(preds)}
        rw = {"rename": rename(ast, pm), "reorder": reorder(ast), "contrapositive": contrapositive(ast)}
        greedy = [g for g in by[c["sentence_id"]] if g["frame"] == "system" and g["sample_idx"] == 0 and g["parse_ok"] and g["system"] != c["system"]]
        pil = [p for p in by[c["sentence_id"]] if p["frame"] == "pilot" and p["parse_ok"]]
        peers = [(g["fol_canon"], W.get(g["system"], 1.0)) for g in greedy] + [(p["fol_canon"], W.get("pilot", 1.0) / len(pil)) for p in pil]
        for kind, a in rw.items():
            if a is None:
                continue
            fs = to_str(a)
            fs = to_str(parse(fs).ast)
            plan.append({"cand_id": c["cand_id"], "kind": kind, "fol": fs, "peers": peers, "orig": dc[c["cand_id"]]["DC"]})
            for pf, _ in peers:
                if pf == fs:
                    continue
                k, x, y = pair_key(fs, pf)
                tasks[c["sentence_id"]][k] = {"key": k, "a": x, "b": y, "kind": "invariance"}
    tasks = {s: sorted(v.values(), key=lambda p: p["key"]) for s, v in tasks.items()}
    logger.info(f"invariance: {len(plan)} rewrites, {sum(len(v) for v in tasks.values())} pairs")
    run(tasks, "invariance", 300.0, workers, None, LIMITS)
    rel = {}
    for f in (WORK / "dc_pairs" / "invariance").glob("*.jsonl"):
        for r in read_jsonl(f):
            rel[r["key"]] = r["relation"]
    from dc.api import INVERSE, score_from_relations
    res = []
    for p in plan:
        rels = []
        for pf, w in p["peers"]:
            if pf == p["fol"]:
                rels.append("EQUIV")
                continue
            k, x, y = pair_key(p["fol"], pf)
            r = rel.get(k, "UNKNOWN")
            rels.append(r if p["fol"] == x else INVERSE.get(r, r))
        sc = score_from_relations(rels, [w for _, w in p["peers"]])
        res.append({"cand_id": p["cand_id"], "kind": p["kind"], "orig": p["orig"], "new": sc["score"],
                    "delta": sc["score"] - p["orig"], "false_alarm": abs(sc["score"] - p["orig"]) > 0.05})
    out = {"n_candidates": len(pick), "by_kind": {}}
    for k in ("rename", "reorder", "contrapositive"):
        sel = [r for r in res if r["kind"] == k]
        if sel:
            out["by_kind"][k] = {"n": len(sel), "false_alarm_rate": float(np.mean([r["false_alarm"] for r in sel])),
                                 "mean_abs_delta": float(np.mean([abs(r["delta"]) for r in sel]))}
    out["rows"] = res
    jdump(out, RES / "invariance.json")
    logger.info(f"invariance: {out['by_kind']}")


def _atoms(ast):
    if ast[0] in ("forall", "exists"):
        yield from _atoms(ast[2])
    elif ast[0] == "not":
        yield from _atoms(ast[1])
    elif ast[0] in SYM:
        yield from _atoms(ast[1])
        yield from _atoms(ast[2])
    elif ast[0] == "atom":
        yield ast[1]


def placebo(workers: int) -> None:
    cfg = jload(RES / "dc_config.json")
    W = cfg["ds_weights"]["w"]
    cands = read_jsonl(WORK / "candidates.jsonl")
    by = _peers(cands)
    samp = {s["item_id"] for s in jload(WORK / "panel_sample.json")["items"]}
    sids = sorted({c["sentence_id"] for c in cands if c["cand_id"] in samp})
    rng = random.Random(SEED + 13)
    perm = sids[:]
    while True:
        rng.shuffle(perm)
        if all(a != b for a, b in zip(sids, perm)):
            break
    other = dict(zip(sids, perm))
    tasks = defaultdict(dict)
    plan = []
    for sid in sids:
        peers_src = [g for g in by[other[sid]] if g["frame"] == "system" and g["sample_idx"] == 0 and g["parse_ok"]]
        for c in by[sid]:
            if c["cand_id"] not in samp or not c["parse_ok"]:
                continue
            ps = [(g["fol_canon"], W.get(g["system"], 1.0)) for g in peers_src if g["system"] != c["system"]]
            plan.append({"cand_id": c["cand_id"], "fol": c["fol_canon"], "peers": ps})
            for pf, _ in ps:
                if pf == c["fol_canon"]:
                    continue
                k, x, y = pair_key(c["fol_canon"], pf)
                tasks[sid][k] = {"key": k, "a": x, "b": y, "kind": "placebo"}
    tasks = {s: sorted(v.values(), key=lambda p: p["key"]) for s, v in tasks.items()}
    logger.info(f"placebo: {len(plan)} candidates, {sum(len(v) for v in tasks.values())} pairs")
    run(tasks, "placebo", 120.0, workers, None, dict(LIMITS, pair_seconds=10.0))
    rel = {}
    for f in (WORK / "dc_pairs" / "placebo").glob("*.jsonl"):
        for r in read_jsonl(f):
            rel[r["key"]] = r["relation"]
    from dc.api import INVERSE, score_from_relations
    rows = []
    for p in plan:
        rels = []
        for pf, w in p["peers"]:
            k, x, y = pair_key(p["fol"], pf)
            r = "EQUIV" if pf == p["fol"] else rel.get(k, "UNKNOWN")
            rels.append(r if p["fol"] == x else INVERSE.get(r, r))
        sc = score_from_relations(rels, [w for _, w in p["peers"]])
        rows.append({"key": p["cand_id"], "DC_placebo": sc["score"], "DC_placebo_cov": sc["coverage"],
                     "rels": dict(Counter(rels))})
    write_jsonl(WORK / "placebo_scores.jsonl", rows)
    logger.info(f"placebo scored {len(rows)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    ap.add_argument("--workers", type=int, default=5)
    a = ap.parse_args()
    {"invariance": lambda: invariance(a.workers), "placebo": lambda: placebo(a.workers)}[a.cmd]()


if __name__ == "__main__":
    main()
