# Held-out NL→FOL faithfulness meta-evaluation dataset (run_qY2a2IS-WLIs, iteration 1)

This is the **held-out confirmation population** for gold-free NL→FOL faithfulness metrics. The iter-1 screen never touches it.

It contains:
- **700 sentences** from MALLS-v0.1-test, FOLIO-v2-train and ProverQA-dev. 45.1% are in the top complexity tercile.
- **Real candidates from 9 current systems** (7 families, 8B to frontier-mini): 6,300 greedy candidates plus 7,000 T=0.8 samples.
- **Audited gold** and **layered labels**: L0 gold audit, L1 lexical-free solver equivalence, L2 granularity-aware equivalence, and L3 blinded 3-model adjudication.
- An audit of the screen's FOLIO-dev gold (L4).
- An entity-renamed contamination set (E1).
- The user's EU-AI-Act pilot formulas as an unlabeled transfer split (E2).

Workspace (absolute): `/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_dataset_1`

---

## 1. Headline facts about the labels (read before using them)

All numbers below come from `label_report.json`, with 95% CIs.

| Quantity | Value |
|---|---|
| **Wrong shipped gold** (L0 panel-unfaithful share) | MALLS-test 45.6% [39.5, 51.8] (n=250)<br>FOLIO-v2-train, non-trivial sentences, 62.0% [55.8, 67.8] (n=250)<br>FOLIO-v1-validation (screen) 44.2% [39.1, 49.3] (n=360)<br>ProverQA-dev 17.5% [12.9, 23.4] (n=200) |
| Panel vs **human** relabelling (arXiv:2606.02837, MALLS first-100, n=99) | agreement 78.8%, Cohen κ = 0.57. Human wrong-rate 41.4%, panel 46.5%. Confusion: 45 both-ok, 33 both-wrong, 13 panel-only, 8 human-only |
| **Correct-but-gold-inequivalent** rate: L3-faithful share among L1_audited non-equivalent candidates | **43.9% [39.5, 48.6]** (n=546, weighted)<br>no-bijection 44.7%<br>bijection-but-non-equivalent 39.5%<br>by corpus: FOLIO 59.7%, MALLS 32.7%, ProverQA 31.0%<br>top tercile 42.9% |
| Same rate against the ORIGINAL gold (L1_orig non-equivalent) | 47.8% [43.6, 51.9] |
| Panel-unfaithful share among L1 **equivalent** candidates | 9.9% [3.3, 18.1] (n=63) |
| Agreement of solver-only (L1) labels with the L3 panel majority | 67.6% [63.5, 71.1] (weighted over the frame) |
| L2 `equiv_granular` items judged faithful by the panel | 87.5% (35/40) |
| Fleiss κ, L3 (3 raters, 609 items) | 0.63 on the candidate; 0.53 on the gold |
| Fleiss κ, L0 (full-panel 20% subset, 224 items) | 0.55 |
| Scope + cardinality share of real errors (weighted, L3-unfaithful) | 6.9% |
| Most frequent real error types (weighted) | added_condition 26%, quantifier_forall_exists 22%, dropped_condition 15%, implication_direction_or_only 7% |

Consequences for iteration 2:
1. **Solver-equivalence-to-gold is a poor ground truth here.** Even after the gold audit, about 44% of "non-equivalent" candidates are faithful under different vocabulary or granularity. The strict arity-preserving bijection (the screen's label definition) is the main cause: 3,356 of 6,300 greedy candidates are `non_equiv_no_bijection`.
2. The trustworthy labels are:
   - the **609 `label_source=panel3` items**, unbiased with `metadata_L3_sampling_weight`;
   - the L1-equivalent items, which the panel confirms 90% of the time.
3. For non-adjudicated L1-unfaithful items, `metadata_L3_stratum_p_faithful` gives the estimated probability that the label is wrong. Use it for probabilistic labels, sensitivity analyses, or restricting to low-noise strata.
4. **ProverQA is not synthetic-clean.** 33% of a 30-item spot check was flagged, so the audit was escalated to all 200 items. The dominant failure is a gold that drops a restrictor the sentence states, e.g. "For all fish, …" with no `fish(x)`. The same defect appeared in 3 of the 15 ProverQA "faithful-by-construction" calibration golds.
5. Real errors are dominated by added/dropped conditions and ∀/∃ choice. Scope and cardinality errors are rare (≈7%), so a metric that is blind to scope loses little on this population.

## 2. Layout

| Path | What it is |
|---|---|
| `full_data_out/full_data_out_{1,2,3}.json` | **THE DATASET** (exp_sel_data_out schema): the 5 chosen groups, split under the 20 MB-per-file limit. Each part holds `{"metadata", "datasets": [{"dataset": <group>, "examples": [...]}]}` |
| `full_data_out/{mini,preview}_full_data_out_{i}.json` | First 3 rows per group of each part; preview truncates strings to 200 chars |
| `mini_full_data_out.json`, `preview_full_data_out.json` | First 3 rows of EVERY group (all 5), whole dataset |
| `data.py` | **uv inline script** (`uv run data.py`). It reads `work/assembled_data_out.json.gz` (the pipeline output) and re-verifies every row against the raw source files in `temp/datasets/`. It adds `metadata_source_verified` (15,606/15,606 true) and `metadata_source_file`, then writes `full_data_out.json`. `src/split_outputs.py` splits that file into `full_data_out/` |
| `label_report.json` | Label-quality documentation: counts, exclusions, parse rates, L1/L2 distributions, wrong-gold rates, panel-vs-human and panel-vs-folio-refined agreement, correct-but-inequivalent rates, error-type mix, Fleiss κ, calibration, post-stratification, costs |
| `cost_ledger.jsonl` | One line per OpenRouter call (18k calls, $9.22 total), with phase, model, tokens, provider and cost |
| `raw/generations/<system>.jsonl` | **Irreproducible raw API outputs** of the 9 systems (greedy + samples), including provider, usage and finish_reason |
| `raw/github/` | FOLIO v0.0 (v1) train/validation and Logic-LM `FOLIO_dev_*.json` outputs (screen sources) |
| `raw/hf_downloads/` | HF source files (kept; `restore.sh` re-downloads them if missing) |
| `raw/pilot/` | User pilot zip, extracted read-only (deleted after the round; see §9) |
| `prompts/` | Frozen prompts: `generation_prompt.txt` (sha1 in every row), `gold_audit.txt`, `adjudication.txt` |
| `src/fol_parse.py` | Tolerant FOL parser/printer: unicode + ASCII + LaTeX, snake_case/CamelCase, multi-binders, wide-scope repair, implicit closure of free x/y/z |
| `src/fol_equiv.py` | **L1**: lexical-free equivalence up to an arity-preserving predicate+constant bijection. Random-structure refutation → propositional grounding over domains 1..4 with z3 (countermodel = sound non-equivalence) → unbounded z3 (`DeclareSort`, 10 s) |
| `src/fol_granular.py` | **L2**: WordNet-lemma compound definitions (≤2 literals), substituted, then L1 rerun. Flagged lexical |
| `src/prep_sources.py` | Steps 1–3: loaders, filters, disjointness, complexity features, stratified sample, screen reproduction, calibration set |
| `src/generate.py` | Step 4: async generation with 9 systems (resumable) |
| `src/reextract.py` | Re-applies the v2 extractor (LaTeX unwrapping) to stored raw outputs |
| `src/label_l1.py` | Step 5: L1/L2 labelling with 4 spawn workers and a pair cache |
| `src/panel.py`, `src/calibrate.py`, `src/calibrate_variants.py` | Step 6: panel prompts, members and the known-label calibration gate |
| `src/audit.py` | Step 7: L0 + L4 cascaded gold audit |
| `src/l3_adjudicate.py`, `src/l3_extra.py` | Step 8: blinded A/B 3-member adjudication (460 stratified + 150 extra top-tercile) |
| `src/e1_contamination.py`, `src/e2_transfer.py` | Steps 10–11 |
| `src/assemble.py`, `src/split_outputs.py` | Steps 9 and 12: final labels + report (→ `work/assembled_data_out.json.gz`), then split + mini/preview of `full_data_out.json` |
| `src/fix_varlike_patch.py` | Post-hoc repair after a parser bug fix (see §6) |
| `src/or_client.py` | OpenRouter client: usage accounting, cost ledger, hard $9.30 cap |
| `tests/test_fol.py` | 29 unit tests: 15 hand formulas with parse→print→parse round trip, plus equivalence, entailment and sat/validity cases |
| `work/` | Intermediate state:<br>`heldout_sentences.json`, `screen_sentences.json`, `calibration_set.json`, `pool.json`, `gold_checks.json`<br>`audit_results.json`, `l3_results.json`, `e1_results.json`, `e2_rows.json`<br>`panel_cache.jsonl` (every panel response, irreproducible), `l1_cache.jsonl`<br>`calibration_*.json`, `panel_config.json`, `prep_report.json`, `openrouter_catalog.json` |
| `temp/datasets/` | The 10 kept source datasets (symlinks into `raw/`, plus the ccg2lambda parquet files) |
| `temp/previews/`, `temp/websearch/`, `temp/hf_search.txt` | Dataset-search evidence (§7) |
| `logs/` | Run logs |

Loading the data:
```python
import glob, json
parts = sorted(glob.glob('full_data_out/full_data_out_*.json'), key=lambda p: int(p.rsplit('_', 1)[1][:-5]))
rows = [ex for f in parts for d in json.load(open(f))['datasets'] for ex in d['examples']]
greedy = [r for r in rows if r['metadata_fold'] == 'heldout_confirm']
```

## 3. Groups (`metadata_fold`) and sizes

These are the **5 datasets chosen** for the deliverable (target_num_datasets = 5). They are derived from the 10 kept source datasets. `heldout_confirm` is the primary confirmation set; `heldout_samples` supports self-consistency baselines; `screen_gold_audit` gives audited labels joinable to the iter-1 screen; `contamination` supports the gold-recall check; `transfer_unlabeled` holds the user's domain.

| Group | Rows | Content |
|---|---|---|
| `heldout_confirm` | 6,300 | 700 sentences × 9 systems, greedy (T=0). Unparseable outputs are kept (301, `parse_ok=false`) |
| `heldout_samples` | 7,000 | 700 × 5 samples (T=0.8, seed=idx) × {gpt-4.1-mini, llama-3.1-8b}. L1 labels only |
| `screen_gold_audit` | 1,003 | Screen reproduction: sha1-first-360 FOLIO-v1-validation sentences (300 + 60 buffer, `metadata_in_screen_first300`) × Logic-LM {gpt-3.5-turbo, gpt-4, text-davinci-003} candidates, labelled against panel-audited gold. Join key: `metadata_sentence_id` = sha1(norm)[:10]; `metadata_item_id` = sha1[:10]:system |
| `contamination` | 936 | E1: 104 kept entity-renamed paraphrases × 9 renamed greedy candidates. Label transferred from the original candidate; the original sentence is kept for gold-recall probes |
| `transfer_unlabeled` | 367 | E2: EU-AI-Act Art. 3 definitions × {grounded, ungrounded} × runs from the user pilot. `output='unlabeled'`. 289 parse; the 66 `⊆` formulas stay `parse_ok=false` |

Sample composition:
- **MALLS 250**, including all 99 eligible paper-corrected items;
- **FOLIO-train 250**, from stories disjoint from both FOLIO validation versions (5 stories excluded, overlap asserted 0);
- **ProverQA hard 120 / medium 80**, de-templated, ≤2 per story, non-trivial.

Per-corpus terciles are 45/30/25% (top/middle/bottom). Complexity features follow the screen recipe:
- n_tokens;
- n_quantifiers;
- nesting depth;
- n_conditions = if/unless/except/only/either/neither/not (with n't counted as not) + gold → ↔ ⊕ ∨ ¬.

The composite is the mean of the 4 z-scores over the 4,527-sentence eligible pool. The z-parameters and cut-points are in the dataset metadata and `label_report.json`.

## 4. Row schema (`heldout_confirm` / `heldout_samples`)

- **`input`**: a JSON string `{"sentence", "candidate_fol"}`, where `candidate_fol` is the extracted formula line.
- **`output`**: `faithful` | `unfaithful` | `unknown`.

Final-label precedence:
1. **L3 panel majority** (`label_source=panel3`, 609 greedy rows).
2. For ProverQA with gold the panel judged faithful: **L1 vs the original gold** (`equiv_synthetic_gold`).
3. Otherwise: **L1 vs audited gold** (`equiv_audited_gold`). `equiv_proved`/`equiv_bounded` map to faithful; `non_equiv`/`non_equiv_no_bijection` map to unfaithful.
4. Otherwise `unknown` (453 greedy rows): unparseable candidates, `no_audited_gold` (the panel's correction failed to parse or verify) and `unknown_capped`. Unknown rows are kept and counted.

Main metadata fields:
- **Provenance**: `corpus`, `corpus_subset`, `source_id`, `story_id`, `licence`, `system`, `model`, `system_tier` (required/extra), `provider`, `sample_idx`, `temperature`, `raw_output`, `parse_ok`, `parse_error`, `parse_notes`, `finish_reason`, `prompt_sha1`, `extractor_version`, `gen_usd`, `gen_seconds`.
- **Gold**:
  - `gold_fol_original`, `gold_fol_audited`;
  - `gold_source` ∈ {original, panel_corrected, panel_flagged_uncorrected (the panel flagged the gold but no correction parsed/verified, so `gold_fol_audited`=null and the label is unknown unless L3-adjudicated), paper_corrected}. In the greedy rows: original 3,087, panel_corrected 2,160, paper_corrected 891, panel_flagged_uncorrected 162;
  - `gold_fol_paper` + `paper_corrected_flag` (the 2606.02837 human correction);
  - `gold_fol_refined` (yfxiao/folio-refined, metadata only).
- **L0**: `gold_audit_votes` (per member: faithful, ambiguous, error types, explanation, model), `gold_faithful_final`, `sentence_ambiguous`, `gold_audit_primary_error`, `gold_audit_cascade_rule`, `gold_audit_full_panel_subset`, `gold_correction_status`.
- **L1**, for both `L1_orig_*` and `L1_audited_*`:
  - `status` ∈ {equiv_proved, equiv_bounded, non_equiv, non_equiv_no_bijection, unknown_capped, unknown_timeout, unparseable, no_audited_gold};
  - `mapping` (gold→candidate bijection);
  - `entail_cand_to_gold` / `entail_gold_to_cand` (bounded one-directional hints under the best mapping);
  - `method` (bounded/unbounded), `max_domain`, `seconds`.
- **L2**: `L2_status` ∈ {equiv_granular, non_equiv, not_applicable, not_run_equivalent}, `L2_definitions`, `L2_lexical=true`, `L2_orig_status`.
- **L3**:
  - `L3_selected`;
  - `L3_votes` (per member: cand_faithful, gold_faithful, error_types, primary_error, ambiguous, same_meaning, model);
  - `L3_majority`, `L3_primary_error`, `L3_dissent`, `L3_gold_shown_as`;
  - `L3_sampling_weight` (post-stratified N_h/n_h), `L3_poststratum`, `L3_design_weight`, `L3_design_stratum`;
  - `L3_stratum_p_faithful` (estimated panel-faithful share of this row's post-stratum; a label-noise prior for non-adjudicated rows).
- **Complexity**: `n_tokens`, `n_quantifiers`, `nesting_depth`, `n_conditions`, `complexity_composite`, `complexity_tercile`, `complexity_gold_used`.
- **`label_source`**; **`source_verified`** / **`source_file`** (set by `data.py`).

## 5. How labels were built

**Panel.** Every member is family-disjoint from all 9 generators (Meta, Qwen, Mistral, OpenAI, Google, DeepSeek, Microsoft) and from the gemini judge baseline.

| Member | Model | Calibration gate (40 known-label items, ≥80% required) | Note |
|---|---|---|---|
| M1 | anthropic/claude-haiku-4.5 | 0.90 | The planned claude-sonnet-4.5 **failed** at 0.775: it rejected valid contrapositive and material-implication rewrites. The plan's fallback was used |
| M2 | x-ai/grok-4.3 (reasoning low) | 0.90 | grok-4-fast is no longer in the OpenRouter catalog |
| M3 | z-ai/glm-4.6, **non-thinking** | 0.875 | Chosen for cost; the low-reasoning config scored 0.925 |

The calibration set:
- 15 ProverQA-easy golds;
- 15 solver-verified non-equivalent mutants: negation flip, ∀↔∃, implication reversal, dropped conjunct, and ∧↔∨ (used because ProverQA-easy has no binary predicates for argument swaps);
- 10 solver-verified equivalent rewrites: contrapositive, material implication, predicate renaming.

The gate uses the original, pre-registered labels, even though 3 of the "faithful" golds are defensibly wrong.

**L0 / L4 gold audit.** A cascade: M2 and M3 vote on every gold; M1 votes on disagreements plus a seeded 20% subset. There were 264 M1 tie-breaks among 1,060 golds.

A correction is accepted only if it:
- parses;
- is satisfiable (bounded);
- has a bounded countermodel against the original.

Otherwise it is rejected: 33 corrections were equivalent to the original, and some were unparseable because they used function terms. For the 99 MALLS items with a human correction, `gold_fol_audited` = the paper's gold.

**L1** is lexical-free.
- It checks the arity profile first. A mismatch gives `non_equiv_no_bijection`.
- It then tries all bijections, capped at 5,040 (only 2 greedy items hit the cap).
- Only countermodels count as proofs of non-equivalence.
- `equiv_proved` needs an unbounded z3 `unsat`. All equivalences in this run were proved, so no `equiv_bounded` items occur.

Validation on the 59 parseable pairs among the paper's first 60 MALLS items: every uncorrected pair was equivalent (37/37) and every corrected pair was non-equivalent (22/22). Mean cost is about 6 ms per pair.

**L3** is blinded and symmetric: gold and candidate appear as Formula A / Formula B in seeded random order, with no source or system named.
- The design sample was 460: 400 non-equivalent, with the top tercile oversampled 1.5×, including 40 of the 77 L2-granular items; plus 60 equivalent.
- 150 extra items were drawn uniformly at random within the top-tercile non-equivalent strata.
- Estimates use post-stratified weights on the final frame. The frame has 5,848 greedy parseable candidates with audited gold; every stratum has at least 3 adjudicated items.

**E1.**
- 203 sentences carried a named entity or constant: FOLIO 187, MALLS only 16, because MALLS gold is almost constant-free. So the planned 75/75 split became 187/16.
- gpt-4.1-mini paraphrased each sentence and renamed its entities. The renaming was applied to the gold constants and predicate substrings.
- M2 verified both the meaning and the renamed gold. 104 of 203 passed (target was ≥120). Most drops are "the renamed gold is not faithful to the paraphrase", which reflects residual gold problems.
- 124 of 936 renamed candidates are flagged `contamination_rename_incomplete`.

## 6. Deviations from the plan (honest list)

1. **Corrected gold WAS found.** arXiv:2606.02837's release is on HF as `DSAVlab-UNIUD/MALLS_test_subset-CURATED` (100 items = MALLS-test indices 0–99, verified by NL match) and `DSAVlab-UNIUD/FOLIO_validation-curated` (275 FOLIO-v2-validation instances: 73 whole-story premise blocks plus 202 conclusions). The paper's GitHub repo is still 404.
   - The FOLIO file corrects stories and v2 conclusions, not v1 premises. So the L4 panel-vs-human check covers only the 22 screen conclusions whose v1 gold equals the v2 gold the paper judged (κ = 0.18, n = 22: too small to conclude anything).
2. **Panel substitutions**: haiku-4.5 for sonnet-4.5 (failed the gate), grok-4.3 for the unavailable grok-4-fast, glm-4.6 non-thinking. See §5.
3. **ProverQA was audited in full** (the 10% escalation rule fired). Its flagged golds use panel-corrected gold (`gold_source=panel_corrected`).
4. **L3 was enlarged** from 300 to 610 adjudicated items (460 design + 150 extra top-tercile), funded from the reserve. Weights are post-stratified.
5. **A parser bug was found and fixed after L0.** v1 read constants such as `yr2028`/`p1080` as free variables and universally closed them. It affected 8 golds (4 held-out) and 9 candidates.
   - The drawn sample was kept frozen.
   - The 4 affected sentences' complexity features were recomputed with the stored z-parameters (the old values are in `complexity_v1_buggy`).
   - All L1/L2 labels were recomputed from scratch; the old cache is kept as `work/l1_cache_v1_buggy.jsonl`.
   - The panel corrections were re-derived (0 changed).
   - E1 verification was re-keyed on content. This re-called all 203 verifications, costing $0.49 of waste.
   - 3 L3 items changed stratum; post-stratification absorbs this.
6. **Extractor v2**: phi-4 answered in LaTeX (`\(\forall x \, \text{P}(x)\)`). A formatting fix, not a prompt change, raised its parse rate from 68% to 88%. All rows were re-extracted from the stored `raw_output`.
7. **The ASCII `^` is read as ∧, not ⊕**, because LLM outputs use it as a look-alike of ∧.
8. The **folio-refined** signal barely agrees with the panel: κ = 0.004 on 416 FOLIO items; refined differs from the original on 34%, the panel flags 51%. Its (undocumented) refinement targets something other than faithfulness, e.g. cross-story vocabulary alignment. It is kept as metadata only.
9. **Class balance**: 62% of labelled greedy rows are unfaithful, above the 25–60% target. This is inflated by the L1 label noise described in §1. Per corpus: ProverQA 42%, MALLS 66%, FOLIO 75%.
10. **"Heavily conditioned" means connective-heavy, not exception-heavy.** The public sentence-level gold corpora contain almost no `unless`/`except` sentences, so the top tercile is driven by multiple connectives, ⊕, ↔ and quantifier nesting. E2 (EU AI Act) is the only exception-rich material, and it is unlabeled.
11. Temperature-0 output is not bit-deterministic across OpenRouter providers. The provider is recorded per row, and `raw_output` is the ground truth of what was scored.
12. `kenken6696/folio_by_ccg2lambda` and `kenken6696/MALLS_by_ccg2lambda` were downloaded (to `temp/datasets/`) as possible iter-2 non-LLM systems but **not used**. Their neo-Davidsonian event FOL has no predicate bijection to gold, so they could only be adjudicated by the panel.

## 7. Dataset search and selection (TODOs 2–5)

**Search.** 40 broad HF queries (`temp/hf_search.txt`), including: folio, MALLS, ProverQA, first-order logic, FOL, autoformalization, logical reasoning, semantic parsing, ProofWriter, LogicNLI, theorem proving, lambda calculus, monotonicity, logic-lm, …

**Previews.** 20 candidates were previewed through the HF datasets-server API (`temp/previews/candidate_previews.json`; the skill's own preview script lacked the `datasets` module). 14 provenance web searches are in `temp/websearch/`.

**KEPT (10):**

| Dataset | Downloads | Licence | Role |
|---|---|---|---|
| tasksource/folio | 6.2k | FOLIO MIT | FOLIO-v2 train/validation (yale-nlp/FOLIO is gated for this token) |
| yuan-yang/MALLS-v0 | 158 | CC BY-NC 4.0 | MALLS-v0.1-test (Yang et al. 2023) |
| DSAVlab-UNIUD/MALLS_test_subset-CURATED | 26 | — | Human corrections from arXiv:2606.02837. Low downloads, but provenance is verified: card, paper and authors |
| DSAVlab-UNIUD/FOLIO_validation-curated | 61 | — | Same paper; FOLIO side |
| opendatalab/ProverQA | 380 | — | ICLR 2025, dev easy/medium/hard via `hf_hub_download`; `load_dataset` breaks |
| yfxiao/folio-refined | 20 | MIT | Independent wrong-gold signal (method undocumented; metadata only) |
| Yale-LILY/FOLIO GitHub v0.0 | — | — | v1 validation/train (screen gold) |
| teacherpeterpan/Logic-LLM `outputs/logic_programs/FOLIO_dev_*.json` | — | — | Screen candidates |
| User `dpv_pilot_study.zip` | — | — | E2 |
| kenken6696/{folio,MALLS}_by_ccg2lambda | — | CC BY 4.0 | Downloaded for iter 2, unused |

**DISCARDED**, each with its reason:

| Dataset | Reason |
|---|---|
| benlipkin/folio, minimario/FOLIO, jhkim64/NL2FOL_sentence | Duplicate FOLIO mirrors, or <10 downloads with no card |
| tasksource/FOL-nli (182 MB), tasksource/LogicNLI, tasksource/proofwriter, logicreasoning/logi_glue (963 MB), kkkarry/LogicGraph (698 MB) | NLI/QA with TPTP or proof annotations; no sentence-level NL→FOL gold, and some are too large |
| Isotonic/symbolic_data_first_order_logic | Arithmetic "FOL"; no card |
| verify-ppt/ppt-logic_first_order | No loadable data |
| tasksource/monotonicity-entailment (MED) | Used by screen Arm A, not a FOL corpus |

## 8. How to run (in order)

```bash
uv venv .venv --python=3.12 && uv pip install --python=.venv/bin/python z3-solver nltk aiohttp loguru huggingface_hub numpy scipy tenacity requests pyyaml pytest
bash restore.sh                                    # sources + nltk data + pilot extraction
.venv/bin/python -m pytest -q -c pytest.ini tests/test_fol.py
.venv/bin/python src/prep_sources.py               # steps 1-3 (no API)
.venv/bin/python src/generate.py --concurrency 24  # step 4 (~$0.72; resumable)
.venv/bin/python src/reextract.py                  # extractor v2
.venv/bin/python src/label_l1.py --stage orig
.venv/bin/python src/calibrate.py && .venv/bin/python src/calibrate_variants.py   # (~$0.88)
.venv/bin/python src/audit.py --cap 4.0            # L0 + L4 (~$3.43)
.venv/bin/python src/fix_varlike_patch.py          # only needed for artefacts produced by parser v1
.venv/bin/python src/label_l1.py --stage audited
.venv/bin/python src/l3_adjudicate.py --n-non 400 --n-eq 60 --cap 2.8   # (~$2.46)
.venv/bin/python src/l3_extra.py --n 150 --cap 0.85                      # (~$0.88)
.venv/bin/python src/e1_contamination.py --n 203 --cap 0.75              # (~$0.86)
.venv/bin/python src/e2_transfer.py
.venv/bin/python src/assemble.py                  # -> work/assembled_data_out.json.gz + label_report.json
uv run data.py                                     # source verification -> full_data_out.json (validated: exp_sel_data_out)
.venv/bin/python src/split_outputs.py             # -> full_data_out/full_data_out_{1,2,3}.json + mini/preview
```

Every panel and generation response is cached (`work/panel_cache.jsonl`, `raw/generations/`), so a re-run of the labelling steps costs $0.

Total spend: **$9.22**:

| Phase | Cost |
|---|---|
| Generation | $0.72 |
| Calibration | $0.88 |
| Gold audit | $3.43 |
| L3 | $2.46 + $0.88 |
| E1 | $0.86 |

It stayed under the $9.30 hard cap, with the ledger updated after every call.

## 9. Restoring removed files

These paths are deleted after the round (see `.aii/manifest.yaml`). `bash restore.sh` recreates all of them. It also re-downloads `raw/hf_downloads/` and the ccg2lambda files in `temp/datasets/` if they are missing; those are small and are kept.

| Path | Restore with |
|---|---|
| `raw/pilot/` | `python -c "import zipfile; zipfile.ZipFile('/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/user_uploads/dpv_pilot_study.zip').extractall('raw/pilot')"` |
| `nltk_data/` | `python -c "import nltk; [nltk.download(p, download_dir='nltk_data') for p in ('wordnet','omw-1.4')]"` |
| `.venv/` | The `uv venv …` line in §8 |
| `__pycache__/`, `.pytest_cache/` | Regenerated automatically |
