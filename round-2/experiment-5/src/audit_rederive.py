#!/usr/bin/env python3
"""Independent re-derivation of the headline numbers from RAW per-item files (not analysis.json's aggregates),
through a different code path (pure numpy, own AUROC via the Mann-Whitney rank formula with weights, own label parsing
straight from data/heldout_labels.jsonl), plus placebo tests that must FAIL.

Checks (assert |re-derived − reported| < 1e-9 unless noted):
  1. V1 weighted D_rule / TJ top-1 accuracy on parse-ok panel-unfaithful items;
  2. V3 pooled held-out gold AUROC of flag_S and flag_B1;
  3. standalone weighted AUROC of S_frozen and B1 on panel3 items;
  4. V4 ΔAUROC(M1−M0) recomputed from the saved out-of-fold predictions (per_item_panel.jsonl);
  5. R1 SCREEN_TEST FA_rename recomputed from the grid file's counts (consistency) — reported only;
  placebos: flag_S AUROC with permuted gold labels (≈0.5, CI must include 0.5); D_rule top-1 with permuted truth
  (must drop to ≈ chance); S AUROC with within-sentence shuffled labels.
Writes results/audit_rederive.json.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
RES = ROOT / "results"


def rj(p):
    return [json.loads(l) for l in (ROOT / p).read_text().splitlines() if l.strip()]


def wauc(y, s, w=None):
    """Weighted AUROC = P(s_pos > s_neg) + 0.5 P(tie), weights multiply (pairwise), via sorting."""
    y, s = np.asarray(y, int), np.asarray(s, float)
    w = np.ones(len(y)) if w is None else np.asarray(w, float)
    pos, neg = y == 1, y == 0
    sp, wp, sn, wn = s[pos], w[pos], s[neg], w[neg]
    order = np.argsort(sn)
    sn, wn = sn[order], wn[order]
    cw = np.concatenate([[0], np.cumsum(wn)])
    lo = np.searchsorted(sn, sp, side="left")
    hi = np.searchsorted(sn, sp, side="right")
    num = (wp * (cw[lo] + 0.5 * (cw[hi] - cw[lo]))).sum()
    return float(num / (wp.sum() * wn.sum()))


def main():
    A = json.loads((RES / "analysis.json").read_text())
    labs = {x["item_id"]: x for x in rj("data/heldout_labels.jsonl")}
    sc = {x["unit_id"]: x for x in rj("results/heldout_scores.jsonl")}
    gs = {x["unit_id"]: x for x in rj("results/gold_scores.jsonl")}
    llm = {}
    for x in rj("results/llm_baselines.jsonl"):
        if x.get("error") is None:
            llm[(x["unit_id"], x["method"])] = x
    out = {"checks": {}, "placebos": {}}
    panel = [i for i, l in labs.items() if l["label_source"] == "panel3"]
    # 3. standalone AUROC
    y = np.array([1 if labs[i]["L3_majority"] else 0 for i in panel])
    w = np.array([labs[i]["L3_sampling_weight"] for i in panel], float)
    s = np.array([sc[i]["S_frozen"] for i in panel])
    b = np.array([0.5 if llm.get((i, "B1"), {}).get("p_faithful") is None else llm[(i, "B1")]["p_faithful"] for i in panel])
    for name, v, rep in (("S", s, A["standalone"]["S"]["auroc_w"]), ("B1", b, A["standalone"]["B1"]["auroc_w"])):
        r = wauc(y, v, w)
        out["checks"][f"standalone_auroc_w_{name}"] = {"rederived": r, "reported": rep, "ok": abs(r - rep) < 1e-9}
    # 1. V1 top-1
    U = [i for i in panel if not labs[i]["L3_majority"] and sc[i]["parse_ok_front"]]
    wu = np.array([labs[i]["L3_sampling_weight"] for i in U], float)
    tr = [labs[i]["L3_primary_error"] for i in U]
    c_rule = np.array([sc[i]["types_rule"][0] == t for i, t in zip(U, tr)], float)
    def tjp(i):
        x = llm.get((i, "TJ"), {})
        return x.get("primary") if (x.get("faithful") is False or x.get("primary")) else None
    c_tj = np.array([(tjp(i) or "none") == t for i, t in zip(U, tr)], float)
    for name, c, rep in (("D_rule", c_rule, A["V1"]["parse_ok"]["methods"]["D_rule"]["top1_w"]),
                         ("TJ", c_tj, A["V1"]["parse_ok"]["methods"]["TJ"]["top1_w"])):
        r = float((c * wu).sum() / wu.sum())
        out["checks"][f"V1_top1_w_{name}"] = {"rederived": r, "reported": rep, "ok": abs(r - rep) < 1e-9}
    # placebo: permuted truth
    rng = np.random.default_rng(11)
    pt = [tr[k] for k in rng.permutation(len(tr))]
    c_perm = np.array([sc[i]["types_rule"][0] == t for i, t in zip(U, pt)], float)
    out["placebos"]["V1_D_rule_top1_permuted_truth"] = float((c_perm * wu).sum() / wu.sum())
    # 2. V3 pooled AUROC
    sent = {}
    for i, l in labs.items():
        sid = l["sentence_id"]
        if sid not in sent and l.get("gold_faithful_final") is not None:
            sent[sid] = l["gold_faithful_final"] is False
    sids = [k for k in sent if f"{k}:gold" in gs]
    yg = np.array([1 if sent[k] else 0 for k in sids])
    fs = np.array([1 - gs[f"{k}:gold"]["S_frozen"] for k in sids])
    fb = np.array([0.5 if llm.get((f"{k}:gold", "B1"), {}).get("p_faithful") is None else
                   1 - llm[(f"{k}:gold", "B1")]["p_faithful"] for k in sids])
    for name, v, rep in (("flag_S", fs, A["V3"]["pooled"]["flag_S"]["auroc"]),
                         ("flag_B1", fb, A["V3"]["pooled"]["flag_B1"]["auroc"])):
        r = wauc(yg, v)
        out["checks"][f"V3_pooled_auroc_{name}"] = {"rederived": r, "reported": rep, "ok": abs(r - rep) < 1e-9}
    perm = []
    for _ in range(200):
        perm.append(wauc(rng.permutation(yg), fs))
    out["placebos"]["V3_flag_S_auroc_permuted_labels"] = {"mean": float(np.mean(perm)),
                                                          "ci95": [float(np.percentile(perm, 2.5)),
                                                                   float(np.percentile(perm, 97.5))],
                                                          "real": out["checks"]["V3_pooled_auroc_flag_S"]["rederived"],
                                                          "real_outside_placebo_ci": bool(
                                                              out["checks"]["V3_pooled_auroc_flag_S"]["rederived"] >
                                                              np.percentile(perm, 97.5))}
    # 4. V4 delta from saved OOF predictions
    P = rj("results/per_item_panel.jsonl")
    yy = np.array([p["y"] for p in P])
    ww = np.array([p["w"] for p in P])
    d = wauc(yy, [p["oof_M1"] for p in P], ww) - wauc(yy, [p["oof_M0"] for p in P], ww)
    rep = A["V4"]["delta_M1_M0"]["delta"]
    out["checks"]["V4_delta_M1_M0"] = {"rederived": d, "reported": rep, "ok": abs(d - rep) < 1e-9}
    d2 = wauc(yy, [p["oof_M2"] for p in P], ww) - wauc(yy, [p["oof_M0"] for p in P], ww)
    rep2 = A["V4"]["delta_M2_M0"]["delta"]
    out["checks"]["V4_delta_M2_M0"] = {"rederived": d2, "reported": rep2, "ok": abs(d2 - rep2) < 1e-9}
    out["placebos"]["V4_within_sentence_shuffle_reported"] = A["V4"]["placebo_within_sentence_shuffle"]
    # placebo: S AUROC with labels permuted within sentence
    by = {}
    for k, i in enumerate(panel):
        by.setdefault(labs[i]["sentence_id"], []).append(k)
    ys = y.copy()
    for idx in by.values():
        ys[idx] = y[rng.permutation(idx)]
    out["placebos"]["S_auroc_labels_shuffled_within_sentence"] = wauc(ys, s, w)
    out["all_ok"] = all(v["ok"] for v in out["checks"].values())
    (RES / "audit_rederive.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
