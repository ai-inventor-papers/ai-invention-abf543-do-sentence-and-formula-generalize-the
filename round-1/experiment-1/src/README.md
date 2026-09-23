# Monotonicity-signature faithfulness metrics for NL→FOL: Screen Arm A (iter 1)

This repo is a gold-free meta-evaluation. It asks whether a candidate FOL formalization is faithful to its sentence. The test compares where each content word sits in the text (upward- or downward-entailing position) with the exact semantic monotonicity of each predicate in the formula, computed by a solver.

Three candidate metrics (A1, A2, A3) are screened on real outputs of three systems: the Logic-LM FOLIO-dev releases of gpt-3.5-turbo, gpt-4 and text-davinci-003. They are compared against six baselines and controls on identical items, and the pre-registered selection rule is then applied verbatim.

Workspace (all paths below are relative to it):
`/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_experiment_1`

## Headline results

Setup: 300 sentences, 835 real candidates, primary labels, 1000× sentence-clustered bootstrap.

| metric | AUROC [95% CI] | low / mid / top tercile | G1 cov | G2 FA | G3 ΔAUROC over judge+parse [CI] | Δ over B1+parse+B3nli+B7+B8 [CI] | $/item |
|---|---|---|---|---|---|---|---|
| **A1** LLM-probe signature | 0.711 [0.663, 0.756] | 0.726 / 0.739 / 0.507 | 0.86 | 0.131 | +0.084 [0.037, 0.138] | +0.057 [0.022, 0.092] | 0.0009 |
| **A2** A1 + relativized coords | 0.711 [0.662, 0.756] | 0.724 / 0.739 / 0.507 | 0.86 | 0.131 | +0.084 [0.036, 0.138] | +0.056 [0.021, 0.092] | 0.0009 |
| **A3** zero-LLM rules signature | **0.718** [0.673, 0.763] | 0.757 / 0.737 / 0.508 | 0.88 | 0.143 | **+0.093** [0.048, 0.143] | +0.062 [0.029, 0.097] | 0 |
| A0 alignment-only ablation | 0.674 [0.629, 0.715] | 0.694 / 0.665 / 0.519 | 0.86 | 0.133 | +0.067 [0.025, 0.113] | +0.036 [0.008, 0.065] | 0 |
| Ccov concept-coverage control | 0.661 [0.616, 0.706] | 0.677 / 0.651 / 0.460 | 0.97 | 0.160 | +0.056 [0.019, 0.099] | +0.024 [0.004, 0.044] | 0 |
| B1 gemini-2.5-flash judge (anchor) | 0.644 [0.597, 0.693] | 0.680 / 0.623 / 0.533 | 1.00 | 0.308 | — | — | 0.00002 |
| B2 parse rate / B2sat | 0.527 / 0.529 | ≈0.53 | 1.00 | — | +0.000 | — | 0 |
| B3cos round-trip MiniLM | 0.614 [0.562, 0.663] | 0.702 / 0.517 / 0.424 | 1.00 | — | +0.015 [−0.008, 0.038] | — | 0.00006 |
| B3nli round-trip DeBERTa-v3-large | 0.660 [0.612, 0.706] | 0.681 / 0.625 / 0.472 | 1.00 | — | +0.027 [−0.005, 0.060] | — | 0.00006 |
| B4 decomposed LLM judge (ablation) | 0.715 [0.665, 0.760] | 0.710 / 0.769 / 0.521 | 0.82 | 0.183 | +0.088 [0.040, 0.142] | +0.064 [0.027, 0.102] | 0.0041 |
| B5 gold-signature oracle (ceiling) | 0.741 [0.694, 0.782] | 0.773 / 0.758 / 0.583 | 0.87 | 0.141 | +0.114 [0.065, 0.168] | +0.080 [0.043, 0.117] | — |
| B7 structural (user pilot) | 0.537 [0.519, 0.557] | 0.561 / 0.533 / 0.545 | 1.00 | — | −0.002 [−0.011, 0.006] | — | 0 |
| B8 self-consistency (cross-story re-translations) | 0.608 [0.564, 0.655] | 0.576 / 0.640 / **0.701** | 0.55 | — | +0.027 [−0.009, 0.066] | — | 0 |

How to read the table:
- AUROC is robust to the label choice. For A1, A3 and B1 respectively, it is 0.712 / 0.714 / 0.666 against the original v0.0 gold and 0.717 / 0.725 / 0.649 with lexical-bijection labels. On the 97-sentence subset with curated (corrected) gold it is 0.760 / 0.782 / 0.721.
- The G2 false-alarm rate uses δ = 0 for signature-like scores and δ = 0.10 for continuous scores. B1's rate at δ = 0 is 0.43.

**Verdict under the pre-registered rule: no candidate survives.**
- All three pass G1, G3 and G4. All fail **G2**, with 13–14% false alarms.
- The false alarms come *only* from synonym-renamed rewrites (A1 38%, A3 42% of 142 SYN_RENAME rewrites), where the lexical alignment breaks.
- On the 270 purely logical rewrites (reorder, contrapositive, De Morgan, prenex) the signature metrics have **0%** false alarms, while the judge B1 has 20–40%.
- Under the no-survivor clause, **A3 advances** because its ΔAUROC point estimate is 0.093 ≥ 0.03.

**Diagnosis:**
1. **The text side is the bottleneck.** B6 downward accuracy of the gemini-2.5-flash probe is 0.60, well under 0.80. The zero-LLM rule marker scores 0.86 downward on 3,401 MED single-span edits. The oracle gap B5 − A1 = +0.030 [0.005, 0.058].
2. **Exact semantics vs decomposition.** A1 − B4 = −0.005 [−0.024, 0.014]. Asking an LLM the same per-predicate questions ties exact solver semantics on real items, at about 5× the cost. It is worse on mutants: for example ARG_SWAP 0.50 vs 0.61, NEG 0.65 vs 0.76.
3. **Polarity vs alignment.** A large part of the signal is lexical alignment/coverage: A0 = 0.674 and Ccov = 0.661.
   - Standalone, the polarity comparison adds A1 − A0 = +0.037 [0.006, 0.069] and A3 − A0 = +0.044 [0.009, 0.078].
   - Once the judge and A0 are in the logistic model, the increment is not significant: A1 +0.013 [−0.013, 0.040], A3 +0.024 [−0.005, 0.056].
4. **Complexity.** Every metric collapses to about chance in the TOP tercile (A1 0.507, B1 0.533, B5 0.583). The crossover hypothesis (signature beats judge on the most conditioned sentences) is **not supported** on FOLIO: Δ(A1−B1) is +0.05 / +0.12 / −0.03 across low / mid / top. FOLIO's top tercile is only mildly conditioned. The only metric that rises with complexity is B8 (0.70 in the top tercile), and only on its 55% covered subset.
5. **Pre-registered blind spots.**
   - Confirmed: A1 CARD = 0.50 [0.35, 0.65] (n=37) and A1 ANDOR = 0.50 [0.40, 0.59] (n=109).
   - **A2 does not rescue ANDOR** (0.50). The formula-side relativized signature separates ∧/∨ (unit test: ≥6 differing coordinates), but the text side produces relativized coordinates for very few FOLIO sentences.
   - SCOPE is untestable: 0 golds have mixed quantifier prefixes.
6. **Error typing** (confusion matrix, 8 non-blind types): macro recall A1 0.52, A2 0.54, A3 0.56. Chance is 0.125. Among detected mutants, SWAP recall is 1.00; negation is often labelled conflation.
7. **Labels.**
   - 0 unlabeled. Bounded (1..4) vs unbounded z3 agree on 389/389 equivalent items.
   - 79% of non-equivalences are *vocabulary-shape* mismatches (a different predicate arity multiset), which is where correct-but-inequivalent granularity lands.
   - Curated gold changed 50 of the 97 matchable golds (52%). Labels agree between the original and curated gold on 75% of items; 62 items are equivalent to the original gold but not to the curated one.
   - Blind vs lexical bijection labels disagree on 12 items (reversed-implication-by-swap cases).
8. **System level.** Kendall τ over 3 systems is reported but uninterpretable (n=3).
9. **Cost.** Total OpenRouter spend was **$5.67** (cap $5.80): B4 $4.72, probe $0.75, B1 $0.07, B3 $0.05, B6 $0.07.

## Independent audit of the headline numbers (`audit_rederive.py` → `results/audit_rederive.json`)

The audit script reads only the raw per-item files: labels from `data/screen_set.json`, per-item scores from `results/*.jsonl`, and the ledger. None of its code is shared with `analyze.py`:
- AUROC comes from a hand-written Mann-Whitney rank formula.
- The sentence-clustered bootstrap uses its own RNG (500 draws).
- G3 uses a numpy Newton-Raphson logistic regression with md5-hash sentence folds.

Everything reproduces:
- **AUROC:** A1 0.711, A3 0.718, B1 0.644, B3nli 0.660, B4 0.715, B5 0.741, A0 0.674, Ccov 0.661. The CIs agree to within ±0.005.
- **Top tercile:** A1 0.507, B1 0.533.
- **G2:** A1 0.131 (rename 0.380, other rewrites 0/270), A3 0.143, B1 0.308.
- **Mutant detection:** A1 NEG 0.758, CARD 0.50, ANDOR 0.495.
- **Equiv rate per system** and **total spend $5.666** match.
- **G3.** A1 +0.078 [0.031, 0.124] and A3 +0.090 [0.046, 0.140]. The point estimates differ by ≤0.006 from the analyze.py values (different folds and regularisation); the conclusion is the same.
- **Increment over [B1, parse, A0]** is again not significant: A1 +0.015 [−0.016, 0.045], A3 +0.027 [−0.0005, 0.054].

**Placebos behave as they should.**
- With permuted labels, A3's AUROC is 0.528 and its G3 CI includes 0 ([−0.009, 0.059]).
- A random-noise metric gets AUROC 0.486 and G3 −0.002 [−0.012, 0.008].
- The increment test therefore does not pass vacuously.

## Layout

| path | what |
|---|---|
| `method.py` | **Reusable API** (`signature_faithfulness(text, fol, variant)`, `alignment_only`, `concept_coverage`) + pipeline orchestrator (`--stages all`, `--demo`) |
| `build_screen_set.py` | STEP 1: frozen screen set (shared recipe with Arm B), labels under both golds, mutants, rewrites, complexity terciles |
| `run_sigs.py` | STEP 2: solver signatures for 2,645 formulas (19 s) + B7 structural metrics |
| `run_text.py` | STEP 3 + B6: MED probe-config pilot, text concepts/copies/rule marker, LLM substitution probe, B6 on MED/HELP |
| `run_baselines.py` | B1 judge, B1-on-mutants, B3 round-trip (MiniLM + DeBERTa NLI), B4 decomposed judge, (B1+ tuned judge: skipped, budget) |
| `run_selfcons.py` | B8 self-consistency from Logic-LM cross-story re-translations (added) |
| `run_metrics.py` | alignment + A1/A2/A3/A0/Ccov/B4/B5/B5A2 scoring of real, gold, original-gold, mutants, rewrites |
| `audit_rederive.py` | independent re-derivation of headline numbers + placebo tests |
| `analyze.py` | AUROCs, clustered bootstrap, terciles, G1–G4, per-operator detection, confusion, system level, gold-error flagging, verdict, diagnosis, figures, `method_out.json` |
| `src/fol_parse.py` | FOLIO-syntax parser (∀∃¬∧∨→↔⊕, =, ≠, 0-ary atoms, free-variable closure); ∈/≤/function terms → ParseError |
| `src/ground.py` | exact propositional grounding covering all domain sizes 1..N in ONE SAT query (active-element encoding) |
| `src/solver_sig.py` | formula signature: per-predicate +/−/0/±, role anchors, relativized coordinates |
| `src/labeler.py` | equivalence up to arity-preserving bijection (blind, primary) + lexical-bijection secondary label |
| `src/mutate.py` | 10 typed mutation operators + 5 rewrite kinds (all solver-verified) |
| `src/text_sig.py` | spaCy concepts, specialised copies, relativized copies, probe prompt/parse, A3 rule-based monotonicity marker |
| `src/align.py` | lexical aligner (compound-head and lexical-negation rules; optional domain nouns) |
| `src/score.py` | mismatch-fraction score + pre-registered error-type decision list |
| `src/llm.py` | OpenRouter client, disk cache, per-call cost ledger, hard $ cap |
| `tests/test_units.py` | T0 unit tests (all pass) |
| `data/screen_set.json` | **the meta-evaluation dataset**: 300 sentences (gold, gold source, features, tercile), 835 real candidates with labels (primary / original-gold / lexical), 1,375 mutants, 412 rewrites |
| `data/screen_set_ids.txt` | sorted real item ids for Arm B's identity check |
| `data/raw/` | downloaded public inputs (Logic-LM outputs, FOLIO v0.0 validation, DSAVlab-UNIUD curated FOLIO, MED, HELP, yfxiao refined FOLIO) |
| `full_method_out.json`, `mini_method_out.json`, `preview_method_out.json` | aii-json full / mini / preview variants of `method_out.json` |
| `results/method_out.json` (= `method_out.json`) | full results (schema exp_gen_sol_out, validated) incl. per-item predictions |
| `results/summary.json` | compact table + verdict + diagnosis |
| `results/screen_scores.jsonl` | one row per (item, metric): score, raw score, covered, coverage, error type, mismatches, $ |
| `results/formula_sigs.json`, `results/text_sigs.json`, `results/alignments.json`, `results/b4_llm_sigs.json` | intermediate signatures (formula, text probe answers, alignments, B4 LLM signatures) |
| `results/baseline_*.jsonl`, `results/b6_results.json`, `results/b7_structural.json` | baseline scores |
| `results/probe_config.json` | MED pilot + pre-registered thinking-config choice + the documented fallback deviation |
| `results/cost_ledger.jsonl` | every OpenRouter call with its usage and cost |
| `results/llm_cache/` | cached LLM responses (rerun costs $0) |
| `figures/` | `roc_real`, `delta_vs_b1_tercile`, `mutant_detection_heatmap` (png + pdf) |
| `pilot_ref/` | the user's pilot scripts (read only to port B7 definitions) |
| `logs/` | all run logs |

## How to run

```bash
uv venv .venv --python=3.12
uv pip install --python .venv/bin/python -r requirements.txt   # exact pins (same as pyproject.toml)
# (en_core_web_sm is included in the pins; the next line is only needed if installing unpinned)
uv pip install --python .venv/bin/python "en_core_web_sm @ https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"
export NLTK_DATA=$PWD/.nltk_data
.venv/bin/python -c "import nltk; nltk.download('wordnet', download_dir='$NLTK_DATA'); nltk.download('omw-1.4', download_dir='$NLTK_DATA')"
.venv/bin/python tests/test_units.py            # T0
.venv/bin/python method.py --demo                # zero-LLM A3 on hand examples
export OPENROUTER_API_KEY=...                    # only needed for uncached LLM calls
.venv/bin/python method.py --stages all          # full pipeline (LLM calls served from results/llm_cache)
```

Use as a library:

```python
from method import signature_faithfulness
signature_faithfulness("No student who smokes is healthy.", "∀x ((Student(x) ∧ Smoke(x)) → ¬Healthy(x))", "A3")
# {'score': 1.0, 'error_type_pred': 'none', 'text_labels': {...}, 'formula_labels': {...}, ...}
```

## Deviations from the plan (all logged in `method_out.json → metadata.config`)

- **Corrected gold.** Found on HF as `DSAVlab-UNIUD/FOLIO_validation-curated` (the 2606.02837 release; the GitHub repo is still 404). Its NL matches FOLIO v0.0 for only 97 of the 300 screen sentences: the release rewrote many premises and is story-level (30 of 73 stories could not be split into sentences). The primary label uses the curated gold on those 97 sentences and the v0.0 gold elsewhere; all AUROCs are also given under v0.0-only labels.
- **Probe-model fallback (11) not applied.** Both gemini configs piloted below 0.70 downward. The pre-registered fallback, gpt-4.1-mini, piloted *worse* (downward 0.32 vs 0.64), so the probe keeps gemini-2.5-flash with thinking 1024 (`results/probe_config.json`).
- **A3 is A3-rules.** Udep2Mono was not installed (fallback 10). The rule marker was validated on MED instead: 0.87 accuracy, 0.86 downward.
- **T1 text-side fixes.** The gold full-match was 0.31, below 0.50, so fixes were made using gold/mutant/rewrite behaviour only:
  - optional domain nouns and light verbs;
  - predicates may align to PROPN concepts, and constants to NOUN concepts.
  Gold full-match then rose to 0.43 (B5 oracle 0.53). The residue is genuine granularity: FOLIO golds omit content words.
- **Budget.** B4 cost 3.8× the estimate. B4 mutants were therefore cut to 20 per operator and rewrites to 120, and B1+ was skipped (budget rules 12–13).
- **Added controls.** A0, Ccov and B8 were not in the plan.
- **Deferred to iter 2** as planned: contamination check, adjudicated correct-but-inequivalent rate. Gold-error flagging is only reported on the 72 re-scored original golds (A1 precision@50 0.62 vs base rate 0.58: weak).

## Restoring removed files

Only regenerable or redownloadable bulk is marked `delete` in `.aii/manifest.yaml`:

- `.venv/` — `uv venv .venv --python=3.12 && uv pip install --python .venv/bin/python -r requirements.txt && uv pip install --python .venv/bin/python "en_core_web_sm @ https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"`
- `.nltk_data/` — `.venv/bin/python -c "import nltk; nltk.download('wordnet', download_dir='.nltk_data'); nltk.download('omw-1.4', download_dir='.nltk_data')"`
- `src/__pycache__/`, `__pycache__/` — regenerated automatically on import (e.g. `.venv/bin/python -c "import sys; sys.path.insert(0,'src'); import fol_parse"`).
- The HF models (MiniLM, DeBERTa-v3-large NLI) live in the run's shared cache, not here. They re-download on first use: `sentence-transformers/all-MiniLM-L6-v2`, `MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli`.
- `data/raw/` is kept. To re-fetch it, rerun the URLs in `build_screen_set.py`'s docstring and the plan: the Logic-LM raw GitHub files, FOLIO `data/v0.0/folio-validation.jsonl`, `https://huggingface.co/datasets/DSAVlab-UNIUD/FOLIO_validation-curated/resolve/main/FOLIO_instances.jsonl`, and MED/HELP from `verypluming/{MED,HELP}`.
