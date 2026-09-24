#!/usr/bin/env python3
"""M5 mechanism ladder + typing, M6 within-sentence recomputation of exp5's partnered pairs, M7 wrong-gold flag.
-> results/m5_ladder_typing.json, results/m6_within_sentence.json, results/m7_goldflag.json"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from dc.common import EXP3, EXP5, RES, WORK, jdump, rj  # noqa: E402
from dc import stats as ST  # noqa: E402
from m0_anchor import load_all, strata  # noqa: E402

VISIBLE = ["added_condition", "dropped_condition", "quantifier_forall_exists", "negation_polarity", "argument_swap",
           "implication_direction_or_only"]
BLIND = ["quantifier_scope", "cardinality_numeric", "connective_and_or"]
LADDER = [("S0_LC_maj_star_L1", "S0_L1"), ("S1_plus_L2", "S1_L2"), ("S2_plus_L3", "S2_L3"), ("S3_plus_DS_eq_DC", "DC")]
TYPE_MAP = {"added_condition": "added", "dropped_condition": "dropped", "quantifier_forall_exists": "forall_exists",
            "implication_direction_or_only": "impl", "negation_polarity": "negation", "argument_swap": "arg_swap"}


def tmap(t):
    return TYPE_MAP.get(t or "", "other")


def partnered(G, gold_dc, b1all, b3):
    """exp5 v2 partnered set (partner_mode='any_faithful', tagmode='primary'): each panel-unfaithful item paired with
    every other item of its sentence labelled faithful (any label source); if none, the gold when
    gold_faithful_final (fallback)."""
    by = defaultdict(list)
    for r in G:
        by[r["sentence_id"]].append(r)
    recs = []
    for r in G:
        if r["y_panel"] != 0:
            continue
        parts = [j for j in by[r["sentence_id"]] if j["item_id"] != r["item_id"] and j["output"] == "faithful"]
        fallback = False
        if not parts and r.get("gold_faithful_final") is True and f"{r['sentence_id']}:GOLD" in gold_dc:
            parts = ["__gold__"]
            fallback = True
        if not parts:
            continue
        rec = {"item_id": r["item_id"], "sid": r["sentence_id"], "w": r["w"], "primary": r["L3_primary_error"],
               "fallback_gold": fallback}
        for m in ("DC", "DC_L2w", "S0_L1", "S1_L2", "S2_L3", "LC_maj", "LC_onecoin", "LC_ds_binary", "B1", "B3nli", "B3cos", "VC"):
            se = r["m"].get(m)
            ds = []
            unc = 0
            for j in parts:
                if j == "__gold__":
                    if m in ("DC", "S0_L1"):
                        sf = gold_dc[f"{r['sentence_id']}:GOLD"].get(m)
                    else:
                        sf = None
                else:
                    sf = j["m"].get(m)
                if se is None or sf is None:
                    unc += 1
                    continue
                ds.append(ST.det(sf, se))
            rec[m] = float(np.mean(ds)) if ds else None
            rec[m + "_uncovered_partners"] = unc
        recs.append(rec)
    return recs


def det_table(recs, metrics, tags):
    tab = {}
    for t in tags:
        R = [x for x in recs if (x["primary"] == t if t not in ("PREDICTED_VISIBLE", "PREDICTED_BLIND") else
                                 (x["primary"] in (VISIBLE if t == "PREDICTED_VISIBLE" else BLIND)))]
        row = {"n": len(R), "descriptive_only": len(R) < 20}
        for m in metrics:
            v = [np.nan if x[m] is None else x[m] for x in R]
            if not R or all(np.isnan(v)):
                continue
            cb = ST.cluster_boot_mean(v, [x["w"] for x in R], [x["sid"] for x in R])
            row[m] = {"det_w": cb["mean"], "ci95": cb["ci"], "n_scored": cb["n"],
                      "n_uncovered": sum(1 for x in R if x[m] is None)}
        tab[t] = row
    return tab


def main():
    G, sc = load_all()
    for r in G:
        s = sc[r["item_id"]]
        for m in ("S1_L2", "S2_L3"):
            r["m"][m] = s.get(m)
    gold_dc = {r["item_id"]: r for r in rj(WORK / "gold_dc_scores.jsonl")}
    P = [r for r in G if r["y_panel"] is not None]
    stt = strata(P)
    # ---------------- M5 ladder
    lad = {}
    prev = None
    for name, m in LADDER:
        blk = {}
        for lab, R, yk, wk in (("panel", P, "y_panel", "w"), ("solver", [r for r in G if r["y_solver"] is not None], "y_solver", None)):
            y = [r[yk] for r in R]
            s = [r["m"][m] for r in R]
            w = [r[wk] for r in R] if wk else None
            blk[lab] = ST.auc_ci(y, s, w, [r["sentence_id"] for r in R], strata(R))
            if prev:
                blk[lab]["delta_vs_prev"] = ST.paired_delta(y, s, [r["m"][prev] for r in R], w, [r["sentence_id"] for r in R], strata(R))
        lad[name] = blk
        prev = m
    recs = partnered(G, gold_dc, None, None)
    tags = VISIBLE + BLIND + ["PREDICTED_VISIBLE"]
    ladm = [m for _, m in LADDER]
    lad_det = det_table(recs, ladm, tags)
    lifts = {}
    for t in VISIBLE:
        row = lad_det.get(t, {})
        if all(m in row for m in ladm):
            lifts[t] = {f"{ladm[i]}->{ladm[i + 1]}": row[ladm[i + 1]]["det_w"] - row[ladm[i]]["det_w"] for i in range(3)}
            lifts[t]["max_step_lift"] = max(lifts[t].values())
    best_t = max(lifts, key=lambda t: lifts[t]["max_step_lift"]) if lifts else None
    # typing (2): dev panel-unfaithful items vs L3_primary_error
    U = [r for r in P if r["y_panel"] == 0]
    tj = {}
    for x in rj(EXP5 / "results" / "llm_baselines.jsonl"):
        if x.get("method") == "TJ" and x.get("error") is None:
            tj[x["unit_id"]] = x
    rowsT = []
    for r in U:
        s = sc[r["item_id"]]
        tr = tmap(r["L3_primary_error"])
        pred = s.get("error_type")
        pc = tmap(pred) if pred not in (None, "none") else "none"
        t = tj.get(r["item_id"])
        tp = tmap(t.get("primary")) if t else None
        rowsT.append({"truth": tr, "dc": pc, "tj": tp, "w": r["w"], "sid": r["sentence_id"]})
    W = sum(x["w"] for x in rowsT)
    maj = Counter()
    for x in rowsT:
        maj[x["truth"]] += x["w"]
    both = [x for x in rowsT if x["tj"] is not None]
    Wb = sum(x["w"] for x in both) or 1
    b01 = sum(1 for x in both if x["dc"] == x["truth"] and x["tj"] != x["truth"])
    b10 = sum(1 for x in both if x["dc"] != x["truth"] and x["tj"] == x["truth"])
    from scipy.stats import binomtest
    typing_real = {"n": len(rowsT), "weighted_top1_DC": sum(x["w"] for x in rowsT if x["dc"] == x["truth"]) / W,
                   "majority_baseline": max(maj.values()) / W, "majority_class": max(maj, key=maj.get),
                   "n_TJ_available": len(both),
                   "weighted_top1_TJ_same_items": sum(x["w"] for x in both if x["tj"] == x["truth"]) / Wb,
                   "weighted_top1_DC_same_items": sum(x["w"] for x in both if x["dc"] == x["truth"]) / Wb,
                   "mcnemar_b01_dc_only": b01, "mcnemar_b10_tj_only": b10,
                   "mcnemar_p": binomtest(b01, b01 + b10, 0.5).pvalue if b01 + b10 else None,
                   "dc_pred_distribution": dict(Counter(x["dc"] for x in rowsT)),
                   "truth_distribution": dict(Counter(x["truth"] for x in rowsT)),
                   "recall_per_class": {c: (sum(1 for x in rowsT if x["truth"] == c and x["dc"] == c) /
                                            max(1, sum(1 for x in rowsT if x["truth"] == c))) for c in set(x["truth"] for x in rowsT)},
                   "note": "DC predicts 'none' when the item is in its sentence's weighted mode (counted as wrong here)"}
    # typing (1): constructed confusion on M1 conf/tok arms
    Pm = [p for p in rj(WORK / "m1_probes.jsonl") if p["kind"] == "M" and p["arm"] in ("conf", "tok") and not p.get("iso_L1")]
    OPT = {"DROP_CONJ": "dropped", "ADD_CONJ": "added", "QUANT": "forall_exists", "IMPL_REV": "impl", "NEG": "negation",
           "ARG_SWAP": "arg_swap"}
    conf = {}
    from sklearn.metrics import f1_score
    for var in ("type_contract", "type_repair"):
        y = [OPT[p["op"]] for p in Pm]
        yh = [(tmap(p.get(var)) if p.get(var) not in (None, "none") else "none") for p in Pm]
        labels = sorted(set(y) | set(yh))
        cmx = {a: dict(Counter(b for yy, b in zip(y, yh) if yy == a)) for a in sorted(set(y))}
        conf[var] = {"accuracy": float(np.mean([a == b for a, b in zip(y, yh)])),
                     "macro_f1": float(f1_score(y, yh, labels=sorted(set(y)), average="macro", zero_division=0)),
                     "recall_per_class": {a: float(np.mean([b == a for yy, b in zip(y, yh) if yy == a])) for a in sorted(set(y))},
                     "confusion": cmx, "n": len(y)}
    jdump({"ladder_auroc": lad, "ladder_within_sentence_detection": lad_det, "step_lifts": lifts,
           "P1_largest_step_lift_type": best_t, "P1_PASS": best_t == "added_condition",
           "typing_constructed_M1": conf, "typing_real_panel_unfaithful": typing_real,
           "P2_PASS": typing_real["weighted_top1_DC"] > typing_real["majority_baseline"]}, RES / "m5_ladder_typing.json")
    # ---------------- M6 within-sentence (exp5 partnered set)
    metrics = ["B1", "B3nli", "B3cos", "LC_maj", "LC_onecoin", "LC_ds_binary", "DC", "DC_L2w", "VC"]
    tab = det_table(recs, metrics, VISIBLE + BLIND + ["PREDICTED_VISIBLE", "PREDICTED_BLIND"])
    exp5 = json.loads((EXP5 / "results" / "analysis.json").read_text())["V2"]["any_faithful"]
    m6 = {"n_errors_with_partner": len(recs), "n_fallback_gold": sum(x["fallback_gold"] for x in recs),
          "exp5_reference": {"n_errors_with_partner": exp5["n_errors_with_partner"], "n_fallback_gold": exp5["n_fallback_gold"],
                             "dropped_condition": exp5["primary"].get("dropped_condition"),
                             "implication_direction_or_only": exp5["primary"].get("implication_direction_or_only")},
          "n_dropped": tab["dropped_condition"]["n"], "n_impl": tab["implication_direction_or_only"]["n"],
          "assert_n_dropped_36": tab["dropped_condition"]["n"] == 36, "assert_n_impl_24": tab["implication_direction_or_only"]["n"] == 24,
          "table_primary": tab,
          "note": "det_w = weighted mean over panel-unfaithful items of mean over partners of 1[s_partner > s_err] + 0.5 ties; "
                  "B1 from exp3 b1_scores (all rows); B3 only where exp3 ran it (uncovered partners counted); gold partner "
                  "(fallback) scored only for DC/S0_L1 (M7 gold scores)."}
    jdump(m6, RES / "m6_within_sentence.json")
    # ---------------- M7 wrong-gold flag
    by = {}
    for r in G:
        by.setdefault(r["sentence_id"], r)
    gs5 = {x["unit_id"]: x for x in rj(EXP5 / "results" / "gold_scores.jsonl")}
    pg5 = {x["sid"]: x for x in rj(EXP5 / "results" / "per_gold.jsonl")}
    rows = []
    for sid, r in by.items():
        g = gold_dc.get(f"{sid}:GOLD")
        if g is None or r.get("gold_faithful_final") is None:
            continue
        p5 = pg5.get(sid, {})
        rows.append({"sid": sid, "y": 1.0 if r["gold_faithful_final"] else 0.0, "DC": g["DC"], "DC_cov": g["DC_cov"],
                     "S0_L1": g["S0_L1"], "corpus": r["corpus"], "tercile": r["complexity_tercile"],
                     "flag_B1": p5.get("flag_B1"), "flag_TJ": p5.get("flag_TJ")})
    y = np.array([x["y"] for x in rows])
    st7 = {x["sid"]: f"{x['corpus']}|{x['tercile']}" for x in rows}
    res7 = {"n_golds": len(rows), "wrong_gold_rate": float(1 - y.mean()),
            "DC_gold_auroc_vs_L0": ST.auc_ci(y, [x["DC"] for x in rows], None, [x["sid"] for x in rows], st7),
            "S0_L1_gold_auroc_vs_L0": ST.auc_ci(y, [x["S0_L1"] for x in rows], None, [x["sid"] for x in rows], st7),
            "coverage_DC": float(np.mean([x["DC_cov"] for x in rows]))}
    # judge-only references (exp5 per_gold flags are 1 - p_faithful)
    for j in ("B1", "TJ"):
        R = [x for x in rows if x[f"flag_{j}"] is not None]
        if len(R) > 20:
            yy = np.array([x["y"] for x in R])
            sj = np.array([1 - x[f"flag_{j}"] for x in R])
            res7[f"{j}_gold_auroc"] = ST.wauc(yy, sj)
            X0 = sj.reshape(-1, 1)
            X1 = np.column_stack([sj, [x["DC"] for x in R]])
            sids = np.array([x["sid"] for x in R])
            p0 = ST.oof_stack(X0, yy, sids)
            p1 = ST.oof_stack(X1, yy, sids)
            b = ST.boot(list(sids), st7, n=ST.NBOOT, seed=3)
            vals = [ST.wauc(yy[ix], p1[ix]) - ST.wauc(yy[ix], p0[ix]) for ix in b]
            res7[f"stack_{j}_plus_DC"] = {"auroc_judge_oof": ST.wauc(yy, p0), "auroc_judge_plus_DC_oof": ST.wauc(yy, p1),
                                          "delta": ST.wauc(yy, p1) - ST.wauc(yy, p0), "ci": ST.ci(vals), "n": len(R)}
    per = {}
    for c in sorted({x["corpus"] for x in rows}):
        R = [x for x in rows if x["corpus"] == c]
        yy = np.array([x["y"] for x in R])
        per[c] = {"n": len(R), "wrong_rate": float(1 - yy.mean()),
                  "DC_auroc": ST.wauc(yy, np.array([x["DC"] for x in R])) if len(set(yy)) > 1 else None}
        if c == "proverqa":
            order = sorted(R, key=lambda x: x["DC"])[:25]
            per[c]["P_at_25_wrong_among_lowest_DC"] = float(np.mean([1 - x["y"] for x in order]))
    res7["per_corpus"] = per
    res7["nearest_neighbour"] = ("Brunello et al., arXiv:2606.02837: LLM-guided relabelling framework directing human "
                                 "reviewers to error-prone NL-FOL instances (v2: 90% accuracy after reviewing <20%)")
    res7["P1_PASS"] = bool(res7["DC_gold_auroc_vs_L0"]["ci"][0] and res7["DC_gold_auroc_vs_L0"]["ci"][0] > 0.5)
    jdump(res7, RES / "m7_goldflag.json")
    print(json.dumps({"ladder": {k: v["panel"]["auroc"] for k, v in lad.items()}, "best_lift": best_t,
                      "typing": {k: typing_real[k] for k in ("weighted_top1_DC", "majority_baseline", "weighted_top1_TJ_same_items")},
                      "m6_n": (m6["n_dropped"], m6["n_impl"]), "m7": res7["DC_gold_auroc_vs_L0"]["auroc"]}, default=str))


if __name__ == "__main__":
    main()
