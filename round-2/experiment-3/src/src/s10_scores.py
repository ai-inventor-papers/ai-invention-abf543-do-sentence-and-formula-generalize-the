#!/usr/bin/env python3
"""STEP 7 (plan numbering): scores for every fresh greedy row -> results/scores.jsonl (long format).

DC (frozen config), DC0 (unparseable -> 0), DC+SP features (score, sp_net, sp_incomparable, sp_contradictory),
DC error type (vs the modal representative), DC_self (peers = own 5 samples, uniform w; 2 systems), frozen
neighbours LC_onecoin / LC_maj / LC_ds_binary / LC_huiwalter, LC_within, B8, VC, B1, B2, B3nli, B3cos, B7 (+ parts),
B7_jacc, TJ, B1plus. DS weights are refitted label-free on the fresh EQUIV clusters (the frozen procedure).
"""
from __future__ import annotations

import json
from collections import defaultdict

from loguru import logger

from common import RES, SAMPLE_SYSTEMS, SYSTEMS, WORK, assert_frozen, log_reads, read_jsonl, setup_logging, write_jsonl
from dc.consensus import DCConfig
from dcscore import score_all
from pairs import load_cache, lookup
from typing_jobs import run_typing

FR = WORK / "fresh_frame.jsonl"


def pair_seconds(cache, canons: dict) -> dict:
    """Solver seconds attributed to each output: half of every pair it takes part in."""
    out = defaultdict(float)
    keys = [k for k, c in canons.items() if c]
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            rec, _ = lookup(cache, canons[a], canons[b])
            s = (rec or {}).get("s", 0.0) or 0.0
            out[a] += s / 2
            out[b] += s / 2
    return out


@logger.catch(reraise=True)
def main() -> None:
    setup_logging("s10_scores")
    fz = assert_frozen()
    log_reads("s10_scores")
    c = fz["config"]
    cfg = DCConfig(use_L3=c["use_L3"], unalign_in_denominator=c["unalign_in_denominator"], weights=c["weights"],
                   half_caps=c["half_caps"], rule_1b=c["rule_1b"])
    rows = read_jsonl(FR)
    G = [r for r in rows if r["fold"] == "fresh_greedy"]
    by_item = {r["item_id"]: r for r in rows}
    groups = defaultdict(dict)
    for r in G:
        groups[r["sid"]][r["system"]] = r["canon"]
    cache = load_cache()
    sc, w, winfo = score_all(groups, cache, cfg, SYSTEMS)
    logger.info(f"DC scored {len(sc)}; weights {w}")
    long = []

    def add(iid, metric, score, covered, usd=0.0, seconds=None, **extra):
        long.append({"item_id": iid, "metric": metric, "score": float(score) if covered else 0.5,
                     "covered": bool(covered), "usd": usd, "seconds": seconds, "extra": {"raw_score": score, **extra}})
    secs = {}
    for sid, g in groups.items():
        for s, v in pair_seconds(cache, g).items():
            secs[(sid, s)] = v
    # typing: every parseable non-mode greedy row vs its modal representative
    jobs = []
    for r in G:
        res = sc[(r["sid"], r["system"])]
        if r["parse_ok"] and res.get("mode_rep") and not res.get("in_mode"):
            jobs.append((r["item_id"], r["canon"], groups[r["sid"]][res["mode_rep"]]))
    typ = run_typing(jobs, use_L3=cfg.use_L3)
    key_t = "type_1b_on" if cfg.rule_1b else "type_1b_off"
    for r in G:
        res = sc[(r["sid"], r["system"])]
        t = None
        if r["parse_ok"]:
            t = "none" if res.get("in_mode") else typ.get(r["item_id"], {}).get(key_t, "other" if res.get("mode_rep") else None)
        add(r["item_id"], "DC", res["score"], res["covered"], 0.0, secs.get((r["sid"], r["system"])),
            error_type=t, relations=res.get("relations"), n_peers_covered=res.get("n_peers_covered"),
            in_mode=res.get("in_mode"), mode_size=res.get("mode_size"), n_clusters=res.get("n_clusters"),
            mode_weight_share=res.get("mode_weight_share"), unparseable=res.get("unparseable"),
            type_flags=typ.get(r["item_id"], {}).get("flags"))
        add(r["item_id"], "DC0", res["score_DC0"], True)
        for k in ("sp_net", "sp_incomparable", "sp_contradictory", "sp_unalignable"):
            if res.get(k) is not None:
                add(r["item_id"], k, res[k], res["covered"])
    # DC_self (peers = own samples, uniform weights)
    samples = defaultdict(dict)
    for r in rows:
        if r["fold"] == "fresh_samples":
            samples[(r["sid"], r["system"])][f"s{r['sample_idx']}"] = r["canon"]
    for sysn in SAMPLE_SYSTEMS:
        gs = {r["sid"]: {"greedy": r["canon"], **samples.get((r["sid"], sysn), {})} for r in G if r["system"] == sysn}
        cself = DCConfig(use_L3=cfg.use_L3, unalign_in_denominator=cfg.unalign_in_denominator, weights="uniform",
                         half_caps=cfg.half_caps)
        ss, _, _ = score_all(gs, cache, cself, ["greedy", "s1", "s2", "s3", "s4", "s5"])
        for sid in gs:
            res = ss[(sid, "greedy")]
            add(f"{sid}:{sysn}:0", "DC_self", res["score"], res["covered"])
    # frozen neighbours
    for x in read_jsonl(WORK / "lc_scores_fresh.jsonl"):
        sid, sysn = x["item_id"].split(":", 1)
        iid = f"{sid}:{sysn}:0"
        if iid in by_item and x["metric"] in ("LC_onecoin", "LC_maj", "LC_ds_binary", "LC_huiwalter", "LC_within", "B8"):
            add(iid, x["metric"], x["score"], x["covered"])
    for x in read_jsonl(WORK / "vc_fresh.jsonl"):
        add(x["item_id"], "VC", x["VC"], x["covered"])
    for x in read_jsonl(WORK / "b1_fresh.jsonl"):
        add(x["item_id"], "B1", x["B1"], x["covered"], x.get("usd", 0.0), x.get("seconds"))
    for x in read_jsonl(WORK / "b7_fresh.jsonl"):
        for m in ("B2", "B7", "B7_arity_self", "B7_arity_story", "B7_joint"):
            add(x["item_id"], m, x[m], True)
        if x.get("B7_jacc") is not None or x["item_id"].split(":")[1] in SAMPLE_SYSTEMS:
            add(x["item_id"], "B7_jacc", x.get("B7_jacc") if x.get("B7_jacc") is not None else 0.5, x.get("B7_jacc") is not None)
    for x in read_jsonl(WORK / "b3_fresh.jsonl"):
        add(x["item_id"], "B3nli", x["B3nli"], x["covered"], x.get("usd", 0.0) / 2)
        add(x["item_id"], "B3cos", x["B3cos"], x["covered"], x.get("usd", 0.0) / 2)
    for x in read_jsonl(WORK / "tj_fresh.jsonl"):
        pf = x.get("p_faithful")
        add(x["item_id"], "TJ", pf if pf is not None else 0.5, pf is not None, x.get("usd", 0.0),
            tj_primary=x.get("primary"), tj_faithful=x.get("faithful"))
    for x in read_jsonl(WORK / "b3L_fresh.jsonl"):
        add(x["item_id"], "B3nliL", x["B3nliL"], x["covered"], 0.0, model=x.get("model"))
        add(x["item_id"], "B3cosL", x["B3cosL"], x["covered"], 0.0, model=x.get("model"))
    for x in read_jsonl(WORK / "tjL_fresh.jsonl"):
        pf = x.get("p_faithful")
        add(x["item_id"], "TJ_L", pf if pf is not None else 0.5, pf is not None, 0.0, seconds=x.get("seconds"),
            tj_primary=x.get("primary"), tj_faithful=x.get("faithful"))
    for x in read_jsonl(WORK / "b1plus_fresh.jsonl"):
        add(x["item_id"], "B1plus", x["B1plus"], x["covered"], x.get("usd", 0.0))
    write_jsonl(RES / "scores.jsonl", long)
    (WORK / "fresh_dc_weights.json").write_text(json.dumps({"weights": w, "info": winfo, "dev_weights": fz.get("dev_weights_selected")},
                                                           indent=1, default=str))
    from collections import Counter
    logger.info(f"scores: {Counter(x['metric'] for x in long)}")


if __name__ == "__main__":
    main()
