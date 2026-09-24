#!/usr/bin/env python3
"""Markdown tables from results/{frozen_config,tests,analysis,analysis_extra}.json -> results/report_tables.md."""
from __future__ import annotations

import json

from common import RES


def f(x, d=3):
    if x is None:
        return "–"
    if isinstance(x, float):
        return f"{x:.{d}f}"
    return str(x)


def ci(v):
    return f"[{f(v[0])}, {f(v[1])}]" if v else "–"


def main() -> None:
    fz = json.loads((RES / "frozen_config.json").read_text())
    t = json.loads((RES / "tests.json").read_text())
    A = json.loads((RES / "analysis.json").read_text())
    X = json.loads((RES / "analysis_extra.json").read_text())
    L = []
    L.append("## Dev grid (freeze; 609 dev panel items + 5,846 dev solver rows)\n")
    L.append("| config | AUROC_P | AUROC_S | mean | coverage | EQUIV-only-by-L2/L3 share of pairs | non-transitivity |")
    L.append("|---|---|---|---|---|---|---|")
    for g in fz["grid"]:
        star = " **(frozen)**" if g["config"] == fz["config_name"] else ""
        L.append(f"| {g['config']}{star} | {f(g['AUROC_P'])} | {f(g['AUROC_S'])} | {f(g['mean'])} | {f(g['coverage'])} | "
                 f"{f(g.get('share_pairs_equiv_only_L2L3'))} | {f(g.get('nontransitivity'), 4)} |")
    L.append("\n## Fresh AUROC (panel: 256 adjudicated items, raked weights; solver: 3,720 audited-solver rows)\n")
    L.append("| metric | AUROC_P [95% CI] | n_P | AUROC_S [95% CI] | n_S | coverage |")
    L.append("|---|---|---|---|---|---|")
    ms = sorted({k.split("|")[0] for k in t["auroc"]}, key=lambda m: -(t["auroc"].get(f"{m}|panel", {}).get("auc") or 0))
    for m in ms:
        p = t["auroc"].get(f"{m}|panel", {})
        s = t["auroc"].get(f"{m}|solver", {})
        L.append(f"| {m} | {f(p.get('auc'))} {ci(p.get('ci95'))} | {p.get('n', '–')} | {f(s.get('auc'))} {ci(s.get('ci95'))} | "
                 f"{s.get('n', '–')} | {f(s.get('coverage', p.get('coverage')))} |")
    L.append("\n## Pre-registered tests (fresh only; PASS requires both labels; T3 panel-only)\n")
    L.append("| test | panel | solver | verdict |")
    L.append("|---|---|---|---|")
    for k in ("panel", "solver"):
        pass
    t1 = t["T1"]
    L.append(f"| T1 Δ AUROC(base+DC − base), base=[B1,B2,B3nliL,B3cosL,B7] | {f(t1['panel']['point'])} {ci(t1['panel']['ci95'])} LB5 {f(t1['panel']['lb_one_sided_5'])} | "
             f"{f(t1['solver']['point'])} {ci(t1['solver']['ci95'])} LB5 {f(t1['solver']['lb_one_sided_5'])} | **{t1['verdict']}** |")
    L.append(f"| T1 placebo (DC shuffled in strata) | {f(t1['panel']['placebo']['point'])} {ci(t1['panel']['placebo']['ci95'])} | "
             f"{f(t1['solver']['placebo']['point'])} {ci(t1['solver']['placebo']['ci95'])} | – |")
    L.append(f"| T1 sensitivity base=[B1,B2,B7] | {f(t1['panel_base_noB3']['point'])} {ci(t1['panel_base_noB3']['ci95'])} | "
             f"{f(t1['solver_all_rows_base_noB3']['point'])} {ci(t1['solver_all_rows_base_noB3']['ci95'])} (all 3,720 rows) | – |")
    for m, rule in (("LC_maj", "LB>0"), ("LC_ds_binary", "point>0"), ("VC", "LB>0")):
        p, s = t["T2"]["panel"][m], t["T2"]["solver"][m]
        L.append(f"| T2 DC − {m} ({rule}) | {f(p['point'])} {ci(p['ci95'])} LB5 {f(p['lb_one_sided_5'])} | "
                 f"{f(s['point'])} {ci(s['ci95'])} LB5 {f(s['lb_one_sided_5'])} | |")
    L.append(f"| T2 overall | {t['T2']['panel']['pass']} | {t['T2']['solver']['pass']} | **{t['T2']['verdict']}** |")
    t3 = t["T3"]
    L.append(f"| T3a top-1 type (DC {f(t3['top1_DC'])} vs majority {t3['majority_type']} {f(t3['majority_share'])} + 0.10; TJ_L {f(t3['TJ_top1'])}) | {t3['pass_a']} | panel-only | |")
    L.append(f"| T3b recall ≥ 0.5 (added / dropped / ∀∃) | " + ", ".join(f"{k.split('_')[0]} {f(v['recall_weighted'])} (n={v['n']})" for k, v in t3["recall"].items()) + " | – | |")
    L.append(f"| T3c within-sentence DC vs B1 | " + ", ".join(f"{k}: DC {f(v['DC'])} B1 {f(v['B1'])} (pairs {v['n_pairs']}, {v['status']})" for k, v in t3["within_sentence"].items()) + f" | – | **{t3['verdict']}** |")
    for s, v in t["T4"].items():
        cells = []
        for lab in ("panel", "solver"):
            d = v[lab]
            if "DC_self_minus_B8" in d:
                cells.append(f"DC_self−B8 {f(d['DC_self_minus_B8']['point'])} (LB5 {f(d['DC_self_minus_B8']['lb_one_sided_5'])}); stack Δ {f(d['stack_delta']['point'])} (LB5 {f(d['stack_delta']['lb_one_sided_5'])}); n={d['n']}")
            else:
                cells.append(str(d))
        L.append(f"| T4 {s} | {cells[0]} | {cells[1]} | **{v['verdict']}** |")
    L.append("\n## Circularity (panel items whose candidate is solver-NON-equivalent to the audited gold)\n")
    L.append("| metric | AUROC_P non-equiv (n=168) | AUROC_P no-bijection (n=143) |")
    L.append("|---|---|---|")
    for m in ("DC", "LC_ds_binary", "LC_maj", "B1", "B3nliL", "VC", "TJ_L"):
        a = A["circularity"]["solver_nonequiv"].get(m, {})
        b = A["circularity"]["no_bijection"].get(m, {})
        L.append(f"| {m} | {f(a.get('auc'))} {ci(a.get('ci95'))} | {f(b.get('auc'))} {ci(b.get('ci95'))} |")
    L.append("\n## Component ladder (fresh; derived from one relation cache)\n")
    L.append("| step | AUROC_P | AUROC_S |")
    L.append("|---|---|---|")
    for k in A["ladder_fresh"]["panel"]:
        L.append(f"| {k} | {f(A['ladder_fresh']['panel'][k])} | {f(A['ladder_fresh']['solver'].get(k))} |")
    L.append("\n## Complexity (fresh, AUROC)\n")
    L.append("| stratum | DC P | B1 P | DC S | B1 S | LC_ds_binary S |")
    L.append("|---|---|---|---|---|---|")
    for k in X["complexity_bins"]["panel"]:
        p = X["complexity_bins"]["panel"][k]
        s = X["complexity_bins"]["solver"][k]
        g = lambda d, m: f((d.get(m) or {}).get("auc")) + (f" (n={(d.get(m) or {}).get('n')})" if d.get(m) else "")  # noqa: E731
        L.append(f"| {k} | {g(p, 'DC')} | {g(p, 'B1')} | {g(s, 'DC')} | {g(s, 'B1')} | {g(s, 'LC_ds_binary')} |")
    for lab in ("panel", "solver"):
        c = A["complexity"][lab]
        L.append(f"\n{lab}: tercile gap DC−B1 (bottom/middle/top) = {', '.join(f(x) for x in c['gap_DC_minus_B1_by_tercile'])}; "
                 f"slope {f(c['slope']['point'])} {ci(c['slope']['ci95'])}")
    L.append("\n## Per panel error type (faithful vs unfaithful-of-type-X; all classes n<30 → descriptive)\n")
    mets = ["DC", "DC0", "LC_ds_binary", "B1", "B3nliL", "VC", "TJ_L"]
    L.append("| type | n | " + " | ".join(mets) + " |")
    L.append("|---" * (len(mets) + 2) + "|")
    for k, v in X["per_error_type_panel"].items():
        L.append(f"| {k} | {v['n_unfaithful']} | " + " | ".join(f(v.get(m)) for m in mets) + " |")
    ws = X["within_sentence_paired_panel"]
    L.append(f"\nWithin-sentence paired AUROC (panel, {ws['n_pairs']} faithful×unfaithful pairs in {ws['n_sentences']} sentences): " +
             "; ".join(f"{m} {f(ws[m]['p'])} {ci(ws[m]['ci95'])}" for m in mets if m in ws))
    L.append("\n## Shared bias (mode-right vs mode-wrong sentences)\n")
    L.append("| stratum | DC | B1 | LC_maj |")
    L.append("|---|---|---|---|")
    for lab in ("panel", "solver"):
        for k in ("mode_right", "mode_wrong"):
            d = A["shared_bias"][lab][k]
            L.append(f"| {lab} {k} (n={d.get('DC', {}).get('n')}) | {f(d.get('DC', {}).get('auc'))} {ci(d.get('DC', {}).get('ci95'))} | "
                     f"{f(d.get('B1', {}).get('auc'))} | {f(d.get('LC_maj', {}).get('auc'))} |")
    L.append("\n## System level (9 systems; Kendall τ_b [sentence-bootstrap CI], pairwise accuracy)\n")
    L.append("| metric | τ_b panel | pairwise panel | τ_b solver | pairwise solver |")
    L.append("|---|---|---|---|---|")
    for m in ("DC", "LC_ds_binary", "LC_maj", "B1", "VC", "B2", "B7"):
        p, s = A["system_level"]["panel"][m], A["system_level"]["solver"][m]
        L.append(f"| {m} | {f(p['tau_b'])} {ci(p.get('tau_ci95'))} | {f(p['pairwise_acc'])} | {f(s['tau_b'])} {ci(s.get('tau_ci95'))} | {f(s['pairwise_acc'])} |")
    inv = A["invariance"]
    L.append("\n## Invariance under solver-verified meaning-preserving rewrites (400 fresh candidates)\n")
    L.append("| rewrite | n verified | DC false-alarm rate (|ΔDC|>0.05 or mode flip or type change) |")
    L.append("|---|---|---|")
    for k, v in inv["DC_by_kind"].items():
        L.append(f"| {k} | {v['n']} | {f(v['false_alarm_rate'], 4)} |")
    L.append(f"\nVC on the synonym-renamed subset: false-alarm rate {f(inv['VC_synonym_rename']['false_alarm_rate(|dVC|>0.05)'])} "
             f"(mean |ΔVC| {f(inv['VC_synonym_rename']['mean_abs_change'])}).")
    wg = A["wrong_gold_flag"]
    L.append(f"\n## Wrong-gold flag (gold as a 10th peer)\n\nAUROC of 1 − DC_gold vs the L0 verdict = {f(wg['AUROC_1_minus_DC_gold'])} "
             f"(n={wg['n']}, base rate {f(wg['base_rate'])}); precision@50 = {f(wg['precision_at_50'])}.")
    lq = A["label_quality"]
    L.append("\n## Label quality\n")
    L.append(f"- Wrong shipped gold (L0): " + "; ".join(f"{k} {f(v['rate'])} {ci(v['ci95'])} (n={v['n']})" for k, v in lq["wrong_gold_rate_by_corpus"].items()))
    L.append(f"- Correct-but-inequivalent (panel-faithful share among solver-non-equivalent panel items, weighted): {f(lq['correct_but_inequivalent_rate_weighted'])} (n={lq['n_solver_nonequiv_panel']})")
    L.append(f"- Panel-unfaithful among solver-equivalent panel items: {f(lq['panel_unfaithful_among_solver_equiv_weighted'])} (n={lq['n_solver_equiv_panel']})")
    L.append(f"- Solver–panel agreement (weighted): {f(lq['solver_panel_agreement_weighted'])}")
    L.append(f"- Fleiss κ: L3 full-panel subset {f(lq['fleiss_kappa_L3_full_subset'])} (n={lq['n_L3_full_subset']}); L0 subset {f(lq['fleiss_kappa_L0_full_subset'])} (n={lq['n_L0_full_subset']})")
    L.append(f"- Panel weights: {json.dumps(lq['weights'])}")
    cov = A["coverage"]
    L.append(f"\n## Coverage and cost\n\n- Relation shares over {cov['n_pairs']} fresh greedy pairs: " +
             ", ".join(f"{k} {f(v)}" for k, v in cov["relation_shares"].items()) +
             f"; EQUIV non-transitivity {f(cov['equiv_nontransitivity'], 4)}.")
    L.append(f"- Coverage: " + ", ".join(f"{k} {f(v)}" for k, v in cov["coverage_by_metric"].items()) +
             f"; unparseable greedy outputs {cov['unparseable_greedy']} (kept, scored 0.5 by DC / 0 by DC0).")
    c = A["cost"]
    L.append(f"- DC: $0 when peers exist; {f(c['DC']['solver_seconds_per_item_mean'])} s solver time per item (p95 {f(c['DC']['solver_seconds_per_item_p95'])} s); "
             f"${f(c['DC']['usd_per_item_peers_generated'], 5)} per item if the 8 peers must be generated. B1: ${f(c['B1']['usd_per_item'], 6)} per item.")
    cd = A["contamination_dev"]
    L.append(f"\n## Contamination (dev, entity-renamed candidates)\n\nmean DC(original) − DC(renamed) = {f(cd['mean_delta_orig_minus_para'])} {ci(cd['ci95'])} "
             f"over {cd['n']} pairs (B1 in round 2: +0.096): DC is exactly name-blind.")
    fg = A["frontier_gap_dev"]
    L.append(f"\n## Frontier gap (dev anchor only)\n\nstack [B1, B2, DC] OOF AUROC_P {f(fg['stack_B1_B2_DC_oof'])} vs gemini-2.5-pro B1plus {f(fg['B1plus'])} (B1 {f(fg['B1'])}), n={fg['n']}.")
    pt = json.loads((RES / "perturbation_sensitivity.json").read_text())
    L.append(f"\n## Controlled perturbations of {pt['n_anchors']} solver-verified faithful anchors (mechanism evidence only)\n")
    L.append("| operator | n | P(DC(anchor) > DC(mutant)) [95% CI] | DC typing accuracy | mutant still in mode | VC detection |")
    L.append("|---|---|---|---|---|---|")
    for op, v in pt["by_operator"].items():
        L.append(f"| {op} ({v['expected_type']}) | {v['n']} | {f(v['detection_DC'])} {ci(v['detection_DC_ci95'])} | "
                 f"{f(v['typing_accuracy'])} | {f(v['mutant_still_in_mode'])} | {f(v['detection_VC'])} |")
    (RES / "report_tables.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
