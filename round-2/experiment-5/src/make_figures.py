#!/usr/bin/env python3
"""Figures from results/analysis.json (numbers are read, never recomputed): V1 confusion heatmaps (D_rule, TJ),
V2 per-type detection forest, V3 P@k-vs-base bars, V4 ΔAUROC forest. PDF + PNG in figures/."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parent
FIG = ROOT / "figures"
FIG.mkdir(exist_ok=True)
plt.rcParams.update({"pdf.fonttype": 42, "font.size": 9, "axes.spines.top": False, "axes.spines.right": False})
A = json.loads((ROOT / "results" / "analysis.json").read_text())


def save(fig, name):
    fig.tight_layout()
    fig.savefig(FIG / f"{name}.pdf")
    fig.savefig(FIG / f"{name}.png", dpi=200)
    plt.close(fig)


# V1 confusion
blk = A["V1"]["parse_ok"]
truth = [t for t in blk["truth_mix_w"]]
fig, axes = plt.subplots(1, 2, figsize=(12, 5.2))
for ax, m in zip(axes, ("D_rule", "TJ")):
    conf = blk["methods"][m]["confusion_w"]
    preds = sorted({p for row in conf.values() for p in row}, key=lambda p: (p not in truth, truth.index(p) if p in truth else 0, p))
    M = np.array([[conf.get(t, {}).get(p, 0.0) for p in preds] for t in truth])
    M = M / np.maximum(M.sum(1, keepdims=True), 1e-9)
    ax.imshow(M, cmap="Blues", vmin=0, vmax=1)
    ax.set_xticks(range(len(preds)), [p.replace("_", " ")[:18] for p in preds], rotation=70, ha="right", fontsize=7)
    ax.set_yticks(range(len(truth)), [t.replace("_", " ")[:22] for t in truth], fontsize=7)
    ax.set_title(f"{m}: top-1 = {blk['methods'][m]['top1_w']:.2f} (weighted)")
    ax.set_xlabel("predicted type")
axes[0].set_ylabel("panel primary error (row-normalised)")
save(fig, "v1_confusion")

# V2 forest
tab = A["V2"]["any_faithful"]["primary"]
keys = [k for k in ["added_condition", "dropped_condition", "quantifier_forall_exists", "implication_direction_or_only",
                    "negation_polarity", "argument_swap", "PREDICTED_VISIBLE", "quantifier_scope", "connective_and_or",
                    "cardinality_numeric", "PREDICTED_BLIND"] if tab.get(k, {}).get("n")]
fig, ax = plt.subplots(figsize=(7, 4.5))
for j, (m, c) in enumerate((("S", "#1f77b4"), ("A0", "#999999"), ("B1", "#d62728"))):
    for i, k in enumerate(keys):
        r = tab[k].get(m)
        if not r:
            continue
        y = i + (j - 1) * 0.22
        ax.plot(r["ci95"], [y, y], color=c, lw=1.2)
        ax.plot(r["det_w"], y, "o", color=c, ms=4, label=m if i == 0 else None)
ax.axvline(0.5, ls=":", color="k", lw=0.8)
ax.axvline(0.8, ls="--", color="gray", lw=0.8)
ax.set_yticks(range(len(keys)), [f"{k.replace('_', ' ')} (n={tab[k]['n']})" for k in keys], fontsize=7)
ax.set_xlabel("detection vs faithful partners of the same sentence")
ax.legend(fontsize=7)
ax.invert_yaxis()
save(fig, "v2_detection_forest")

# V3 P@k
v3 = A["V3"]
corp = [c for c in v3 if isinstance(v3[c], dict) and "flag_S" in v3[c] and c not in ("pooled_excl_ambiguous",)]
fig, ax = plt.subplots(figsize=(7.5, 3.8))
flags = ["flag_S", "flag_A0", "flag_Ccov", "flag_B1", "flag_TJ"]
w = 0.14
for j, f in enumerate(flags):
    vals = [v3[c][f].get("P@50", np.nan) for c in corp]
    ax.bar(np.arange(len(corp)) + (j - 2) * w, vals, w, label=f.replace("flag_", ""))
for i, c in enumerate(corp):
    ax.hlines(v3[c]["base_rate"], i - 0.4, i + 0.4, colors="k", linestyles="--", lw=1)
ax.set_xticks(range(len(corp)), corp)
ax.set_ylabel("precision@50 (dashed = base rate)")
ax.legend(fontsize=7, ncol=5)
save(fig, "v3_precision_at_k")

# V4 forest
v4 = A["V4"]
ks = [("delta_M1_M0", "S over [B1,parse,A0]"), ("delta_M2_M0", "P over [B1,parse,A0]"),
      ("delta_M3_M3base", "iter-1 A3 over [B1,parse,A0_iter1]"), ("delta_B1_S_B1only", "S over B1")]
fig, ax = plt.subplots(figsize=(6, 2.8))
for i, (k, lab) in enumerate(ks):
    r = v4[k]
    ax.plot(r["ci95"], [i, i], color="#1f77b4")
    ax.plot(r["delta"], i, "o", color="#1f77b4")
pl = v4["placebo_within_sentence_shuffle"]
ax.plot(pl["delta_M1_M0_ci95"], [len(ks)] * 2, color="gray")
ax.plot(pl["delta_M1_M0"], len(ks), "o", color="gray")
ax.axvline(0, ls=":", color="k")
ax.set_yticks(range(len(ks) + 1), [l for _, l in ks] + ["placebo (S shuffled in sentence)"], fontsize=7)
ax.set_xlabel("cross-fitted ΔAUROC (weighted, 95% clustered CI)")
ax.invert_yaxis()
save(fig, "v4_delta_auroc")
print("figures written")
