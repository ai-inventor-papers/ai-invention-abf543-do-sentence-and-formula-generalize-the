# Screen Arm B — can small worlds and instances catch NL→FOL errors?

Iter-1 **wide screen, Arm B** of run `run_qY2a2IS-WLIs`. The screen tests three **gold-free** faithfulness metrics
for NL→FOL output. Each one takes a sentence and a candidate FOL. They are tested on **real** system outputs:
Logic-LM's released FOLIO-dev translations by gpt-3.5-turbo, gpt-4 and text-davinci-003. All three are compared
with the same baselines on identical items:

| metric | what it measures |
|---|---|
| **TVJT** (truth-value judgement over solver worlds) | z3 builds a minimal finite world that separates the candidate F from each of its own typed mutants M_j. The worlds are verbalized, and `gemini-2.5-flash` (T=0, reasoning off) judges only whether the **sentence** is true in each world; it never sees F or M. Score = share of worlds where the judged sentence truth equals F(w). `error_type` = the operator whose worlds disagree most. |
| **NLI_deberta** (instance-consequence NLI, zero LLM) | z3 labels (premise facts, hypothesis) pairs about named individuals as E, C or N under F. Hypotheses are ground literals plus templated quantified consequences: shared witness, existence, universal, at-least-two. `DeBERTa-v3-large-mnli-fever-anli-ling-wanli` reads *sentence + facts ⇒ hypothesis*. Score = mean binary agreement with F's labels. |
| **LC_onecoin** (latent class over systems) | The 3 systems' outputs for a sentence are clustered by solver equivalence (blind predicate bijection). A one-coin latent-class EM with an explicit all-wrong state gives the posterior that each candidate's class is the correct one. |
| B1 (baseline) | The fixed-prompt `gemini-2.5-flash` judge, `Sentence/FOL → probability 0-100`, with the exact strategy prompt (`results/b1_request_example.json`). |
| B2 (baseline) | Parse rate (parse_ok). |
| B3sc (baseline) | Zero-cost self-consistency: the share of the same system's *other* translations of the sentence (Logic-LM re-translates premises in each example) that are bijection-equivalent to the candidate. |

Secondary variants, reported only: TVJT_gloss (Logic-LM predicate glosses used in the verbalizer); TVJT_nv
(non-vacuous worlds, with ≥1 instance of every ∀-restrictor); NLI_deberta_gloss; NLI_gemini (same pairs judged by
gemini); LC_huiwalter (π and p_w per complexity tercile); LC_maj (agreement share); LC_ds_binary (crowd-kit Dawid–Skene);
LC_onecoin_str (trigram-map clustering).

## Screen set and labels (rebuilt deterministically from public sources)

- **Screen size.** 300 sentences, the sha1(norm(nl))-first eligible ones. That gives **833 real candidates**
  (gpt-3.5-turbo 265, gpt-4 297, text-davinci-003 271). 246 sentences are matched by all 3 systems.
- **Fingerprint.** `a74f4cdd6586fce69e33aa3882e44faeab848d6e` = sha1 of the sorted real item_ids.
- **Unparseable candidates.** 58 (7.0%), kept as `parse_ok=0`, labelled incorrect, and scored 0.5 by every metric:
  free_var 34, non-FOL symbols 15, function terms 8, tokenize 1.
- **Primary label `L_bij`.** Blind z3 equivalence to gold, under an arity-preserving bijection of predicates and
  constants, over domains 1..4. Result: **463 correct / 370 incorrect / 0 unlabeled**. All 463 bounded-equivalent
  items are also unbounded-equivalent under an uninterpreted-sort check.
- **Secondary labels.**
  - `L_str`: a trigram-anchored Hungarian map instead of the blind bijection.
  - `L_bij_orig`: against v1 gold.
  - `L_bij_cur`: against the DSAVlab-UNIUD curated gold.
  - `L_any`: the union of the above.
- **Controlled items**, generated from the 300 golds, seeded and each z3-verified:
  - 1187 typed mutants: NEG 300, QUANT 141, IMPL_REV 121, DROP_CONJ 82, ADD_CONJ 300, ARG_SWAP 81, AND_OR 94,
    **SCOPE_SWAP 0**, MERGE 40, CARD 28.
  - 499 meaning-preserving rewrites: RENAME 274, CONTRAPOSITIVE 104, REORDER 66, DEMORGAN 55.
- **Blind-spot supplement.** 477 SCOPE_SWAP/CARD mutants: SCOPE_SWAP 37, CARD 440. Sources: the remaining FOLIO-dev
  golds, FOLIO-train, curated MALLS and MALLS-v0.1-test. These are **never used for gates or ranking.**

### Gold policy (deviation, documented)

The item set follows the recipe exactly. The **primary labels, however, use FOLIO v1 gold** whenever it is usable
(299/300 sentences). The curated release (arXiv 2606.02837) is a re-annotation of FOLIO **v2**. It rewords story
sentences, uses a different vocabulary with binary predicates and constants, and adopts different conventions, such
as "some" = at least two. Equivalence against it therefore mostly measures vocabulary mismatch, which the numbers
below quantify. Every AUROC is also reported under `L_bij_cur`, `L_str` and `L_any` (`results/analysis.json →
metrics.*.by_label`).

### How noisy are the labels? (the user's two known problems)

- **Wrong gold.** 108 curated-matched sentences have parseable curated gold. For these, v1 gold is
  bijection-equivalent to the curated gold on 65 and non-equivalent on 43:
  - 37 of the 43 are vocabulary/granularity mismatches;
  - only **6 (5.6%)** are semantic disagreements with compatible vocabulary.

  The gold-as-4th-rater latent-class model estimates v1 gold error at **22.9%**. The observed curated-changed rate
  is 33.9% on 109 sentences.
- **Correct but not equivalent** (vocabulary/granularity). **67.6% of 'incorrect' labels (250/370) are vocabulary
  mismatches**, i.e. a different arity multiset or constant count, such as a compound predicate or an extra
  restrictor. Such candidates can never be bijection-equivalent, so this share upper-bounds that noise.
  - Measured bias: switching from v1 to curated gold flips 64 v1-correct items to incorrect and only 9 the other way
    (23.9% disagreement on 305 items).
  - AUROC restricted to vocabulary-compatible items is in the table below.
- **Blind-bijection false positives.** Reversed implications or argument swaps can pass under a swapped map. L_bij
  and L_str disagree on 2.0% of items (17 items are L_bij-correct but L_str-incorrect). n_equiv_maps>1 on 11.6%.

## Results (all numbers from `results/analysis.json`; CIs = 1000× sentence-clustered bootstrap, seed 0)

| metric | role | AUROC_real [95% CI] | tercile 0 / 1 / 2 | G1 cov | G2 FA@τ* (FA@0.5) | G3 ΔAUROC [CI] | within-sentence acc [CI] | AUROC vocab-compatible | $/item | s/item (median) |
|---|---|---|---|---|---|---|---|---|---|---|
| TVJT | RULE | 0.701 [0.656, 0.745] | 0.669 / 0.684 / 0.751 | 0.930 | 0.479 (0.184) | +0.039 [+0.011, +0.067] | 0.729 [0.666, 0.791] | 0.706 | 0.000191 | 0.69 |
| NLI_deberta | RULE | 0.603 [0.550, 0.647] | 0.766 / 0.450 / 0.518 | 0.918 | 0.683 (0.028) | +0.001 [-0.017, +0.018] | 0.537 [0.444, 0.626] | 0.571 | 0.000000 | 0.06 |
| LC_onecoin | RULE | 0.853 [0.813, 0.888] | 0.863 / 0.836 / 0.829 | 0.900 | N/A | +0.111 [+0.073, +0.150] | 0.765 [0.681, 0.839] | 0.814 | 0.000000 | 0.00 |
| B1 | baseline | 0.665 [0.616, 0.711] | 0.718 / 0.646 / 0.552 | 1.000 | 0.527 (0.409) | — | 0.593 [0.514, 0.671] | 0.663 | 0.000024 | 0.51 |
| B2 | baseline | 0.578 [0.558, 0.600] | 0.569 / 0.530 / 0.612 | 1.000 | 0.000 (0.000) | — | 0.585 [0.550, 0.624] | 0.500 | 0.000000 | 0.00 |
| B3sc | baseline | 0.597 [0.553, 0.642] | 0.568 / 0.613 / 0.703 | 0.519 | N/A | -0.013 [-0.050, +0.023] | 0.610 [0.556, 0.664] | 0.539 | 0.000000 | 0.00 |
| TVJT_gloss | secondary | 0.716 [0.680, 0.752] | 0.732 / 0.661 / 0.718 | 0.930 | — | +0.044 [+0.016, +0.075] | 0.740 [0.681, 0.796] | 0.696 | 0.000174 | 0.67 |
| TVJT_nv | secondary | 0.667 [0.621, 0.709] | 0.669 / 0.672 / 0.637 | 0.930 | 0.489 (0.238) | +0.022 [-0.004, +0.048] | 0.652 [0.581, 0.728] | 0.670 | 0.000196 | 0.69 |
| NLI_deberta_gloss | secondary | 0.610 [0.561, 0.658] | 0.770 / 0.474 / 0.516 | 0.918 | — | -0.009 [-0.031, +0.010] | 0.548 [0.461, 0.638] | 0.571 | 0.000000 | 0.06 |
| NLI_gemini | secondary | 0.682 [0.645, 0.719] | 0.771 / 0.655 / 0.659 | 0.918 | — | +0.023 [+0.004, +0.044] | 0.667 [0.599, 0.733] | 0.618 | 0.000482 | 0.96 |
| LC_huiwalter | secondary | 0.855 [0.814, 0.890] | 0.863 / 0.828 / 0.841 | 0.900 | N/A | +0.110 [+0.072, +0.149] | 0.754 [0.670, 0.831] | 0.827 | 0.000000 | 0.00 |
| LC_maj | secondary | 0.821 [0.783, 0.854] | 0.837 / 0.815 / 0.765 | 0.900 | N/A | +0.158 [+0.115, +0.203] | 0.650 [0.575, 0.720] | 0.798 | 0.000000 | 0.00 |
| LC_ds_binary | secondary | 0.833 [0.793, 0.866] | 0.849 / 0.837 / 0.759 | 0.900 | N/A | +0.168 [+0.122, +0.214] | 0.630 [0.542, 0.707] | 0.816 | 0.000000 | 0.00 |
| LC_onecoin_str | secondary | 0.853 [0.813, 0.886] | 0.869 / 0.836 / 0.829 | 0.900 | N/A | +0.116 [+0.077, +0.159] | 0.765 [0.681, 0.839] | 0.811 | 0.000000 | 0.00 |

- Tercile 2 = the most complex third, by the composite of tokens, quantifiers, depth and conditions.
- G3 = out-of-fold (GroupKFold by sentence) logistic stack of [B1, parse_ok, metric] vs [B1, parse_ok].
- Within-sentence acc = P(score of a correct candidate > score of an incorrect candidate *for the same sentence*),
  over the 94 mixed-label sentences.
- Negative controls:
  - a pure-noise metric has AUROC 0.494 and a G3 CI of
    [-0.014, +0.010], which contains 0;
  - shuffled labels give AUROC 0.501.

**Pre-registered selection rule (verbatim; `results/verdict.json`).** Survivors: ['LC_onecoin']. Outcome: **winner**,
advancing ['LC_onecoin']. Gate values:
- **TVJT:** G1 0.9304, G2 FA 0.479, G3 +0.039 [0.0109, 0.0673],
  G4 0.7014. It fails **only G2**.
- **NLI_deberta:** G1 0.9184, G2 FA 0.6834,
  G3 +0.001 [-0.0168, 0.0181], G4 0.6031.
- **LC_onecoin:** G1 0.9004, G2 N/A, G3 +0.111
  [0.0726, 0.1498], G4 0.853; top-tercile AUROC 0.8285.

Paired AUROC differences (same items, clustered bootstrap):

| comparison | ΔAUROC all | ΔAUROC top tercile |
|---|---|---|
| TVJT-B1 | +0.036 [-0.015, +0.094] | +0.199 [+0.085, +0.308] |
| LC_onecoin-LC_maj | +0.032 [+0.018, +0.047] | +0.064 [+0.028, +0.104] |
| LC_onecoin-B1 | +0.188 [+0.137, +0.240] | +0.277 [+0.159, +0.388] |
| TVJT_gloss-TVJT | +0.015 [-0.021, +0.053] | -0.033 [-0.088, +0.022] |
| TVJT_nv-TVJT | -0.035 [-0.058, -0.013] | -0.114 [-0.180, -0.046] |
| NLI_deberta-B1 | -0.062 [-0.117, -0.010] | -0.034 [-0.121, +0.046] |
| NLI_gemini-NLI_deberta | +0.079 [+0.030, +0.129] | +0.141 [+0.070, +0.212] |
| TVJT-NLI_gemini | +0.019 [-0.026, +0.063] | +0.091 [+0.025, +0.168] |

### What the screen says

1. **Cross-system agreement (latent class) is the strongest gold-free signal.** It holds up:
   - within a sentence (0.765), not only between sentences;
   - on vocabulary-compatible items (0.814);
   - under the trigram labels (0.846).

   The one-coin EM beats plain majority (+0.032 [+0.018, +0.047];
   +0.064 on the top tercile).

   **Caveat.** Labels and agreement use the same equivalence machinery. If two systems agree and one is gold-equivalent,
   the other is too, so agreement is favoured by construction. LC also needs ≥2 systems and cannot score a lone
   output. At system level it orders the systems ['gpt-3.5-turbo', 'gpt-4', 'text-davinci-003'];
   the label order is ['gpt-4', 'gpt-3.5-turbo', 'text-davinci-003'].
2. **TVJT adds signal beyond the LLM judge, and the gain grows with sentence complexity.**
   - AUROC by tercile: TVJT 0.669 → 0.684 →
     **0.751**; B1 0.718 → 0.646 →
     **0.552**.
   - TVJT − B1 on the top tercile = **+0.199
     [+0.085, +0.308]**. Over all items it is +0.036
     [-0.015, +0.094].
   - TVJT discriminates within sentences (0.729; B1
     0.593).
   - **Its failure is invariance** (G2): rewrites get different worlds from their own mutants, and the judge disagrees
     on some of them. Rewrite FA is 0.479 at τ*=1.0 and 0.1844 at 0.5.
     By rewrite kind: {'CONTRAPOSITIVE': 0.3077, 'DEMORGAN': 0.3455, 'RENAME': 0.5839, 'REORDER': 0.4242}.
3. **Instance-consequence NLI with DeBERTa does not track correctness beyond the simplest tercile.**
   - Terciles: 0.766 / 0.450 / 0.518;
     within-sentence 0.537. A negative result.
   - Asking gemini the same pairs (NLI_gemini) changes AUROC by +0.079
     [+0.030, +0.129]. The consequence construction carries signal; the small NLI
     model cannot read quantified, instance-level entailments.
4. **Non-vacuous worlds hurt**: TVJT_nv − TVJT = -0.035
   [-0.058, -0.013]. Minimal worlds are not the bottleneck. Gloss verbalization:
   TVJT_gloss − TVJT = +0.015 [-0.021, +0.053].
5. **LLM non-determinism at T=0.** gemini-2.5-flash with temperature 0 and reasoning off is not fully deterministic.
   In the first pass, identical prompts sent concurrently (e.g. two systems emitting the same FOL string) sometimes got
   different answers. The final numbers come from a second, cache-consistent pass (identical input → identical cached
   answer; $0). The shift was ≤0.002 AUROC for TVJT, and the verdict was unchanged
   (`logs/repro/verdict_before.json` vs `results/verdict.json`).

### Per-operator detection (controlled mutants of the 300 screen golds)

| operator | n mutants | TVJT pairwise (judge sides with gold on the separating world) | NLI-DeBERTa pairwise | TVJT standalone (score<τ*) | B1 standalone (score<τ*) |
|---|---|---|---|---|---|
| NEG | 300 | 0.838 | 0.788 (53 undistinguishable) | 0.957 | 0.990 |
| QUANT | 141 | 0.883 | 0.709 (12 undistinguishable) | 0.950 | 0.957 |
| IMPL_REV | 121 | 0.864 | 0.703 (30 undistinguishable) | 0.984 | 0.992 |
| DROP_CONJ | 82 | 0.860 | 0.677 (35 undistinguishable) | 0.744 | 0.671 |
| ADD_CONJ | 300 | 0.863 | 0.582 (213 undistinguishable) | 0.890 | 0.803 |
| ARG_SWAP | 81 | 0.883 | 0.735 (27 undistinguishable) | 0.901 | 0.407 |
| AND_OR | 94 | 0.830 | 0.702 (22 undistinguishable) | 0.957 | 0.947 |
| SCOPE_SWAP | 0 | — | — (— undistinguishable) | — | — |
| MERGE | 40 | 0.825 | 0.713 (13 undistinguishable) | 0.325 | 0.575 |
| CARD | 28 | 0.762 | 0.679 (14 undistinguishable) | 0.929 | 0.893 |

- Judge oracle accuracy on gold worlds: 0.8555. Mean score on gold:
  NLI-DeBERTa 0.8195, NLI-gemini 0.9385.
- Error-type identification (argmax operator, 10 classes), macro-F1: TVJT 0.2525
  (top-1 0.3564); NLI 0.1814 (top-1 0.2115).
- ADD_CONJ with a fresh predicate on ground formulas is invisible to NLI, because the hypotheses use only F's own
  vocabulary.
- **FOLIO-dev gold has zero mixed ∀/∃ formulas**, so SCOPE_SWAP never applies on the screen.

**Blind-spot head-to-head** (`results/blindspot_headtohead.json`; Arm A's signature predicted ≈ chance):

| metric / op / split | detection | n | Wilson 95% |
|---|---|---|---|
| TVJT / SCOPE_SWAP / screen | — | 0 | [None, None] |
| TVJT / SCOPE_SWAP / screen+supplement | 0.649 | 37 | [0.4876, 0.7818] |
| TVJT / CARD / screen | 0.762 | 84 | [0.6606, 0.8403] |
| TVJT / CARD / screen+supplement | 0.662 | 468 | [0.6184, 0.7038] |
| NLI_deberta / SCOPE_SWAP / screen | — | 0 | [None, None] |
| NLI_deberta / SCOPE_SWAP / screen+supplement | 0.473 | 37 | [0.3224, 0.6287] |
| NLI_deberta / CARD / screen | 0.643 | 56 | [0.512, 0.7555] |
| NLI_deberta / CARD / screen+supplement | 0.605 | 440 | [0.5582, 0.6492] |

### Other reported quantities

- **Coverage.** Uncovered items get 0.5 and stay in every AUROC: TVJT 0.9304,
  NLI 0.9184, LC 0.9004, B3sc 0.5186.
  World coverage is 1.0 of parseable targets, with 4.268 worlds
  per target.
- **Verbalizer failure.** 0.0698 of items and 0.0398
  of predicates.
- **Cost per item** (fresh-call $ | median s):
  - TVJT $0.000191 | 0.687 s;
  - B1 $0.000024 | 0.507 s;
  - NLI-gemini $0.000482 | 0.96 s;
  - NLI-DeBERTa $0 | 0.059 s;
  - LC $0 (z3 pairwise equivalence done in the build stage).

  **Total OpenRouter spend of this workspace: $1.5501**, covering dev checks, the mini
  run and the full screen, out of a $10 budget with a $6.50 hard cap.
- **Judge prompt checks.** Dev slice (T2, 20 non-screen FOLIO-dev sentences): judge oracle
  accuracy 0.702 and 0% malformed JSON,
  so the TVJT prompt v1 was frozen. Blind-spot probe pairs (T1): the judge sided with gold on
  7/8.
- **System level.** With 3 systems, τ is not reported. The ordering by metric mean is in
  `analysis.json → system_level`.

## Independent audit of headline numbers

`audit/rederive.py` recomputes the headline numbers from the RAW files: `data/screen_set.json` labels,
`results/screen_scores.jsonl` rows, `data/candidate_pairs.json` and the cost ledgers. It uses a different code path:
sklearn `roc_auc_score`, a pandas cluster bootstrap, `cross_val_predict` OOF, brute-force within-sentence pairs, its
own Youden loop and a direct MAJ recount. Output: `audit/rederive_out.json`.
- **Matched exactly** (point estimates):
  - AUROC: LC 0.853, TVJT 0.701, NLI 0.603, B1 0.665, and all terciles;
  - G3 deltas: LC +0.111, TVJT +0.039, NLI +0.001;
  - within-sentence accuracy: LC 0.765, TVJT 0.729, B1 0.593;
  - TVJT − B1 on the top tercile: +0.199;
  - TVJT G2 false alarms: 0.479 at τ*=1.0 and 0.184 at 0.5;
  - labels 463/370, vocab-mismatch share 0.676, LC_maj (0 mismatches), spend $1.55.
- **Confidence intervals** differ only in the third decimal (different bootstrap RNG).
- **Placebo:** with permuted labels, AUROC is 0.51–0.52 and LC's G3 CI is [−0.032, +0.043], so G3 correctly fails.
- **Not independently re-derived:** the z3 labels themselves (the audit reuses them) and the LC_onecoin EM posteriors
  (only their AUROC was re-derived).

## Layout

```
method.py                 orchestrator: --stage build,b1,tvjt,nli,lc,tvjt_nv,analysis,export  [--limit N for mini runs]
src/fol_core.py           tokenizer/parser (FOLIO unicode), finite grounding → z3, py_eval, bounded/unbounded equivalence,
                          blind bijection labeller (fingerprint filter + z3), trigram-anchored labeller
src/mutants.py            10 typed mutation operators + 5 meaning-preserving rewrites (z3-verified)
src/build_screen.py       recipe: Logic-LM files × FOLIO v1 gold × curated gold → 300 sentences, labels, controls, supplement
src/verbalize.py          deterministic fact verbalizer (WordNet/spaCy head category; gloss variant)
src/tvjt.py               metric (ii): distinguishing-world search (z3 Optimize, minimal worlds), prompt, scoring
src/instance_nli.py       metric (iii): consequence pairs, z3 E/C/N labels, DeBERTa agreement, error type
src/latent_class.py       metric (iv): one-coin EM w/ all-wrong state, Hui–Walter, gold-as-rater, MAJ, Dawid–Skene, B3sc
src/llm.py                OpenRouter client: sha1 disk cache, cost ledger, $6.50 breaker
src/stages.py             stage implementations (B1/B2, TVJT, TVJT_nv, NLI, LC)
src/analysis.py           AUROC + clustered CIs, gates G1–G4, detection, confusion, costs, robustness, selection rule, figures
src/export.py             method_out.json (exp_gen_sol_out schema)
src/dev_checks.py         T1 probe pairs + T2 dev-slice prompt check (then prompt frozen)
src/integrity.py          T6 checks + cross-arm screen diff
src/metrics_api.py        reusable (text, fol) functions: tvjt_score, instance_nli_score, latent_class_scores, parse_ok
audit/rederive.py         independent re-derivation of headline numbers + placebo tests (audit/rederive_out.json)
src/make_readme.py        regenerates README.md (Results section filled only from results/*.json; head/tail templates in src/readme_*.md)
tests/test_core.py        T0 unit tests (parser, equivalence, reversed-implication flaw, py_eval≡z3, verbalizer, worlds, scope)
data/screen_set.json      sentences, real items + all labels, mutants, rewrites, counts, feature_spec, fingerprint
data/alt_candidates.jsonl duplicate per-example translations (self-consistency resource) with equivalence to primary
data/blindspot_supplement.jsonl  SCOPE_SWAP/CARD mutants (split = screen | supplement | supplement_folio_train | ...)
data/candidate_pairs.json pairwise equivalence of the 3 systems' candidates (blind + trigram maps)
data/worlds_cache.jsonl   TVJT worlds + prompts per target;  data/worlds_cache_nv.jsonl for TVJT_nv
data/consequences_cache.jsonl  NLI (premise, hypothesis) texts, z3 labels, mutant relabels per target
data/raw/                 downloaded public inputs (Logic-LM outputs, FOLIO v1 val/train, curated FOLIO/MALLS, MALLS-v0.1 test)
results/screen_scores.jsonl  one row per (item, metric): score, covered, error_type_pred, usd, seconds (+ per-world detail)
results/analysis.json     every reported number;  results/verdict.json gates + selection outcome
results/blindspot_headtohead.json, results/latent_class_info.json, results/integrity_checks.json, results/dev_checks.json
results/prompts_frozen.json, results/b1_request_example.json, results/cost_ledger*.jsonl
figures/                  auroc_by_tercile, per_operator_detection, confusion_TVJT / confusion_NLI_deberta (png/pdf)
runs/mini_10/             T3 mini run (first 10 screen sentences), full pipeline outputs
logs/                     run logs; logs/repro/ = first-pass verdict + score hash for the cache-consistent re-run check
method_out.json           exp_gen_sol_out export: every real/gold/mutant/rewrite item with labels + predict_<metric>
cache/llm/                sha1-keyed paid LLM responses (re-running everything costs $0)
```

## How to run

```bash
uv venv .venv --python=3.12
uv pip install --python .venv/bin/python -r requirements.txt
uv pip install --python .venv/bin/python https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl
# wordnet for the verbalizer / RENAME rewrites (see 'Restoring removed files')
export OPENROUTER_API_KEY=...        # only needed for uncached calls
.venv/bin/python method.py --stage all --limit 10     # mini run → runs/mini_10/
.venv/bin/python method.py --stage all                # full screen (~15 min on 6 CPU workers + 1 GPU; ~$1.5 uncached)
.venv/bin/python src/dev_checks.py                    # T1/T2 prompt checks
.venv/bin/python src/integrity.py                     # T6 checks
.venv/bin/python -m pytest -q -c tests/pytest.ini tests/
```

Raw inputs are downloaded into `data/raw/`, and they are already present:

- Logic-LM outputs: `raw.githubusercontent.com/teacherpeterpan/Logic-LLM/main/outputs/logic_programs/FOLIO_dev_*.json`
- FOLIO v1 gold: `raw.githubusercontent.com/Yale-LILY/FOLIO/main/data/v0.0/folio-{validation,train}.jsonl`
- Curated gold: HF `DSAVlab-UNIUD/FOLIO_validation-curated` and `DSAVlab-UNIUD/MALLS_test_subset-CURATED`
- MALLS test set: HF `yuan-yang/MALLS-v0` (`MALLS-v0.1-test.json`)

The NLI model `MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli` is loaded from the run's shared HF cache.

## Kept artifacts (workspace paths, for citation by path)

- `./data/screen_set.json`, `./data/alt_candidates.jsonl`, `./data/worlds_cache.jsonl`,
  `./data/consequences_cache.jsonl`, `./data/blindspot_supplement.jsonl`
- `./results/screen_scores.jsonl`, `./results/cost_ledger.jsonl`, `./results/analysis.json`, `./results/verdict.json`
- `./cache/llm/` (paid LLM responses; excluded from the GitHub upload, kept on the volume)

## Deviations from the plan (also in `method_out.json → metadata.deviations`)

1. Primary label gold = FOLIO v1; curated gold is secondary (see Gold policy).
2. The blind-spot supplement is extended beyond FOLIO-dev (FOLIO-train, curated MALLS, MALLS-v0.1-test), because
   FOLIO-dev gold has no mixed-quantifier formulas.
3. The one-coin likelihood includes (1−ρ) for non-coinciding wrong pairs.
4. The Dawid–Skene sanity row uses worker = other system, label = agrees. The plan's one-worker-per-task
   reformulation is degenerate.
5. Added the TVJT_nv secondary variant and the robustness analyses (within-sentence, vocabulary-compatible subset,
   paired deltas). Neither enters the rule.
6. Examples in FOLIO v1 whose premise and premise-FOL counts differ are not zipped, to avoid misaligned gold. Arm A
   zips them; the two screens therefore differ on ~11 sentences, and the 803 shared items have identical candidates
   (`results/integrity_checks.json`).

## Restoring removed files

The manifest (`.aii/manifest.yaml`) marks these for deletion after the round:

- `.venv/` (regenerable):
  `uv venv .venv --python=3.12 && uv pip install --python .venv/bin/python -r requirements.txt` (requirements.txt pins every package, including the spaCy model wheel URL)
- `nltk_data/` (redownloadable WordNet):
  `mkdir -p nltk_data/corpora && curl -sfL -o nltk_data/corpora/wordnet.zip https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/packages/corpora/wordnet.zip && (cd nltk_data/corpora && unzip -q -o wordnet.zip)`
- `tests/.pytest_cache/` (regenerable): `.venv/bin/python -m pytest -q -c tests/pytest.ini tests/`

The DeBERTa NLI weights live in the run's shared HF cache (`huggingface-cli download
MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli`), not in this workspace.
