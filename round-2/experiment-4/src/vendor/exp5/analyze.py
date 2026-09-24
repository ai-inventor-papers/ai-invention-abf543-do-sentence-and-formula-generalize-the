#!/usr/bin/env python3
"""STEP 7: ANALYSES (labels are loaded HERE ONLY, through the firewall: heldout_io.load_labels()).

V1 error-type naming  | V2 blind spots on real errors | V3 wrong-gold flagging | V4 polarity increment + standalone
AUROCs | criterion-5 (correct-but-gold-inequivalent) | silver held-out text side | system level | V5 document
conflation (exploratory) | V6 EU-AI-Act transfer (descriptive) | verdicts.
Common machinery: panel3 rows weighted by L3_sampling_weight; 2,000 sentence-clustered bootstrap resamples (percentile
95%); every number also unweighted. Writes results/analysis.json, results/verdict.json, results/per_item_panel.jsonl,
results/per_gold.jsonl.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from loguru import logger
from scipy import stats
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, roc_auc_score

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import sigfaith  # noqa: E402
from sigfaith import core, decoder as D, heldout_io, textside  # noqa: E402

logger.remove()
logger.add(sys.stdout, level="INFO", format="{time:HH:mm:ss}|{level:<7}|{message}")
logger.add(ROOT / "logs" / "analyze.log", rotation="30 MB", level="DEBUG")
RES = ROOT / "results"
B = 2000
RNG = np.random.default_rng(20260923)
VISIBLE = ["added_condition", "dropped_condition", "quantifier_forall_exists", "negation_polarity", "argument_swap",
           "implication_direction_or_only"]
BLIND = ["quantifier_scope", "cardinality_numeric", "connective_and_or"]


# ------------------------------------------------------------------ helpers
def rj(p):
    return [json.loads(l) for l in Path(p).read_text().splitlines() if l.strip()]


def auc(y, s, w=None):
    y = np.asarray(y)
    if len(np.unique(y)) < 2:
        return float("nan")
    return float(roc_auc_score(y, s, sample_weight=w))


def cluster_index(groups):
    by = defaultdict(list)
    for i, g in enumerate(groups):
        by[g].append(i)
    arrs = [np.array(v) for v in by.values()]
    boots = []
    n = len(arrs)
    for _ in range(B):
        pick = RNG.integers(0, n, n)
        boots.append(np.concatenate([arrs[k] for k in pick]))
    return boots


def ci(vals):
    v = np.array([x for x in vals if x is not None and not (isinstance(x, float) and math.isnan(x))])
    if len(v) == 0:
        return [None, None]
    return [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]


def boot_stat(fn, boots):
    return ci([fn(ix) for ix in boots])


def wilson(k, n, z=1.96):
    if n == 0:
        return [None, None]
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [c - h, c + h]


def h(s):
    return hashlib.sha1(str(s).encode()).hexdigest()


# ------------------------------------------------------------------ load
def load():
    labels = heldout_io.load_labels()
    inputs = {r["item_id"]: r for r in heldout_io.load_inputs(with_design=False)}
    sc = {r["unit_id"]: r for r in rj(RES / "heldout_scores.jsonl")}
    gs = {r["unit_id"]: r for r in rj(RES / "gold_scores.jsonl")}
    llm = {}
    for r in rj(RES / "llm_baselines.jsonl"):
        if r.get("error") is None:
            llm[(r["unit_id"], r["method"])] = r
    return labels, inputs, sc, gs, llm


def panel_frame(labels, inputs, sc, llm):
    rows = []
    for iid, lab in labels.items():
        if lab.get("label_source") != "panel3":
            continue
        s, inp = sc[iid], inputs[iid]
        b1 = llm.get((iid, "B1"), {})
        tj = llm.get((iid, "TJ"), {})
        tjp = llm.get((iid, "TJplus"), {}) if llm.get((iid, "TJplus"), {}).get("parse_ok") else {}
        votes = lab.get("L3_votes") or {}
        if isinstance(votes, str):
            votes = json.loads(votes)
        anyt = set()
        prim_members = []
        for m, v in votes.items():
            anyt |= {t for t in (v.get("error_types") or []) if t and t != "none"}
            if v.get("primary_error"):
                prim_members.append(v["primary_error"])
        rows.append({"item_id": iid, "sid": inp["sentence_id"], "system": inp["system"], "corpus": inp["corpus"],
                     "tercile": inp.get("complexity_tercile"), "y": 1 if lab["L3_majority"] else 0,
                     "w": float(lab["L3_sampling_weight"] or 1.0), "primary": lab.get("L3_primary_error"),
                     "any": sorted(anyt), "members_primary": prim_members, "votes": votes,
                     "L1": lab.get("L1_audited_status"), "parse_ok": 1.0 if s["parse_ok_front"] else 0.0,
                     "S": s["S_frozen"], "S_raw": s["S_raw"], "P": s["P_frozen"], "A0": s["A0_frozen"],
                     "Ccov": s["Ccov_frozen"], "A3i": s["A3_iter1"], "A0i": s["A0_iter1"], "covered": s["covered"],
                     "types_rule": s["types_rule"], "types_lr": s["types_lr"], "legacy_type": s["legacy_type_panel"],
                     "B1": b1.get("p_faithful"), "TJ": tj.get("p_faithful"), "TJ_faithful": tj.get("faithful"),
                     "TJ_primary": tj.get("primary"), "TJ_secondary": tj.get("secondary"),
                     "TJp_faithful": tjp.get("faithful"), "TJp_primary": tjp.get("primary"),
                     "TJp_secondary": tjp.get("secondary"), "TJp_parsed": bool(tjp),
                     "B1_usd": b1.get("usd"), "TJ_usd": tj.get("usd"), "TJp_usd": tjp.get("usd")})
    return rows


# ------------------------------------------------------------------ V4 + standalone
METRICS = ["S", "P", "A0", "Ccov", "A3i", "A0i", "B1", "TJ", "parse_ok"]


def col(rows, k, fill=0.5):
    return np.array([fill if r[k] is None else float(r[k]) for r in rows])


def standalone(rows, boots):
    y = np.array([r["y"] for r in rows])
    w = np.array([r["w"] for r in rows])
    out = {}
    for m in METRICS:
        s = col(rows, m)
        n_missing = sum(r[m] is None for r in rows)
        out[m] = {"auroc_w": auc(y, s, w), "auroc_w_ci": boot_stat(lambda ix: auc(y[ix], s[ix], w[ix]), boots),
                  "auroc_unw": auc(y, s), "spearman": float(stats.spearmanr(s, y).correlation),
                  "n_missing_filled_0.5": n_missing}
        by = {}
        for key in ("tercile", "corpus"):
            for g in sorted({r[key] for r in rows}):
                mk = np.array([r[key] == g for r in rows])
                by[f"{key}={g}"] = {"auroc_w": auc(y[mk], s[mk], w[mk]), "n": int(mk.sum())}
        out[m]["by"] = by
    return out


def oof(rows, feats, reps=10, seed=0):
    y = np.array([r["y"] for r in rows])
    w = np.array([r["w"] for r in rows])
    X = np.column_stack([col(rows, f) for f in feats])
    groups = np.array([r["sid"] for r in rows])
    ug = np.unique(groups)
    pred = np.zeros(len(rows))
    rng = np.random.default_rng(seed)
    for rep in range(reps):
        perm = rng.permutation(len(ug))
        fold_of = {g: perm[i] % 5 for i, g in enumerate(ug)}
        folds = np.array([fold_of[g] for g in groups])
        p = np.zeros(len(rows))
        for k in range(5):
            tr, te = folds != k, folds == k
            m = LogisticRegression(max_iter=2000, C=1.0)
            m.fit(X[tr], y[tr], sample_weight=w[tr])
            p[te] = m.predict_proba(X[te])[:, 1]
        pred += p / reps
    return pred


def v4(rows, boots):
    y = np.array([r["y"] for r in rows])
    w = np.array([r["w"] for r in rows])
    models = {"M0": ["B1", "parse_ok", "A0"], "M1": ["B1", "parse_ok", "A0", "S"], "M2": ["B1", "parse_ok", "A0", "P"],
              "M3base": ["B1", "parse_ok", "A0i"], "M3": ["B1", "parse_ok", "A0i", "A3i"],
              "B1only": ["B1"], "B1_S": ["B1", "S"]}
    preds = {k: oof(rows, v) for k, v in models.items()}
    out = {"models": models, "auroc_oof": {k: auc(y, p, w) for k, p in preds.items()}}
    for a, b in (("M1", "M0"), ("M2", "M0"), ("M3", "M3base"), ("B1_S", "B1only")):
        pa, pb = preds[a], preds[b]
        d = auc(y, pa, w) - auc(y, pb, w)
        out[f"delta_{a}_{b}"] = {"delta": d, "ci95": boot_stat(lambda ix: auc(y[ix], pa[ix], w[ix]) -
                                                                auc(y[ix], pb[ix], w[ix]), boots)}
    # placebo: S and P shuffled within sentence
    rng = np.random.default_rng(7)
    sh = [dict(r) for r in rows]
    by = defaultdict(list)
    for i, r in enumerate(sh):
        by[r["sid"]].append(i)
    for idx in by.values():
        perm = rng.permutation(idx)
        vals = [(rows[j]["S"], rows[j]["P"]) for j in perm]
        for i, (sv, pv) in zip(idx, vals):
            sh[i]["S"], sh[i]["P"] = sv, pv
    p0, p1, p2 = oof(sh, models["M0"]), oof(sh, models["M1"]), oof(sh, models["M2"])
    out["placebo_within_sentence_shuffle"] = {
        "delta_M1_M0": auc(y, p1, w) - auc(y, p0, w),
        "delta_M1_M0_ci95": boot_stat(lambda ix: auc(y[ix], p1[ix], w[ix]) - auc(y[ix], p0[ix], w[ix]), boots),
        "delta_M2_M0": auc(y, p2, w) - auc(y, p0, w),
        "delta_M2_M0_ci95": boot_stat(lambda ix: auc(y[ix], p2[ix], w[ix]) - auc(y[ix], p0[ix], w[ix]), boots)}
    return out, preds


# ------------------------------------------------------------------ V1
def v1(rows):
    U = [r for r in rows if r["y"] == 0]
    Up = [r for r in U if r["parse_ok"] == 1.0]
    out = {"n_U": len(U), "n_U_parse_ok": len(Up)}

    def methods(r):
        rule = r["types_rule"] or ["other"]
        lr = r["types_lr"] or ["other"]
        tjp = r["TJ_primary"] if r["TJ_faithful"] is False or r["TJ_primary"] else None
        tjs = r["TJ_secondary"]
        tpp = r["TJp_primary"] if r["TJp_faithful"] is False or r["TJp_primary"] else None
        tps = r["TJp_secondary"]
        return {"TJplus": (tpp or "none", [t for t in (tpp, tps) if t][:2]),"D_rule": (rule[0], D.top2_list(rule)), "D_lr": (lr[0], D.top2_list(lr)),
                "TJ": (tjp or "none", [t for t in (tjp, tjs) if t][:2]),
                "legacy_iter1": (r["legacy_type"] or "none", [r["legacy_type"] or "none"]),
                "majority_added": ("added_condition", ["added_condition", "quantifier_forall_exists"])}

    def block(R, label):
        res = {}
        w = np.array([r["w"] for r in R])
        truth = [r["primary"] for r in R]
        types_n = Counter(truth)
        big = [t for t, n in types_n.items() if n >= 10]
        per_method = {}
        for name in ("D_rule", "D_lr", "TJ", "TJplus", "legacy_iter1", "majority_added"):
            t1 = [methods(r)[name][0] for r in R]
            t2 = [methods(r)[name][1] for r in R]
            c1 = np.array([a == b for a, b in zip(t1, truth)], float)
            c2 = np.array([b in t for t, b in zip(t2, truth)], float)
            cl = np.array([a in r["any"] for a, r in zip(t1, R)], float)
            conf = defaultdict(lambda: defaultdict(float))
            for a, b, ww in zip(t1, truth, w):
                conf[b][a] += ww
            pt = {}
            for t in sorted(types_n):
                n_t = sum(1 for b in truth if b == t)
                k_t = sum(1 for a, b in zip(t1, truth) if b == t and a == t)
                pred_t = sum(1 for a in t1 if a == t)
                pt[t] = {"n": n_t, "recall": k_t / n_t if n_t else None, "recall_ci": wilson(k_t, n_t),
                         "precision": (k_t / pred_t) if pred_t else None, "precision_ci": wilson(k_t, pred_t),
                         "descriptive_only": n_t < 20}
            per_method[name] = {"top1_w": float((c1 * w).sum() / w.sum()), "top1_unw": float(c1.mean()),
                                "top2_w": float((c2 * w).sum() / w.sum()), "lenient_w": float((cl * w).sum() / w.sum()),
                                "macro_f1_types_n>=10": float(f1_score(truth, t1, labels=big, average="macro",
                                                                       zero_division=0)),
                                "per_type": pt, "confusion_w": {k: dict(v) for k, v in conf.items()},
                                "_c1": c1.tolist()}
        mix = Counter()
        for r, ww in zip(R, w):
            mix[r["primary"]] += ww
        tot = sum(mix.values())
        per_method["prior_random_expected"] = {"top1_w": sum((v / tot) ** 2 for v in mix.values())}
        res["methods"] = per_method
        res["n"] = len(R)
        res["truth_mix_w"] = {k: v / tot for k, v in mix.most_common()}
        res["types_with_n>=10"] = big
        # paired D_rule vs TJ
        c_r = np.array(per_method["D_rule"]["_c1"])
        c_t = np.array(per_method["TJ"]["_c1"])
        groups = [r["sid"] for r in R]
        boots = cluster_index(groups)
        res["paired_Drule_minus_TJ"] = {
            "delta_w": float(((c_r - c_t) * w).sum() / w.sum()),
            "ci95": boot_stat(lambda ix: float(((c_r[ix] - c_t[ix]) * w[ix]).sum() / w[ix].sum()), boots),
            "mcnemar_exact_p": float(stats.binomtest(int(((c_r == 1) & (c_t == 0)).sum()),
                                                     int((c_r != c_t).sum()) or 1, 0.5).pvalue),
            "n_rule_only": int(((c_r == 1) & (c_t == 0)).sum()), "n_tj_only": int(((c_r == 0) & (c_t == 1)).sum())}
        c_p = np.array(per_method["TJplus"]["_c1"])
        res["paired_Drule_minus_TJplus"] = {
            "delta_w": float(((c_r - c_p) * w).sum() / w.sum()),
            "ci95": boot_stat(lambda ix: float(((c_r[ix] - c_p[ix]) * w[ix]).sum() / w[ix].sum()), boots),
            "note": "TJ+ unparsed items (19/302 after one retry) count as 'none' (wrong)"}
        res["TJplus_n_parsed"] = sum(r["TJp_parsed"] for r in R)
        res["union_Drule_or_TJ_top1_w"] = float((np.maximum(c_r, c_t) * w).sum() / w.sum())
        agree = np.array([methods(r)["D_rule"][0] == methods(r)["TJ"][0] for r in R])
        res["agreement_conditioned"] = {"share_agree": float(agree.mean()),
                                        "acc_when_agree_w": float((c_r[agree] * w[agree]).sum() / w[agree].sum())
                                        if agree.any() else None}
        nochg = [r for r in R if (r["types_rule"] or [""])[0] == D.NO_CHANGE]
        res["no_signature_change"] = {"n": len(nochg), "truth_mix": dict(Counter(r["primary"] for r in nochg)),
                                      "precision_blind_bucket": (sum(r["primary"] in D.BLIND for r in nochg) /
                                                                 len(nochg)) if nochg else None}
        for m in per_method.values():
            m.pop("_c1", None)
        return res

    out["parse_ok"] = block(Up, "parse_ok")
    out["all_U"] = block(U, "all")
    out["covered_only"] = block([r for r in Up if r["covered"]], "covered")
    # ceiling: panel member agreement on primary error
    pair, loo_k, loo_n = [], 0, 0
    for r in U:
        mp = [v.get("primary_error") for v in r["votes"].values()]
        mp = [x for x in mp if x]
        for i in range(len(mp)):
            for j in range(i + 1, len(mp)):
                pair.append(mp[i] == mp[j])
        for i in range(len(mp)):
            others = [mp[j] for j in range(len(mp)) if j != i]
            if len(others) == 2 and others[0] == others[1]:
                loo_n += 1
                loo_k += mp[i] == others[0]
    out["ceiling"] = {"mean_pairwise_primary_agreement": float(np.mean(pair)) if pair else None,
                      "leave_one_member_out_agreement": loo_k / loo_n if loo_n else None, "loo_n": loo_n,
                      "note": "members' primary_error includes 'none' when a member judged the item faithful"}
    return out


# ------------------------------------------------------------------ V2
def v2(rows, labels, inputs, sc, gs, llm):
    by_sid = defaultdict(list)
    for iid, lab in labels.items():
        by_sid[inputs[iid]["sentence_id"]].append(iid)
    panel = {r["item_id"]: r for r in rows}
    out = {}
    for partner_mode in ("any_faithful", "panel3_faithful_only"):
        recs = []
        for r in rows:
            if r["y"] == 1:
                continue
            parts = []
            for j in by_sid[r["sid"]]:
                if j == r["item_id"] or labels[j]["output"] != "faithful":
                    continue
                if partner_mode == "panel3_faithful_only" and labels[j].get("label_source") != "panel3":
                    continue
                parts.append(j)
            fallback = False
            if not parts:
                g = gs.get(f"{r['sid']}:gold")
                if g is not None and labels[by_sid[r["sid"]][0]].get("gold_faithful_final") is True:
                    parts = ["__gold__"]
                    fallback = True
            if not parts:
                continue
            rec = {"item_id": r["item_id"], "sid": r["sid"], "w": r["w"], "primary": r["primary"], "any": r["any"],
                   "fallback_gold": fallback}
            for m, key in (("S", "S_frozen"), ("A0", "A0_frozen"), ("A3i", "A3_iter1"), ("P", "P_frozen")):
                se = sc[r["item_id"]][key]
                ds = []
                for j in parts:
                    sf = gs[f"{r['sid']}:gold"][key] if j == "__gold__" else sc[j][key]
                    ds.append(1.0 if se < sf else (0.5 if se == sf else 0.0))
                rec[m] = float(np.mean(ds))
            for m in ("B1", "TJ"):
                se = r[m]
                ds = []
                for j in parts:
                    if j == "__gold__":
                        continue
                    pj = panel.get(j)
                    if pj is None or pj[m] is None or se is None:
                        continue
                    ds.append(1.0 if se < pj[m] else (0.5 if se == pj[m] else 0.0))
                rec[m] = float(np.mean(ds)) if ds else None
            recs.append(rec)
        res = {"n_errors_with_partner": len(recs), "n_fallback_gold": sum(r["fallback_gold"] for r in recs)}
        for tagmode in ("primary", "any"):
            tab = {}
            groups = {t: [x for x in recs if (x["primary"] == t if tagmode == "primary" else t in x["any"])]
                      for t in VISIBLE + BLIND}
            groups["PREDICTED_VISIBLE"] = [x for x in recs if (x["primary"] in VISIBLE if tagmode == "primary"
                                                               else set(x["any"]) & set(VISIBLE))]
            groups["PREDICTED_BLIND"] = [x for x in recs if (x["primary"] in BLIND if tagmode == "primary"
                                                             else set(x["any"]) & set(BLIND))]
            for t, R in groups.items():
                if not R:
                    tab[t] = {"n": 0}
                    continue
                boots = cluster_index([x["sid"] for x in R])
                row = {"n": len(R), "descriptive_only": len(R) < 20}
                for m in ("S", "A0", "A3i", "P", "B1", "TJ"):
                    v = np.array([np.nan if x[m] is None else x[m] for x in R])
                    ww = np.array([x["w"] for x in R])
                    ok = ~np.isnan(v)
                    if not ok.any():
                        continue
                    f = lambda ix: float(np.nansum(v[ix] * ww[ix]) / ww[ix][~np.isnan(v[ix])].sum())  # noqa: E731
                    row[m] = {"det_w": f(np.arange(len(R))), "ci95": boot_stat(f, boots), "n_scored": int(ok.sum())}
                tab[t] = row
            res[tagmode] = tab
        out[partner_mode] = res
    # placebo: random score -> ~0.5
    rng = np.random.default_rng(3)
    main = out["any_faithful"]["primary"]
    vis, bl = main.get("PREDICTED_VISIBLE", {}), main.get("PREDICTED_BLIND", {})
    reading = {}
    if "S" in vis and "S" in bl:
        vis_lo = vis["S"]["ci95"][0]
        b_ci = bl["S"]["ci95"]
        reading = {"visible_det": vis["S"]["det_w"], "visible_ci": vis["S"]["ci95"], "blind_det": bl["S"]["det_w"],
                   "blind_ci": b_ci, "blind_n": bl["n"],
                   "visible_ge_0.80": vis["S"]["det_w"] >= 0.80,
                   "blind_ci_contains_0.5": b_ci[0] <= 0.5 <= b_ci[1],
                   "blind_upper_lt_visible_lower": b_ci[1] < vis_lo,
                   "BLIND_SPOTS_CONFIRMED": bool(b_ci[0] <= 0.5 <= b_ci[1] and b_ci[1] < vis_lo),
                   "power_note": "blind pool is small (n<~31); CI-overlap statement only, never a confirmation of ≈0.5"}
        per_type = {t: (main[t]["S"]["det_w"] if "S" in main.get(t, {}) else None, main.get(t, {}).get("n"))
                    for t in VISIBLE}
        reading["visible_per_type_det_S"] = per_type
    out["reading"] = reading
    out["placebo_random_scores_det"] = float(np.mean([rng.random() < rng.random() for _ in range(5000)]))
    return out


# ------------------------------------------------------------------ V3
def v3(labels, inputs, gs, llm):
    sent = {}
    for iid, lab in labels.items():
        sid = inputs[iid]["sentence_id"]
        if sid in sent:
            continue
        sent[sid] = {"sid": sid, "corpus": inputs[iid]["corpus"], "wrong": lab.get("gold_faithful_final") is False,
                     "known": lab.get("gold_faithful_final") is not None, "ambiguous": bool(lab.get("sentence_ambiguous")),
                     "gold_primary": lab.get("gold_audit_primary_error"), "paper_flag": lab.get("paper_corrected_flag"),
                     "paper_gold": lab.get("gold_fol_paper"), "sentence": inputs[iid]["sentence"],
                     "gold": inputs[iid]["gold_fol_original"], "tercile": inputs[iid].get("complexity_tercile")}
    units = []
    for sid, u in sent.items():
        g = gs.get(f"{sid}:gold")
        if g is None or not u["known"]:
            continue
        b1 = llm.get((f"{sid}:gold", "B1"), {}).get("p_faithful")
        tj = llm.get((f"{sid}:gold", "TJ"), {})
        units.append({**u, "flag_S": 1 - g["S_frozen"], "flag_P": 1 - g["P_frozen"], "flag_A0": 1 - g["A0_frozen"],
                      "flag_Ccov": 1 - (g["Ccov_frozen"] if g["parse_ok_front"] else 0.5), "flag_A3iter1": 1 - g["A3_iter1"],
                      "flag_B1": None if b1 is None else 1 - b1,
                      "flag_TJ": None if tj.get("p_faithful") is None else 1 - tj["p_faithful"],
                      "raw": g["S_raw"], "type_top1": g["type_top1"], "TJ_primary": tj.get("primary"),
                      "covered": g["covered"]})
    flags = ["flag_S", "flag_P", "flag_A0", "flag_Ccov", "flag_A3iter1", "flag_B1", "flag_TJ"]

    def table(U, tag):
        y = np.array([1 if u["wrong"] else 0 for u in U])
        res = {"n": len(U), "base_rate": float(y.mean()) if len(U) else None}
        idx = np.arange(len(U))
        boots = [RNG.integers(0, len(U), len(U)) for _ in range(B)] if len(U) else []
        for f in flags:
            s = np.array([0.5 if u[f] is None else u[f] for u in U])
            r = {"auroc": auc(y, s), "auroc_ci": boot_stat(lambda ix: auc(y[ix], s[ix]), boots),
                 "n_missing": sum(u[f] is None for u in U)}
            # P@k with tie-break raw_score (lower raw = more suspicious), then sentence hash
            order = sorted(idx, key=lambda i: (-s[i], (U[i]["raw"] if U[i]["raw"] is not None else 1.0), h(U[i]["sid"])))
            for k in (25, 50):
                if len(U) < k:
                    continue
                top = order[:k]
                p = float(y[top].mean())
                b = float(y.mean())
                r[f"P@{k}"] = p
                r[f"lift@{k}"] = p / b if b else None
                r[f"enrich@{k}"] = (p - b) / (1 - b) if b < 1 else None
                r[f"binom_p@{k}"] = float(stats.binomtest(int(y[top].sum()), k, b, alternative="greater").pvalue)
                eb = []
                for ix in boots[:1000]:
                    Ub = [U[i] for i in ix]
                    yb = y[ix]
                    sb = s[ix]
                    ob = sorted(range(len(Ub)), key=lambda i: (-sb[i], h(Ub[i]["sid"]) + str(i)))[:k]
                    bb = yb.mean()
                    eb.append((yb[ob].mean() - bb) / (1 - bb) if bb < 1 else np.nan)
                r[f"enrich@{k}_ci"] = ci(eb)
                if tag.startswith("proverqa") and f == "flag_S":
                    dr = [i for i in idx if U[i]["wrong"] and U[i]["gold_primary"] == "dropped_condition"]
                    r[f"proverqa_recall_dropped_restrictor@{k}"] = (len(set(dr) & set(top)) / len(dr)) if dr else None
            res[f] = r
        return res

    out = {"pooled": table(units, "pooled")}
    for c in sorted({u["corpus"] for u in units}):
        out[c] = table([u for u in units if u["corpus"] == c], c.lower())
    out["pooled_excl_ambiguous"] = table([u for u in units if not u["ambiguous"]], "noamb")
    # type agreement in top-50 per corpus
    ta = {}
    for c in sorted({u["corpus"] for u in units}):
        U = [u for u in units if u["corpus"] == c]
        top = sorted(U, key=lambda u: (-u["flag_S"], u["raw"] if u["raw"] is not None else 1.0, h(u["sid"])))[:50]
        tw = [u for u in top if u["wrong"] and u["gold_primary"]]
        topj = sorted(U, key=lambda u: (-(u["flag_TJ"] or 0), h(u["sid"])))[:50]
        tj = [u for u in topj if u["wrong"] and u["gold_primary"]]
        ta[c] = {"n_wrong_in_top50": len(tw),
                 "D_rule_top1_acc": (sum(u["type_top1"] == u["gold_primary"] for u in tw) / len(tw)) if tw else None,
                 "D_rule_confusion": dict(Counter(f"{u['gold_primary']}->{u['type_top1']}" for u in tw).most_common(12)),
                 "TJ_acc_on_TJ_top50": (sum(u["TJ_primary"] == u["gold_primary"] for u in tj) / len(tj)) if tj else None,
                 "TJ_acc_on_S_top50": (sum(u["TJ_primary"] == u["gold_primary"] for u in tw) / len(tw)) if tw else None}
    out["type_agreement_top50"] = ta
    pq = [u for u in units if u["corpus"].lower().startswith("prover")]
    pw = [u for u in pq if u["wrong"]]
    out["proverqa_dropped"] = {"n_wrong": len(pw),
                               "n_wrong_gold_primary_dropped": sum(u["gold_primary"] == "dropped_condition" for u in pw),
                               "share_wrong_labelled_dropped_by_D_rule": (sum(u["type_top1"] == "dropped_condition"
                                                                              for u in pw) / len(pw)) if pw else None}
    # complementarity B1 + flag_S, cross-fitted by sentence (5-fold x 10)
    U = [u for u in units if u["flag_B1"] is not None]
    y = np.array([1 if u["wrong"] else 0 for u in U])
    X1 = np.array([[u["flag_B1"]] for u in U])
    X2 = np.array([[u["flag_B1"], u["flag_S"]] for u in U])
    rng = np.random.default_rng(1)
    p1, p2 = np.zeros(len(U)), np.zeros(len(U))
    for rep in range(10):
        folds = rng.permutation(len(U)) % 5
        for k in range(5):
            tr, te = folds != k, folds == k
            p1[te] += LogisticRegression(max_iter=1000).fit(X1[tr], y[tr]).predict_proba(X1[te])[:, 1] / 10
            p2[te] += LogisticRegression(max_iter=1000).fit(X2[tr], y[tr]).predict_proba(X2[te])[:, 1] / 10
    boots = [RNG.integers(0, len(U), len(U)) for _ in range(B)]
    out["complementarity_B1_plus_S"] = {"auroc_B1": auc(y, p1), "auroc_B1_S": auc(y, p2),
                                        "delta": auc(y, p2) - auc(y, p1),
                                        "delta_ci95": boot_stat(lambda ix: auc(y[ix], p2[ix]) - auc(y[ix], p1[ix]), boots)}
    # secondary: MALLS 99 human corrections
    M = [u for u in units if u["paper_flag"] is not None]
    if M:
        y = np.array([1 if u["paper_flag"] else 0 for u in M])
        boots = [RNG.integers(0, len(M), len(M)) for _ in range(B)]
        out["malls_human_99"] = {"n": len(M), "base_rate": float(y.mean())}
        for f in flags:
            s = np.array([0.5 if u[f] is None else u[f] for u in M])
            out["malls_human_99"][f] = {"auroc": auc(y, s), "auroc_ci": boot_stat(lambda ix: auc(y[ix], s[ix]), boots)}
        # sanity: corrected (paper) golds vs originals among flagged items
        fz = heldout_io.check_frozen()
        from solver_sig import signature
        cor = [u for u in M if u["paper_flag"] and u["paper_gold"]]
        exs = textside.extract_many([u["sentence"] for u in cor])
        prb = textside.probe_many([u["sentence"] for u in cor], exs) if fz["text_side"] != "T0" else {}
        diffs = []
        aligner = sigfaith.aligner_from(fz["aligner"])
        for u in cor:
            p, _ = core.parse_front(u["paper_gold"])
            S = None
            if p is not None:
                try:
                    S = signature(p.ast, N=3, timeout_ms=5000, with_rel=True, rel_max_unary=8)
                except Exception:  # noqa: BLE001
                    S = None
            lab = textside.labels_for(exs[u["sentence"]], fz["text_side"], prb.get(u["sentence"]))
            r = sigfaith.score_parsed(exs[u["sentence"]], lab, p, S, fz, aligner)
            diffs.append({"sid": u["sid"], "orig": 1 - u["flag_S"], "paper": r["score"], "flagged": u["flag_S"] > 0})
        fl = [d for d in diffs if d["flagged"]]
        out["malls_paper_gold_sanity"] = {"n_corrected": len(diffs), "n_flagged_orig": len(fl),
                                          "mean_orig_flagged": float(np.mean([d["orig"] for d in fl])) if fl else None,
                                          "mean_paper_flagged": float(np.mean([d["paper"] for d in fl])) if fl else None,
                                          "share_paper_higher": (sum(d["paper"] > d["orig"] for d in fl) / len(fl))
                                          if fl else None}
    return out, units


def v3_screen_dev(gs, llm):
    l4 = {}
    for l in (ROOT / "data" / "screen_l4.jsonl").read_text().splitlines():
        x = json.loads(l)
        l4.setdefault(x["sentence_id"], x)
    U = []
    for sid, x in l4.items():
        g = gs.get(f"{sid}:screen_gold")
        if g is None or x.get("gold_faithful_final") is None:
            continue
        b1 = llm.get((f"{sid}:screen_gold", "B1"), {}).get("p_faithful")
        tj = llm.get((f"{sid}:screen_gold", "TJ"), {}).get("p_faithful")
        U.append({"y": 0 if x["gold_faithful_final"] else 1, "S": 1 - g["S_frozen"], "A0": 1 - g["A0_frozen"],
                  "Ccov": 1 - (g["Ccov_frozen"] if g["parse_ok_front"] else 0.5), "A3i": 1 - g["A3_iter1"],
                  "B1": None if b1 is None else 1 - b1, "TJ": None if tj is None else 1 - tj})
    y = np.array([u["y"] for u in U])
    out = {"n": len(U), "base_rate": float(y.mean()), "note": "DEV (screen golds were used for R2 silver); non-confirmatory"}
    for f in ("S", "A0", "Ccov", "A3i", "B1", "TJ"):
        out[f] = auc(y, np.array([0.5 if u[f] is None else u[f] for u in U]))
    return out


# ------------------------------------------------------------------ criterion 5, silver, system level
def criterion5(rows):
    R = [r for r in rows if r["y"] == 1 and r["L1"] in ("non_equiv", "non_equiv_no_bijection")]
    out = {"n": len(R)}
    if R:
        out["frozen_full_match_score1"] = sum(r["S"] == 1.0 for r in R) / len(R)
        out["frozen_full_match_raw1"] = sum(r["S_raw"] == 1.0 for r in R) / len(R)
        out["legacy_full_match_score1"] = sum(r["A3i"] == 1.0 for r in R) / len(R)
        out["frozen_mean_score"] = float(np.mean([r["S"] for r in R]))
        out["legacy_mean_score"] = float(np.mean([r["A3i"] for r in R]))
        tj = [r for r in R if r["TJ_faithful"] is not None]
        out["TJ_false_flag_rate"] = (sum(r["TJ_faithful"] is False for r in tj) / len(tj)) if tj else None
        b1 = [r for r in R if r["B1"] is not None]
        out["B1_below_0.5_rate"] = (sum(r["B1"] < 0.5 for r in b1) / len(b1)) if b1 else None
    return out


def silver_heldout(units):
    fz = heldout_io.check_frozen()
    sigs = json.loads((RES / "heldout_formula_sigs.json").read_text())
    good = [u for u in units if not u["wrong"]]
    exs = textside.extract_many([u["sentence"] for u in good])
    side = fz["text_side"]
    probes = textside.probe_many([u["sentence"] for u in good], exs) if side != "T0" else {}  # cached ($0)
    aligner = sigfaith.aligner_from(fz["aligner"])
    t = defaultdict(lambda: [0, 0])
    for u in good:
        p, _ = core.parse_front(u["gold"])
        S = sigs.get(u["gold"])
        if p is None or S is None or "error" in S:
            continue
        ex = exs[u["sentence"]]
        A = aligner(p.preds, p.consts, ex["concepts"], ex["anchors"])
        labs = {"T0": textside.labels_for(ex, "T0"), side: textside.labels_for(ex, side, probes.get(u["sentence"]))}
        for P, a in A["preds"].items():
            if a["cid"] is None:
                continue
            sl = S["labels"].get(P, "?")
            if a["flip"]:
                sl = core.FLIP[sl]
            if sl not in ("+", "-", "0"):
                continue
            for sd, lab in labs.items():
                tl = lab.get(a["cid"])
                for k in (f"silver_{sl}", f"{u['corpus']}", "all"):
                    t[f"{sd}|{k}"][0] += tl == sl
                    t[f"{sd}|{k}"][1] += 1
    return {k: {"acc": v[0] / v[1], "n": v[1], "ci95": wilson(v[0], v[1])} for k, v in t.items()}


def system_level(rows, sc, inputs):
    acc = defaultdict(lambda: [0.0, 0.0])
    for r in rows:
        acc[r["system"]][0] += r["w"] * r["y"]
        acc[r["system"]][1] += r["w"]
    mean_s = defaultdict(list)
    for iid, s in sc.items():
        mean_s[inputs[iid]["system"]].append(s["S_frozen"])
    systems = sorted(acc)
    a = [acc[s][0] / acc[s][1] for s in systems]
    out = {"systems": systems, "panel_acc_w": dict(zip(systems, a))}
    for key in ("S_frozen", "A0_frozen", "A3_iter1", "Ccov_frozen"):
        m = {s: float(np.mean([sc[i][key] for i in sc if inputs[i]["system"] == s])) for s in systems}
        tau = stats.kendalltau(a, [m[s] for s in systems])
        out[key] = {"mean_per_system": m, "kendall_tau": float(tau.correlation), "p": float(tau.pvalue)}
    out["note"] = "n=9 systems: low power"
    return out


# ------------------------------------------------------------------ V5, V6
def v5(labels, inputs, sc, rows):
    fz = heldout_io.check_frozen()
    folio = defaultdict(set)
    for iid, r in inputs.items():
        if r["corpus"] == "folio":
            folio[r["story_id"]].add(r["sentence_id"])
    stories = {k: sorted(v) for k, v in folio.items() if len(v) >= 2}
    panel = {r["item_id"]: r for r in rows}
    aligner = sigfaith.aligner_from(fz["aligner"])
    sent_of = {}
    for iid, r in inputs.items():
        sent_of[r["sentence_id"]] = r["sentence"]
    exs = textside.extract_many([sent_of[s] for v in stories.values() for s in v])
    cells = Counter()
    hits = []
    listing = []
    n_docs = 0
    systems = sorted({r["system"] for r in inputs.values()})
    by_key = {(r["sentence_id"], r["system"]): iid for iid, r in inputs.items()}
    for st, sids in stories.items():
        for sysn in systems:
            iids = [by_key.get((s, sysn)) for s in sids]
            aligned = []
            for s, iid in zip(sids, iids):
                p, _ = core.parse_front(inputs[iid]["candidate_fol"]) if iid else (None, "")
                if p is None:
                    aligned.append({"ex": exs[sent_of[s]], "alignment": {}, "arity": {}})
                    continue
                A = aligner(p.preds, p.consts, exs[sent_of[s]]["concepts"], exs[sent_of[s]]["anchors"])
                aligned.append({"ex": exs[sent_of[s]], "alignment": {k: v["cid"] for k, v in A["preds"].items()},
                                "arity": dict(p.preds)})
            d = sigfaith.document_signature([sent_of[s] for s in sids], [inputs[i]["candidate_fol"] if i else "" for i in iids],
                                            aligned=aligned)
            n_docs += 1
            flagged = set(d["flagged_sentences"]["conflation"]) | set(d["flagged_sentences"]["split"])
            for k, iid in enumerate(iids):
                if iid in panel:
                    pr = panel[iid]
                    has = pr["y"] == 0 and (pr["primary"] in ("conflation", "wrong_split") or
                                            bool(set(pr["any"]) & {"conflation", "wrong_split"}))
                    cells[(k in flagged, has)] += 1
                    if has:
                        hits.append(k in flagged)
            if (d["conflation"] or d["split"]) and len(listing) < 10:
                listing.append({"story": st, "system": sysn, "conflation": d["conflation"][:2], "split": d["split"][:2],
                                "arity_conflicts": d["arity_conflicts"][:2]})
    return {"EXPLORATORY": True, "n_stories_ge2_sentences": len(stories), "n_documents": n_docs,
            "table_flagged_x_hasConflSplit": {f"flag={a},has={b}": v for (a, b), v in cells.items()},
            "hit_rate": (sum(hits) / len(hits)) if hits else None, "n_true_conflation_split_panel": len(hits),
            "examples": listing}


def v6(inputs, sc):
    T = rj(RES / "transfer_scores.jsonl")
    ok = [t for t in T if t["parse_ok_front"]]
    cov = [t for t in ok if t["covered"]]
    held_pred_unf = [s for s in sc.values() if s["covered"] and s["S_frozen"] < 1.0]
    lr = json.loads((ROOT.parent.parent.parent / "iter_1" / "gen_art" / "gen_art_dataset_1" / "label_report.json")
                    .read_text()).get("L3_error_type_distribution_weighted")

    def dist(xs):
        c = Counter(x["type_top1"] for x in xs)
        n = sum(c.values())
        return {k: v / n for k, v in c.most_common()} if n else {}
    return {"n_rows": len(T), "n_parse_ok": len(ok), "n_unparseable": len(T) - len(ok),
            "n_unparseable_subset_symbol": sum(1 for t in T if not t["parse_ok_front"] and "⊆" in (t.get("parse_error") or "")),
            "coverage_rate_of_parse_ok": len(cov) / len(ok) if ok else None,
            "score_quantiles_covered": [float(q) for q in np.percentile([t["S_frozen"] for t in cov], [10, 25, 50, 75, 90])]
            if cov else None,
            "mean_score_covered": float(np.mean([t["S_frozen"] for t in cov])) if cov else None,
            "D_rule_top1_dist_transfer": dist([t for t in cov if t["S_frozen"] < 1.0]),
            "D_rule_top1_dist_heldout_pred_unfaithful": dist(held_pred_unf),
            "panel_weighted_mix": lr, "why_uncovered": dict(Counter(t["why_uncovered"] for t in ok if not t["covered"])),
            "note": "no accuracy claim; grounded/ungrounded not split (out of scope)"}


def coverage_cost(sc, llm):
    S = list(sc.values())
    out = {"n_rows": len(S), "parse_ok_rate": sum(s["parse_ok_front"] for s in S) / len(S),
           "covered_rate": sum(s["covered"] for s in S) / len(S),
           "why_uncovered": dict(Counter(s["why_uncovered"] for s in S if not s["covered"])),
           "sig_errors": dict(Counter((s["sig_error"] or "").split(":")[0] for s in S if s["sig_error"])),
           "sec_per_item_mean": float(np.mean([s["seconds"] for s in S])),
           "sec_per_item_median": float(np.median([s["seconds"] for s in S])), "usd_per_item_signature_T0": 0.0}
    for m in ("B1", "TJ"):
        v = [r["usd"] for (u, mm), r in llm.items() if mm == m and r.get("usd") is not None and not r.get("cached")]
        out[f"usd_per_item_{m}"] = float(np.mean(v)) if v else None
        out[f"n_{m}"] = sum(1 for (u, mm) in llm if mm == m)
    return out


@logger.catch(reraise=True)
def main():
    labels, inputs, sc, gs, llm = load()
    rows = panel_frame(labels, inputs, sc, llm)
    logger.info(f"panel rows {len(rows)}; unfaithful {sum(r['y'] == 0 for r in rows)}")
    boots = cluster_index([r["sid"] for r in rows])
    A = {"n_panel": len(rows)}
    A["standalone"] = standalone(rows, boots)
    A["V4"], preds = v4(rows, boots)
    logger.info(f"V4 done: {json.dumps({k: v for k, v in A['V4'].items() if k.startswith('delta')})}")
    A["V1"] = v1(rows)
    logger.info("V1 done")
    A["V2"] = v2(rows, labels, inputs, sc, gs, llm)
    logger.info("V2 done")
    A["V3"], gunits = v3(labels, inputs, gs, llm)
    A["V3_screen_dev"] = v3_screen_dev(gs, llm)
    logger.info("V3 done")
    A["criterion5"] = criterion5(rows)
    A["silver_heldout"] = silver_heldout(gunits)
    A["system_level"] = system_level(rows, sc, inputs)
    A["V5"] = v5(labels, inputs, sc, rows)
    A["V6"] = v6(inputs, sc)
    A["coverage_cost"] = coverage_cost(sc, llm)
    ledger = rj(RES / "cost_ledger.jsonl")
    A["api_cost"] = {"total_usd": float(sum(r.get("cost") or 0 for r in ledger)), "n_calls": len(ledger),
                     "by_purpose": {k: float(sum(r.get("cost") or 0 for r in ledger if r["purpose"] == k))
                                    for k in sorted({r["purpose"] for r in ledger})}}
    (RES / "analysis.json").write_text(json.dumps(A, indent=1, default=float))
    with (RES / "per_item_panel.jsonl").open("w") as f:
        for r, k in zip(rows, range(len(rows))):
            f.write(json.dumps({**{x: r[x] for x in r if x != "votes"}, "oof_M0": float(preds["M0"][k]),
                                "oof_M1": float(preds["M1"][k]), "oof_M2": float(preds["M2"][k])}, default=float) + "\n")
    with (RES / "per_gold.jsonl").open("w") as f:
        for u in gunits:
            f.write(json.dumps(u, default=float) + "\n")
    verdict(A)


def verdict(A):
    r1 = json.loads((RES / "r1_grid.json").read_text())
    v1p = A["V1"]["parse_ok"]["methods"]
    dr, tj, mj = v1p["D_rule"], v1p["TJ"], v1p["majority_added"]
    d = A["V1"]["parse_ok"]["paired_Drule_minus_TJ"]
    rec = {t: dr["per_type"].get(t, {}).get("recall") for t in ("added_condition", "dropped_condition",
                                                                 "quantifier_forall_exists")}
    diag = bool(d["ci95"][0] is not None and d["ci95"][0] >= -0.05 and dr["top1_w"] >= mj["top1_w"] + 0.15 and
                all(v is not None and v >= 0.6 for v in rec.values()))
    p = A["V3"]["pooled"]
    pq = next((v for k, v in A["V3"].items() if k.lower().startswith("prover")), {})
    flag = bool(p["flag_S"]["auroc_ci"][0] is not None and p["flag_S"]["auroc_ci"][0] > 0.5 and
                ((pq.get("flag_S", {}).get("P@25") or 0) >= 0.35 or (p["flag_S"].get("enrich@50_ci", [None])[0] or -1) > 0)
                and p["flag_S"]["auroc"] >= p["flag_Ccov"]["auroc"])
    m2 = A["V4"]["delta_M2_M0"]
    pol = bool(m2["ci95"][0] is not None and m2["ci95"][0] > 0)
    tc = r1["test_chosen"]
    c5 = A["criterion5"].get("frozen_full_match_score1")
    ren = bool((tc["FA_rename"] or 0) <= 0.05 and (tc.get("FA_RENAME2") if tc.get("FA_RENAME2") is not None else 1) <= 0.10
               and (c5 or 0) >= 0.80)
    V = {"DIAGNOSER_POSITIVE": {"pass": diag, "D_rule_top1_w": dr["top1_w"], "TJ_top1_w": tj["top1_w"],
                                "delta_vs_TJ": d["delta_w"], "delta_ci95": d["ci95"], "majority_top1_w": mj["top1_w"],
                                "recall_added_dropped_forallexists": rec,
                                "rule": "D_rule top1 >= TJ-0.05 (CI lower) AND >= majority+0.15 AND recall>=0.6 on added/dropped/∀∃"},
         "FLAGGER_POSITIVE": {"pass": flag, "pooled_auroc": p["flag_S"]["auroc"], "pooled_auroc_ci": p["flag_S"]["auroc_ci"],
                              "proverqa_P@25": pq.get("flag_S", {}).get("P@25"), "pooled_enrich@50": p["flag_S"].get("enrich@50"),
                              "pooled_enrich@50_ci": p["flag_S"].get("enrich@50_ci"), "Ccov_auroc": p["flag_Ccov"]["auroc"],
                              "B1_auroc": p["flag_B1"]["auroc"], "TJ_auroc": p["flag_TJ"]["auroc"]},
         "POLARITY_CARRIES_SIGNAL": {"pass": pol, "delta_M2_M0": m2["delta"], "ci95": m2["ci95"],
                                     "delta_M1_M0": A["V4"]["delta_M1_M0"]},
         "RENAME_FIXED": {"pass": ren, "FA_rename_test": tc["FA_rename"], "FA_RENAME2_test": tc.get("FA_RENAME2"),
                          "criterion5_full_match": c5, "legacy_FA_rename_test": r1["test_legacy"]["FA_rename"],
                          "legacy_FA_RENAME2_test": r1["test_legacy"].get("FA_RENAME2"),
                          "legacy_criterion5": A["criterion5"].get("legacy_full_match_score1")},
         "BLIND_SPOTS_CONFIRMED": {"pass": bool(A["V2"]["reading"].get("BLIND_SPOTS_CONFIRMED")), **A["V2"]["reading"]}}
    (RES / "verdict.json").write_text(json.dumps(V, indent=1, default=float))
    logger.info(f"VERDICTS: { {k: v['pass'] for k, v in V.items()} }")


if __name__ == "__main__":
    main()
