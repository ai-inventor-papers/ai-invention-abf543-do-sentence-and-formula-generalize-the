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

