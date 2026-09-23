# sigfaith — naming FOL errors and flagging bad gold (run_qY2a2IS-WLIs, iter 2, experiment 5)

This experiment takes the iter-1 **monotonicity-signature** faithfulness metric for NL→FOL (Arm A, variant A3) and:
1. repairs it on the screen only;
2. freezes it behind a hash-checked label firewall;
3. validates it on held-out real outputs (dataset art_iyzYyaqlqpSX) in four roles.

The four roles are **V1** error-type naming, **V2** blind spots on real errors, **V3** wrong-gold flagging and **V4** the polarity increment. Two further analyses are exploratory: **V5** document conflation and **V6** EU-AI-Act transfer.

The headline result is **mostly negative**, and every pre-registered verdict is reported with its numbers.

Workspace (absolute): `/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_2/gen_art/gen_art_experiment_5`

## Headline results

All numbers are post-freeze and use panel3 labels with post-stratified weights. CIs come from 2,000 sentence-clustered bootstrap resamples.

**Screen repair.** The screen was split sha1-by-sentence into 150 DEV and 150 TEST sentences.

**R1 aligner** (Hungarian; lemma, WordNet-path and MiniLM similarity, plus an arity term; polarity-blind).
- The pre-registered rule picked `τ=0.55, path, MiniLM-L6, β=0.1`, which is the only DET-feasible family.
- On SCREEN_TEST:

  | Measure | Repaired | Legacy |
  |---|---|---|
  | SYN_RENAME false alarms | **0.129** | 0.419 |
  | FA_RENAME2 (unseen gpt-4.1-mini renames, WordNet-filtered, n=134) | **0.515** | 0.575 |
  | FA on logical rewrites | 0.007 | 0.0 |
  | AUROC on real candidates | 0.738 | 0.732 |

- `R1_TARGET_MISSED` (the ≤0.05 target). The pre-registered mpnet fallback variant broke ADD detection and was rejected.

**R2 text side.** The chosen side is **T1c**: rule default, overridden by a consistent gemini probe '−'.

| Text side | DEV balanced | DEV silver | DEV downward | TEST downward (Wilson 95% CI) | TEST balanced |
|---|---|---|---|---|---|
| T1c | 0.943 | 0.922 | 0.962 | **0.949 [0.91, 0.97]** | 0.925 |
| T0 rules | 0.913 | 0.915 | 0.894 | 0.847 | 0.879 |

- T2 with gpt-5-mini tied T1c on the objective and lost the tie-break to the cheaper side. gemini-2.5-pro was ineligible (projected $1.72 > $1.5).
- **Held-out silver** (text label vs the solver sign of L0-faithful golds): T1c 0.748 vs T0 0.635. Downward concepts: 0.648 vs 0.435.

**R3 decoder.** On SCREEN_TEST mutants, D_rule has macro-F1 0.389, top-1 0.40 and top-2 0.59; D_lr has macro-F1 0.453, so both are carried to held-out. On the SCOPE_SWAP supplement, detection is exactly 0.5 (blind by construction).

**Pre-registered verdicts** (`results/verdict.json`):

| Verdict | Result | Numbers |
|---|---|---|
| DIAGNOSER_POSITIVE | **FAIL** | D_rule weighted top-1 **0.111** vs TJ (typed gemini judge) 0.302: Δ −0.19 [−0.26, −0.12], McNemar p=1.5e-7.<br>TJ+ (thinking) 0.281; majority class 0.249; D_lr 0.145.<br>Recall: added 0.08, dropped 0.43, ∀∃ 0.10.<br>With truth permuted, D_rule scores 0.090, so it is barely above chance.<br>Panel ceiling: pairwise primary agreement 0.37; leave-one-member-out 0.55 |
| FLAGGER_POSITIVE | **FAIL** (one clause) | Pooled held-out gold AUROC 0.673 [0.634, 0.712] (> 0.5 ✓).<br>ProverQA P@25 = 0.40 (✓); pooled enrichment@50 = 0.58 [0.34, 0.76] (✓).<br>But Ccov 0.686 ≥ flag_S, so the "S ≥ coverage control" clause fails ✗.<br>B1 0.840 and TJ 0.859 dominate.<br>**Complementarity**: B1 + flag_S, cross-fitted, 0.861 vs B1 0.808, Δ +0.054 [0.029, 0.079] |
| POLARITY_CARRIES_SIGNAL | **FAIL** | ΔAUROC(M2 = [B1, parse, A0] + P) = +0.011 [−0.010, 0.031]; with S: +0.009 [−0.012, 0.029].<br>A within-sentence placebo gives a similar value (+0.009), so no evidence that polarity adds over alignment |
| RENAME_FIXED | **FAIL** | FA_rename 0.129; FA_RENAME2 0.515.<br>Criterion 5 (full signature match on 250 panel-faithful, solver-non-equivalent items) = **0.256** (legacy 0.212; target ≥ 0.80) |
| BLIND_SPOTS_CONFIRMED | **not confirmed** | PREDICTED_VISIBLE detection 0.73 [0.67, 0.79] (< 0.80).<br>PREDICTED_BLIND 0.59 [0.43, 0.77], n=23. The blind CI contains 0.5, but its upper bound is not below the visible lower bound: underpowered |

**Standalone AUROC** (panel3, weighted):

| Metric | AUROC |
|---|---|
| S_frozen | 0.654 [0.60, 0.71] |
| A0 | 0.673 |
| Ccov | 0.674 |
| A3_iter1 | 0.639 |
| P (polarity-only) | 0.580 |
| B1 | 0.745 |
| TJ | 0.777 |

In the top complexity tercile: S 0.608, B1 0.758. Placebo check: S keeps AUROC 0.648 when labels are shuffled *within* sentence, so most of its item-level signal is between sentences.

**Where the signature does work.**
- **Within-sentence detection**, against faithful partners from other systems: dropped condition 0.85 [0.74, 0.94] and implication 0.87 [0.68, 0.99]. B1 scores 0.62 and 0.77 on these; TJ scores 0.49 and 0.53.
- **Gold flagging as a complement to an LLM judge.** It adds significant AUROC over B1.
- **Cost**: zero LLM calls on the formula side, a median 0.06 s per item, and 93.8% coverage (301 unparseable, 88 low-coverage).

**Other results.**
- V5 (exploratory, 585 documents): the document conflation/split flags hit 16 of 30 real conflation/split errors, but also flag 60 of 120 clean rows. That is no better than chance.
- V6 transfer (EU AI Act): 289 of 367 formulas parse (66 of the 78 failures use '⊆'). Coverage is 93% of parseable formulas, with median score 0.50. That is far below held-out, which reflects long definitions with many dropped concepts.

**API spend**: $4.48 of the $6 hard cap (cap test passed). By phase:

| Phase | Cost |
|---|---|
| Held-out probes | $2.49 |
| TJ | $0.38 |
| TJ+ | $0.84 + $0.37 retry |
| R2 | $0.35 |
| B1 | $0.04 |
| RENAME2 | $0.015 |

## Layout

| Path | What |
|---|---|
| `method.py` | Pipeline driver (`--stages all`) and `make_outputs()` → `method_out.json` (exp_gen_sol_out, validated) |
| `sigfaith/` | **Deliverable module**:<br>`__init__.py` holds `signature_faithfulness`, `gold_audit` and `document_signature`, with docstrings stating what each measures and its blind spots;<br>`align2.py` (R1); `decoder.py` (R3); `core.py` (front-end adapter, text-side chooser, full-coordinate scorer);<br>`textside.py` (spaCy + probe); `llm.py` (OpenRouter client: ledger, $6 hard cap, cache); `heldout_io.py` (label firewall); `front_parse.py` (dataset parser) |
| `legacy_armA/` | Vendored iter-1 Arm A code (unchanged except `llm.py` → `legacy_llm.py` to avoid a name clash), plus iter-1 text/formula signatures |
| `prep_data.py` | Splits the dataset into label-free inputs (`data/heldout_inputs.jsonl`) and firewalled labels (`data/heldout_labels.jsonl`) |
| `screen_common.py`, `phase1_r1.py`, `phase1_r2.py`, `phase1_r3.py` | Screen repair: regression test, RENAME2, R1 grid, R2 DEV/pilot/select/TEST, R3 calibration |
| `r2_warm.py`, `tjplus_retry.py`, `key_watch.py` | Probe-cache pre-warm; TJ+ truncation retry; OpenRouter availability poller (used once) |
| `freeze.py` | Writes `results/frozen_config.json` (config, decoder, sha256 of `sigfaith/` + `legacy_armA/src/`, screen tables); checks the firewall is closed before and open after |
| `phase2_sigs.py`, `phase2_score.py`, `phase2_llm.py` | Held-out solver signatures; frozen scoring (inputs only); B1/TJ/TJ+ baselines |
| `analyze.py` | V1–V6, criterion 5, silver, system level, verdicts → `results/analysis.json`, `results/verdict.json`, `results/per_item_panel.jsonl`, `results/per_gold.jsonl` |
| `audit_rederive.py` | Independent re-derivation (own weighted-AUROC code, raw files) of the V1 top-1, V3 pooled AUROC, V4 ΔAUROC and standalone AUROCs, plus placebos → `results/audit_rederive.json` (all_ok = true) |
| `make_figures.py`, `figures/` | V1 confusion heatmaps, V2 detection forest, V3 P@50 bars, V4 ΔAUROC forest (PDF+PNG) |
| `tests/test_align2.py` | 20 tests, all passing (`results/pytest_result.txt`): aligner (teacher↔Educator, ExcellentLocation, rex, Adores arity), polarity-blind sim matrix, 12 solver hand formulas, decoder, budget guard, firewall |
| `results/` | All screen tables (`r1_grid.json`, `r2_*.json`, `r3_decoder.json`, `regression_test.json`, `rename2_report.json`), frozen config, per-item scores (`heldout_scores.jsonl`, `gold_scores.jsonl`, `transfer_scores.jsonl`), LLM baselines (`llm_baselines.jsonl`), `cost_ledger.jsonl`, solver signatures |
| `cache/llm/`, `cache/llm_iter1/` | Content-hash cache of every OpenRouter answer (irreproducible, kept; excluded from the GitHub upload) |
| `data/` | Copied screen set, MED/HELP, blind-spot supplement, adjudication prompt, RENAME2 set, split dataset files |
| `method_out.json`, `full_/mini_/preview_method_out.json` | Per-item predictions: 6,300 candidates + 700 gold audits + 367 transfer rows. Metadata holds every analysis table, the verdicts and the frozen config |

## How to run

```bash
uv venv .venv --python=3.12 && uv pip install --python .venv/bin/python -r requirements.txt \
  --extra-index-url https://download.pytorch.org/whl/cpu
.venv/bin/python -c "import nltk; [nltk.download(p, download_dir='nltk_data') for p in ('wordnet','omw-1.4')]"
export OPENROUTER_API_KEY=...        # cached answers in cache/ make a re-run nearly free
.venv/bin/python method.py --stages all
.venv/bin/python -m pytest -c pytest.ini tests/test_align2.py
```

Using the API directly:
```python
import sigfaith
sigfaith.signature_faithfulness("All dogs that are not trained bark.", "∀x ((Dog(x) ∧ ¬Trained(x)) → Bark(x))")
sigfaith.gold_audit(sentence, gold_fol)["flag_score"]
sigfaith.document_signature([s1, s2], [f1, f2])
```

## Deviations (honest list)

1. **OpenRouter daily-limit 403** (shared key) at 14:38 UTC. The first RENAME2 attempt waited, and a watcher (`key_watch.py`) found the key working again at 14:49 after one poll costing $0.0000134 (not in the ledger). No LLM result was substituted.
2. **Pre-freeze label peek (format only).** While writing `prep_data.py`, the counts of `L3_majority` (307/302) and `L1_audited_status` in the label file were printed to check field formats. These numbers are already published in the dataset README. No metric was compared with any label before the freeze.
3. `heldout_io.load_inputs()` exposes one **design variable**, `in_panel_sample` (= `L3_selected`, adjudication-sample membership). It was needed to know which items B1/TJ must score. No verdict, weight or type is exposed.
4. **R2 on MED/HELP** is evaluated probe-style: the iter-1 substitution questions for the edited concept (2 specialised copies × up/down). This lets all text sides be compared on identical items; the iter-1 NLI-style B6 answers cannot give T1b/T1c. Usable items were DEV 278/400 and TEST 439/600, after the iter-1 single-span filter and dropping items with no extracted concept.
5. **A0_iter1** on held-out uses the T0 text side. In iter-1, A0 used the LLM side's '?' labels; the regression test reproduces that iter-1 convention exactly on the screen.
6. **TJ+** was run post-freeze on the 302 panel-unfaithful items. Selection by label is allowed for a baseline; the spend was under the $4.5 rule. 87 answers were truncated at max_tokens 1600 and re-asked once at 3000; 19 are still unparsed and count as wrong.
7. **R1_TARGET_MISSED.** The ≤0.05 FA_rename target was missed. The pre-registered mpnet fallback was evaluated and rejected by the DET constraint.
8. Solver: heavy formulas fall back to N=2 (>12 predicates or >6 quantifiers). One held-out formula timed out at 120 s, and 374 of 6,371 distinct formulas are unparseable.
9. Figures were drawn with matplotlib directly, reading numbers from `analysis.json`.

## Restoring removed files

| Path (deleted after the round) | Restore with |
|---|---|
| `.venv/` | `uv venv .venv --python=3.12 && uv pip install --python .venv/bin/python -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cpu` |
| `nltk_data/` | `.venv/bin/python -c "import nltk; [nltk.download(p, download_dir='nltk_data') for p in ('wordnet','omw-1.4')]"` |
| `**/__pycache__/`, `.pytest_cache/` | Regenerated automatically by Python / pytest |

SBERT models (`sentence-transformers/all-MiniLM-L6-v2`, `all-mpnet-base-v2`) live in the run's shared HF cache, not in this workspace.
