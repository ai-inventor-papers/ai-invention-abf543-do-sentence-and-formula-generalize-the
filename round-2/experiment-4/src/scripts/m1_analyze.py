#!/usr/bin/env python3
"""M1 analysis -> results/m1_confound.json.
(a) constructed: AUROC(F vs M) per arm {conf, tok, syn} for DC, DC_L2w, S0_L1, S2_L3, LC_maj*, VC, B1; per-operator
    (non-iso primary, iso separately); arm gaps with paired sentence bootstrap (95% and 90% CI); CROSSED AUROC
    (F_tok vs M_conf); within-sentence detection per arm.
(b) real dev: DC AUROC within VC quintiles; cross-fitted sentence-grouped ΔAUROC of DC over [B1, parse_ok, VC] and
    [B1, parse_ok, VC, LC_maj] (exp3 oof_stack, 5 folds x 5 repeats; sentence bootstrap of the OOF AUROC gap)."""
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dc.common import RES, WORK, jdump, rj  # noqa: E402
from dc import stats as ST  # noqa: E402
sys.path.insert(0, str(ROOT / "scripts"))
from m0_anchor import load_all, strata  # noqa: E402

METRICS = ["DC", "DC_L2w", "S0_L1", "S2_L3", "LC_maj_star", "VC", "B1"]
OPS = ["DROP_CONJ", "ADD_CONJ", "QUANT", "IMPL_REV", "NEG", "ARG_SWAP"]
NB = ST.NBOOT


def sboot(sids, n=NB, seed=0):
    by = defaultdict(list)
    for i, s in enumerate(sids):
        by[s].append(i)
    arrs = [np.array(v) for v in by.values()]
    rng = np.random.default_rng(seed)
    return [np.concatenate([arrs[j] for j in rng.integers(0, len(arrs), len(arrs))]) for _ in range(n)]


def auc_set(F, M, m, boots_seed=0):
    """AUROC F (positive) vs M (negative) with a sentence bootstrap."""
    R = [r for r in F + M if r.get(m) is not None]
    if not R or len({r["kind"] for r in R}) < 2:
        return {"auroc": None, "n_F": len(F), "n_M": len(M)}
    y = np.array([1.0 if r["kind"] == "F" else 0.0 for r in R])
    s = np.array([r[m] for r in R], float)
    sid = [r["sid"] for r in R]
    bs = sboot(sid, seed=boots_seed)
    vals = [ST.wauc(y[ix], s[ix]) for ix in bs]
    return {"auroc": ST.wauc(y, s), "ci": ST.ci(vals), "ci90": [float(np.nanpercentile(vals, 5)),
                                                                     float(np.nanpercentile(vals, 95))],
            "n_F": int(y.sum()), "n_M": int((1 - y).sum()), "_boot": vals}


def strip(d):
    return {k: v for k, v in d.items() if not k.startswith("_")}


def main():
    P = rj(WORK / "m1_probes.jsonl")
    b1 = {(r["sid"], r["arm"], r["kind"], r["op"]): r for r in rj(WORK / "m1_b1.jsonl")}
    for p in P:
        x = b1.get((p["sid"], p["arm"], p["kind"], p["op"]))
        p["B1"] = x["B1"] if x else None
    info = json.loads((WORK / "m1_build_info.json").read_text())
    out = {"build": info, "arms": {}, "per_operator": {}, "gaps": {}, "crossed": {}, "within_sentence": {}}
    # paired set: (sid, op) with non-iso, non-fresh mutants present in all 3 arms
    have = defaultdict(set)
    for p in P:
        if p["kind"] == "M" and not p.get("iso_L1") and not p.get("fresh_pred"):
            have[(p["sid"], p["op"])].add(p["arm"])
    paired = {k for k, v in have.items() if v == {"conf", "tok", "syn"}}
    sids_ok = {k[0] for k in paired}
    for arm in ("conf", "tok", "syn"):
        F = [p for p in P if p["arm"] == arm and p["kind"] == "F" and p["sid"] in sids_ok]
        M = [p for p in P if p["arm"] == arm and p["kind"] == "M" and (p["sid"], p["op"]) in paired]
        Mall = [p for p in P if p["arm"] == arm and p["kind"] == "M" and not p.get("iso_L1")]
        Fall = [p for p in P if p["arm"] == arm and p["kind"] == "F"]
        out["arms"][arm] = {m: strip(auc_set(F, M, m)) for m in METRICS}
        out["arms"][arm + "_all_noniso_incl_fresh"] = {m: strip(auc_set(Fall, Mall, m)) for m in METRICS}
        for op in OPS:
            for iso in (False, True):
                Mo = [p for p in P if p["arm"] == arm and p["kind"] == "M" and p["op"] == op and bool(p.get("iso_L1")) == iso]
                if not Mo:
                    continue
                sid_o = {p["sid"] for p in Mo}
                Fo = [p for p in Fall if p["sid"] in sid_o]
                blk = {m: strip(auc_set(Fo, Mo, m)) for m in METRICS}
                # within-sentence detection
                fs = {p["sid"]: p for p in Fo}
                for m in METRICS:
                    v = [ST.det(fs[p["sid"]].get(m), p.get(m)) for p in Mo if p["sid"] in fs]
                    blk[m]["within_det"] = ST.cluster_boot_mean(v, np.ones(len(v)), [p["sid"] for p in Mo if p["sid"] in fs])
                blk["n"] = len(Mo)
                blk["descriptive_only"] = len(Mo) < 40
                out["per_operator"][f"{arm}|{op}|{'iso' if iso else 'noniso'}"] = blk
        fs = {p["sid"]: p for p in F}
        out["within_sentence"][arm] = {m: ST.cluster_boot_mean([ST.det(fs[p["sid"]].get(m), p.get(m)) for p in M],
                                                               np.ones(len(M)), [p["sid"] for p in M]) for m in METRICS}
    # gaps (paired: same sentences, same ops) and crossed
    for m in METRICS:
        a = {arm: auc_set([p for p in P if p["arm"] == arm and p["kind"] == "F" and p["sid"] in sids_ok],
                          [p for p in P if p["arm"] == arm and p["kind"] == "M" and (p["sid"], p["op"]) in paired], m)
             for arm in ("conf", "tok", "syn")}
        g = {}
        for other in ("tok", "syn"):
            if a["conf"]["auroc"] is None or a[other]["auroc"] is None:
                continue
            d = np.array(a["conf"]["_boot"]) - np.array(a[other]["_boot"])
            g[f"conf_minus_{other}"] = {"gap": a["conf"]["auroc"] - a[other]["auroc"], "ci95": ST.ci(d),
                                        "ci90": [float(np.nanpercentile(d, 5)), float(np.nanpercentile(d, 95))]}
        out["gaps"][m] = g
        Ft = [p for p in P if p["arm"] == "tok" and p["kind"] == "F" and p["sid"] in sids_ok]
        Mc = [p for p in P if p["arm"] == "conf" and p["kind"] == "M" and (p["sid"], p["op"]) in paired]
        out["crossed"][m] = strip(auc_set(Ft, Mc, m))
    # predictions
    dcg = out["gaps"]["DC"]
    vcg = out["gaps"]["VC"]
    pr = {}
    pr["P1_DC_arm_gap"] = {"gaps": dcg, "PASS": all(abs(v["gap"]) < 0.02 for v in dcg.values()),
                           "equivalent_within_0.03": all(-0.03 <= v["ci90"][0] and v["ci90"][1] <= 0.03 for v in dcg.values())}
    pr["P2_DC_crossed"] = {"auroc": out["crossed"]["DC"]["auroc"], "PASS": (out["crossed"]["DC"]["auroc"] or 0) >= 0.85}
    pr["P3_VC_gap"] = {"gap": vcg.get("conf_minus_tok", {}).get("gap"),
                       "PASS": (vcg.get("conf_minus_tok", {}).get("gap") or 0) > 0.2}
    pr["P4_VC_crossed"] = {"auroc": out["crossed"]["VC"]["auroc"], "PASS": (out["crossed"]["VC"]["auroc"] or 1) < 0.5}
    iso = out["per_operator"].get("tok|IMPL_REV|iso", {})
    if iso:
        wd = iso["DC"]["within_det"]
        pr["P5_iso_blind_spot"] = {"within_det": wd, "n": iso["n"],
                                   "PASS": wd["ci"][0] is not None and wd["ci"][0] <= 0.5 <= wd["ci"][1]}
    d3 = out["per_operator"].get("tok|DROP_CONJ|noniso", {})
    a3 = out["per_operator"].get("tok|ADD_CONJ|noniso", {})
    ng = out["per_operator"].get("tok|NEG|noniso", {})
    pr["P6_L3_granularity_blind_spot"] = {
        "DROP_CONJ_det": {"DC": d3.get("DC", {}).get("within_det"), "DC_L2w": d3.get("DC_L2w", {}).get("within_det")},
        "ADD_CONJ_det": {"DC": a3.get("DC", {}).get("within_det"), "DC_L2w": a3.get("DC_L2w", {}).get("within_det")},
        "PASS": bool(d3 and d3["DC"]["within_det"]["mean"] < d3["DC_L2w"]["within_det"]["mean"]),
        "post_hoc_NEG_absorption (not pre-registered)": {"DC": ng.get("DC", {}).get("within_det"),
                                                         "DC_L2w": ng.get("DC_L2w", {}).get("within_det")}}
    out["predictions"] = pr
    # (b) real dev
    G, sc = load_all()
    for r in G:
        r["m"]["parse_ok"] = 1.0 if sc[r["item_id"]]["coverage"]["self_parseable"] else 0.0
    outb = {}
    for lab, yk, wk in (("panel", "y_panel", "w"), ("solver", "y_solver", None)):
        R = [r for r in G if r[yk] is not None]
        vc = np.array([r["m"]["VC"] for r in R])
        qs = np.quantile(vc, [0.2, 0.4, 0.6, 0.8])
        qbin = np.digitize(vc, qs)
        blk = {}
        stt = strata(R)
        for q in range(5):
            Rq = [r for r, b in zip(R, qbin) if b == q]
            if len(Rq) < 20 or len({r[yk] for r in Rq}) < 2:
                blk[f"Q{q + 1}"] = {"n": len(Rq), "auroc": None}
                continue
            blk[f"Q{q + 1}"] = ST.auc_ci([r[yk] for r in Rq], [r["m"]["DC"] for r in Rq],
                                         [r[wk] for r in Rq] if wk else None, [r["sentence_id"] for r in Rq], stt, n=1000)
            blk[f"Q{q + 1}"]["VC_range"] = [float(min(r["m"]["VC"] for r in Rq)), float(max(r["m"]["VC"] for r in Rq))]
        outb[f"DC_within_VC_quintiles_{lab}"] = blk
        # stacking
        for base in (["B1", "parse_ok", "VC"], ["B1", "parse_ok", "VC", "LC_maj"]):
            X0 = np.array([[0.5 if r["m"].get(f) is None else r["m"][f] for f in base] for r in R], float)
            X1 = np.column_stack([X0, [r["m"]["DC"] for r in R]])
            y = np.array([r[yk] for r in R])
            w = np.array([r[wk] for r in R], float) if wk else np.ones(len(R))
            sids = np.array([r["sentence_id"] for r in R])
            p0 = ST.oof_stack(X0, y, sids, w)
            p1 = ST.oof_stack(X1, y, sids, w)
            b = ST.boot(list(sids), stt, n=NB, seed=7)
            vals = [ST.wauc(y[ix], p1[ix], w[ix]) - ST.wauc(y[ix], p0[ix], w[ix]) for ix in b]
            outb[f"stack_{lab}_base_{'+'.join(base)}"] = {"auroc_base": ST.wauc(y, p0, w), "auroc_base_plus_DC": ST.wauc(y, p1, w),
                                                          "delta": ST.wauc(y, p1, w) - ST.wauc(y, p0, w), "ci": ST.ci(vals),
                                                          "n": len(R)}
            # placebo: random feature
            rng = np.random.default_rng(11)
            Xr = np.column_stack([X0, rng.random(len(R))])
            pr_ = ST.oof_stack(Xr, y, sids, w)
            outb[f"stack_{lab}_base_{'+'.join(base)}"]["placebo_random_feature_delta"] = ST.wauc(y, pr_, w) - ST.wauc(y, p0, w)
    out["M1b_real_dev"] = outb
    pb = outb["stack_panel_base_B1+parse_ok+VC"]
    out["predictions"]["M1b"] = {"delta": pb["delta"], "ci": pb["ci"], "PASS": pb["ci"][0] is not None and pb["ci"][0] > 0}
    jdump(out, RES / "m1_confound.json")
    for arm in ("conf", "tok", "syn"):
        print(arm, {m: round(out["arms"][arm][m]["auroc"] or -1, 3) for m in METRICS})
    print("crossed", {m: round(out["crossed"][m]["auroc"] or -1, 3) for m in METRICS})
    print(json.dumps({k: v.get("PASS") for k, v in out["predictions"].items()}))


if __name__ == "__main__":
    main()
