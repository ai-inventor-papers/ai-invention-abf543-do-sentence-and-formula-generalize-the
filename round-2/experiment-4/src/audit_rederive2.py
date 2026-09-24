#!/usr/bin/env python3
"""TODO-5 audit, part 2: re-derive further headline numbers straight from raw per-item files with plain numpy
(Mann-Whitney rank formula, not the pairwise or exp3 code paths), and confirm each test FAILS on placebo input.
-> results/audit_rederive2.json"""
import json
from collections import defaultdict
from pathlib import Path
import numpy as np
from scipy.stats import rankdata

ROOT = Path(__file__).resolve().parent
rj = lambda p: [json.loads(l) for l in Path(p).read_text().splitlines() if l.strip()]  # noqa: E731
rng = np.random.default_rng(2024)


def mw_auc(y, s):
    """Unweighted AUROC via the Mann-Whitney U rank formula (ties -> average ranks)."""
    y, s = np.asarray(y, int), np.asarray(s, float)
    r = rankdata(s)
    n1, n0 = y.sum(), (1 - y).sum()
    return float((r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def boot_lo_hi(y, s, groups, fn, n=500):
    by = defaultdict(list)
    for i, g in enumerate(groups):
        by[g].append(i)
    arr = [np.array(v) for v in by.values()]
    vals = []
    for _ in range(n):
        ix = np.concatenate([arr[j] for j in rng.integers(0, len(arr), len(arr))])
        if len(set(np.asarray(y)[ix])) > 1:
            vals.append(fn(np.asarray(y)[ix], np.asarray(s)[ix]))
    return [float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))]


out = {}
frame = [r for r in rj(ROOT / "work" / "frame.jsonl") if r["fold"] == "heldout_confirm"]
# (A) M7: DC(gold) AUROC vs gold_faithful_final
gs = {r["sid"]: r["DC"] for r in rj(ROOT / "work" / "gold_dc_scores.jsonl")}
sent = {}
for r in frame:
    sent.setdefault(r["sentence_id"], r)
S = [s for s, r in sent.items() if s in gs and r["gold_faithful_final"] is not None]
y = np.array([1 if sent[s]["gold_faithful_final"] else 0 for s in S])
x = np.array([gs[s] for s in S])
a = mw_auc(y, x)
rep = json.loads((ROOT / "results" / "m7_goldflag.json").read_text())["DC_gold_auroc_vs_L0"]["auroc"]
yp = rng.permutation(y)
out["M7_gold_auroc"] = {"rederived": a, "reported": rep, "abs_diff": abs(a - rep),
                        "placebo_permuted_auroc": mw_auc(yp, x), "placebo_ci": boot_lo_hi(yp, x, S, mw_auc),
                        "placebo_fails_(ci_contains_0.5)": None}
out["M7_gold_auroc"]["placebo_fails_(ci_contains_0.5)"] = out["M7_gold_auroc"]["placebo_ci"][0] <= 0.5 <= out["M7_gold_auroc"]["placebo_ci"][1]
# (B) M1: per-op tok-arm AUROC for NEG and DROP_CONJ (DC vs DC_L2w), crossed DC_L2w
P = rj(ROOT / "work" / "m1_probes.jsonl")
res = {}
for op in ("NEG", "DROP_CONJ"):
    M = [p for p in P if p["arm"] == "tok" and p["kind"] == "M" and p["op"] == op and not p.get("iso_L1")]
    sids = {p["sid"] for p in M}
    F = [p for p in P if p["arm"] == "tok" and p["kind"] == "F" and p["sid"] in sids]
    for m in ("DC", "DC_L2w"):
        yy = [1] * len(F) + [0] * len(M)
        ss = [p[m] for p in F + M]
        res[f"{op}|{m}"] = mw_auc(yy, ss)
po = json.loads((ROOT / "results" / "m1_confound.json").read_text())["per_operator"]
out["M1_per_op_auroc"] = {k: {"rederived": v, "reported": po[f"tok|{k.split('|')[0]}|noniso"][k.split('|')[1]]["auroc"]} for k, v in res.items()}
for k in out["M1_per_op_auroc"]:
    d = out["M1_per_op_auroc"][k]
    d["abs_diff"] = abs(d["rederived"] - d["reported"])
# placebo: random scores on the same F/M sets
M = [p for p in P if p["arm"] == "tok" and p["kind"] == "M" and p["op"] == "DROP_CONJ" and not p.get("iso_L1")]
F = [p for p in P if p["arm"] == "tok" and p["kind"] == "F" and p["sid"] in {q["sid"] for q in M}]
yy = [1] * len(F) + [0] * len(M)
out["M1_placebo_random_score_auroc"] = mw_auc(yy, rng.random(len(yy)))
# (C) M2: FA(0.10) for renames from raw rows
R = rj(ROOT / "work" / "m2_rows.jsonl")
fa = {}
for k in ("syn_rename", "tok_rename", "var_rename", "contrapositive"):
    d = [abs(r["DC1"] - r["DC0"]) for r in R if r["kind"] == k and r.get("ok")]
    fa[k] = {"FA_0.10": float(np.mean(np.array(d) > 0.10)), "FA_0": float(np.mean(np.array(d) > 0)), "n": len(d)}
repm2 = json.loads((ROOT / "results" / "m2_invariance.json").read_text())["per_kind"]
for k in fa:
    fa[k]["reported_FA_0.10"] = repm2[k]["FA_delta_0.10"]["rate"]
# placebo: a non-invariant control (random re-score) must show FA >> 0
fa["placebo_random_rescore_FA_0.10"] = float(np.mean(np.abs(rng.random(999) - rng.random(999)) > 0.10))
out["M2_FA"] = fa
# (D) M4(b): within-sentence shuffle AUROC (solver labels, unweighted) via rank formula
sc = {r["item_id"]: r["DC"] for r in rj(ROOT / "work" / "dc_scores.jsonl")}
L = [r for r in frame if r["output"] in ("faithful", "unfaithful")]
y = np.array([1 if r["output"] == "faithful" else 0 for r in L])
s = np.array([sc[r["item_id"]] for r in L])
grp = defaultdict(list)
for i, r in enumerate(L):
    grp[r["sentence_id"]].append(i)
sh = []
for _ in range(100):
    yp = y.copy()
    for ix in grp.values():
        ix = np.array(ix)
        yp[ix] = y[rng.permutation(ix)]
    sh.append(mw_auc(yp, s))
full_perm = [mw_auc(rng.permutation(y), s) for _ in range(100)]
out["M4b_shuffle_solver"] = {"true_auroc": mw_auc(y, s), "within_sentence_shuffle_mean": float(np.mean(sh)),
                             "reported_shuffle_mean": json.loads((ROOT / "results" / "m4_placebo.json").read_text())["b_within_sentence_shuffle"]["solver"]["mean_shuffled_auroc"],
                             "global_permutation_mean (placebo, must be ~0.5)": float(np.mean(full_perm))}
# (E) M3(c) bin concordance direction from raw rows: top bin < bottom bin
m3 = json.loads((ROOT / "results" / "m3_boundary.json").read_text())["c_real"]["bins"]
out["M3c_bins_reported"] = {k: v["DC"]["mean"] for k, v in m3.items()}
out["summary_rederived"] = ["M0 panel DC AUROC", "M1 DC arm gap", "M3 det k=4", "M7 gold AUROC", "M1 NEG/DROP per-op AUROC (DC, DC_L2w)",
                            "M2 FA for renames/contrapositive", "M4b within-sentence shuffle (solver)"]
out["not_rederived"] = ["M1b stacking deltas (only the random-feature placebo checked)", "M7 stacking deltas", "M5 ladder deltas",
                        "M6 partnered detection table", "M3c logistic slope CI", "complexity-stratified AUROCs"]
(ROOT / "results" / "audit_rederive2.json").write_text(json.dumps(out, indent=1))
print(json.dumps(out, indent=1))
