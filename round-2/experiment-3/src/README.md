# Directional Consensus: freeze on dev, confirm on fresh NL→FOL data

Run `run_ujABDGgoK_5Q`, iteration 2, experiment 3 (plan `gen_plan_experiment_1`: "Checking a formula against its peers, on fresh data").

Workspace (absolute path; every kept artefact lives here):
`.`

**Directional Consensus (DC)** is a gold-free, text-blind faithfulness score for one NL→FOL output. It works as follows:
1. Align each peer formalisation's vocabulary into the candidate's without reading names. The alignment is an arity-preserving bijection (L1), a partial map with fresh leftovers (L2), or an optional granularity split (L3).
2. Let z3 decide the entailment relation of the pair: EQUIV / STRONGER / WEAKER / INCOMPARABLE / CONTRADICTORY / UNALIGNABLE / UNKNOWN.
3. Score the candidate by the Dawid–Skene-weighted share of covered peers that are EQUIV.

The strength profile and a solver diff against the modal cluster give an error type.

The study was run freeze-then-confirm:
1. **Freeze.** The configuration was chosen from a 12-config grid on the 700-sentence dev set (art_iyzYyaqlqpSX), and a sha256 receipt was written at **04:14:11 UTC**, before any fresh label existed.
2. **Confirm.** The frozen DC was tested on a **fresh, overlap-free set of 450 sentences × 9 systems**. The tests are the pre-registered T1–T4, run under **panel** (L3) labels and under **audited-solver** (L1) labels. A test passes only if it passes under both.

> **Read first: deviations that change power.** (1) This session received only the last ~200 characters of its task prompt. The full GEN_ART prompt was reconstructed from the sibling sessions of the same step (identical template and dependency block), plus plan 1 and this workspace path. (2) The run's OpenRouter key has a **$7.00 limit shared by the three parallel experiments**, not $10 per artifact. This artifact spent **$2.38**. The key hit $0 at 04:22 UTC, after generation, B1, the gold audit and the panel had run. Consequences:
> - The L3 panel has **256 adjudicated items** (planned ≈1,000; Kish n_eff 202).
> - B3 and the typed judge use the round-2 **local Qwen3-8B substitutes** (B3nliL/B3cosL, TJ_L). This substitution was pre-registered before any test ran.
> - B1plus, DC+arb and the EU-AI-Act transfer were not run.
>
> Full list: `results/deviations.json`.

## 1. Headline results

### 1.1 Pre-registered tests (fresh set only; `results/tests.json`)

| test | panel (256 items, raked weights) | audited solver | verdict |
|---|---|---|---|
| **T1** Δ AUROC of the cross-fitted stack [base + DC] over base [B1, B2, B3nliL, B3cosL, B7] | +0.033 [−0.001, 0.066], one-sided LB5 **+0.005** | +0.118 [0.051, 0.192], LB5 +0.060 (panel frame, n=245) | **PASS** |
| T1 placebo (DC shuffled within corpus × tercile) | −0.003 [−0.016, 0.008] | −0.001 [−0.010, 0.007] | ≈0, as required |
| T1 sensitivity, base [B1, B2, B7] (every piece frozen and API-scored) | +0.126 [0.066, 0.189] | +0.159 [0.129, 0.190] on all 3,720 rows | – |
| **T2** DC − LC_maj (LB > 0) | +0.030 [0.012, 0.049] ✓ | +0.015 [0.005, 0.026] ✓ | |
| T2 DC − LC_ds_binary (point > 0) | **−0.003** [−0.024, 0.017] ✗ | +0.009 [−0.000, 0.019] ✓ | |
| T2 DC − VC (LB > 0) | +0.152 [0.096, 0.209] ✓ | +0.083 [0.066, 0.102] ✓ | **label-dependent** |
| **T3** (panel only) top-1 type | DC 0.122 vs majority class (added_condition) 0.255 + 0.10: ✗. TJ_L reference 0.017 | – | **fail** |
| T3 recall (added / dropped / ∀∃) | 0.04 (n=27) / 0.41 (n=14) / 0.25 (n=21): all n<30, underpowered | – | |
| T3 within-sentence DC vs B1 | dropped: 1.00 vs 0.64 (7 pairs). Implication: 1.00 vs 0.79 (7 pairs). Underpowered | – | |
| **T4** gpt-4.1-mini: DC_self − B8; [base + DC_self] Δ | 0.000; +0.015 (LB5 −0.062), n=76 | −0.002 (LB5 −0.007); +0.089 (LB5 +0.054), n=431 | **fail** |
| **T4** llama-3.1-8b | −0.016; −0.042, n=67 | +0.005 (LB5 −0.002); +0.125 (LB5 +0.081), n=392 | **fail** |

Readings:
- **T1 passes under both labels.** DC adds signal beyond the frozen judge, round-trip and structural base. The panel lower bound is thin (+0.005) with the local B3 substitute in the base. Against the purely API-scored base it is clear (+0.126 [0.066, 0.189]). The independent numpy-IRLS re-derivation of T1 differs by 0.0049 (panel) and 0.0036 (solver), both under the 0.005 check.
- **T2 is label-dependent.** DC beats majority-equivalence clustering (LC_maj) and the vocabulary-conformity control (VC) under both labels. It **does not beat the round-2 binary Dawid–Skene neighbour (LC_ds_binary) on panel labels** (0.827 vs 0.830). The directional machinery (L2 partial maps, DS weights, strength profile) adds nothing detectable over LC_ds_binary once the panel adjudicates.
- **T3 fails.** DC's rule-based error typing (dev: 68% "other") does not name the panel's error types. Recall of added_condition is 0.04, because L2 folds most extra predicates into STRONGER/WEAKER against a mode that is itself often wrong. The directional part pays off neither in typing nor in the DC+SP stack (panel 0.791 < DC 0.827).
- **T4 fails.** With a system's own 5 samples as peers, DC_self is numerically almost identical to B8 self-consistency (dev and fresh). Alignment-level agreement with oneself adds nothing over bijection-level agreement.

### 1.2 Fresh AUROC (`results/report_tables.md`)

| metric | AUROC panel [95% CI] (n=256) | AUROC solver [95% CI] (n=3,720) | coverage |
|---|---|---|---|
| **DC0** (DC, unparseable → 0) | **0.853** [0.798, 0.898] | 0.874 [0.849, 0.897] | 1.00 |
| LC_huiwalter / LC_onecoin (frozen) | 0.836 / 0.834 | 0.852 / 0.850 | 0.98 |
| LC_ds_binary (frozen) | 0.830 [0.773, 0.878] | 0.865 [0.840, 0.889] | 0.98 |
| **DC** (frozen, pre-registered) | 0.827 [0.770, 0.877] | **0.874** [0.849, 0.897] | 0.945 (4,050 rows) |
| LC_maj (frozen) | 0.797 | 0.859 | 0.98 |
| B1 cheap judge (gemini-2.5-flash, frozen prompt) | 0.791 [0.726, 0.843] | 0.727 [0.698, 0.755] | 1.00 |
| B3nliL / B3cosL (Qwen3-8B back-translation substitute) | 0.784 / 0.752 | 0.619 / 0.657 (n=260) | 1.00 |
| VC vocabulary conformity | 0.674 | 0.791 | 0.945 |
| TJ_L typed judge (Qwen3-8B substitute) | 0.659 | 0.593 (n=260) | 1.00 |
| B7 structural / B2 parse (user's pilot family) | 0.554 / 0.549 | 0.503 / 0.500 | 1.00 |
| DC_self / B8 (2 systems) | 0.842 / 0.843 (n=143) | 0.784 / 0.784 (n=823) | 0.99 |

- The dev→fresh transfer holds. The frozen config scored dev AUROC_P 0.777 / AUROC_S 0.855; on fresh it scores 0.827 / 0.874.
- The fresh panel is a different, smaller sample: sentence-paired, with 12 unparseable items included. That is why DC0 > DC there.

### 1.3 Secondary findings (`results/analysis.json`, `results/analysis_extra.json`)

- **Circularity.** On panel items whose candidate is solver-NON-equivalent to the audited gold (n=168), DC keeps AUROC 0.776 [0.679, 0.858], and 0.771 on the no-bijection subset. So DC is not merely re-deriving the shared z3 checker. LC_ds_binary scores 0.805 and B3nliL 0.799 on the same items.
- **Shared bias is DC's boundary.** In sentences whose modal cluster is wrong, DC collapses: panel AUROC 0.419 [0.292, 0.557] (n=61) against B1's 0.786. Where the mode is right, DC scores 0.883 vs B1 0.782. Agreement cannot see an error the majority shares. This is correlational (mode correctness from labels).
- **Complexity (the user's priority).** On the panel, DC's advantage over B1 shrinks with complexity:
  - Tercile gap DC−B1 is +0.088 / +0.107 / −0.028 (bottom / middle / top). The slope −0.058 [−0.135, 0.022] is not significant.
  - DC is weakest on items with 2+ quantifiers (0.659 vs B1 0.778, n=45), nesting depth 4–5 (0.661 vs 0.732) and more than 20 tokens (0.727 vs 0.810, n=40).
  - DC is strongest with 3+ conditions (0.871 vs 0.787, n=124).
  - Under solver labels DC ≥ B1 in every bin, but that arm is partially circular.
  - These data are connective-heavy, not exception-heavy: public corpora hold almost no unless/except sentences, and the EU-AI-Act transfer could not be run.
- **Within-sentence paired AUROC** (70 faithful × unfaithful pairs from the same sentence): DC 0.929 [0.864, 0.979], LC_ds_binary 0.914, B1 0.786, B3nliL 0.721. Ranking two outputs of the same sentence is where agreement is strongest.
- **Invariance.** Across 1,695 z3-verified meaning-preserving rewrites of 400 fresh candidates, DC's false-alarm rate is 0.25% for synonym renaming and 0.5% for random renaming. The only flips are typing changes, never score or mode changes, and the rate varies by one item between runs because typing searches under wall-clock limits. It is 0% for contrapositive, De Morgan and reorder. The vocabulary-conformity control VC false-alarms on 86% of synonym renamings.
- **Contamination** (dev, renamed-entity candidates). DC is exactly name-blind: the mean Δ between original and renamed candidates is 0.000, against the judge's +0.096 in round 2. Caveat: these contamination candidates are renamed copies of the original outputs, not regenerations.
- **Controlled perturbations** (mechanism evidence only; `results/perturbation_sensitivity.json`). A faithful anchor is a greedy candidate that z3 proves equivalent to the audited gold; there are 298, one per sentence. Each was mutated by one operator, the mutant was kept only if z3 shows it non-equivalent, and the mutant was scored against the same 8 peers.

  | operator | P(DC(anchor) > DC(mutant)) | DC typing accuracy |
  |---|---|---|
  | NEG | 0.93 | 0.02 |
  | ∧↔∨ | 0.92 | 0.00 |
  | ADD | 0.91 | **0.72** |
  | IMPL_REV | 0.89 | 0.23 |
  | DROP | 0.89 | 0.50 |
  | ∀↔∃ | 0.87 | **0.60** |
  | ARG_SWAP | **0.65** | 0.20 |

  - DC detects synthetic errors well except argument swaps. Lexical-free alignment can absorb a swap by permuting constants.
  - Its typing works for the operators its rules target.
  - Real panel errors are typed far worse (T3). The gap is the one the field warns about: synthetic sensitivity is not faithfulness to text.
  - The two low typing rows have simple causes. For NEG, rule 1b (literal flip) was frozen off because it gave no gain on real dev errors. ∧↔∨ has no rule.
- **Wrong-gold flag.** Treating the shipped gold as a 10th peer, 1 − DC_gold predicts the L0 "gold is wrong" verdict with AUROC **0.859** (n=450, base rate 0.458), precision@50 = 0.80. This is a cheap gold-audit prioritiser.
- **System level** (9 systems, Kendall τ_b). Solver labels: DC 0.889 [0.667, 0.944], the best of all metrics. Panel labels: DC 0.556 [0.222, 0.722], while B1 reaches 0.833. Nine systems give wide intervals.
- **Per panel error type** (all classes n<30, descriptive). DC detects ∀/∃ errors (0.896), implication direction (0.881), added conditions (0.799) and dropped conditions (0.785). B1 is better on unparseable (0.963), negation (0.996, n=3) and scope (0.875) errors.
- **Component ladder** (fresh; panel / solver AUROC):
  - L1-only uniform 0.801 / 0.864;
  - adding L2 changes nothing (0.801);
  - adding L3 lowers it (0.791);
  - DS weights raise it to DC 0.827 / 0.874;
  - DC+SP 0.791 / 0.867.

  The weighting carries the gain, not the directional alignment.
- **Coverage and cost.**
  - Relation shares over 14,520 fresh pairs: EQUIV 38.5%, INCOMPARABLE 31.5%, WEAKER 11.3%, STRONGER 9.6%, UNALIGNABLE 9.0%, CONTRADICTORY 0.1%. Timeouts are 0.14% (in 13–20-atom pairs only); EQUIV non-transitivity is 0.
  - DC costs $0 when peers exist, with 0.16 s of solver time per item (p95 0.53 s). If the 8 peers must be generated it costs $0.00039 per item, against $0.00003 for B1.
  - Unparseable greedy outputs (222 of 4,050) are kept. They score 0.5 in DC (uncovered) and 0 in DC0.

### 1.4 Labels (the meta-evaluation set; `results/fresh_set.jsonl`)

- **L0 gold audit** (450 fresh golds). Wrong shipped gold: MALLS 55.3% [48.2, 62.9], FOLIO-v2-train 62.0% [54.0, 70.0], ProverQA 14.6% [9.2, 20.8]; overall 45.8%. Corrections: 193 accepted, 13 flagged but uncorrected (their rows get unknown solver labels).
- **Correct-but-gold-inequivalent.** 43.8% (weighted) of panel items that are solver-non-equivalent to the audited gold are panel-faithful. 8.1% of solver-equivalent items are panel-unfaithful. Solver–panel agreement is 68.9%. These reproduce the dev rates (43.9%, 9.9%, 67.6%).
- **Panel.**
  - Calibration gate re-run: M1 claude-haiku-4.5 0.90, M2 grok-4.3 0.90, M3 glm-4.6 0.85 (round 1: 0.90 / 0.90 / 0.875).
  - Fleiss κ is 0.54 on the 24-item full-panel subset (round 1: 0.63 on 609).
  - The L0 cascade equals the 3-member majority on 45/45 full-subset golds.
  - 16 panel items lost their tie-break when the key ran out. They are excluded and counted.

## 2. Reusable functions (`dc/`, text is never read)

| function | what it measures |
|---|---|
| `dc.parse_fol(s)` | Parsed, arity-normalised AST of a formula string, or None (vendor tolerant parser: unicode / ASCII / LaTeX / snake_case). |
| `dc.align_pair(A, B, caps, use_L3)` | Finds the lexical-free vocabulary map from B's symbols into A's under which the two formulas stand in the strongest solver-verified entailment relation. Returns a config-agnostic record with the L1/L2/L3 results and the map. |
| `dc.derive(rec, use_L3, half_caps)` | The relation under one grid configuration, derived from a record without re-solving. |
| `dc.pair_relation(A, B)` | The solver-decided entailment relation of A to B over a shared vocabulary. The bounded check uses grounding over domains 1–4 (a countermodel is sound); the unbounded check uses z3 DeclareSort with a 5 s limit. |
| `dc.fit_weights(sentences, systems)` | Label-free one-coin Dawid–Skene system reliabilities from the EQUIV clusters. w = clip(logit p, 0.05, 3). |
| `dc.score_group(outputs, rel, w, cfg)` | DC for every output of one sentence: the weighted EQUIV share among covered peers, plus the strength profile, mode cluster and modal representative. |
| `dc.directional_consensus(text, fol, peers, weights, cfg)` | The reliability-weighted share of peer formalisations that are solver-equivalent to this one under lexical-free alignment. `text` is not read. Returns the score, coverage, relations, error type and cost. |
| `dc.type_error(C, M, rec)` | Error type of C against the modal representative M: rules 1 / 1b / 2–7 (negation, added / dropped condition, ∀∃, implication direction, argument swap, other). |

Example:
```python
from dc import directional_consensus, DCConfig
cfg = DCConfig(use_L3=False, unalign_in_denominator=True, weights="DS")   # the FROZEN configuration
r = directional_consensus("Every dog barks.", "∀x (Dog(x) → Barks(x))",
                          ["∀y (Hund(y) → Bellt(y))", "∀x (Dog(x) ∧ Big(x) → Barks(x))"], cfg=cfg)
# r["score"] == 0.5, r["covered"] True, r["relations"] {"EQUIV": 1, "STRONGER": 1}; weights default to 1 per peer
```
The unit tests are in `tests/test_dc.py`: 16 pass (`results/unit_tests.json`). The vendor parser and solver tests pass 29/29.

**Frozen configuration** (`results/frozen_config.json` + `.sha256`):
- L3 **off**, UNALIGNABLE **in** the denominator, **DS** weights, caps ×1, typing rule 1b off.
- dc/ tree sha256 `7f805769…df965`. The receipt verifies, no dc/ file changed after the freeze, and the 78 vendored files are byte-identical to their sources (`results/integrity.json`).
- Selection rule: argmax mean(AUROC_P, AUROC_S), with ties within 0.005 going to the simpler config.
- L3off_UAout_DS scored 0.8169 against 0.8159 for the chosen config. They tied, and the rule picked the simpler "UA in".

## 3. What was run

| step | script | what | cost |
|---|---|---|---|
| sample | `src/s01_sample_fresh.py` | 450 fresh sentences (MALLS 170, FOLIO-v2-train 150, ProverQA 130). 50% top tercile. Zero overlap with the dev 700, screen 360, contamination originals and calibration 40 (by normalised string AND FOLIO story id, asserted); seed 20260924 | $0 |
| generate | `src/s02_generate.py` | 9 systems × greedy (T=0) + gpt-4.1-mini / llama-3.1-8b × 5 samples (T=0.8); frozen round-1 prompt (sha1 `afabb41e…`); 8,550 outputs, 0 failed calls; greedy parse rate 0.81 (phi-4) to 0.996 | $0.4535 |
| dev | `src/s03_dev_frame.py`, `src/pairs.py`, `src/s04_freeze.py` | Dev relation cache (14.6k greedy pairs + 7.4k within-system pairs, about 2 min on 12 cores), the 12-config grid, rule-1b decision, ladder, diagnostics, receipt. L1 reproduces 8,180/8,180 round-2 'equiv' verdicts; L1-uniform vs round-2 LC_maj Pearson 0.982 | $0 |
| fresh | `src/s05_fresh.py` | Fresh frame; DC cache (12.6k pairs); frozen LC (Arm B `find_bijections` + `latent_class.run_latent_class` verbatim, 14.2k pairs); B7 / B2 / B7_jacc port; VC (WordNet lemmas) | $0 |
| labels | `src/s06_labels.py` | Calibration gate; L0 cascade; L1 lexical-free solver labels (vendor `fol_equiv.equivalence`); L3 sentence-paired blinded A/B cascade | $0.150 + $0.876 + $0.806 |
| baselines | `src/s09_llm_baselines.py`, `src/s09b_local.py` | B1 on all 4,050 greedy rows (frozen request); Qwen3-8B substitutes B3L / TJ_L on the 272 panel items (RTX 4090) | $0.0995 |
| scores / tests | `src/s10_scores.py`, `src/s11_tests.py` | `results/scores.jsonl`; T1–T4 with 2,000 sentence-cluster draws within corpus × tercile | $0 |
| secondary | `src/s12_secondary.py`, `src/s12b_extra.py`, `src/s12c_perturb.py` | Circularity, ladder, system level, complexity, invariance, shared bias, wrong-gold flag, contamination, coverage, cost, label quality, per-type, within-sentence; controlled perturbations | $0 |
| export | `src/s13_export.py`, `src/report_tables.py`, `audit_rederive.py` | `method_out.json` (+ full / mini / preview), `results/fresh_set.jsonl`, `results/report_tables.md`, `results/audit_rederive.json`, `results/integrity.json` | $0 |

Total OpenRouter spend is **$2.3848** (the sum of `cost_ledger.jsonl`, one line per call).

## 4. Layout

- `method.py`: the single entry point, `uv run method.py --stage {sample,generate,devframe,devpairs,freeze,fresh,gate,labels,llm,local,scores,tests,secondary,export,all_offline}`.
- `dc/`: the DC library. `parse.py` (parsing, renaming, fingerprints), `align.py` (L1/L2/L3 search, `derive`), `relation.py` (z3 relation), `weights.py` (DS), `consensus.py` (DC score, strength profile, mode), `errtype.py` (typing).
- `src/`: pipeline stages (table above).
  - `common.py`: paths, loaders, the freeze-receipt guard (`assert_frozen`), the post-freeze read logger.
  - `orc.py`: capped OpenRouter client with a per-call ledger and request cache; the proxy URL comes from `OPENROUTER_BASE_URL`.
  - `pairs.py`: the config-agnostic relation cache.
  - `dcscore.py`: batch DC scoring.
  - `typing_jobs.py`: parallel typing.
  - `aframe.py`: analysis frame with raked panel weights.
  - `rewrites.py`: meaning-preserving rewrites.
- `tests/test_dc.py`: DC unit tests.
- `vendor/`: read-only copies, sha1s in `results/vendor_manifest.json`.
  - `vendor/ds/`: dataset code, prompts, panel config and calibration set (art_iyzYyaqlqpSX).
  - `vendor/r2/`: round-2 exp-3 code (stats, gpu_b3, llm_stages, local_llm, Arm B `fol_core` / `latent_class`, workers).
  - `vendor/tj/`: the typed-judge prompt source.
- `results/`:
  - `frozen_config.json` (+ `.sha256`): the receipt, with the dev grid, ladder and diagnostics.
  - `fresh_sentences.json`, `fresh_sample_report.json`.
  - `fresh_set.jsonl`: **the fresh meta-evaluation set**, 8,550 outputs with provenance, original and audited gold, L0 votes, L1 status and entailment hints, L3 votes / majority / primary error, design and raked weights, complexity, and final label + label_source.
  - `scores.jsonl`: long format, item_id / metric / score / covered / usd / seconds / extra.
  - `tests.json`, `analysis.json`, `analysis_extra.json`, `perturbation_sensitivity.json`, `report_tables.md`.
  - `calibration_gate.json`, `deviations.json`, `unit_tests.json`, `audit_rederive.json`, `integrity.json`, `post_freeze_reads.log`, `dev_L3_equiv_samples.json` (20 L3-EQUIV dev pairs for inspection).
- `work/`: caches, all text.
  - `generations/<system>.jsonl`: **irreproducible raw API outputs**.
  - `llm_cache/*.jsonl`: every paid response, keyed by request.
  - `pair_cache.jsonl`: DC relations. `pair_cache_v0_asymmetric_share.jsonl` is the pre-fix cache, kept for audit.
  - `lc_pairs_cache.jsonl`, `lc_scores_fresh.jsonl`.
  - `l0_results.json`, `l1_fresh.jsonl`, `l3_fresh.json`.
  - `b1_fresh.jsonl`, `b3L_fresh.jsonl`, `tjL_fresh.jsonl`, `local_llm/`.
  - `dev_frame.jsonl`, `dev_baselines.json` (round-2 frozen dev scores).
  - `failed_api/`: the empty outputs of the calls made after the key ran out.
- `rederive_headline.py` → `results/rederive_headline.json`: independent pandas/sklearn re-derivation of the headline numbers from raw files, with its own raking and placebos. AUROCs are identical; T1 panel +0.029 with refit LB5 +0.0035; the shuffled-DC and permuted-label placebos fail.
- `reproducibility.md`: step-by-step reproduction. `requirements.lock.txt` and `pyproject.toml` hold the exact pins.
- `cost_ledger.jsonl`: one line per paid call.
- `method_out.json`: exp_gen_sol_out, validated; `full_` / `mini_` / `preview_` variants alongside. One example per fresh greedy output (4,050): input `{sentence, candidate_fol}`, output = final label, `predict_{DC, DC0, DC_self, LC_*, VC, B1, B2, B7, B8, B3nliL, B3cosL, TJ_L, sp_*}` and `predict_DC_error_type`.

## 5. How to run

```bash
bash restore.sh                              # .venv (pinned; torch 2.11.0 cu128) + WordNet + DC unit tests
uv run method.py --stage all_offline         # rebuild every $0 stage from the caches (dev, fresh, scores, tests, analyses, export)
uv run audit_rederive.py                     # independent AUROC re-derivation, bounded-vs-unbounded check, integrity
# paid stages (all cached per request; re-running them costs $0 while work/llm_cache/ is present):
uv run method.py --stage generate && uv run method.py --stage gate && uv run method.py --stage labels && uv run method.py --stage llm
```
Before any label stage, `results/frozen_config.json` must exist and its sha256 must verify. Stages `l0`, `l1`, `l3`, `scores` and `tests` refuse to start otherwise.

## 6. Deviations (full text in `results/deviations.json`)

| ID | deviation |
|---|---|
| D-PROMPT-TRUNCATED | The task prompt arrived truncated. It was reconstructed from the sibling sessions: the same template, with plan 1 and this workspace |
| D-KEY-SHARED | The $7 key was shared by 3 experiments and was exhausted at 04:22 UTC. This artifact spent $2.38 |
| D-L3-SIZE | 272 panel items sampled, 256 with a majority (planned ≈1,000). The panel arm is underpowered and the solver arm carries power |
| D-L3-DESIGN | Sentence-paired sampler (mode + minority per sentence); weights raked over stratum × system; max/min ratio capped at 6 (148 items floor-capped, Kish 202) |
| D-L0-CASCADE | glm-first cascade (M3 → M1 → M2). It agrees with the 3-member majority on 96.6% of dev golds and 45/45 fresh subset golds |
| D-B3-LOCAL / D-TJ-LOCAL | Qwen3-8B substitutes for B3 and TJ, pre-registered before the tests. TJ_L is lenient (219/272 "faithful"), so it is a weak T3 reference |
| D-B1PLUS / D-ARB / D-EUAI / D-A3 | Not run (key exhausted). The frontier gap is reported on dev only: stack [B1, B2, DC] 0.796 vs gemini-2.5-pro 0.825 |
| D-SHARE-SYMMETRY | Pre-freeze fix: the 50% mapped-share rule became symmetric after the symmetry unit test failed. Dev caches were recomputed |
| D-DS-MODEL | Pre-freeze fix: the DS EM had degenerate optima; a wrong-cluster penalty was added and the 'none' state dropped |
| D-TYPING | Unit-test cases adapted where lexical-free alignment is ill-posed. Dev typing gave 68% 'other' (F9); rule 1b gave no gain and is off |
| D-L3-EQUIV-MERGE | A unit test shows lexical-free L3 cannot tell an added conjunct from a split concept. The dev grid chose L3 off, and L3 lowers AUROC on fresh too |
| D-TORCH | The pinned torch 2.14 (CUDA 13) cannot use the host driver (CUDA 12.8). torch 2.11.0+cu128 was installed for the GPU substitutes |

## 7. Restoring removed files

| removed path (`.aii/manifest.yaml`) | restore with |
|---|---|
| `.venv/` | `bash restore.sh` (runs `uv venv .venv --python 3.12 && uv pip install -r pyproject.toml`, then `uv pip install --reinstall-package torch torch==2.11.0 --index-url https://download.pytorch.org/whl/cu128`). The exact freeze is in `requirements.lock.txt` |
| `.nltk_data/` | `bash restore.sh`, which curls `https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/packages/corpora/{wordnet,omw-1.4}.zip` into `.nltk_data/corpora` and unzips them |
| `**/__pycache__/` | Regenerated automatically |
| `vendor/ds/.pytest_cache/` | `cd vendor/ds && ../../.venv/bin/python -m pytest -q -c pytest.ini tests/test_fol.py` |
| HF weights (outside the workspace, in the run's shared `$HF_HOME`) | Downloaded on first use: `sentence-transformers/all-MiniLM-L6-v2`, `MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli`. Qwen3-8B was read from a local snapshot of `Qwen/Qwen3-8B` rev `b968826d9c46dd6066d109eabc6255188de91218`; `huggingface-cli download Qwen/Qwen3-8B --revision b968826d…` restores it |
