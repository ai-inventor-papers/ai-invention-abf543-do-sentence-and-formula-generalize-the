#!/usr/bin/env python3
"""STEPS 4-5 (+ B5 oracle, in-domain text diagnostic): align every formula (gold, real, mutant, rewrite) to
the sentence's text concepts and score A1 / A2 / A3 / B5 / B5-A2 with the SAME score.py.
Inputs: data/screen_set.json, results/formula_sigs.json, results/text_sigs.json
Outputs: results/screen_scores_signature.jsonl, results/alignments.json, results/text_diag.json
"""
from __future__ import annotations

import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
from align import align, is_optional, prewarm, pred_tokens  # noqa: E402
from fol_parse import ParseError, parse  # noqa: E402
from score import FLIP, signature_score  # noqa: E402

logger.remove()
logger.add(sys.stdout, level="INFO", format="{time:HH:mm:ss}|{level:<7}|{message}")
logger.add(ROOT / "logs" / "run_metrics.log", rotation="30 MB", level="DEBUG")


def text_T(ts: dict, variant: str) -> dict:
    anchors = ts["anchors"]
    if variant == "A3":
        return {"labels": {int(k): v for k, v in ts["marker"].items()}, "anchors": anchors,
                "rel": {tuple(_k(k)): v for k, v in ts["a3_rel"].items()}}
    labels = {int(k): v for k, v in ts["llm_labels"].items()}
    rel = {tuple(_k(k)): v for k, v in ts["llm_rel"].items()} if variant == "A2" else {}
    return {"labels": labels, "anchors": anchors, "rel": rel}


def _k(k: str):
    c, q, side = k.split("|")
    return int(c), int(q), side


def oracle_T(ts: dict, T: dict, Sg: dict, Ag: dict, with_rel: bool) -> dict:
    """B5: text labels replaced by the GOLD formula's signature on aligned concepts."""
    labels = dict(T["labels"])
    by_c = defaultdict(list)
    for P, a in Ag["preds"].items():
        if a["cid"] is not None:
            by_c[a["cid"]].append(P)
    for cid in list(labels):
        Ps = by_c.get(cid, [])
        if Ps:
            sl = Sg["labels"].get(Ps[0], "?")
            labels[cid] = FLIP[sl] if Ag["preds"][Ps[0]]["flip"] else sl
    anchors = []
    for an in T["anchors"]:
        Rs = [P for P in by_c.get(an["verb_cid"], []) if Sg["arity"].get(P, 1) >= 2]
        args = [P for P in by_c.get(an["arg_cid"], []) if Sg["arity"].get(P, 1) == 1]
        args += [f"c:{k}" for k, cid in Ag["consts"].items() if cid == an["arg_cid"]]
        slot = an["slot"]
        if Rs and args:
            R = Rs[0]
            js = [j for j in range(Sg["arity"][R]) if Sg["anchors"].get(f"{R}|{j}|{args[0]}") is True]
            if len(js) == 1:
                slot = js[0]
        anchors.append({**an, "slot": slot})
    rel = {}
    if with_rel:
        keys = set(T.get("rel", {}).keys()) | {tuple(_k(k)) for k in ts["a3_rel"]}
        for (c, q, side) in keys:
            Pc = [P for P in by_c.get(c, []) if Sg["arity"].get(P, 1) == 1]
            Pq = [P for P in by_c.get(q, []) if Sg["arity"].get(P, 1) == 1]
            if Pc and Pq and Pc[0] != Pq[0]:
                sl = Sg["rel"].get(f"{Pc[0]}|{Pq[0]}|{side}")
                if sl and sl != "?":
                    rel[(c, q, side)] = FLIP[sl] if Ag["preds"][Pc[0]]["flip"] else sl
    return {"labels": labels, "anchors": anchors, "rel": rel}


@logger.catch(reraise=True)
def main():
    d = json.loads((ROOT / "data" / "screen_set.json").read_text())
    sigs = json.loads((ROOT / "results" / "formula_sigs.json").read_text())
    b4p = ROOT / "results" / "b4_llm_sigs.json"
    b4 = json.loads(b4p.read_text()) if b4p.exists() else {}
    logger.info(f"B4 LLM-signatures available for {len(b4)} items")
    tsig = json.loads((ROOT / "results" / "text_sigs.json").read_text())
    sents = {s["sid"]: s for s in d["sentences"] if s["sid"] in tsig}
    logger.info(f"{len(sents)} sentences with text signatures")
    # items per sentence
    items = []
    for s in sents.values():
        items.append({"item_id": f"{s['sid']}:gold", "set": "gold", "sid": s["sid"], "fol": s["gold_fol"], "parse_ok": True})
    for r in d["real"]:
        if r["sid"] in sents:
            items.append({"item_id": r["item_id"], "set": "real", "sid": r["sid"], "fol": r["cand_fol"],
                          "parse_ok": r["parse_ok"]})
    for s in sents.values():
        if s.get("gold_fol_corr") and s.get("gold_fol_orig") and s["gold_fol_orig"] != s["gold_fol"]:
            ok = True
            try:
                parse(s["gold_fol_orig"])
            except (ParseError, RecursionError):
                ok = False
            items.append({"item_id": f"{s['sid']}:gold_orig", "set": "gold_orig", "sid": s["sid"],
                          "fol": s["gold_fol_orig"], "parse_ok": ok})
    for m in d["mutants"]:
        if m["sid"] in sents:
            items.append({"item_id": m["mid"], "set": "mutant", "sid": m["sid"], "fol": m["fol"], "parse_ok": True,
                          "operator": m["operator"]})
    for rw in d["rewrites"]:
        if rw["sid"] in sents:
            items.append({"item_id": rw["rid"], "set": "rewrite", "sid": rw["sid"], "fol": rw["fol"], "parse_ok": True,
                          "kind": rw["kind"]})
    # prewarm MiniLM cache
    texts = set()
    for it in items:
        if it["parse_ok"]:
            try:
                p = parse(it["fol"])
                texts |= {" ".join(pred_tokens(P)) for P in p.preds} | {" ".join(pred_tokens(c)) for c in p.consts}
            except (ParseError, RecursionError):
                pass
    for ts in tsig.values():
        texts |= {c["span"] for c in ts["concepts"]}
    t0 = time.time()
    prewarm(sorted(t for t in texts if t))
    logger.info(f"MiniLM prewarm {len(texts)} strings in {time.time() - t0:.1f}s")

    # per-sentence text-probe cost for amortisation
    n_real_per_sid = Counter(r["sid"] for r in d["real"])
    rows = []
    aligns = {}
    gold_cache = {}
    for it in items:
        s = sents[it["sid"]]
        ts = tsig[it["sid"]]
        t1 = time.time()
        S, A = None, None
        if it["parse_ok"]:
            try:
                p = parse(it["fol"])
                S = sigs.get(it["fol"])
                if S is not None and "error" in S:
                    S = None
                A = align(p.preds, p.consts, ts["concepts"])
            except (ParseError, RecursionError):
                S, A = None, None
        t_align = time.time() - t1
        if it["sid"] not in gold_cache:
            pg = parse(s["gold_fol"])
            gold_cache[it["sid"]] = (sigs.get(s["gold_fol"]), align(pg.preds, pg.consts, ts["concepts"]))
        Sg, Ag = gold_cache[it["sid"]]
        aligns[it["item_id"]] = A
        probe_cost = ts["usage"]["cost"]
        amort = probe_cost / max(1, n_real_per_sid[it["sid"]])
        sig_secs = (S or {}).get("seconds", 0.0)
        optional = {c["cid"] for c in ts["concepts"] if is_optional(c)}
        variants = ["A1", "A2", "A3", "B5", "B5A2", "A0", "Ccov"] + (["B4"] if it["item_id"] in b4 else [])
        for variant in variants:
            base = "A2" if variant in ("A2", "B5A2") else ("A3" if variant == "A3" else "A1")
            T = text_T(ts, base)
            if variant.startswith("B5"):
                if Sg is None or "error" in Sg:
                    continue
                T = oracle_T(ts, T, Sg, Ag, with_rel=(variant == "B5A2"))
            if variant == "Ccov":
                cv = A["coverage"] if (A is not None and it["parse_ok"]) else None
                res = {"score": 0.5 if cv is None else cv, "raw_score": cv, "covered": cv is not None,
                       "coverage": cv or 0.0, "n_coords": 0, "mismatches": [], "error_type_pred": "none",
                       "why_uncovered": "" if cv is not None else "unparseable"}
            elif variant == "B4":
                Sl = b4[it["item_id"]]
                Sl = None if "error" in Sl else Sl
                res = signature_score(T, Sl, A, variant="A1", parse_ok=it["parse_ok"] and Sl is not None,
                                      optional=optional)
            else:
                res = signature_score(T, S, A, variant=variant, parse_ok=it["parse_ok"] and S is not None,
                                      optional=optional)
            rows.append({"item_id": it["item_id"], "set": it["set"], "sid": it["sid"], "metric": variant,
                         "score": res["score"], "raw_score": res["raw_score"], "covered": res["covered"],
                         "coverage": res["coverage"], "n_coords": res["n_coords"],
                         "error_type_pred": res["error_type_pred"], "why_uncovered": res["why_uncovered"],
                         "mismatches": res["mismatches"][:12],
                         "usd": (0.0 if variant in ("A3", "B5", "B5A2", "A0", "Ccov") else amort) +
                                (b4[it["item_id"]].get("usd", 0.0) if variant == "B4" else 0.0),
                         "usd_per_sentence_probe": 0.0 if variant in ("A3", "B5", "B5A2", "A0", "Ccov") else probe_cost,
                         "seconds": round(sig_secs + t_align, 4),
                         "operator": it.get("operator"), "kind": it.get("kind")})
    out = ROOT / "results" / "screen_scores_signature.jsonl"
    with out.open("w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (ROOT / "results" / "alignments.json").write_text(json.dumps(aligns, ensure_ascii=False))
    logger.info(f"wrote {len(rows)} score rows")

    # in-domain diagnostic: text labels vs gold signature on aligned concepts
    diag = {"llm": Counter(), "marker": Counter()}
    strat = {"llm": defaultdict(Counter), "marker": defaultdict(Counter)}
    for sid, (Sg, Ag) in gold_cache.items():
        ts = tsig[sid]
        if Sg is None or "error" in Sg:
            continue
        for P, a in Ag["preds"].items():
            if a["cid"] is None:
                continue
            sl = Sg["labels"].get(P, "?")
            if a["flip"]:
                sl = FLIP[sl]
            for name, labs in (("llm", ts["llm_labels"]), ("marker", ts["marker"])):
                tl = labs.get(str(a["cid"]))
                if tl is None or tl == "?":
                    continue
                ok = tl == sl
                diag[name]["n"] += 1
                diag[name]["agree"] += ok
                strat[name][tl]["n"] += 1
                strat[name][tl]["agree"] += ok
                strat[name][f"gold={sl}"]["n"] += 1
                strat[name][f"gold={sl}"]["agree"] += ok
    td = {k: {"n": v["n"], "agree_rate": v["agree"] / v["n"] if v["n"] else None,
              "by_label": {lk: {"n": lv["n"], "agree_rate": lv["agree"] / lv["n"] if lv["n"] else None}
                           for lk, lv in strat[k].items()}} for k, v in diag.items()}
    cov = [a["coverage"] for a in (gold_cache[s][1] for s in gold_cache)]
    td["gold_alignment_coverage_mean"] = sum(cov) / len(cov) if cov else None
    (ROOT / "results" / "text_diag.json").write_text(json.dumps(td, indent=1))
    logger.info(f"text diag: llm={td['llm']['agree_rate']} marker={td['marker']['agree_rate']}")
    for m in ("A1", "A2", "A3", "B5"):
        rr = [r for r in rows if r["metric"] == m and r["set"] == "real"]
        gg = [r for r in rows if r["metric"] == m and r["set"] == "gold"]
        logger.info(f"{m}: real covered={sum(r['covered'] for r in rr) / max(1, len(rr)):.3f} "
                    f"gold full-match={sum(1 for r in gg if r['raw_score'] == 1.0) / max(1, len(gg)):.3f} "
                    f"why={Counter(r['why_uncovered'] for r in rr)}")


if __name__ == "__main__":
    main()
