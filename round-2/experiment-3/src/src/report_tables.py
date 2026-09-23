"""Print markdown tables from results/*.json (used to write README.md; no computation beyond formatting)."""
from __future__ import annotations

import json
from pathlib import Path

RES = Path(__file__).resolve().parents[1] / "results"


def f(x, d=3):
    return "–" if x is None else f"{x:.{d}f}"


def ci(c):
    return "–" if not c or c[0] is None else f"[{c[0]:.3f}, {c[1]:.3f}]"


def main():
    a = json.loads((RES / "analysis.json").read_text())
    ct = json.loads((RES / "confirmation_table.json").read_text())
    order = ["LC_onecoin", "LC_huiwalter", "LC_maj", "LC_ds_binary", "LC_onecoin_str", "LC_granular", "A3", "A0", "Ccov",
             "A1", "B1", "B1plus", "B3cos", "B3nli", "A1L", "B1L", "B1plusL", "B3cosL", "B3nliL", "B3cL", "B2", "B2_armB", "B7", "B7_arity_self",
             "B7_arity_story", "B7_joint", "LC_within", "B8", "B7_jacc"]
    print("| metric | AUROC_P [95% CI] | AUROC_S | AUROC_T | AUROC_U | coverage | C1 | C2 ΔAUROC [CI] | C3 | CONFIRMED | top-tercile AUROC_P |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for m in order:
        if m not in ct:
            continue
        t = ct[m]
        cov = t["coverage"] if m not in ("A1", "B1plus", "B3cos", "B3nli", "B1plusL", "B3cosL", "B3nliL", "B3cL", "LC_within", "B8",
                                         "B7_jacc") else t["coverage_run_rows"]
        print(f"| {m} | {f(t['AUROC_P'])} {ci(t['CI_P'])} | {f(t['AUROC_S'])} | {f(t['AUROC_T'])} | {f(t['AUROC_U'])} | "
              f"{f(cov)} | {'Y' if t['C1'] else 'n'} | {f(t['C2_delta'])} {ci(t['C2_ci'])} | {'Y' if t['C3'] else 'n'} | "
              f"{'**YES**' if t['CONFIRMED'] else 'no'} | {f(t['top_tercile_AUROC_P'])} |")
    print()
    c = a["circularity"]
    print("Circularity (b) inside solver-NON-equivalent panel items, n =", c["b_nonequiv"]["n"],
          "faithful share", f(c["b_nonequiv"]["faithful_share_weighted"]))
    print("| metric | (b) AUROC [CI] | reading | (d) no-bijection AUROC [CI] | (a) panel − solver-pure [CI] |")
    print("|---|---|---|---|---|")
    for m in ["LC_onecoin", "LC_maj", "LC_ds_binary", "LC_huiwalter", "LC_granular", "A3", "A0", "Ccov", "A1", "B1",
              "B1plus", "B3nli", "B3cos", "A1L", "B1L", "B1plusL", "B3nliL", "B3cosL", "B3cL", "B7"]:
        b = c["b_nonequiv"].get(m)
        d = c["d_no_bijection"].get(m)
        aa = c["a_panel_vs_solver_same_items"].get(m)
        if not b:
            continue
        print(f"| {m} | {f(b['auroc'])} {ci(b['ci'])} | {b['preregistered_reading'] or ''} | "
              f"{f(d['auroc']) if d else '–'} {ci(d['ci']) if d else ''} | "
              f"{f(aa['diff_panel_minus_solver']) if aa else '–'} {ci(aa['diff_ci']) if aa else ''} |")
    print()
    print("Class position (c):", json.dumps(c["c_class_position"]))
    print()
    st = a["stacking"]
    print("Stacking base:", st["base_features"], "AUROC_base", f(st["auc_base"]))
    for k, v in st["combos"].items():
        print(f"- {k}: Δ {f(v['delta'])} {ci(v['ci'])}")
    print("- placebo:", f(st["placebo_random_feature"]["delta"]), ci(st["placebo_random_feature"]["ci"]))
    if "with_B1plus_in_base" in st:
        w = st["with_B1plus_in_base"]
        print("With", w.get("B1plus_used"), "in base: AUROC_base", f(w["auc_base"]),
              {m: (round(v["delta"], 3), [round(x, 3) for x in v["ci"]]) for m, v in w["per_metric"].items()})
    if "base_without_roundtrip" in st:
        w = st["base_without_roundtrip"]
        print("Base without round-trip", w["base"], "AUROC_base", f(w["auc_base"]),
              {m: (round(v["delta"], 3), [round(x, 3) for x in v["ci"]]) for m, v in w["per_metric"].items()})
    if "two_system_subset" in st:
        t = st["two_system_subset"]
        print("Two-system subset n", t["n"], "base", t["base"], "AUROC_base", f(t["auc_base"]),
              {m: (round(v["delta"], 3), [round(x, 3) for x in v["ci"]]) for m, v in t["per_metric"].items()},
              "B8 over base", round(t["B8_over_base"]["delta"], 3), [round(x, 3) for x in t["B8_over_base"]["ci"]])
    print()
    cx = a["complexity"]["crossover"]
    print("Crossover vs", a["complexity"].get("B1_reference"))
    print("| pop|metric | gap bottom/middle/top | slope [CI] | top gap CI | CONFIRMED | interaction>0 |")
    print("|---|---|---|---|---|---|")
    for k, v in cx.items():
        g = v["gap_by_tercile"]
        print(f"| {k} | {f(g['bottom'])}/{f(g['middle'])}/{f(g['top'])} | {f(v['slope'])} {ci(v['slope_ci'])} | "
              f"{ci(v['top_gap_ci'])} | {v['CROSSOVER_CONFIRMED']} | {(v.get('interaction') or {}).get('positive')} |")
    print()
    pc = a["complexity"]["per_cell"]
    print("| cell | n (pos/neg) | LC_onecoin | LC_ds_binary | A3 | B1 | B1plus | B3nli |")
    print("|---|---|---|---|---|---|---|---|")
    for k, v in pc.items():
        print(f"| {k} | {v['n']} ({v['n_pos']}/{v['n_neg']}){' insufficient' if v.get('insufficient_n') else ''} | "
              + " | ".join(f(v.get(m, {}).get("auroc")) for m in ["LC_onecoin", "LC_ds_binary", "A3", "B1", "B1plus", "B3nli"]) + " |")
    print()
    sl = a["system_level"]["metrics"]
    print("| metric | tau_b all items [CI] | pairwise acc | tau_b panel [CI] |")
    print("|---|---|---|---|")
    for m in ["LC_onecoin", "LC_maj", "LC_ds_binary", "A3", "A0", "A1", "B1", "B1plus", "B3nli", "B1L", "B1plusL", "B2", "B7",
              "RANDOM"]:
        v = sl.get(m, {})
        al, pa = v.get("all_items", {}), v.get("panel_items", {})
        print(f"| {m} | {f(al.get('tau_b'))} {ci(al.get('tau_ci'))} | {f(al.get('pairwise_acc'))} | "
              f"{f(pa.get('tau_b'))} {ci(pa.get('tau_ci'))} |")
    print()
    co = a["contamination"]["all"]
    print("| metric | mean Δ(orig−para) [CI] | AUROC orig | AUROC para | diff [CI] |")
    print("|---|---|---|---|---|")
    for m, v in co.items():
        if isinstance(v, dict) and "mean_delta" in v:
            print(f"| {m} | {f(v['mean_delta'])} {ci(v['delta_ci'])} | {f(v.get('auroc_original'))} | "
                  f"{f(v.get('auroc_paraphrase'))} | {f(v.get('auroc_diff'))} {ci(v.get('auroc_diff_ci'))} |")
    print("Recall probe (local):", json.dumps(a["contamination"].get("gold_recall_probe_local_Qwen3_8B"))[:600])
    print()
    print("Judge reliability:", json.dumps(a["judge_reliability"])[:1500])
    print("Per error type:", json.dumps({k: {m: round(x["auroc"], 3) for m, x in v.items() if m in
                                               ("LC_onecoin", "A3", "B1", "B1plus", "LC_ds_binary")}
                                          for k, v in a["per_error_type"].items() if k != "type_counts_unweighted"}))
    print("LC_within vs onecoin:", json.dumps({k: {m: (round(x["auroc"], 3) if isinstance(x, dict) and x.get("auroc") else x)
                                                   for m, x in v.items()} for k, v in a["lc_within_vs_onecoin_same_items"].items()}))
    print("meta:", json.dumps({k: a["meta"][k] for k in ("n_panel", "panel_kish_n_eff", "n_solver_labelled", "n_soft",
                                                         "n_unanimous", "base_features_used", "local_substitutes_used")}))
    print("sanity:", json.dumps(a["sanity"])[:600])
    print("lc fit:", json.dumps({k: {kk: vv for kk, vv in v.items() if kk in ("pi", "rho", "degenerate", "pairs_touched",
                                                                              "pairs_merged")} for k, v in a["lc_fit_info"].items()
                                 if isinstance(v, dict)})[:900])


if __name__ == "__main__":
    main()
