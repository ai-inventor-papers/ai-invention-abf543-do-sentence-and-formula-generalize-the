#!/usr/bin/env python3
"""T5 audit: re-derive three headline numbers with an INDEPENDENT numpy implementation (O(n^2) pairwise AUROC, no
shared code with dc/stats.py) and run the statistics placebos. -> results/audit_rederive.json"""
import json
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent
rj = lambda p: [json.loads(l) for l in Path(p).read_text().splitlines() if l.strip()]  # noqa: E731


def pw_auc(y, s, w):
    y, s, w = map(lambda a: np.asarray(a, float), (y, s, w))
    P, N = y == 1, y == 0
    d = s[P][:, None] - s[N][None, :]
    ww = w[P][:, None] * w[N][None, :]
    return float(((d > 0) + 0.5 * (d == 0)).astype(float).__mul__(ww).sum() / ww.sum())


frame = {r["item_id"]: r for r in rj(ROOT / "work" / "frame.jsonl") if r["fold"] == "heldout_confirm"}
sc = {r["item_id"]: r for r in rj(ROOT / "work" / "dc_scores.jsonl")}
out = {}
# (1) M0 panel weighted AUROC of DC
P = [r for r in frame.values() if r["label_source"] == "panel3" and r["output"] in ("faithful", "unfaithful")]
y = [1 if r["output"] == "faithful" else 0 for r in P]
s = [sc[r["item_id"]]["DC"] for r in P]
w = [float(r["L3_sampling_weight"] or 1) for r in P]
a = pw_auc(y, s, w)
ref = json.loads((ROOT / "results" / "m0_anchor.json").read_text())["panel_weighted"]["DC"]["auroc"]
out["M0_panel_DC_auroc"] = {"rederived": a, "reported": ref, "abs_diff": abs(a - ref), "match_1e-6": abs(a - ref) < 1e-6}
# (2) M1 DC arm gap conf - tok (paired non-iso non-fresh set)
pr = rj(ROOT / "work" / "m1_probes.jsonl")
have = {}
for p in pr:
    if p["kind"] == "M" and not p.get("iso_L1") and not p.get("fresh_pred"):
        have.setdefault((p["sid"], p["op"]), set()).add(p["arm"])
paired = {k for k, v in have.items() if v == {"conf", "tok", "syn"}}
sids = {k[0] for k in paired}


def arm_auc(arm):
    F = [p for p in pr if p["arm"] == arm and p["kind"] == "F" and p["sid"] in sids]
    M = [p for p in pr if p["arm"] == arm and p["kind"] == "M" and (p["sid"], p["op"]) in paired]
    return pw_auc([1] * len(F) + [0] * len(M), [p["DC"] for p in F + M], [1] * (len(F) + len(M)))
g = arm_auc("conf") - arm_auc("tok")
ref = json.loads((ROOT / "results" / "m1_confound.json").read_text())["gaps"]["DC"]["conf_minus_tok"]["gap"]
out["M1_DC_arm_gap_conf_minus_tok"] = {"rederived": g, "reported": ref, "abs_diff": abs(g - ref), "match_1e-6": abs(g - ref) < 1e-6}
# (3) M3 pooled detection at k=4 (random order)
D = rj(ROOT / "work" / "m3_dose.jsonl")
v = [(1.0 if r["DC_F"] > r["DC_M"] else 0.5 if r["DC_F"] == r["DC_M"] else 0.0) for d in D for r in d["rows"]
     if r["order"] == "random" and r["k"] == 4]
det = float(np.mean(v))
ref = json.loads((ROOT / "results" / "m3_boundary.json").read_text())["a_dose"]["random"]["k=4"]["pooled"]["det_DC"]["mean"]
out["M3_det_k4"] = {"rederived": det, "reported": ref, "abs_diff": abs(det - ref), "match_1e-6": abs(det - ref) < 1e-6}
# placebos
rng = np.random.default_rng(0)
perm = [pw_auc(rng.permutation(y), s, w) for _ in range(200)]
out["placebo_permuted_label_auroc"] = {"mean": float(np.mean(perm)), "sd": float(np.std(perm))}
rnd = [pw_auc(y, rng.random(len(y)), w) for _ in range(200)]
out["placebo_random_metric_auroc"] = {"mean": float(np.mean(rnd)), "sd": float(np.std(rnd))}
m1 = json.loads((ROOT / "results" / "m1_confound.json").read_text())["M1b_real_dev"]
out["placebo_random_stacking_feature_delta"] = {k: v2["placebo_random_feature_delta"] for k, v2 in m1.items() if k.startswith("stack")}
out["ALL_MATCH"] = all(out[k]["match_1e-6"] for k in ("M0_panel_DC_auroc", "M1_DC_arm_gap_conf_minus_tok", "M3_det_k4"))
(ROOT / "results" / "audit_rederive.json").write_text(json.dumps(out, indent=1))
print(json.dumps(out, indent=1))
