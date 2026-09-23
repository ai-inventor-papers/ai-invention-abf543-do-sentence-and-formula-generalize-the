"""Assemble every metric score into one long table (results/heldout_scores.jsonl) and a wide per-item frame.

Conventions (pre-registered): uncovered items keep score 0.5 (covered=False) and stay in every analysis; the raw
metric value (e.g. LC's own 0.0 for its unparseable candidates) is kept in `extra.raw_score`.
"""
from __future__ import annotations

import json
from collections import defaultdict

from common import RES, SAMPLE_SYSTEMS, WORK, read_jsonl, sha1, write_jsonl

LC_METRICS = ["LC_onecoin", "LC_onecoin_str", "LC_huiwalter", "LC_maj", "LC_ds_binary", "LC_granular"]
METRICS = LC_METRICS + ["LC_within", "A3", "A1", "A0", "Ccov", "B1", "B1plus", "B2", "B2_armB", "B3cos", "B3nli",
                        "B3c", "B7", "B7_arity_self", "B7_arity_story", "B7_joint", "B7_jacc", "B8",
                        # local-GPU substitutes (Qwen3-8B; same frozen prompts) -- see src/local_llm.py
                        "B1L", "B1plusL", "A1L", "B3cosL", "B3nliL", "B3cL"]


def build_long(frame_rows: list[dict]) -> list[dict]:
    by_id = {r["item_id"]: r for r in frame_rows}
    G = [r for r in frame_rows if r["fold"] == "heldout_confirm"]
    g_by_sid_sys = {(r["sentence_id"], r["system"]): r["item_id"] for r in G}
    canon = {r["h"]: r for r in read_jsonl(WORK / "canon.jsonl")}
    pb = {r["h"]: r for r in read_jsonl(WORK / "armB_parse.jsonl")}
    out = []

    def add(item_id, metric, score, covered, usd=0.0, seconds=None, **extra):
        r = by_id.get(item_id)
        out.append({"item_id": item_id, "fold": r["fold"] if r else None, "metric": metric,
                    "score": float(score) if covered else 0.5, "covered": bool(covered), "usd": usd or 0.0,
                    "seconds": seconds, "extra": {"raw_score": score, **extra}})
    # LC family (item ids 'sid:system' -> dataset item id 'sid:system:0'); LC_within/B8 'sid:system'
    for r in read_jsonl(WORK / "lc_scores.jsonl"):
        sid, sysn = r["item_id"].split(":", 1)
        iid = g_by_sid_sys.get((sid, sysn))
        if iid is None:
            continue
        ex = {k: v for k, v in r.items() if k not in ("item_id", "metric", "score", "covered")}
        add(iid, r["metric"], r["score"], r["covered"], **ex)
    lc_info = json.loads((WORK / "lc_info.json").read_text()) if (WORK / "lc_info.json").exists() else {}
    # Arm A
    for f in ("armA_scores.jsonl", "armA_scores_a1.jsonl", "armA_scores_a1L.jsonl"):
        for r in read_jsonl(WORK / f):
            if r["key"] in by_id:
                add(r["key"], r["metric"], r["score"] if r["covered"] else r.get("raw_score"), r["covered"],
                    seconds=r.get("seconds"), error_type_pred=r.get("error_type_pred"),
                    why_uncovered=r.get("why_uncovered"), mismatches=r.get("mismatches"))
    # A1 per-sentence probe cost amortised over the sentence's scored candidates
    a1cost = {r["sentence"]: r.get("usd", 0.0) for r in read_jsonl(WORK / "a1_raw.jsonl")}
    n_per_sent = defaultdict(int)
    for x in out:
        if x["metric"] == "A1":
            n_per_sent[by_id[x["item_id"]]["sentence"]] += 1
    for x in out:
        if x["metric"] == "A1":
            s = by_id[x["item_id"]]["sentence"]
            x["usd"] = a1cost.get(s, 0.0) / max(1, n_per_sent[s])
    # LLM judges / round trip
    for f, m in (("b1_scores.jsonl", "B1"), ("b1plus_scores.jsonl", "B1plus"), ("b3_scores.jsonl", None),
                 ("b3c_scores.jsonl", "B3c"), ("b1L_scores.jsonl", "B1L"), ("b1plusL_scores.jsonl", "B1plusL"),
                 ("b3L_scores.jsonl", None), ("b3cL_scores.jsonl", "B3cL")):
        for r in read_jsonl(WORK / f):
            if r["key"] not in by_id:
                continue
            ex = {k: v for k, v in r.items() if k in ("raw", "model", "cached", "extra", "nli_model")}
            add(r["key"], r.get("metric", m), r["score"] if r["covered"] else None, r["covered"],
                usd=r.get("usd", 0.0), seconds=r.get("seconds"), **ex)
    # B2 parse (dataset parse_ok = B2; Arm B's own parser on the metric input string = B2_armB)
    for r in frame_rows:
        if r["fold"] not in ("heldout_confirm", "contamination"):
            continue
        add(r["item_id"], "B2", float(bool(r["parse_ok"])), True)
        raw = r.get("candidate_fol") or ""
        c, b = canon.get(sha1(raw), {}), pb.get(sha1(raw), {})
        ok = bool(b.get("armB_ok_canon")) if c.get("canon") else bool(b.get("armB_ok_raw"))
        add(r["item_id"], "B2_armB", float(ok), True)
    # B7 structural + components
    for r in read_jsonl(WORK / "b7_scores.jsonl"):
        for m in ("B7", "B7_arity_self", "B7_arity_story", "B7_joint"):
            add(r["key"], m, float(r[m]), True, joint_status=r.get("joint_status"))
        if "B7_jacc" in r:
            add(r["key"], "B7_jacc", r["B7_jacc"], r["B7_jacc"] is not None)
    # LC_within / B8 are keyed 'sid:system' -> dataset greedy item
    return out, lc_info


def wide(long_rows: list[dict]) -> dict:
    """{item_id: {metric: (score, covered)}}"""
    W = defaultdict(dict)
    for r in long_rows:
        W[r["item_id"]][r["metric"]] = (r["score"], r["covered"])
    return W


def write_long(long_rows: list[dict]) -> None:
    write_jsonl(RES / "heldout_scores.jsonl", long_rows)
