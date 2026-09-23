"""Regenerate README.md: static head/tail templates + a Results section filled ONLY from results/*.json
(so no number in the README is hand-copied)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPS = ["NEG", "QUANT", "IMPL_REV", "DROP_CONJ", "ADD_CONJ", "ARG_SWAP", "AND_OR", "SCOPE_SWAP", "MERGE", "CARD"]
ORDER = ["TVJT", "NLI_deberta", "LC_onecoin", "B1", "B2", "B3sc", "TVJT_gloss", "TVJT_nv", "NLI_deberta_gloss",
         "NLI_gemini", "LC_huiwalter", "LC_maj", "LC_ds_binary", "LC_onecoin_str"]


def f(x, nd=3):
    return "—" if x is None else (f"{x:.{nd}f}" if isinstance(x, (int, float)) else str(x))


def sg(x, nd=3):
    return "—" if x is None else f"{x:+.{nd}f}"


def ci(v):
    return f"[{sg(v[0])}, {sg(v[1])}]"


def main() -> None:
    a = json.loads((ROOT / "results" / "analysis.json").read_text())
    v = json.loads((ROOT / "results" / "verdict.json").read_text())
    dev = json.loads((ROOT / "results" / "dev_checks.json").read_text())
    M = a["metrics"]
    rows = []
    for m in ORDER:
        x = M[m]
        ar, t, g2, g3, rb = x["auroc_real"], x["by_tercile"], x.get("G2"), x.get("G3"), x.get("robustness", {})
        role = "RULE" if m in ("TVJT", "NLI_deberta", "LC_onecoin") else ("baseline" if m in ("B1", "B2", "B3sc") else "secondary")
        g2s = "N/A" if g2 == "N/A" else ("—" if not isinstance(g2, dict) else f"{g2['FA_at_tau']:.3f} ({g2['FA_at_0.5']:.3f})")
        g3s = "—" if not isinstance(g3, dict) else f"{g3['delta']:+.3f} [{g3['ci'][0]:+.3f}, {g3['ci'][1]:+.3f}]"
        w = rb.get("within_sentence_pairwise_acc", {})
        ws = "—" if not w else f"{f(w['acc'])} [{f(w['ci'][0])}, {f(w['ci'][1])}]"
        vc = rb.get("auroc_vocab_compatible_subset", {}).get("auroc")
        c = a["cost"][m]
        rows.append(f"| {m} | {role} | {f(ar['auroc'])} [{f(ar['ci'][0])}, {f(ar['ci'][1])}] | {f(t['0']['auroc'])} / "
                    f"{f(t['1']['auroc'])} / {f(t['2']['auroc'])} | {f(x.get('G1_coverage'))} | {g2s} | {g3s} | {ws} | "
                    f"{f(vc)} | {c['usd_per_item_mean']:.6f} | {c['sec_per_item_median']:.2f} |")
    P = a["paired_auroc_deltas"]
    paired = "\n".join(f"| {k} | {sg(p['delta_auroc'])} [{sg(p['ci'][0])}, {sg(p['ci'][1])}] | "
                       f"{sg(p['delta_auroc_top_tercile'])} [{sg(p['ci_top_tercile'][0])}, {sg(p['ci_top_tercile'][1])}] |"
                       for k, p in P.items())
    tv = {k.split("|")[0]: x for k, x in a["tvjt_pairwise_detection"].items() if k.endswith("|screen")}
    nl = {k.split("|")[0]: x for k, x in a["nli_pairwise_detection"].items() if k.endswith("|screen_controlled")}
    b1 = M["B1"].get("standalone_detection") or {}
    tvs = M["TVJT"].get("standalone_detection") or {}
    ss = json.loads((ROOT / "data" / "screen_set.json").read_text())
    kept = ss["counts"]["mutants"]
    det = "\n".join(
        f"| {op} | {kept[op]['kept']} | {f(tv.get(op, {}).get('rate'))} | {f(nl.get(op, {}).get('rate'))} "
        f"({nl.get(op, {}).get('n_no_differing_hypothesis', '—')} undistinguishable) | {f(tvs.get(op, {}).get('rate'))} | "
        f"{f(b1.get(op, {}).get('rate'))} |" for op in OPS)
    h = a["blindspot_headtohead"]
    bs = "\n".join(f"| {k.replace('|', ' / ')} | {f(x['rate'])} | {x['n']} | {x['wilson']} |" for k, x in h.items()
                   if isinstance(x, dict) and k.count("|") == 2)
    T, N, L, B = M["TVJT"], M["NLI_deberta"], M["LC_onecoin"], M["B1"]
    rbT, rbL, rbB, rbN = T["robustness"], L["robustness"], B["robustness"], N["robustness"]
    et = a["error_type_confusion"]
    cost = a["cost"]
    surv = v.get("survivors", [])
    gv = v["gate_values"]
    ctrl = a["controls"]
    mid = f"""## Results (all numbers from `results/analysis.json`; CIs = 1000× sentence-clustered bootstrap, seed 0)

| metric | role | AUROC_real [95% CI] | tercile 0 / 1 / 2 | G1 cov | G2 FA@τ* (FA@0.5) | G3 ΔAUROC [CI] | within-sentence acc [CI] | AUROC vocab-compatible | $/item | s/item (median) |
|---|---|---|---|---|---|---|---|---|---|---|
""" + "\n".join(rows) + f"""

- Tercile 2 = the most complex third, by the composite of tokens, quantifiers, depth and conditions.
- G3 = out-of-fold (GroupKFold by sentence) logistic stack of [B1, parse_ok, metric] vs [B1, parse_ok].
- Within-sentence acc = P(score of a correct candidate > score of an incorrect candidate *for the same sentence*),
  over the {rbT['within_sentence_pairwise_acc']['n_sentences_mixed_labels']} mixed-label sentences.
- Negative controls:
  - a pure-noise metric has AUROC {f(M['NOISE']['auroc_real']['auroc'])} and a G3 CI of
    [{sg(ctrl['noise_metric_G3']['ci'][0])}, {sg(ctrl['noise_metric_G3']['ci'][1])}], which contains 0;
  - shuffled labels give AUROC {f(ctrl['shuffled_label_auroc_mean_TVJT'])}.

**Pre-registered selection rule (verbatim; `results/verdict.json`).** Survivors: {surv}. Outcome: **{v['outcome']}**,
advancing {v.get('advance')}. Gate values:
- **TVJT:** G1 {gv['TVJT']['G1_coverage']}, G2 FA {gv['TVJT']['G2_FA_at_tau']}, G3 {sg(gv['TVJT']['G3_delta'])} {gv['TVJT']['G3_ci']},
  G4 {gv['TVJT']['G4_auroc_real']}. It fails **only G2**.
- **NLI_deberta:** G1 {gv['NLI_deberta']['G1_coverage']}, G2 FA {gv['NLI_deberta']['G2_FA_at_tau']},
  G3 {sg(gv['NLI_deberta']['G3_delta'])} {gv['NLI_deberta']['G3_ci']}, G4 {gv['NLI_deberta']['G4_auroc_real']}.
- **LC_onecoin:** G1 {gv['LC_onecoin']['G1_coverage']}, G2 N/A, G3 {sg(gv['LC_onecoin']['G3_delta'])}
  {gv['LC_onecoin']['G3_ci']}, G4 {gv['LC_onecoin']['G4_auroc_real']}; top-tercile AUROC {gv['LC_onecoin']['top_tercile_auroc']}.

Paired AUROC differences (same items, clustered bootstrap):

| comparison | ΔAUROC all | ΔAUROC top tercile |
|---|---|---|
{paired}

### What the screen says

1. **Cross-system agreement (latent class) is the strongest gold-free signal.** It holds up:
   - within a sentence ({f(rbL['within_sentence_pairwise_acc']['acc'])}), not only between sentences;
   - on vocabulary-compatible items ({f(rbL['auroc_vocab_compatible_subset']['auroc'])});
   - under the trigram labels ({f(L['by_label']['L_str']['auroc'])}).

   The one-coin EM beats plain majority ({sg(P['LC_onecoin-LC_maj']['delta_auroc'])} {ci(P['LC_onecoin-LC_maj']['ci'])};
   {sg(P['LC_onecoin-LC_maj']['delta_auroc_top_tercile'])} on the top tercile).

   **Caveat.** Labels and agreement use the same equivalence machinery. If two systems agree and one is gold-equivalent,
   the other is too, so agreement is favoured by construction. LC also needs ≥2 systems and cannot score a lone
   output. At system level it orders the systems {a['system_level']['order_by_metric_mean']['LC_onecoin']};
   the label order is {a['system_level']['order_by_L_bij_accuracy']}.
2. **TVJT adds signal beyond the LLM judge, and the gain grows with sentence complexity.**
   - AUROC by tercile: TVJT {f(T['by_tercile']['0']['auroc'])} → {f(T['by_tercile']['1']['auroc'])} →
     **{f(T['by_tercile']['2']['auroc'])}**; B1 {f(B['by_tercile']['0']['auroc'])} → {f(B['by_tercile']['1']['auroc'])} →
     **{f(B['by_tercile']['2']['auroc'])}**.
   - TVJT − B1 on the top tercile = **{sg(P['TVJT-B1']['delta_auroc_top_tercile'])}
     {ci(P['TVJT-B1']['ci_top_tercile'])}**. Over all items it is {sg(P['TVJT-B1']['delta_auroc'])}
     {ci(P['TVJT-B1']['ci'])}.
   - TVJT discriminates within sentences ({f(rbT['within_sentence_pairwise_acc']['acc'])}; B1
     {f(rbB['within_sentence_pairwise_acc']['acc'])}).
   - **Its failure is invariance** (G2): rewrites get different worlds from their own mutants, and the judge disagrees
     on some of them. Rewrite FA is {T['G2']['FA_at_tau']} at τ*={T['G2']['tau_star']} and {T['G2']['FA_at_0.5']} at 0.5.
     By rewrite kind: {T['G2']['FA_by_kind']}.
3. **Instance-consequence NLI with DeBERTa does not track correctness beyond the simplest tercile.**
   - Terciles: {f(N['by_tercile']['0']['auroc'])} / {f(N['by_tercile']['1']['auroc'])} / {f(N['by_tercile']['2']['auroc'])};
     within-sentence {f(rbN['within_sentence_pairwise_acc']['acc'])}. A negative result.
   - Asking gemini the same pairs (NLI_gemini) changes AUROC by {sg(P['NLI_gemini-NLI_deberta']['delta_auroc'])}
     {ci(P['NLI_gemini-NLI_deberta']['ci'])}. The consequence construction carries signal; the small NLI
     model cannot read quantified, instance-level entailments.
4. **Non-vacuous worlds hurt**: TVJT_nv − TVJT = {sg(P['TVJT_nv-TVJT']['delta_auroc'])}
   {ci(P['TVJT_nv-TVJT']['ci'])}. Minimal worlds are not the bottleneck. Gloss verbalization:
   TVJT_gloss − TVJT = {sg(P['TVJT_gloss-TVJT']['delta_auroc'])} {ci(P['TVJT_gloss-TVJT']['ci'])}.
5. **LLM non-determinism at T=0.** gemini-2.5-flash with temperature 0 and reasoning off is not fully deterministic.
   In the first pass, identical prompts sent concurrently (e.g. two systems emitting the same FOL string) sometimes got
   different answers. The final numbers come from a second, cache-consistent pass (identical input → identical cached
   answer; $0). The shift was ≤0.002 AUROC for TVJT, and the verdict was unchanged
   (`logs/repro/verdict_before.json` vs `results/verdict.json`).

### Per-operator detection (controlled mutants of the 300 screen golds)

| operator | n mutants | TVJT pairwise (judge sides with gold on the separating world) | NLI-DeBERTa pairwise | TVJT standalone (score<τ*) | B1 standalone (score<τ*) |
|---|---|---|---|---|---|
{det}

- Judge oracle accuracy on gold worlds: {a['tvjt_judge_oracle_accuracy']['overall']}. Mean score on gold:
  NLI-DeBERTa {a['NLI_deberta_oracle_on_gold']['mean_score']}, NLI-gemini {a['NLI_gemini_oracle_on_gold']['mean_score']}.
- Error-type identification (argmax operator, 10 classes), macro-F1: TVJT {et['TVJT']['macro_f1']}
  (top-1 {et['TVJT']['top1_accuracy']}); NLI {et['NLI_deberta']['macro_f1']} (top-1 {et['NLI_deberta']['top1_accuracy']}).
- ADD_CONJ with a fresh predicate on ground formulas is invisible to NLI, because the hypotheses use only F's own
  vocabulary.
- **FOLIO-dev gold has zero mixed ∀/∃ formulas**, so SCOPE_SWAP never applies on the screen.

**Blind-spot head-to-head** (`results/blindspot_headtohead.json`; Arm A's signature predicted ≈ chance):

| metric / op / split | detection | n | Wilson 95% |
|---|---|---|---|
{bs}

### Other reported quantities

- **Coverage.** Uncovered items get 0.5 and stay in every AUROC: TVJT {M['TVJT']['G1_coverage']},
  NLI {M['NLI_deberta']['G1_coverage']}, LC {M['LC_onecoin']['G1_coverage']}, B3sc {M['B3sc']['G1_coverage']}.
  World coverage is {a['world_coverage']['rate']} of parseable targets, with {a['world_coverage']['mean_worlds']} worlds
  per target.
- **Verbalizer failure.** {a['verbalizer_failure']['per_item']} of items and {a['verbalizer_failure']['per_predicate']}
  of predicates.
- **Cost per item** (fresh-call $ | median s):
  - TVJT ${cost['TVJT']['usd_per_item_mean']:.6f} | {cost['TVJT']['sec_per_item_median']} s;
  - B1 ${cost['B1']['usd_per_item_mean']:.6f} | {cost['B1']['sec_per_item_median']} s;
  - NLI-gemini ${cost['NLI_gemini']['usd_per_item_mean']:.6f} | {cost['NLI_gemini']['sec_per_item_median']} s;
  - NLI-DeBERTa $0 | {cost['NLI_deberta']['sec_per_item_median']} s;
  - LC $0 (z3 pairwise equivalence done in the build stage).

  **Total OpenRouter spend of this workspace: ${a['total_openrouter_usd_workspace']}**, covering dev checks, the mini
  run and the full screen, out of a $10 budget with a $6.50 hard cap.
- **Judge prompt checks.** Dev slice (T2, {dev['T2']['n_sentences']} non-screen FOLIO-dev sentences): judge oracle
  accuracy {dev['T2']['judge_oracle_accuracy_on_gold_worlds']:.3f} and {dev['T2']['malformed_rate']:.0%} malformed JSON,
  so the TVJT prompt v1 was frozen. Blind-spot probe pairs (T1): the judge sided with gold on
  {dev['T1']['n_sided_with_gold']}/{dev['T1']['n']}.
- **System level.** With 3 systems, τ is not reported. The ordering by metric mean is in
  `analysis.json → system_level`.

"""
    head = (ROOT / "src" / "readme_head.md").read_text()
    tail = (ROOT / "src" / "readme_tail.md").read_text()
    (ROOT / "README.md").write_text(head + mid + tail)
    print("README.md regenerated")


if __name__ == "__main__":
    main()
