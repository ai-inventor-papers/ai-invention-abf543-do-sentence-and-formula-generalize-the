#!/usr/bin/env python3
"""S6 analysis (no API): pre-registered X1-X5 + secondary analyses on the panel-labelled long legal set.

Label y = panel majority 'faithful' (sentence-only, no gold); weights = post-stratified N_h / n_h(labelled) per frame
(frame A: system x agreement x marker_bin; frame B: definition). 2,000 sentence-clustered bootstrap draws (vendor
stats.StratBoot; sentences resampled within strata in_ai_act x marker_bin). One-sided alpha 0.05 -> the 5th percentile
of the bootstrap distribution is the test bound; 95% intervals are also reported. Every number is 'panel-only'.
Writes results/tests.json, results/analysis.json, results/scores.jsonl, results/exception_set.jsonl.
"""
from __future__ import annotations

import json
import math
import random
import time
from collections import Counter, defaultdict

import numpy as np

from common import RES, SEED, SYSTEMS, VENDOR, WORK, jdump, jload, read_jsonl, setup_logger, write_jsonl
from stats_ext import StratBoot, kendall_pairwise, kish, oof_stack, wauc

logger = setup_logger("analysis")
NBOOT = 2000
LABEL = "panel-only (sentence-only no-gold 3-member panel; secondary transfer)"
METRICS = ["DC", "DC_noL3", "DC_fp", "DC_unw", "DS_dc", "LC_maj", "DS_bin", "VC", "B1", "B1plus", "B3nli", "B3cos",
           "B2", "B7", "B7_arity_self", "B7_arity_doc", "B7_joint", "DC_arb"]
TWO_SYS = ["B8", "DC_lone", "B7_jacc"]


def pct(v, q):
    v = [x for x in v if x is not None and not (isinstance(x, float) and math.isnan(x))]
    return float(np.percentile(v, q)) if v else None


def ci_block(vals) -> dict:
    return {"ci95": [pct(vals, 2.5), pct(vals, 97.5)], "lb90": pct(vals, 5), "ub90": pct(vals, 95)}


# ============================================================================================ data
def load_labels(members_filter: set | None = None) -> dict:
    votes = defaultdict(dict)
    for r in read_jsonl(WORK / "panel_votes.jsonl"):
        if r.get("phase") == "adj" and r.get("faithful") is not None:
            votes[r["item_id"]][r["member"]] = r
    out = {}
    for iid, v in votes.items():
        if members_filter:
            v = {m: r for m, r in v.items() if m in members_filter}
            if not v:
                continue
        fa = {m: r["faithful"] for m, r in v.items()}
        n_yes = sum(fa.values())
        if len(fa) >= 3 or (len(fa) == 2 and n_yes != 1) or len(fa) == 1:
            maj = n_yes * 2 > len(fa)
        else:  # 2 votes split: tie broken by M2, then M1
            maj = fa.get("M2", fa.get("M1"))
        unf = [r for r in v.values() if not r["faithful"]]

        def vote(key):
            vals = [r.get(key) for r in unf if r.get(key) is not None]
            if not vals:
                return None
            c = Counter(vals).most_common()
            if len(c) > 1 and c[0][1] == c[1][1]:
                for m in ("M2", "M1", "M3"):
                    if m in v and not v[m]["faithful"] and v[m].get(key) is not None:
                        return v[m][key]
            return c[0][0]
        out[iid] = {"y": int(bool(maj)), "n_votes": len(fa), "votes": fa, "unanimous": len(set(fa.values())) == 1,
                    "primary_error": vote("primary_error") if not maj else "none",
                    "exception_involved": (vote("exception_involved") if not maj else False),
                    "error_types": sorted({e for r in unf for e in (r.get("error_types") or [])}),
                    "sentence_ambiguous": sum(bool(r.get("sentence_ambiguous")) for r in v.values()) * 2 > len(v),
                    "member_rows": v}
    return out


def build_table() -> tuple[list[dict], dict]:
    cfg = jload(RES / "dc_config.json")
    t_read = time.time()
    assert cfg["frozen_at"] < t_read, "DC freeze must precede the first panel-label read"
    sents = {s["sentence_id"]: s for s in jload(WORK / "sentences.json")}
    cands = {c["cand_id"]: c for c in read_jsonl(WORK / "candidates.jsonl")}
    dc = {r["cand_id"]: r for r in read_jsonl(RES / "dc_scores_frozen.jsonl")}
    extra = defaultdict(dict)
    for f in ("b1.jsonl", "b1plus.jsonl", "b3.jsonl", "struct.jsonl", "dc_arb.jsonl", "placebo_scores.jsonl"):
        for r in read_jsonl(WORK / f):
            extra[r["key"]].update({k: v for k, v in r.items() if k != "key"})
    samp = jload(WORK / "panel_sample.json")
    lab = load_labels()
    rows = []
    for it in samp["items"]:
        iid = it["item_id"]
        c = cands[iid]
        s = sents[c["sentence_id"]]
        r = {"item_id": iid, "sentence_id": c["sentence_id"], "system": c["system"], "frame": it["frame"],
             "stratum": it["stratum"], "N_h": it["N_h"], "marker_bin": s["marker_bin"], "n_markers": s["n_markers"],
             "exception_markers": s["exception_markers"], "n_tokens": s["n_tokens"], "act": s["act"],
             "source": s["source"], "in_ai_act": s["in_ai_act"], "has_cross_reference": s["has_cross_reference"],
             "parse_ok": c["parse_ok"], "n_preds": c.get("n_preds"), "agree": it.get("agree")}
        r.update({k: v for k, v in dc.get(iid, {}).items() if k not in r})
        r.update(extra.get(iid, {}))
        if iid in lab:
            r.update({k: v for k, v in lab[iid].items() if k != "member_rows"})
        if not r["parse_ok"]:
            for m in ("DC_unw",):  # contract rule for unparseable candidates (bookkeeping: left empty by dc_score)
                if r.get(m) is None:
                    r[m], r[m + "_cov"] = 0.5, 0
        # POST-HOC diagnostic (not pre-registered): DC with the LC_maj/DS_bin convention unparseable -> 0
        r["DC_unparse0"] = r.get("DC") if r["parse_ok"] else 0.0
        rows.append(r)
    lab_rows = [r for r in rows if "y" in r]
    # post-stratified weights over LABELLED items
    nh = Counter(r["stratum"] for r in lab_rows)
    for r in lab_rows:
        r["w"] = r["N_h"] / nh[r["stratum"]]
    meta = {"labels_first_read_at": t_read, "dc_frozen_at": cfg["frozen_at"], "freeze_precedes_labels": True,
            "n_sample": len(rows), "n_labelled": len(lab_rows), "n_unlabelled_budget_stop": len(rows) - len(lab_rows),
            "n_votes_3": sum(r["n_votes"] == 3 for r in lab_rows), "n_votes_2": sum(r["n_votes"] == 2 for r in lab_rows)}
    return lab_rows, meta


# ============================================================================================ helpers
class Ctx:
    def __init__(self, rows: list[dict], nboot: int = NBOOT, seed: int = 0):
        self.rows = rows
        self.y = np.array([r["y"] for r in rows], float)
        self.w = np.array([r["w"] for r in rows], float)
        self.sids = np.array([r["sentence_id"] for r in rows])
        strata = {r["sentence_id"]: f"{r['in_ai_act']}|{r['marker_bin']}" for r in rows}
        self.boot = StratBoot(self.sids, strata, n=nboot, seed=seed)

    def col(self, m, default=0.5):
        return np.array([(r.get(m) if r.get(m) is not None else default) for r in self.rows], float)

    def mask(self, m):
        return np.array([r.get(m) is not None for r in self.rows])


def auc_block(C: Ctx, m: str, idx=None) -> dict:
    ok = C.mask(m) if idx is None else (C.mask(m) & idx)
    if ok.sum() < 5:
        return {"n": int(ok.sum()), "auroc_w": None}
    s = C.col(m)
    y, w = C.y, C.w
    pt = wauc(y[ok], s[ok], w[ok])
    vals = []
    for b in C.boot:
        bb = b[ok[b]]
        vals.append(wauc(y[bb], s[bb], w[bb]))
    cov = [bool(C.rows[i].get(m + "_cov", True)) for i in np.where(ok)[0]]
    return {"auroc_w": pt, **ci_block(vals), "n": int(ok.sum()), "n_pos": int(y[ok].sum()),
            "n_sentences": len(set(C.sids[ok])), "coverage": float(np.mean(cov)) if cov else None}


def delta_block(C: Ctx, a: np.ndarray, b: np.ndarray, idx=None) -> dict:
    ok = np.ones(len(C.y), bool) if idx is None else idx
    pt = wauc(C.y[ok], a[ok], C.w[ok]) - wauc(C.y[ok], b[ok], C.w[ok])
    vals = []
    for bt in C.boot:
        bb = bt[ok[bt]]
        vals.append(wauc(C.y[bb], a[bb], C.w[bb]) - wauc(C.y[bb], b[bb], C.w[bb]))
    return {"delta": pt, **ci_block(vals), "n": int(ok.sum())}


def stack(C: Ctx, feats: list[str], idx=None, seed0: int = 100) -> np.ndarray:
    ok = np.ones(len(C.y), bool) if idx is None else idx
    X = np.column_stack([C.col(f) for f in feats])[ok]
    out = np.full(len(C.y), np.nan)
    out[ok] = oof_stack(X, C.y[ok], C.sids[ok], C.w[ok], k=5, n_rep=5, seed0=seed0)
    return out


def within_pairs(C: Ctx, m: str, sel_unf, idx=None) -> dict:
    """P(score_f > score_u) + 0.5 ties over (faithful, unfaithful-of-type) pairs within one sentence."""
    ok = np.ones(len(C.y), bool) if idx is None else idx
    s = C.col(m)
    by = defaultdict(lambda: ([], []))
    for i, r in enumerate(C.rows):
        if not ok[i]:
            continue
        if r["y"] == 1:
            by[r["sentence_id"]][0].append(i)
        elif sel_unf(r):
            by[r["sentence_id"]][1].append(i)

    per = {}
    for sid, (f, u) in by.items():
        num = den = 0.0
        for i in f:
            for j in u:
                num += (s[i] > s[j]) + 0.5 * (s[i] == s[j])
                den += 1
        per[sid] = (num, den)

    def stat(sids_count: Counter):
        num = sum(k * per[sid][0] for sid, k in sids_count.items() if sid in per)
        den = sum(k * per[sid][1] for sid, k in sids_count.items() if sid in per)
        return num / den if den else None
    base = Counter({sid: 1 for sid in by})
    pt = stat(base)
    n_pairs = sum(len(f) * len(u) for f, u in by.values())
    n_sent = sum(1 for f, u in by.values() if f and u)
    n_unf = sum(len(u) for f, u in by.values())
    sids_all = sorted(by)
    rng = np.random.default_rng(1)
    vals = []
    for _ in range(1000):
        pick = Counter(rng.choice(sids_all, size=len(sids_all), replace=True)) if sids_all else Counter()
        vals.append(stat(pick))
    return {"p_correct_order": pt, **ci_block(vals), "n_pairs": n_pairs, "n_sentences": n_sent,
            "n_unfaithful_items": n_unf, "underpowered": n_unf < 20}


# ============================================================================================ main analysis
def main() -> None:
    rows, meta = build_table()
    logger.info(f"labelled rows {len(rows)}; meta {meta}")
    C = Ctx(rows)
    A = {"meta": meta, "label_source": LABEL}
    T = {"label_source": LABEL}
    sens = jload(RES / "sensitivity_check.json") if (RES / "sensitivity_check.json").exists() else None
    weak = bool(sens and sens.get("panel_weak_on_exceptions"))
    A["sensitivity_check"] = sens or {"status": "not run", "reason": "run-level OpenRouter budget exhausted (HTTP 403 "
                                      "aii_run_budget_exhausted) before the check; the panel's ability to see exception "
                                      "errors in long formulas is therefore UNCERTIFIED"}
    T["panel_exception_caveat"] = "panel weak on exceptions" if weak else ("panel exception sensitivity not certified (check not run)" if not sens else "ok")
    # ---------------------------------------------------------------- label summary
    y, w = C.y, C.w
    A["labels"] = {"n": len(rows), "weighted_faithful_share": float((w * y).sum() / w.sum()),
                   "unweighted_faithful_share": float(y.mean()), "effective_positives_kish": kish(w[y == 1]),
                   "effective_negatives_kish": kish(w[y == 0]), "n_pos": int(y.sum()), "n_neg": int((1 - y).sum()),
                   "by_frame": {f: {"n": int(sum(r["frame"] == f for r in rows)),
                                    "w_faithful": float(sum(r["w"] * r["y"] for r in rows if r["frame"] == f) /
                                                        max(1e-9, sum(r["w"] for r in rows if r["frame"] == f)))} for f in ("A", "B")},
                   "sentence_ambiguous_rate": float(np.mean([bool(r.get("sentence_ambiguous")) for r in rows])),
                   "unanimous_rate": float(np.mean([r["unanimous"] for r in rows]))}
    A["labels"]["class_imbalance_F7"] = not (0.12 <= A["labels"]["weighted_faithful_share"] <= 0.88)
    A["labels"]["faithful_by_system"] = {s: float(sum(r["w"] * r["y"] for r in rows if r["system"] == s) /
                                                  max(1e-9, sum(r["w"] for r in rows if r["system"] == s)))
                                         for s in SYSTEMS + ["pilot"]}
    A["labels"]["faithful_by_bin"] = {b: {"n": int(sum(r["marker_bin"] == b for r in rows)),
                                          "w_faithful": float(sum(r["w"] * r["y"] for r in rows if r["marker_bin"] == b) /
                                                              max(1e-9, sum(r["w"] for r in rows if r["marker_bin"] == b)))}
                                      for b in ("B0", "B1", "B2")}
    A["labels"]["faithful_by_source"] = {a: float(sum(r["w"] * r["y"] for r in rows if r["act"] == a) /
                                                  max(1e-9, sum(r["w"] for r in rows if r["act"] == a)))
                                         for a in sorted({r["act"] for r in rows})}
    A["labels"]["faithful_parse_ok_vs_not"] = {str(k): float(np.mean([r["y"] for r in rows if r["parse_ok"] == k]) if any(r["parse_ok"] == k for r in rows) else float("nan"))
                                               for k in (True, False)}
    A["agreement"] = panel_agreement(rows)
    # ---------------------------------------------------------------- X1
    x1 = {m: auc_block(C, m) for m in METRICS + TWO_SYS if any(r.get(m) is not None for r in rows)}
    dc = x1["DC"]
    T["X1"] = {"metric": "weighted AUROC(DC) on P (480 system + 200 pilot items, labelled subset)", **dc,
               "pass": bool(dc["auroc_w"] is not None and dc["auroc_w"] >= 0.70 and dc["lb90"] > 0.5),
               "criterion": "point >= 0.70 and one-sided 95% lower bound > 0.5",
               "baselines": {m: {k: v[k] for k in ("auroc_w", "ci95", "n", "coverage") if k in v} for m, v in x1.items()}}
    for fr in ("A", "B"):
        idx = np.array([r["frame"] == fr for r in rows])
        T["X1"][f"frame_{fr}"] = {m: auc_block(C, m, idx) for m in ("DC", "DC_noL3", "B1", "B1plus", "LC_maj", "DS_bin", "VC", "B3nli", "B2", "DC_lone")
                                  if any(rows[i].get(m) is not None for i in np.where(idx)[0])}
    covered = np.array([bool(r.get("DC_cov")) for r in rows])
    T["X1"]["covered_only"] = {m: auc_block(C, m, covered) for m in ("DC", "B1", "B1plus", "LC_maj", "VC")}
    T["X1"]["covered_share"] = float(covered.mean())
    # ---------------------------------------------------------------- X2
    base = stack(C, ["B1", "B2"])
    withdc = stack(C, ["B1", "B2", "DC"])
    x2 = delta_block(C, withdc, base)
    T["X2"] = {"metric": "cross-fitted dAUROC oof_stack([B1, parse, DC]) - oof_stack([B1, parse])", **x2,
               "auroc_base": wauc(y, base, w), "auroc_with_dc": wauc(y, withdc, w),
               "pass": bool(x2["lb90"] is not None and x2["lb90"] > 0), "criterion": "one-sided 95% lower bound > 0"}
    rng = np.random.default_rng(SEED)
    for r in rows:
        r["RANDOM"] = float(rng.random())
    C2 = Ctx(rows)
    plc = delta_block(C2, stack(C2, ["B1", "B2", "RANDOM"]), stack(C2, ["B1", "B2"]))
    T["X2"]["placebo_random_feature"] = {**plc, "contains_0": bool(plc["ci95"][0] <= 0 <= plc["ci95"][1])}
    sec = {}
    fullb = ["B1", "B2", "B3nli", "B3cos", "B7"]
    sec["full_base_plus_DC"] = {**delta_block(C, stack(C, fullb + ["DC"]), stack(C, fullb)), "base": fullb}
    for other in ("LC_maj", "DS_bin", "VC", "DC_noL3"):
        ok = C.mask(other)
        sec[f"DC_minus_{other}"] = delta_block(C, C.col("DC"), C.col(other), ok)
        sec[f"stack_B1_parse_DC_vs_{other}"] = delta_block(C, withdc, stack(C, ["B1", "B2", other]))
    sec["frontier_gap_stack_minus_pro"] = delta_block(C, withdc, C.col("B1plus"), C.mask("B1plus"))
    sec["pro_minus_B1"] = delta_block(C, C.col("B1plus"), C.col("B1"), C.mask("B1plus"))
    sec["stack_B1_parse_pro_plus_DC"] = delta_block(C, stack(C, ["B1", "B2", "B1plus", "DC"]), stack(C, ["B1", "B2", "B1plus"]))
    T["X2"]["secondary"] = sec
    T["X2"]["covered_only"] = {**delta_block(C, stack(C, ["B1", "B2", "DC"], covered), stack(C, ["B1", "B2"], covered), covered),
                               "n": int(covered.sum())}
    T["F3_coverage_collapse"] = {"share_with_2plus_covered_peers": float(np.mean([bool(r.get("DC_cov")) for r in rows])),
                                 "triggered": float(np.mean([bool(r.get("DC_cov")) for r in rows])) < 0.30}
    # ---------------------------------------------------------------- X3
    T["X3"] = x3_block(C, rows)
    # ---------------------------------------------------------------- X4
    T["X4"] = x4_block(C, rows)
    # ---------------------------------------------------------------- X5
    T["X5"] = x5_block(rows)
    # ---------------------------------------------------------------- secondary analyses
    A["X1_full"] = x1
    A["coverage"] = coverage_block(rows)
    A["system_level"] = system_level(rows)
    A["error_distribution_vs_round1"] = error_dist(rows)
    A["shared_bias_boundary"] = shared_bias(C, rows)
    A["label_robustness"] = label_robustness(rows)
    A["cost"] = cost_block(rows)
    A["dev_anchor"] = jload(RES / "dev_anchor.json") if (RES / "dev_anchor.json").exists() else {"status": "not run"}
    A["invariance"] = jload(RES / "invariance.json") if (RES / "invariance.json").exists() else {"status": "not run"}
    if any(r.get("DC_placebo") is not None for r in rows):
        A["placebo_shuffled_peers"] = {"DC_placebo": auc_block(C, "DC_placebo"),
                                       "expected": "AUROC ~ 0.5 (peers from another sentence carry no information)",
                                       "share_DC_placebo_gt0": float(np.mean([(r.get("DC_placebo") or 0) > 0 for r in rows if r.get("DC_placebo") is not None]))}
    else:
        A["placebo_shuffled_peers"] = {"status": "not run"}
    A["cross_impl"] = jload(RES / "cross_impl.json") if (RES / "cross_impl.json").exists() else {"status": "not run"}
    A["dc_arb_info"] = jload(RES / "dc_arb_info.json") if (RES / "dc_arb_info.json").exists() else {"status": "not run"}
    pidx = np.array([bool(r["parse_ok"]) for r in rows])
    A["parseable_only"] = {m: auc_block(C, m, pidx) for m in ("DC", "DC_noL3", "DC_fp", "LC_maj", "DS_bin", "DS_dc", "VC",
                                                              "B1", "B1plus", "B3nli", "B3cos", "B7", "DC_arb")}
    A["parseable_only"]["DC_minus_LC_maj"] = delta_block(C, C.col("DC"), C.col("LC_maj"), pidx)
    A["posthoc_DC_unparse0"] = {"note": "POST-HOC diagnostic, not pre-registered: DC scoring unparseable candidates 0 "
                                        "(the LC_maj/DS_bin convention) instead of the contract's 0.5",
                                "auroc": auc_block(C, "DC_unparse0"),
                                "minus_LC_maj": delta_block(C, C.col("DC_unparse0"), C.col("LC_maj"))}
    A["cross_reference_items"] = {k: auc_block(C, "DC", np.array([r["has_cross_reference"] == k for r in rows])) for k in (True, False)}
    A["pilot_condition_note"] = "pilot formulas pooled across grounded/ungrounded conditions; condition never analysed (out of scope)"
    jdump(T, RES / "tests.json")
    jdump(A, RES / "analysis.json")
    write_exception_set(rows)
    logger.info("X1 " + json.dumps({k: T['X1'][k] for k in ('auroc_w', 'ci95', 'lb90', 'pass')}))
    logger.info("X2 " + json.dumps({k: T['X2'][k] for k in ('delta', 'ci95', 'lb90', 'pass')}))


def panel_agreement(rows: list[dict]) -> dict:
    from itertools import combinations
    mem = ["M1", "M2", "M3"]
    full = [r for r in rows if all(m in r["votes"] for m in mem)]

    def fleiss(items):
        if not items:
            return None
        n = 3
        P, pj = [], np.zeros(2)
        for r in items:
            k = sum(r["votes"][m] for m in mem)
            cnt = np.array([n - k, k])
            pj += cnt
            P.append((cnt * (cnt - 1)).sum() / (n * (n - 1)))
        pj /= len(items) * n
        Pb, Pe = np.mean(P), (pj ** 2).sum()
        return float((Pb - Pe) / (1 - Pe)) if Pe < 1 else None

    def cohen(a, b):
        a, b = np.array(a, float), np.array(b, float)
        po = (a == b).mean()
        pe = a.mean() * b.mean() + (1 - a.mean()) * (1 - b.mean())
        return float((po - pe) / (1 - pe)) if pe < 1 else None
    out = {"n_full_panel": len(full), "fleiss_kappa": fleiss(full),
           "pairwise_cohen": {f"{a}-{b}": cohen([r["votes"][a] for r in full], [r["votes"][b] for r in full]) for a, b in combinations(mem, 2)},
           "member_faithful_rate": {m: float(np.mean([r["votes"][m] for r in full])) for m in mem}}
    out["by_bin"] = {b: {"n": sum(r["marker_bin"] == b for r in full), "fleiss_kappa": fleiss([r for r in full if r["marker_bin"] == b])}
                     for b in ("B0", "B1", "B2")}
    return out


def x3_block(C: Ctx, rows: list[dict]) -> dict:
    out = {"per_bin": {}}
    for b in ("B0", "B1", "B2"):
        idx = np.array([r["marker_bin"] == b for r in rows])
        blk = {m: auc_block(C, m, idx) for m in ("DC", "B1", "B1plus", "B3nli", "VC", "DC_noL3", "LC_maj")}
        blk["gap_DC_minus_B1"] = delta_block(C, C.col("DC"), C.col("B1"), idx)
        blk["n_items"] = int(idx.sum())
        blk["n_pos"] = int(C.y[idx].sum())
        blk["underpowered"] = int(C.y[idx].sum()) < 20 or int((1 - C.y[idx]).sum()) < 20
        out["per_bin"][b] = blk

    def slope_stat(sel_rows_idx, rows_sub_w):
        # per-sentence within-sentence AUROC gap (DC - B1) regressed on marker count (WLS, weight = #pairs)
        by = defaultdict(list)
        for i in sel_rows_idx:
            by[C.rows[i]["sentence_id"]].append(i)
        xs, gs, ws = [], [], []
        s_dc, s_b1 = C.col("DC"), C.col("B1")
        for sid, ii in by.items():
            yy = C.y[ii]
            if yy.min() == yy.max():
                continue
            g = wauc(yy, s_dc[ii], None) - wauc(yy, s_b1[ii], None)
            xs.append(C.rows[ii[0]]["n_markers"])
            gs.append(g)
            ws.append(yy.sum() * (1 - yy).sum())
        if len(xs) < 3:
            return None, len(xs)
        X = np.column_stack([np.ones(len(xs)), xs])
        W = np.diag(ws)
        try:
            beta = np.linalg.solve(X.T @ W @ X, X.T @ W @ np.array(gs))
        except np.linalg.LinAlgError:
            return None, len(xs)
        return float(beta[1]), len(xs)

    def slope_with_ci(mask):
        idx_all = np.where(mask)[0]
        pt, n = slope_stat(idx_all, None)
        vals = []
        for bt in C.boot:
            bb = [i for i in bt if mask[i]]
            v, _ = slope_stat(bb, None)
            vals.append(v)
        return {"slope": pt, **ci_block(vals), "n_sentences_with_both_labels": n}
    allm = np.ones(len(rows), bool)
    cov = np.array([bool(r.get("DC_cov")) for r in rows])
    out["within_sentence_gap_slope"] = slope_with_ci(allm)
    out["within_sentence_gap_slope_covered_only"] = slope_with_ci(cov)
    out["logistic_interaction"] = logit_interaction(C, allm)
    out["logistic_interaction_covered_only"] = logit_interaction(C, cov)
    out["prediction"] = "slope >= 0 (DC's advantage over B1 does not shrink with more exception/condition markers)"
    return out


def logit_interaction(C: Ctx, mask) -> dict:
    from sklearn.linear_model import LogisticRegression

    def fit(ii):
        ii = np.asarray(ii)
        if len(np.unique(C.y[ii])) < 2:
            return None
        m = np.array([C.rows[i]["n_markers"] for i in ii], float)
        dcv, b1 = C.col("DC")[ii], C.col("B1")[ii]
        mm = (m - m.mean()) / (m.std() + 1e-9)
        X = np.column_stack([dcv, b1, dcv * mm, b1 * mm, mm])
        lr = LogisticRegression(C=1.0, max_iter=2000).fit(X, C.y[ii], sample_weight=C.w[ii])
        return float(lr.coef_[0][2] - lr.coef_[0][3])
    idx = np.where(mask)[0]
    pt = fit(idx)
    vals = [fit([i for i in bt if mask[i]]) for bt in list(C.boot)[:500]]
    return {"beta_DCxmarkers_minus_B1xmarkers": pt, **ci_block(vals), "n_boot": 500}


def x4_block(C: Ctx, rows: list[dict]) -> dict:
    types = {"dropped_condition": lambda r: r.get("primary_error") == "dropped_condition",
             "added_condition": lambda r: r.get("primary_error") == "added_condition",
             "implication_direction_or_only": lambda r: r.get("primary_error") == "implication_direction_or_only",
             "exception_involved": lambda r: bool(r.get("exception_involved")),
             "any_unfaithful": lambda r: True}
    out = {"within_sentence": {}}
    for t, f in types.items():
        out["within_sentence"][t] = {m: within_pairs(C, m, f) for m in ("DC", "B1", "B1plus", "DC_noL3", "LC_maj")}
    # DC error naming vs panel primary error on panel-unfaithful covered items
    unf = [r for r in rows if r["y"] == 0 and r.get("DC_cov") and r.get("DC_error_type") not in (None, "none")]
    unf_all = [r for r in rows if r["y"] == 0 and r.get("DC_cov")]
    tot = sum(r["w"] for r in unf_all) or 1.0
    acc = sum(r["w"] for r in unf_all if r.get("DC_error_type") == r.get("primary_error")) / tot
    maj_class = Counter()
    for r in unf_all:
        maj_class[r.get("primary_error")] += r["w"]
    mc = maj_class.most_common(1)[0][0] if maj_class else None
    conf = defaultdict(lambda: defaultdict(float))
    for r in unf_all:
        conf[r.get("primary_error")][r.get("DC_error_type")] += r["w"]
    recall = {k: (v.get(k, 0.0) / sum(v.values()) if sum(v.values()) else None) for k, v in conf.items()}
    out["error_naming"] = {"n_items": len(unf_all), "n_items_dc_named": len(unf), "weighted_top1": acc,
                           "majority_class": mc, "majority_class_top1": (maj_class[mc] / tot) if mc else None,
                           "per_type_recall": recall, "confusion_weighted": {k: dict(v) for k, v in conf.items()},
                           "exception_flag_agreement": exception_flag_agreement(unf_all)}
    return out


def exception_flag_agreement(unf_all):
    a = [(bool(r.get("DC_exception_involved")), bool(r.get("exception_involved"))) for r in unf_all]
    if not a:
        return None
    tp = sum(x and y for x, y in a)
    return {"n": len(a), "panel_exception_rate": sum(y for _, y in a) / len(a), "dc_exception_rate": sum(x for x, _ in a) / len(a),
            "precision": tp / max(1, sum(x for x, _ in a)), "recall": tp / max(1, sum(y for _, y in a))}


def x5_block(rows: list[dict]) -> dict:
    sub = [r for r in rows if r["system"] in ("gpt-4.1-mini", "llama-3.1-8b")]
    out = {}
    if sub:
        C = Ctx(sub, nboot=NBOOT, seed=5)
        out["sampled_systems"] = {"DC_lone": auc_block(C, "DC_lone"), "B8": auc_block(C, "B8"),
                                  "B7_jacc": auc_block(C, "B7_jacc"), "DC": auc_block(C, "DC"),
                                  "delta_DC_lone_minus_B8": delta_block(C, C.col("DC_lone"), C.col("B8")),
                                  "n": len(sub)}
    pil = [r for r in rows if r["frame"] == "B"]
    if pil:
        C = Ctx(pil, nboot=NBOOT, seed=6)
        for r in pil:
            r["pilot_metric2_inv"] = None if r.get("pilot_metric2") is None else 1 - r["pilot_metric2"]
        C = Ctx(pil, nboot=NBOOT, seed=6)
        out["pilot"] = {"DC_lone": auc_block(C, "DC_lone"), "pilot_metric5_jaccard": auc_block(C, "pilot_metric5"),
                        "pilot_metric2_consistency": auc_block(C, "pilot_metric2_inv"), "DC": auc_block(C, "DC"),
                        "B1": auc_block(C, "B1"),
                        "delta_DC_lone_minus_metric5": delta_block(C, C.col("DC_lone"), C.col("pilot_metric5"), C.mask("pilot_metric5")),
                        "n": len(pil)}
    return out


def coverage_block(rows: list[dict]) -> dict:
    cands = read_jsonl(WORK / "candidates.jsonl")
    dc = {r["cand_id"]: r for r in read_jsonl(RES / "dc_scores_frozen.jsonl")}
    sents = {s["sentence_id"]: s for s in jload(WORK / "sentences.json")}
    allr = []
    for c in cands:
        if c["cand_id"] in dc:
            d = dc[c["cand_id"]]
            allr.append({**d, "bin": sents[c["sentence_id"]]["marker_bin"], "n_preds": c.get("n_preds")})
    nps = sorted(r["n_preds"] for r in allr if r["n_preds"] is not None)
    t1, t2 = (nps[len(nps) // 3], nps[2 * len(nps) // 3]) if nps else (0, 0)

    def summ(sel):
        n = len(sel)
        if not n:
            return {"n": 0}
        rc = Counter()
        lv = Counter()
        for r in sel:
            for k, v in (r.get("DC_rel_counts") or {}).items():
                rc[k] += v
            for k, v in (r.get("DC_levels") or {}).items():
                lv[k] += v
        tot = sum(rc.values()) or 1
        return {"n": n, "parse_rate": sum(r["parse_ok"] for r in sel) / n, "coverage": sum(bool(r.get("DC_cov")) for r in sel) / n,
                "pair_relations_share": {k: v / tot for k, v in rc.items()}, "unknown_share": rc.get("UNKNOWN", 0) / tot,
                "unalignable_share": rc.get("UNALIGNABLE", 0) / tot, "levels": dict(lv)}
    out = {"all": summ(allr), "by_bin": {b: summ([r for r in allr if r["bin"] == b]) for b in ("B0", "B1", "B2")},
           "n_preds_terciles": [t1, t2],
           "by_npreds_tercile": {"low": summ([r for r in allr if r["n_preds"] is not None and r["n_preds"] <= t1]),
                                 "mid": summ([r for r in allr if r["n_preds"] is not None and t1 < r["n_preds"] <= t2]),
                                 "high": summ([r for r in allr if r["n_preds"] is not None and r["n_preds"] > t2])},
           "by_frame": {f: summ([r for r in allr if r["frame"] == f]) for f in ("system", "pilot")}}
    timing = jload(RES / "dc_timing_legal.json") if (RES / "dc_timing_legal.json").exists() else {}
    out["timing"] = {k: timing.get(k) for k in ("n_pairs", "sec_mean", "sec_p90", "sec_total", "relations", "levels",
                                                 "sec_by_npreds", "wall_s", "n_missing_marked_unknown")}
    return out


def system_level(rows: list[dict]) -> dict:
    dc = read_jsonl(RES / "dc_scores_frozen.jsonl")
    mean_dc = {s: float(np.mean([r["DC"] for r in dc if r["system"] == s])) for s in SYSTEMS}
    mean_b1 = {}
    b1 = {r["key"]: r for r in read_jsonl(WORK / "b1.jsonl")}
    for s in SYSTEMS:
        mean_b1[s] = float(np.mean([b1[r["cand_id"]]["B1"] for r in dc if r["system"] == s and r["cand_id"] in b1]))
    truth = {s: float(sum(r["w"] * r["y"] for r in rows if r["system"] == s) / max(1e-9, sum(r["w"] for r in rows if r["system"] == s)))
             for s in SYSTEMS}
    parse = {s: float(np.mean([r["parse_ok"] for r in dc if r["system"] == s])) for s in SYSTEMS}
    return {"panel_faithful_rate": truth, "mean_DC": mean_dc, "mean_B1": mean_b1, "parse_rate": parse,
            "DC": kendall_pairwise(mean_dc, truth), "B1": kendall_pairwise(mean_b1, truth),
            "parse": kendall_pairwise(parse, truth), "note": "9 systems: descriptive only (tau CI spans most of [-1, 1])"}


def error_dist(rows: list[dict]) -> dict:
    ref = jload(VENDOR / "ds" / "work" / "label_report.json")["L3_error_type_distribution_weighted"]
    unf = [r for r in rows if r["y"] == 0 and r.get("primary_error")]

    def dist(sel):
        c = defaultdict(float)
        for r in sel:
            c[r["primary_error"]] += r["w"]
        t = sum(c.values()) or 1
        return {k: v / t for k, v in c.items()}
    d = dist(unf)
    keys = sorted(set(d) | set(ref))
    tvd = 0.5 * sum(abs(d.get(k, 0) - ref.get(k, 0)) for k in keys)
    by_s = defaultdict(list)
    for r in unf:
        by_s[r["sentence_id"]].append(r)
    sids = sorted(by_s)
    rng = np.random.default_rng(2)
    vals = []
    for _ in range(1000):
        pick = [r for s in rng.choice(sids, size=len(sids), replace=True) for r in by_s[s]]
        dd = dist(pick)
        vals.append(0.5 * sum(abs(dd.get(k, 0) - ref.get(k, 0)) for k in keys))
    exc = [r for r in unf if r.get("exception_involved")]
    return {"legal_distribution_weighted": d, "round1_public_reference": ref, "tvd": tvd, **ci_block(vals),
            "n_unfaithful": len(unf), "exception_involved_share": len(exc) / max(1, len(unf)),
            "per_type_table": {k: {"legal": d.get(k, 0.0), "public_round1": ref.get(k, 0.0)} for k in keys}}


def shared_bias(C: Ctx, rows: list[dict]) -> dict:
    mode = jload(RES / "dc_mode_info.json")
    lab = {r["item_id"]: r for r in rows}
    sent_mode_ok = {}
    for sid, m in mode.items():
        rep = m["mode_rep"]
        if rep in lab:
            sent_mode_ok[sid] = lab[rep]["y"]
        else:
            ys = [r["y"] for r in rows if r["sentence_id"] == sid and r.get("DC_rel_to_mode") == "EQUIV" and r["frame"] == "A"]
            if ys:
                sent_mode_ok[sid] = int(np.mean(ys) >= 0.5)
    out = {"n_sentences_mode_labelled": len(sent_mode_ok),
           "mode_unfaithful_share": float(1 - np.mean(list(sent_mode_ok.values()))) if sent_mode_ok else None}
    for k, name in ((1, "mode_faithful"), (0, "mode_unfaithful")):
        idx = np.array([sent_mode_ok.get(r["sentence_id"]) == k for r in rows])
        out[name] = {m: auc_block(C, m, idx) for m in ("DC", "B1")}
    shares = [m["mode_weight_share"] for m in mode.values()]
    out["modal_weight_share_mean"] = float(np.mean(shares)) if shares else None
    out["prediction"] = "DC AUROC drops when the mode is panel-unfaithful"
    return out


def label_robustness(rows_base: list[dict]) -> dict:
    out = {}
    variants = {"M1_only": {"M1"}, "M2_only": {"M2"}, "M3_only": {"M3"}}
    for name, mem in variants.items():
        lab = load_labels(mem)
        rows = [dict(r, y=lab[r["item_id"]]["y"]) for r in rows_base if r["item_id"] in lab]
        out[name] = robust_x12(rows)
    rows = [r for r in rows_base if r["unanimous"] and r["n_votes"] == 3]
    out["unanimous_only"] = robust_x12(rows)
    return out


def robust_x12(rows: list[dict]) -> dict:
    if len(rows) < 30 or len({r["y"] for r in rows}) < 2:
        return {"n": len(rows), "note": "too few"}
    C = Ctx(rows, nboot=1000, seed=7)
    x1 = {m: auc_block(C, m) for m in ("DC", "B1", "B1plus", "LC_maj")}
    x2 = delta_block(C, stack(C, ["B1", "B2", "DC"]), stack(C, ["B1", "B2"]))
    return {"n": len(rows), "w_faithful": float((C.w * C.y).sum() / C.w.sum()), "X1": x1, "X2": x2}


def cost_block(rows: list[dict]) -> dict:
    led = read_jsonl(WORK / "cost_ledger.jsonl")
    ph = defaultdict(float)
    for r in led:
        ph[r["phase"]] += r["cost_usd"]
    b1 = read_jsonl(WORK / "b1.jsonl")
    b1p = read_jsonl(WORK / "b1plus.jsonl")
    dcs = read_jsonl(RES / "dc_scores_frozen.jsonl")
    timing = jload(RES / "dc_timing_legal.json") if (RES / "dc_timing_legal.json").exists() else {}
    n_scored = len(dcs)
    gen_per_sentence = ph.get("generation", 0.0) / max(1, len(jload(WORK / "sentences.json")))
    return {"usd_by_phase": dict(ph), "usd_total": sum(ph.values()),
            "B1_usd_per_item": float(np.mean([r.get("B1_usd") or 0 for r in b1])) if b1 else None,
            "B1plus_usd_per_item": float(np.mean([r.get("B1plus_usd") or 0 for r in b1p])) if b1p else None,
            "panel_usd_per_item": ph.get("panel", 0.0) / max(1, len(rows)),
            "DC_cpu_seconds_total": timing.get("sec_total"), "DC_wall_seconds": timing.get("wall_s"),
            "DC_cpu_seconds_per_scored_item": (timing.get("sec_total") or 0) / max(1, n_scored),
            "DC_usd_per_item_peers_exist": 0.0,
            "DC_usd_per_item_peers_generated": gen_per_sentence,
            "note": "DC needs no API call when peers exist (i); when peers must be generated (ii) the cost is the 8 other "
                    "systems' greedy calls for the sentence (mean generation $/sentence over 19 calls reported)"}


def write_exception_set(rows: list[dict]) -> None:
    sents = {s["sentence_id"]: s for s in jload(WORK / "sentences.json")}
    cands = {c["cand_id"]: c for c in read_jsonl(WORK / "candidates.jsonl")}
    lab = load_labels()
    samp = {s["item_id"]: s for s in jload(WORK / "panel_sample.json")["items"]}
    wmap = {r["item_id"]: r["w"] for r in rows}
    out = []
    for iid, s in samp.items():
        c = cands[iid]
        st = sents[c["sentence_id"]]
        L = lab.get(iid)
        out.append({"item_id": iid, "sentence_id": c["sentence_id"], "sentence": st["sentence"], "fol": c["fol"],
                    "system": c["system"], "model": c.get("model"), "frame": s["frame"], "stratum": s["stratum"],
                    "weight": wmap.get(iid), "source": st["source"], "act": st["act"], "article": st["article"],
                    "licence": st["licence"], "url": st["url"], "marker_bin": st["marker_bin"], "n_markers": st["n_markers"],
                    "exception_markers": st["exception_markers"], "n_tokens": st["n_tokens"], "nesting": st["nesting"],
                    "has_cross_reference": st["has_cross_reference"], "parse_ok": c["parse_ok"], "parse_error": c.get("parse_error"),
                    "label": (None if L is None else ("faithful" if L["y"] else "unfaithful")),
                    "label_source": "panel3_nogold" if L else "unlabelled_budget_stop",
                    "primary_error": L["primary_error"] if L else None, "exception_involved": L["exception_involved"] if L else None,
                    "error_types": L["error_types"] if L else None,
                    "votes": ({m: {k: v.get(k) for k in ("model", "faithful", "primary_error", "error_types", "exception_involved",
                                                        "sentence_ambiguous", "explanation", "cost_usd")} for m, v in L["member_rows"].items()} if L else None),
                    "gen_usd": c.get("gen_usd"), "pilot_condition": c.get("pilot_condition"), "pilot_run": c.get("pilot_run")})
    write_jsonl(RES / "exception_set.jsonl", out)


if __name__ == "__main__":
    main()
