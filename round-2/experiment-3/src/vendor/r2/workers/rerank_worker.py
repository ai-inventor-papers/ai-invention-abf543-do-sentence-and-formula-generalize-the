#!/usr/bin/env python3
"""S6 SCREEN RE-RANK under the dataset's AUDITED screen labels (pre-registered iter-1 rule, Arm A analyze.SELECTION_RULE).

Runs in its own interpreter. Each arm's analysis code is loaded under a unique module name with importlib (Arm A
vendor/armA/analyze.py -> `armA_analyze`, Arm B vendor/armB/src/analysis.py -> `armB_analysis`) so that the iter-1
G3 increment code is used verbatim: Arm A `increment` (5-fold x 5-shuffle sentence-grouped OOF logistic, Boot) and
Arm B `oof_delta` (GroupKFold OOF logistic, cluster_boot).

Join: screen_gold_audit rows (metadata_sentence_id = sha1(norm sentence)[:10], metadata_item_id = sid:logiclm_<sys>)
to each arm's screen real items (sid = sha1[:10] of the same normalisation, system in {gpt-3.5-turbo, gpt-4,
text-davinci-003}); the join is verified by normalised sentence equality. Keep metadata_in_screen_first300; exclude
stories 87/105/106/173 (Arm A premise-zip misalignment). y_aud = faithful 1 / unfaithful 0 ('unknown' excluded).
NOTE: y_aud is still solver equivalence against audited gold, so this re-rank cannot test LC's checker circularity.
"""
from __future__ import annotations

import importlib.util
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
A = Path("../../../../../../round-1/experiment-1/src")
B = Path("../../../../../../round-1/experiment-2/src")
EXCL_STORIES = {87, 105, 106, 173}
ARM_METRICS = {"A": ["A1", "A2", "A3"], "B": ["TVJT", "NLI_deberta", "LC_onecoin"]}
CONTROLS = {"A": ["A0", "Ccov"], "B": []}


def load_mod(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def jl(p):
    return [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()]


def norm(s: str) -> str:
    s = re.sub(r"[^\w\s]", "", (s or "").lower())
    return " ".join(s.split())


def main():
    aA = load_mod("armA_analyze", ROOT / "vendor" / "armA" / "analyze.py")
    aB = load_mod("armB_analysis", ROOT / "vendor" / "armB" / "src" / "analysis.py")
    frame = [json.loads(x) for x in (ROOT / "work" / "frame.jsonl").read_text().splitlines() if x.strip()]
    SA = [r for r in frame if r["fold"] == "screen_gold_audit"]
    sa_key = {}
    for r in SA:
        sysn = r["system"].replace("logiclm_", "")
        sa_key[(r["sentence_id"], sysn)] = r
    # ---------------- Arm A frame
    dA = json.loads((A / "data" / "screen_set.json").read_text())
    sentA = {s["sid"]: s for s in dA["sentences"]}
    scA = pd.DataFrame([r for r in jl(A / "results" / "screen_scores.jsonl") if r["set"] == "real"])
    pvA = scA.pivot_table(index="item_id", columns="metric", values="score", aggfunc="first")
    cvA = scA.pivot_table(index="item_id", columns="metric", values="covered", aggfunc="first")
    rowsA = []
    for r in dA["real"]:
        s = sentA[r["sid"]]
        rowsA.append({"item_id": r["item_id"], "sid": r["sid"], "system": r["system"], "parse_ok": float(bool(r["parse_ok"])),
                      "story": int(s["story_id"]) if s.get("story_id") is not None else None, "nl": s["nl"],
                      "tercile_arm": s.get("tercile"), "y_iter1": {True: 1, False: 0}.get(r.get("correct"))})
    FA = pd.DataFrame(rowsA).set_index("item_id").join(pvA, how="left")
    # ---------------- Arm B frame
    dB = json.loads((B / "data" / "screen_set.json").read_text())
    sentB = {s["sid"]: s for s in dB["sentences"]}
    scB = pd.DataFrame([r for r in jl(B / "results" / "screen_scores.jsonl") if r["item_kind"] == "real"])
    pvB = scB.pivot_table(index="item_id", columns="metric", values="score", aggfunc="first")
    cvB = scB.pivot_table(index="item_id", columns="metric", values="covered", aggfunc="first")
    rowsB = []
    for r in dB["real_items"]:
        s = sentB[r["sid"]]
        rowsB.append({"item_id": r["item_id"], "sid": r["sid"], "system": r["system"], "parse_ok": float(bool(r["parse_ok"])),
                      "nl": s["nl"], "story": int(r["example_k"]) if r.get("example_k") is not None else None, "tercile_arm": s.get("tercile"),
                      "y_iter1": {"correct": 1, "incorrect": 0}.get(r.get("L_bij"))})
    FB = pd.DataFrame(rowsB).set_index("item_id").join(pvB, how="left")
    out = {"note_circularity": "y_aud is solver equivalence vs AUDITED gold: this re-rank cannot remove LC's "
                               "checker circularity (only held-out panel tests (a)-(d) address it)",
           "rule": aA.SELECTION_RULE, "excluded_stories": sorted(EXCL_STORIES), "arms": {}}
    joined = {}
    for arm, F, cov in (("A", FA, cvA), ("B", FB, cvB)):
        recs, unmatched, mism = [], [], 0
        story_by_sid = {s["sid"]: s.get("story_id") for s in dA["sentences"]}
        for iid, r in F.iterrows():
            k = (r["sid"], r["system"])
            sa = sa_key.get(k)
            if sa is None:
                unmatched.append(iid)
                continue
            if norm(sa["sentence"]) != norm(r["nl"]):
                mism += 1
            st = r.get("story") if arm == "B" else story_by_sid.get(r["sid"])
            st = None if st is None or (isinstance(st, float) and math.isnan(st)) else st
            recs.append({**r.to_dict(), "item_id": iid, "in300": bool(sa["in_screen_first300"]),
                         "story_A": int(st) if st is not None else None, "out": sa["output"]})
        J = pd.DataFrame(recs)
        n_join = len(J)
        J = J[J["in300"]]
        n300 = len(J)
        J = J[~J["story_A"].isin(EXCL_STORIES)]
        n_excl = n300 - len(J)
        n_unknown = int((J["out"] == "unknown").sum())
        J = J[J["out"] != "unknown"].copy()
        J["y"] = (J["out"] == "faithful").astype(int)
        J["y_aud"] = J["y"]
        info = {"n_arm_real": len(F), "n_joined": n_join, "join_rate": n_join / len(F), "n_unmatched": len(unmatched),
                "unmatched_examples": unmatched[:10], "sentence_text_mismatch": mism, "n_in_first300": n300,
                "n_excluded_stories": n_excl, "n_unknown_label_excluded": n_unknown, "n_final": len(J),
                "label_agreement_iter1_vs_audited": float((J["y_iter1"] == J["y"]).mean())}
        joined[arm] = J
        out["arms"][arm] = {"join": info}
    iter1 = json.loads((A / "results" / "summary.json").read_text())
    vB = json.loads((B / "results" / "verdict.json").read_text())
    anB = json.loads((B / "results" / "analysis.json").read_text())

    def g2_copy(arm, m):
        if arm == "A":
            v = iter1["summary"].get(m, {}).get("G2_false_alarm")
            return {"FA_absolute_iter1": v, "FA_paired_absdiff_gt_0.2": None,
                    "pass": v is not None and v <= 0.10, "definition": "share of solver-verified rewrites scored below "
                                                                         "the Youden threshold (Arm A absolute)"}
        if m == "LC_onecoin":
            return {"FA_absolute_iter1": "N/A", "pass": True, "definition": "N/A (agreement metric, not a function of one "
                                                                             "formula's rewrites)"}
        g = anB["metrics"].get(m, {}).get("G2") or {}
        return {"FA_absolute_iter1": g.get("FA_at_tau"), "FA_paired_absdiff_gt_0.2": g.get("FA_paired_absdiff_gt_0.2"),
                "pass": g.get("FA_at_tau") is not None and g["FA_at_tau"] <= 0.10,
                "definition": "share of rewrites below the gold-vs-mutant Youden tau* (Arm B)"}

    def evaluate(arm, J, metric, ycol, cov_tab):
        df = J.copy()
        df["y"] = df[ycol].astype(int)
        df[metric] = df[metric].fillna(0.5)
        b1 = "B1"
        df[b1] = df[b1].fillna(0.5)
        cov = float(df["item_id"].map(cov_tab[metric] if metric in cov_tab else pd.Series(dtype=float))
                    .fillna(False).astype(bool).mean())
        auc = aB.auc(df["y"].values, df[metric].values)
        top_mask = df["tercile_arm"].isin([2, "top"])
        top = aB.auc(df.loc[top_mask, "y"].values, df.loc[top_mask, metric].values)
        if arm == "A":
            boot = aA.Boot(df["sid"].values)
            inc = aA.increment(df.reset_index(drop=True), ["B1", "parse_ok"], metric, boot)
            g3 = {"delta": inc["delta_auroc"], "ci": inc["ci95"], "pass": inc["passes"], "code": "Arm A analyze.increment"}
        else:
            df["_pok"] = df["parse_ok"]
            r = aB.oof_delta(df.reset_index(drop=True), ["B1", "_pok", metric], ["B1", "_pok"])
            g3 = {"delta": r["delta"], "ci": r["ci"], "pass": r["pass"], "code": "Arm B analysis.oof_delta"}
        g2 = g2_copy(arm, metric)
        gates = {"G1": cov >= 0.70, "G2": g2["pass"], "G3": bool(g3["pass"]), "G4": bool(auc >= 0.65)}
        return {"auroc": auc, "top_tercile_auroc": top, "n_top": int(top_mask.sum()), "G1_coverage": cov, "G2": g2,
                "G3": g3, "gates": gates, "survives": all(gates.values())}

    def rank(res: dict, scores: pd.DataFrame) -> dict:
        surv = [m for m, r in res.items() if r["survives"]]
        v = {"survivors": surv}
        if surv:
            ranked = sorted(surv, key=lambda m: -res[m]["top_tercile_auroc"])
            v["ranking_top_tercile"] = [(m, res[m]["top_tercile_auroc"]) for m in ranked]
            if len(ranked) == 1 or res[ranked[0]]["top_tercile_auroc"] - res[ranked[1]]["top_tercile_auroc"] >= 0.03:
                v.update(outcome="winner", winner=ranked[0])
            else:
                rho = float(scores[[ranked[0], ranked[1]]].fillna(0.5).corr(method="spearman").iloc[0, 1])
                v.update(outcome="pair" if rho < 0.5 else "winner", winner=ranked[0] if rho >= 0.5 else None,
                         pair=ranked[:2] if rho < 0.5 else None, pair_score_correlation=rho)
        else:
            deltas = {m: r["G3"]["delta"] for m, r in res.items() if r["G3"]["delta"] is not None}
            best = max(deltas, key=deltas.get) if deltas else None
            if best is not None and deltas[best] >= 0.03:
                v.update(outcome="advance_without_survivor", winner=best)
            else:
                v.update(outcome="null", winner=None)
            v["delta_point_estimates"] = deltas
        return v
    cov_tabs = {"A": cvA, "B": cvB}
    for arm in ("A", "B"):
        J = joined[arm]
        per = {}
        for lab in ("y_iter1", "y_aud"):
            JJ = J[J[lab].notna()]
            res = {m: evaluate(arm, JJ, m, lab, cov_tabs[arm]) for m in ARM_METRICS[arm] + CONTROLS[arm]}
            per[lab] = {"metrics": res, "verdict": rank({m: res[m] for m in ARM_METRICS[arm]}, JJ)}
        out["arms"][arm]["per_label"] = per
        out["arms"][arm]["ranking_before_iter1_reported"] = (
            iter1["verdict"] if arm == "A" else vB)
    # ---------------- joint ranking on the items both arms share (governing)
    JA = joined["A"].set_index(["sid", "system"])
    JB = joined["B"].set_index(["sid", "system"])
    common = JA.index.intersection(JB.index)
    JAc, JBc = JA.loc[common].reset_index(), JB.loc[common].reset_index()
    joint = {"n_shared": len(common)}
    for lab in ("y_iter1_armB", "y_aud"):
        res = {}
        for arm, JJ in (("A", JAc), ("B", JBc)):
            JJ = JJ.copy()
            if lab == "y_iter1_armB":
                JJ["lab"] = JBc["y_iter1"].values
            else:
                JJ["lab"] = JJ["y_aud"]
            JJ = JJ[JJ["lab"].notna()]
            for m in ARM_METRICS[arm]:
                res[m] = evaluate(arm, JJ, m, "lab", cov_tabs[arm])
        allsc = pd.concat([JAc[ARM_METRICS["A"]], JBc[ARM_METRICS["B"]]], axis=1)
        joint[lab] = {"metrics": res, "verdict": rank(res, allsc)}
    out["joint"] = joint
    before = joint["y_iter1_armB"]["verdict"]
    after = joint["y_aud"]["verdict"]
    out["ranking_before"] = before
    out["ranking_after"] = after
    out["changed"] = (before.get("outcome"), before.get("winner"), before.get("pair")) != (
        after.get("outcome"), after.get("winner"), after.get("pair"))
    out["governing_outcome"] = {"outcome": after.get("outcome"), "winner": after.get("winner"), "pair": after.get("pair"),
                                "rule": "re-applied with the dataset's audited screen labels; if the ranking changes, "
                                        "the audited ranking governs"}
    (ROOT / "results" / "screen_rerank.json").write_text(json.dumps(out, indent=1, default=lambda o: (
        None if isinstance(o, float) and math.isnan(o) else (o.item() if hasattr(o, "item") else str(o)))))
    print(json.dumps({"before": before, "after": after, "changed": out["changed"],
                      "join": {a: out["arms"][a]["join"] for a in ("A", "B")}}, default=str)[:3000])


if __name__ == "__main__":
    main()
