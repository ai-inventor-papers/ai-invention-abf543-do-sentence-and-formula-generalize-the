"""Figures (vector PDF + PNG) drawn only from results/*.json, so every plotted number has a JSON source."""
from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

import common  # noqa: E402
from common import RESULTS  # noqa: E402

FIG = common.ROOT / "figures"
FIG.mkdir(exist_ok=True)
plt.rcParams.update({"font.size": 9, "pdf.fonttype": 42, "axes.spines.top": False, "axes.spines.right": False})
COL = {"TVJT_frozen": "#e08a00", "TVJT_iter1": "#f2c46d", "B1": "#333333", "B1x3": "#888888",
       "LC_onecoin": "#1b6ca8", "A3": "#c23b4e", "TVJT_lite": "#b07cc6", "TVJT_C1": "#e8a94a"}
LAB = {"TVJT_frozen": "TVJT* (repaired, 3 votes)", "TVJT_iter1": "TVJT iter-1 (unrepaired)", "B1": "B1 judge",
       "B1x3": "B1x3 (compute-matched)", "LC_onecoin": "LC one-coin", "A3": "A3 signature",
       "TVJT_lite": "TVJT* flash-lite", "TVJT_C1": "TVJT* vote-0 binary"}


def save(fig, name):
    fig.tight_layout()
    fig.savefig(FIG / f"{name}.pdf")
    fig.savefig(FIG / f"{name}.png", dpi=200)
    plt.close(fig)


def fig_crossover(A):
    P = A["P_main"]
    mets = [m for m in ("TVJT_frozen", "TVJT_iter1", "B1", "B1x3", "LC_onecoin", "A3") if m in P["all"]["auroc"]]
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8), sharey=True)
    for ax, key, bins, title in ((axes[0], "by_tercile", ["bottom", "middle", "top"], "complexity tercile"),
                                 (axes[1], "by_nconditions", ["0-1", "2-3", "4+"], "n_conditions bin")):
        bins = [b for b in bins if b in P[key]]
        for j, m in enumerate(mets):
            pts = [P[key][b]["auroc"][m] for b in bins]
            x = np.arange(len(pts)) + (j - (len(mets) - 1) / 2) * 0.05
            y = [p["point"] for p in pts]
            err = [[p["point"] - p["ci"][0] for p in pts], [p["ci"][1] - p["point"] for p in pts]]
            ax.errorbar(x, y, yerr=err, marker="o", ms=4, capsize=2, lw=1.4, color=COL[m], label=LAB[m])
        ax.set_xticks(range(len(bins)))
        ax.set_xticklabels([f"{b}\n(n={P[key][b]['n']})" for b in bins])
        ax.axhline(0.5, color="#bbbbbb", lw=0.8, ls=":")
        ax.set_xlabel(title)
    axes[0].set_ylabel("weighted AUROC, 609 panel items (95% CI)")
    axes[1].legend(frameon=False, fontsize=7, loc="lower right", ncol=2)
    save(fig, "fig1_auroc_by_complexity")


def fig_forest(A):
    P = A["P_main"]
    rows = []
    for key, bins in (("by_tercile", ["bottom", "middle", "top"]), ("by_nconditions", ["0-1", "2-3", "4+"])):
        for b in bins:
            for pair in ("TVJT_frozen-B1", "TVJT_frozen-B1x3"):
                d = P[key].get(b, {}).get("delta", {}).get(pair)
                if d and d["ci"][0] is not None:
                    rows.append((f"{b} ({'tercile' if key == 'by_tercile' else 'n_cond'})", pair, d))
    d = P["all"]["delta"].get("TVJT_frozen-B1")
    if d:
        rows.insert(0, ("all panel items", "TVJT_frozen-B1", d))
    fig, ax = plt.subplots(figsize=(6.5, 0.32 * len(rows) + 1))
    for i, (lab, pair, d) in enumerate(rows[::-1]):
        c = "#333333" if pair.endswith("B1") else "#888888"
        ax.errorbar(d["point"], i, xerr=[[d["point"] - d["ci"][0]], [d["ci"][1] - d["point"]]], fmt="o", color=c,
                    capsize=2)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([f"{lab}  [{p.replace('TVJT_frozen', 'TVJT*')}]" for lab, p, _ in rows[::-1]], fontsize=7)
    ax.axvline(0, color="#c23b4e", lw=0.8)
    ax.set_xlabel("paired ΔAUROC_w (TVJT* − judge), 95% cluster-bootstrap CI")
    save(fig, "fig2_delta_forest")


def fig_invariance(D, A):
    T1 = D["T1_worldset_identity"]
    kinds = ["REORDER", "DEMORGAN", "CONTRAPOSITIVE", "RENAME"]
    D2 = D["D2_iter1_paired_FA_decomposition"]
    sr = A.get("screen_repair") or {}
    g2 = sr.get("paired_G2_FA", {}).get("C3", {})
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.5))
    x = np.arange(len(kinds))
    axes[0].bar(x - 0.2, [T1[k]["rate_iter1"] for k in kinds], 0.4, color="#cccccc", label="iter-1 worlds")
    axes[0].bar(x + 0.2, [T1[k]["rate_canon"] for k in kinds], 0.4, color="#1b6ca8", label="canonical worlds (R1)")
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(kinds, fontsize=8)
    axes[0].set_ylabel("screen rewrites with the gold's world set")
    axes[0].set_ylim(0, 1.05)
    axes[0].legend(frameon=False, fontsize=7, loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=2)
    axes[1].bar(x - 0.2, [D2.get(f"{k}|all", {}).get("paired_FA") or 0 for k in kinds], 0.4, color="#cccccc",
                label="iter-1 TVJT")
    rep = [g2.get(k, np.nan) for k in kinds]
    axes[1].bar(x + 0.2, rep, 0.4, color="#e08a00", label="repaired TVJT* (C3)")
    for xi, v in zip(x, rep):
        axes[1].text(xi + 0.2, (v if v == v else 0) + 0.005, f"{v:.2f}", ha="center", va="bottom", fontsize=7)
    axes[1].axhline(0.10, color="#c23b4e", lw=0.8, ls="--")
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(kinds, fontsize=8)
    axes[1].set_ylabel("paired false-alarm rate (screen)")
    axes[1].legend(frameon=False, fontsize=7, loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=2)
    save(fig, "fig3_rewrite_invariance")


def fig_errors(A):
    E = A["P_main"]["error_types"]
    mets = [m for m in ("TVJT_frozen", "B1", "LC_onecoin", "A3") if m in next(iter(E.values()))]
    types = [e for e in ("quantifier_forall_exists", "added_condition", "dropped_condition",
                         "implication_direction_or_only", "scope∪cardinality", "conflation", "connective_and_or",
                         "negation_polarity") if e in E]
    fig, ax = plt.subplots(figsize=(10, 3.6))
    x = np.arange(len(types))
    wdt = 0.8 / len(mets)
    for j, m in enumerate(mets):
        d = [E[t][m]["detection"] for t in types]
        err = [[E[t][m]["detection"] - E[t][m]["wilson"][0] for t in types],
               [E[t][m]["wilson"][1] - E[t][m]["detection"] for t in types]]
        ax.bar(x + (j - (len(mets) - 1) / 2) * wdt, d, wdt, yerr=err, capsize=1.5, color=COL[m], label=LAB[m])
    ax.axhline(0.5, color="#888888", lw=0.8, ls=":")
    ax.set_xticks(x)
    ax.set_xticklabels([f"{t.replace('_', ' ')}\n(n={E[t]['n']})" for t in types], fontsize=7)
    ax.set_ylabel("P(error scores below same-sentence faithful)")
    ax.legend(frameon=False, fontsize=7, ncol=4)
    save(fig, "fig4_error_type_detection")


def fig_cost(A):
    P = A["P_main"]["all"]["auroc"]
    cost = A.get("cost", {})
    pts = []
    for m in ("B1", "B1x3", "TVJT_C1", "TVJT_frozen", "TVJT_iter1", "TVJT_lite", "LC_onecoin", "A3"):
        if m in P and m in cost:
            pts.append((m, cost[m].get("usd_per_item", 0), P[m]["point"]))
    if not pts:
        return
    fig, ax = plt.subplots(figsize=(5.5, 3.6))
    for m, c, a in pts:
        ax.scatter(max(c, 1e-6), a, color=COL.get(m, "#555555"), s=30)
        ax.annotate(LAB.get(m, m), (max(c, 1e-6), a), fontsize=7, xytext=(4, 3), textcoords="offset points")
    ax.set_xscale("log")
    ax.set_xlabel("$ per item (fresh calls; zero-LLM metrics plotted at 1e-6)")
    ax.set_ylabel("weighted AUROC on panel items")
    save(fig, "fig5_cost_accuracy")


def main():
    A = json.loads((RESULTS / "analysis.json").read_text())
    D = json.loads((RESULTS / "canon_diagnostic.json").read_text())
    fig_crossover(A)
    fig_forest(A)
    fig_invariance(D, A)
    fig_errors(A)
    fig_cost(A)
    print(sorted(p.name for p in FIG.iterdir()))


if __name__ == "__main__":
    main()
