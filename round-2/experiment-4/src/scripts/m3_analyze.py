#!/usr/bin/env python3
"""M3 analysis -> results/m3_boundary.json (dose curve vs analytic, DC+arb, real shared bias)."""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from dc.common import RES, WORK, jdump, rj  # noqa: E402
from dc import stats as ST  # noqa: E402
from m0_anchor import load_all, strata  # noqa: E402

OPS3 = ["DROP_CONJ", "ADD_CONJ", "QUANT", "IMPL_REV"]


def chosen_index(spec, ans):
    """Index (0/1) into top2 of the cluster the arbiter picks; None if unanswered."""
    if ans is None:
        return None
    return 0 if spec["A_value"] == ans else 1


def main():
    D = rj(WORK / "m3_dose.jsonl")
    A = json.loads((WORK / "m3_arbiter_answers.json").read_text())
    out = {"a_dose": {}, "b_arbiter": {}, "c_real": {}}
    # ---------------- (a)
    for order in ("random", "faithful_first"):
        blk = {}
        for k in (0, 2, 4, 6, 8):
            rowk = {}
            for op in OPS3 + ["pooled"]:
                R = [(d["sid"], r) for d in D for r in d["rows"] if r["order"] == order and r["k"] == k
                     and (op == "pooled" or d["op"] == op)]
                if not R:
                    continue
                g = [s for s, _ in R]
                one = np.ones(len(R))
                rowk[op] = {"det_DC": ST.cluster_boot_mean([r["det"] for _, r in R], one, g),
                            "det_analytic": ST.cluster_boot_mean([r["det_analytic"] for _, r in R], one, g),
                            "det_DC_L2": ST.cluster_boot_mean([r["det_L2"] for _, r in R], one, g),
                            "mean_dev_obs_minus_analytic": float(np.mean([r["det"] - r["det_analytic"] for _, r in R])),
                            "share_copies_recognised_EQUIV": float(np.mean([x for _, r in R for x in r["copy_equiv_M"]]))
                            if any(r["copy_equiv_M"] for _, r in R) else None,
                            "n": len(R)}
            blk[f"k={k}"] = rowk
        out["a_dose"][order] = blk
    pooled = out["a_dose"]["random"]
    d = {k: pooled[f"k={k}"]["pooled"]["det_DC"]["mean"] for k in (0, 2, 4, 6, 8)}
    out["a_dose"]["P1"] = {"det": d, "PASS": bool(d[0] >= 0.9 and d[2] >= 0.9 and 0.3 <= d[4] <= 0.7 and d[6] <= 0.3 and d[8] <= 0.3),
                           "parts": {"k<=2 >= 0.9": d[0] >= 0.9 and d[2] >= 0.9, "k=4 in [0.3,0.7]": 0.3 <= d[4] <= 0.7,
                                     "k>=6 <= 0.3": d[6] <= 0.3 and d[8] <= 0.3}}
    aud = [a for dd in D for a in dd.get("audit", [])]
    out["a_dose"]["inheritance_audit"] = {"n": len(aud), "match_rate": float(np.mean([a["match"] for a in aud])) if aud else None}
    # ---------------- (b) arbiter on constructed
    ans = A["constructed"]
    recs = []
    for dd in D:
        for sp in dd["arb"]:
            rec = {"sid": dd["sid"], "op": dd["op"], "k": sp["k"], "oracle_vocab": sp.get("oracle_vocab", False),
                   "abstain": sp.get("abstain"), "DC_F": sp.get("DC_F"), "DC_M": sp.get("DC_M")}
            a = ans.get(sp.get("prompt")) if sp.get("prompt") else None
            ci = chosen_index(sp, a) if sp.get("prompt") else None
            rec["answered"] = ci is not None
            if ci is not None:
                rec["F_chosen"] = bool(sp["F_in"][ci])
                rec["M_chosen"] = bool(sp["M_in"][ci])
                rec["F_in_top2"] = any(sp["F_in"])
                arbF = 0.5 * sp["DC_F"] + 0.5 * rec["F_chosen"]
                arbM = 0.5 * sp["DC_M"] + 0.5 * rec["M_chosen"]
            else:
                arbF, arbM = sp.get("DC_F"), sp.get("DC_M")
            rec["det_DC"] = ST.det(sp.get("DC_F"), sp.get("DC_M")) if sp.get("DC_F") is not None else np.nan
            rec["det_arb"] = ST.det(arbF, arbM) if arbF is not None else np.nan
            recs.append(rec)
    for k in (4, 6, 8):
        for tag, f in (("all", lambda r: True), ("no_oracle_vocab", lambda r: not r["oracle_vocab"])):
            R = [r for r in recs if r["k"] == k and f(r)]
            if not R:
                continue
            g = [r["sid"] for r in R]
            one = np.ones(len(R))
            Ra = [r for r in R if r["answered"] and r.get("F_in_top2")]
            out["b_arbiter"][f"k={k}|{tag}"] = {
                "n": len(R), "abstain_rate": float(np.mean([not r["answered"] for r in R])),
                "abstain_reasons": dict(Counter(r["abstain"] for r in R if r["abstain"])),
                "det_DC": ST.cluster_boot_mean([r["det_DC"] for r in R], one, g),
                "det_DC_arb": ST.cluster_boot_mean([r["det_arb"] for r in R], one, g),
                "arbiter_accuracy_F_chosen": float(np.mean([r["F_chosen"] for r in Ra])) if Ra else None,
                "arbiter_accuracy_per_op": {op: (float(np.mean([r["F_chosen"] for r in Ra if r["op"] == op]))
                                                 if any(r["op"] == op for r in Ra) else None) for op in OPS3},
                "oracle_vocab_share": float(np.mean([r["oracle_vocab"] for r in R]))}
    b = out["b_arbiter"]
    out["b_arbiter"]["P2"] = {f"k={k}": (b.get(f"k={k}|all", {}).get("det_DC_arb", {}).get("mean"),
                                         b.get(f"k={k}|all", {}).get("det_DC", {}).get("mean")) for k in (4, 6, 8)}
    out["b_arbiter"]["P2_PASS"] = all((v[0] or 0) > (v[1] or 0) for v in out["b_arbiter"]["P2"].values())
    # ---------------- (c) real shared bias
    G, sc = load_all()
    W = json.loads((ROOT / "frozen_dc_config.json").read_text())["weights"]
    by = defaultdict(list)
    for r in G:
        by[r["sentence_id"]].append(r)
    real = {x["sid"]: x for x in rj(WORK / "m3_real.jsonl")}
    ansr = A["real"]
    rows, sent = [], {}
    for sid, rs in by.items():
        rs = sorted(rs, key=lambda r: r["system"])
        x = real.get(sid)
        if x is None:
            continue
        cl = x["cl"]
        for r in rs:
            r["lab"] = r["y_panel"] if r["y_panel"] is not None else r["y_solver"]
        cl_lab = {}
        for c in set(cl):
            if c < 0:
                continue
            mem = [r for r, cc in zip(rs, cl) if cc == c]
            pan = [r["y_panel"] for r in mem if r["y_panel"] is not None]
            sol = [r["y_solver"] for r in mem if r["y_solver"] is not None]
            if pan:
                cl_lab[c] = 0 if np.mean(pan) < 0.5 else 1
            elif sol:
                cl_lab[c] = 0 if np.mean(sol) < 0.5 else 1
        mass = {int(k): v for k, v in x["mass"].items()}
        tot = sum(mass.values()) or 1
        wrong = sum(v for c, v in mass.items() if cl_lab.get(c) == 0) / tot
        mode = max(mass, key=lambda c: mass[c]) if mass else None
        g0 = rs[0]
        chosen = None
        if x.get("prompt"):
            a = ansr.get(x["prompt"])
            ci = chosen_index(x, a)
            if ci is not None:
                chosen = x["top2"][ci]
        sent[sid] = {"wrong_conc": wrong, "mode_unfaithful": cl_lab.get(mode) == 0, "chosen": chosen,
                     "top2": x.get("top2"), "cl_lab": cl_lab,
                     "proverqa_dropped_gold": g0["corpus"] == "proverqa" and "dropped" in str(g0.get("gold_audit_primary_error") or ""),
                     "ambiguous": bool(g0.get("sentence_ambiguous"))}
        for r, c in zip(rs, cl):
            dcv = r["m"]["DC"]
            arb = dcv if chosen is None else 0.5 * dcv + 0.5 * float(c == chosen)
            r["m"]["DC_arb"] = arb
            r["cl"] = c
    # within-sentence concordance vs wrong_conc
    pairs = []
    for sid, rs in by.items():
        if sid not in sent:
            continue
        pos = [r for r in rs if r.get("lab") == 1]
        neg = [r for r in rs if r.get("lab") == 0]
        for a in pos:
            for bq in neg:
                pairs.append({"sid": sid, "wc": sent[sid]["wrong_conc"], "det": ST.det(a["m"]["DC"], bq["m"]["DC"]),
                              "det_arb": ST.det(a["m"]["DC_arb"], bq["m"]["DC_arb"])})
    bins = [(0, 0.25), (0.25, 0.5), (0.5, 0.75), (0.75, 1.01)]
    binres = {}
    for lo, hi in bins:
        R = [p for p in pairs if lo <= p["wc"] < hi]
        binres[f"[{lo},{min(hi, 1.0)})"] = {"DC": ST.cluster_boot_mean([p["det"] for p in R], np.ones(len(R)), [p["sid"] for p in R]),
                                            "DC_arb": ST.cluster_boot_mean([p["det_arb"] for p in R], np.ones(len(R)), [p["sid"] for p in R]),
                                            "n_pairs": len(R), "n_sentences": len({p["sid"] for p in R})}
    from sklearn.linear_model import LogisticRegression

    def slope(P):
        X = np.array([[p["wc"]] for p in P] * 2)
        y = np.array([1] * len(P) + [0] * len(P))
        w = np.array([p["det"] for p in P] + [1 - p["det"] for p in P]) + 1e-9
        return float(LogisticRegression(C=1e6, max_iter=1000).fit(X, y, sample_weight=w).coef_[0][0])
    s0 = slope(pairs)
    byp = defaultdict(list)
    for p in pairs:
        byp[p["sid"]].append(p)
    keys = list(byp)
    rng = np.random.default_rng(13)
    bs = []
    for _ in range(500):
        pick = rng.integers(0, len(keys), len(keys))
        P = [p for j in pick for p in byp[keys[j]]]
        try:
            bs.append(slope(P))
        except ValueError:
            continue
    top = binres["[0.75,1.0)"]["DC"]["mean"]
    out["c_real"] = {"bins": binres, "logistic_slope_det_on_wrong_conc": s0, "slope_ci": ST.ci(bs), "n_boot_slope": len(bs),
                     "n_pairs": len(pairs),
                     "n_sentences_mode_unfaithful": sum(v["mode_unfaithful"] for v in sent.values()),
                     "n_proverqa_dropped_gold": sum(v["proverqa_dropped_gold"] for v in sent.values()),
                     "n_ambiguous": sum(v["ambiguous"] for v in sent.values()),
                     "P3_PASS": bool(s0 < 0 and (ST.ci(bs)[1] or 0) < 0 and top is not None and top < 0.5)}
    # subsets
    sub = {}
    for name, f in (("mode_unfaithful", lambda v: v["mode_unfaithful"]), ("proverqa_dropped_gold", lambda v: v["proverqa_dropped_gold"]),
                    ("ambiguous", lambda v: v["ambiguous"]), ("wrong_conc>=0.5", lambda v: v["wrong_conc"] >= 0.5)):
        S = {s for s, v in sent.items() if f(v)}
        R = [p for p in pairs if p["sid"] in S]
        sub[name] = {"n_sentences": len(S), "n_pairs": len(R),
                     "DC_within_det": ST.cluster_boot_mean([p["det"] for p in R], np.ones(len(R)), [p["sid"] for p in R]),
                     "DC_arb_within_det": ST.cluster_boot_mean([p["det_arb"] for p in R], np.ones(len(R)), [p["sid"] for p in R])}
    out["c_real"]["subsets"] = sub
    # DC+arb AUROC vs DC
    au = {}
    for lab, yk, wk in (("panel", "y_panel", "w"), ("solver", "y_solver", None)):
        for sset, f in (("all", lambda r: True), ("shared_bias_wrong_conc>=0.5", lambda r: sent.get(r["sentence_id"], {}).get("wrong_conc", 0) >= 0.5)):
            R = [r for r in G if r[yk] is not None and f(r) and "DC_arb" in r["m"]]
            y = [r[yk] for r in R]
            w = [r[wk] for r in R] if wk else None
            ss = [r["sentence_id"] for r in R]
            au[f"{lab}|{sset}"] = {"DC": ST.auc_ci(y, [r["m"]["DC"] for r in R], w, ss, strata(R)),
                                   "DC_arb": ST.auc_ci(y, [r["m"]["DC_arb"] for r in R], w, ss, strata(R)),
                                   "delta": ST.paired_delta(y, [r["m"]["DC_arb"] for r in R], [r["m"]["DC"] for r in R], w, ss, strata(R))}
    out["c_real"]["DC_arb_auroc"] = au
    agree = [v for v in sent.values() if v["chosen"] is not None and v["top2"] and len(v["top2"]) == 2
             and {v["cl_lab"].get(v["top2"][0]), v["cl_lab"].get(v["top2"][1])} == {0, 1}]
    out["c_real"]["arbiter_agreement_with_labels"] = {
        "n_sentences_top2_label_split": len(agree),
        "agreement": float(np.mean([v["cl_lab"].get(v["chosen"]) == 1 for v in agree])) if agree else None,
        "n_answered": sum(v["chosen"] is not None for v in sent.values()),
        "n_with_two_clusters": sum(1 for v in sent.values() if v["top2"] and len(v["top2"]) == 2)}
    ledger = [json.loads(l) for l in (ROOT / "cost_ledger.jsonl").read_text().splitlines() if l.strip()]
    out["cost_usd_arbiter"] = sum(x["cost_usd"] for x in ledger if x["phase"].startswith("M3"))
    out["n_calls_arbiter"] = sum(1 for x in ledger if x["phase"].startswith("M3"))
    jdump(out, RES / "m3_boundary.json")
    print(json.dumps({"dose": d, "P1": out["a_dose"]["P1"]["PASS"], "arb": out["b_arbiter"]["P2"],
                      "slope": s0, "slope_ci": ST.ci(bs), "bins": {k: v["DC"]["mean"] for k, v in binres.items()},
                      "arb_agree": out["c_real"]["arbiter_agreement_with_labels"]}, default=str))


if __name__ == "__main__":
    main()
