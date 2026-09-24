# Stress-testing peer agreement on constructed truth: Directional Consensus (DC)

**Workspace (absolute; every kept artefact lives here):**
`/ai-inventor/aii_data/runs/run_ujABDGgoK_5Q/3_invention_loop/iter_2/gen_art/gen_art_experiment_4`

This repository does four things:
- It builds **Directional Consensus (DC)** as a reusable package, `dc/`. DC is a gold-free NL→FOL faithfulness metric built on lexical-free logical agreement with peer formalisations.
- It freezes DC's configuration on the development set.
- It pre-registers predictions.
- It puts DC through constructed-truth tests: M1 confound, M2 invariance, M3 shared-bias boundary and M4 search placebos. It adds a mechanism ladder (M5), a completion of the round-2 record (M6) and a wrong-gold flag (M7).

Data: the 700-sentence × 9-system development set (`art_iyzYyaqlqpSX`). Cost: **$0.088** of API spend (frozen B1 judge on the M1 probes). No fresh labels.

> **Everything here is DEV, not confirmatory.** LC-style agreement already saw this set in round 2. Real-data AUROCs only anchor and calibrate DC. Constructed truth (M1–M3) is mechanism evidence, never a headline. The DC config is frozen with a sha256 (`frozen_dc_config.sha256` = `7ebda7e2…0d960`) so the confirmation artifact can reproduce the dev anchor. Every failed prediction is reported and **not** fixed in the frozen config. The fixes are proposed in `results/proposed_amendments.json`.

---

## 1. Function contracts (what each function measures)

| Function (file) | What it measures / returns |
|---|---|
| `dc.front.canon(fol)` (`dc/front.py`) | Canonical parse: dataset tolerant parser → `to_str` → Arm-B AST. Returns `{ok, canon, ast, preds, consts}` or UNPARSEABLE, which is counted, never dropped. |
| `dc.fp.truth_vector(F, slots)` (`dc/fp.py`) | F's truth values on 64 fixed random finite structures (domains 2 and 3). Predicates are bound to slots by **first-occurrence position, never by name**. Any refutation from these vectors is sound. |
| `dc.align.align_pair(fa, fb)` (`dc/align.py`) | Which vocabulary correspondences between two formulas are admissible, best-first, with **no use of names**. L1: arity-preserving bijections (cap 5040). L2: partial injective maps covering ≥50% of predicate occurrences (cap 2000). L3: granularity definitions (≤2 literals, ≤2 definitions, ≤300 sets, must cover every unmapped predicate). |
| `dc.relation.pair_relation(A, B)` (`dc/relation.py`) | Logical relation of A to B in a shared vocabulary: EQUIV / STRONGER (A⊨B only) / WEAKER / CONTRADICTORY / COMPATIBLE / UNKNOWN. Steps: fingerprint refutation → unbounded z3 (uninterpreted sort) → grounding over domains ≤3 on unknown (then `method='bounded'`). |
| `dc.best_relation(sa, sb)` (`dc/pairs.py`) | The best relation over all admissible alignments. Rule: maximise EQUIV > STRONGER=WEAKER, with lower level winning ties. Otherwise the relation under the top map of the lowest level. Also returns `rel_L1`, `rel_L2`, `rel_L3` (best using levels ≤k) and `rel_lex` (relation under the lexically anchored trigram map). UNALIGNABLE if no map exists. Caches are orientation-free. |
| `dc.core.directional_consensus(text, fol, peers, peer_ids, weights, ...)` (`dc/core.py`) | **DC score** = Σ w·[rel(fol,peer)=EQUIV] / Σ w over peers with rel≠UNKNOWN; UNALIGNABLE stays in the denominator. Unparseable input or fewer than 2 covered peers gives 0.5. Never reads `text` or symbol names. Also returns the strength profile, relation to the weighted mode, error type, coverage and cost. |
| `dc.core.ds_weights(obs, systems)` | One-coin Dawid–Skene (vendor `latent_class.em`) on EQUIV clusters. Returns w_s = clip(logit p_s, 0.05, 3). |
| `dc.core.error_type_contract` / `repair_type` | Error type relative to the mode representative. The contract order is: negation, added, dropped, ∀/∃, implication, argument swap, other. The *repair* variant uses the first single edit that makes fol EQUIV to the mode. |
| `dc.core.vocab_conformity(fol, peers)` | **VC control** (the user's vocabulary/structure family): mean of 0.5·Jaccard(normalised predicate names) + 0.5·1[arity profile equal]. It rewards conventional naming. |
| `dc.probes.*` (`dc/probes.py`) | Constructed-truth builders:<br>- `tokmap`, `synmap` renderings and `map_to_peer` rendering;<br>- ADD_CONJ with an existing predicate;<br>- `var_rename`;<br>- the 7 verified rewrite kinds (bounded n≤4 **and** unbounded z3). |
| `dc.llm` | Capped OpenRouter client (env base URL, ledger, cache, $2.70 hard stop) and the frozen exp3 B1 request. |

Minimal use:
```python
import dc.common                      # env (NLTK_DATA, thread caps)
from dc.core import directional_consensus
r = directional_consensus(None, "∀x (Dog(x) → Bark(x))", ["∀y (Canine(y) → Woof(y))", "∃x (Dog(x) ∧ Bark(x))"])
r["score"], r["strength_profile"], r["error_type"]
```

## 2. Headline results

AUROCs and CIs use 2,000-draw sentence bootstraps, stratified by corpus × tercile. P = the 609 panel items, weighted by `L3_sampling_weight` (Kish n_eff 350). S = audited-solver/final labels, 5,847 rows, unweighted. S labels share z3 machinery with DC, so they are partially circular; P is co-primary.

### 2.1 M0 dev anchor (`results/m0_anchor.json`)

| metric | AUROC P [95% CI] | AUROC S |
|---|---|---|
| **DC** (L1+L2+L3, DS weights, frozen) | 0.769 [0.717, 0.819] | 0.815 |
| DC_L2w (no L3, DS weights) | 0.774 [0.720, 0.825] | 0.833 |
| S1_L2 (L1+L2, unweighted) | 0.763 [0.712, 0.811] | 0.818 |
| S0_L1 (direct L1 EQUIV share) | 0.636 [0.575, 0.693] | 0.717 |
| DC_lex (trigram-anchored map) | 0.612 [0.551, 0.670] | 0.693 |
| LC_maj* (this engine, L1 clusters; T2 check) | 0.774 | 0.830 |
| exp3 LC_maj / LC_onecoin / LC_ds_binary | 0.765 / 0.756 / 0.787 | 0.824 / 0.810 / 0.831 |
| B1 judge (gemini-2.5-flash) / B3nli / B3cos | 0.762 / 0.734 / 0.723 | 0.713 / 0.631 / 0.647 |
| VC (vocabulary conformity) / B7 (structural) | 0.683 / 0.511 | 0.763 / 0.509 |

- **L1 cross-check.** DC's `rel_L1==EQUIV` agrees with exp3's `pairs_cache` bijection verdict on **100% of 22,198 pairs**.
- **T2 reproduction.** LC_maj* is within 0.009 of exp3's LC_maj.
- **DS sanity.** DS p_s correlates with per-system panel accuracy (Spearman 0.78). Four systems (deepseek, llama-8b, phi-4, qwen-7b) sit at the weight floor 0.05.
- **Coverage** is 0.921. Unparseable items are counted, scored 0.5 and never dropped.
- **Cost** is $0: 19,182 unique dev pairs took 136 s on 22 CPU workers. On a cached peer set, scoring takes about 3 ms per item.

### 2.2 M1 confound: vocabulary × meaning (`results/m1_confound.json`)

Design:
- 223 gold-faithful sentences, built from the 251 eligible; 28 had no renderable mode member. By corpus: ProverQA 144, MALLS 60, FOLIO 19.
- The gold is rendered in the modal peer's vocabulary (*conf*), in random tokens (*tok*) and in WordNet synonyms (*syn*).
- The same operator edit is rendered in each arm.
- Peers are the 9 real outputs, with frozen weights.
- 223 F vs 739 paired non-automorphic mutants per arm.

| AUROC F vs M | conf | tok | syn | **crossed** F_tok vs M_conf |
|---|---|---|---|---|
| **DC** | 0.805 | 0.804 | 0.804 | 0.805 |
| DC_L2w | 0.999 | 0.999 | 0.999 | 0.999 |
| S0_L1 | 0.965 | 0.965 | 0.965 | 0.965 |
| LC_maj* | 0.998 | 0.998 | 0.998 | 0.998 |
| VC | 0.542 | 0.533 | 0.533 | **0.176** |
| B1 (text-reading reference) | 0.945 | **0.794** | 0.890 | 0.763 |

- **DC is exactly vocabulary-invariant**: arm gap 0.0015 [90% CI within ±0.03].
- The **B1 judge is not**: conf − tok = 0.151 [0.119, 0.184] and conf − syn = 0.055 [0.035, 0.078]. The cheap judge rewards conventional vocabulary.
- VC falls to 0.176 on the adversarial crossing, as predicted for a conformity metric.

**Per-operator results expose a large, previously unmeasured blind spot of lexical-free granularity definitions (L3).** The table shows AUROC in the tok arm; within-sentence detection gives the same picture.

| operator (n) | DC | DC_L2w | LC_maj* | B1 |
|---|---|---|---|---|
| NEG (223) | **0.511** | 1.000 | 1.000 | 0.812 |
| DROP_CONJ (88) | **0.659** | 0.995 | 0.984 | 0.601 |
| ADD_CONJ (223) | 0.952 | 0.998 | 0.998 | 0.808 |
| QUANT (122) | 1.000 | 0.996 | 0.996 | 0.821 |
| IMPL_REV (189) | 0.999 | 1.000 | 1.000 | 0.819 |
| IMPL_REV automorphic (20) | **0.500** | 0.500 | 0.500 | 0.522 |
| ARG_SWAP (7, descriptive) | 0.643 | 1.000 | 1.000 | 0.439 |

Two mechanisms cause the blind spots:
- A name-free definition `Q := ¬P` absorbs any single negation. This finding was post hoc, not pre-registered.
- `Dog' := Dog ∧ Brown` absorbs a dropped restrictor. This was pre-registered as P6.

A third blind spot is the **automorphism**: 20/209 IMPL_REV mutants are a pure predicate permutation of the gold, for example ∀x(A→B) vs ∀x(B→A). Every lexical-free metric scores them at chance, and the judge also sits at 0.52.

**M1(b), real dev.** Cross-fitted sentence-grouped stacking:

| label | base | base AUROC | Δ from adding DC [95% CI] |
|---|---|---|---|
| panel | [B1, parse_ok, VC] | 0.780 | **+0.015 [−0.009, 0.040]**: does not pass |
| solver | [B1, parse_ok, VC] | – | +0.036 [0.027, 0.045] |
| panel | [B1, parse_ok, VC, LC_maj] | – | −0.001 |

With LC_maj in the base, DC adds nothing: DC carries the same information as LC_maj. The placebo random feature gives Δ ≤ 0.

### 2.3 M2 invariance and contamination (`results/m2_invariance.json`, `results/m2_rename_diagnosis.json`)

Design: 999 candidates (595 panel + 404 others), each verified meaning-preserving rewrite, scored against the same 8 peers with the same weights.

| rewrite | n verified | FA(δ=0) | FA(δ=0.10) | relation-vector change |
|---|---|---|---|---|
| syn_rename | 999 | 0.001 | **0.000** | 0.005 |
| tok_rename | 999 | 0.001 | **0.000** | 0.005 |
| var_rename | 999 | 0.001 | **0.000** | 0.004 |
| reorder | 892 | 0.016 | 0.007 | 0.046 |
| contrapositive | 765 | 0.046 | 0.018 | 0.107 |
| demorgan | 773 | 0.001 | 0.000 | 0.006 |
| prenex | 153 (843 inapplicable) | 0.013 | 0.007 | 0.046 |

- Round-2 references: the signature rename false-alarm rate was 0.38–0.52, and TVJT was 0.26–0.58.
- **DC's rename false-alarm rate is 0/999 at δ = 0.10.**
- The 1/999 exact changes all trace to one cause (fallback-10 diagnosis). The source/target role tie-break follows the lexicographic (lo, hi) storage order of the pair, which depends on names. Amendment A2 proposes the fix.

**Contamination** (104 entity-renamed paraphrases, 936 rows): DC Δ(orig − para) = **+0.0023 [0.0001, 0.0055]**, and 98.2% of scores are exactly equal. The B1 judge's Δ is +0.096 [0.068, 0.126]. DC is 40× less sensitive, but the CI excludes 0 by 0.0001, so the pre-registered prediction formally fails.

### 2.4 M3 shared-bias boundary (`results/m3_boundary.json`)

Dose curve: 200 sentences × 4 operators = 560 items. k of 8 peers are replaced by renamed copies of the mutant. The table reports pooled detection P(DC(F) > DC(M)).

| k | 0 | 2 | 4 | 6 | 8 |
|---|---|---|---|---|---|
| DC (random order) | 0.934 | 0.771 | 0.434 | 0.138 | 0.058 |
| analytic curve | 0.934 | 0.771 | 0.434 | 0.138 | 0.058 |
| DC (faithful peers replaced first) | 0.934 | 0.609 | 0.057 | 0.058 | 0.058 |

- The observed curve **equals** the analytic one: renamed copies are recognised as EQUIV 100% of the time. The inheritance audit matches on 502/502 pairs.
- So the boundary is pure peer-mass arithmetic. Agreement fails exactly when correlated wrong peers carry the weight.
- The pre-registered prediction fails only at k = 2 (0.77 < 0.9).

**Real shared bias** (all 700 dev sentences). Within-sentence DC concordance falls with the weight share of wrong-meaning clusters:

| wrong-meaning weight share | [0, .25) | [.25, .5) | [.5, .75) | ≥ .75 |
|---|---|---|---|---|
| concordance | 0.83 | 0.88 | 0.56 | **0.45** |

- The logistic slope is −2.08 [−2.55, −1.61], so the prediction passes.
- 284/700 sentences have a wrong-meaning weighted mode.

**DC+arb (text-anchored arbiter): NOT RUN.** The run-level OpenRouter budget was exhausted by other artifacts of this run (HTTP 403 `aii_run_budget_exhausted`). The key was polled every 10 min for 60 min (`work/key_status.jsonl`, `logs/m3_ask.out`). All 783 constructed and 619 real arbiter prompts are saved in `work/m3_dose.jsonl` and `work/m3_real.jsonl`. `uv run scripts/m3_ask.py && uv run scripts/m3_analyze.py` completes the stage for about $0.1 when a key is available. In `method_out.json`, `predict_DC_arb` = DC.

### 2.5 M4 search placebos (`results/m4_placebo.json`)

**(a) Cross-sentence peers** (1,000 candidates × 4 arity-matched outputs from other sentences):
- 16.2% are EQUIV at L1. These are *shape-isomorphic* pairs, e.g. "All A are B" vs "All C are D". Name-free equivalence cannot tell them apart.
- L2 adds 0.0% spurious EQUIV. **L3 adds 11.9%** on non-isomorphic pairs (15.3% for ≤3 atoms, 0% for ≥7), so L3 is flagged (>5%).

**(b) Within-sentence label shuffle** (200 permutations): AUROC stays at **0.73** on panel (true 0.77) and 0.70 on solver labels (true 0.82). Signature reference: 0.648. **Most of DC's AUROC is between-sentence structure**: sentences whose outputs agree are more often correct.

**(c) Within-sentence AUROC** over faithful × unfaithful pairs in the same sentence:

| label | DC | DC_L2w | LC_maj | LC_ds_binary | B1 |
|---|---|---|---|---|---|
| panel (122 pairs) | 0.56 [0.41, 0.73] | 0.59 | 0.69 | 0.58 | **0.75** |
| solver (6,772 pairs) | 0.74 | 0.75 | 0.76 | 0.76 | 0.68 |

**(d) Lexical-anchor contrast.**
- 1.9% of within-sentence EQUIVs that have a trigram map are non-EQUIV under it, i.e. "manufactured" by the solver-chosen map.
- The rate is enriched among unfaithful items (P3 passes):

| label | unfaithful | faithful |
|---|---|---|
| panel | 3.7% | 2.1% |
| solver | 4.3% | 1.3% |

- Forcing the lexical map (DC_lex) costs 0.16 AUROC, so manufactured agreement is a minor channel.

### 2.6 M5 mechanism ladder and typing (`results/m5_ladder_typing.json`)

| ladder step | panel AUROC | Δ vs previous [CI] | solver AUROC |
|---|---|---|---|
| S0 L1 EQUIV share | 0.636 | – | 0.717 |
| S1 + L2 partial maps | 0.763 | **+0.128 [0.081, 0.178]** | 0.818 |
| S2 + L3 definitions | 0.758 | −0.006 [−0.022, 0.010] | 0.799 |
| S3 + DS weights = DC | 0.769 | +0.011 [−0.005, 0.027] | 0.815 |

- **L2 carries the whole mechanism.** L3 is neutral-to-harmful, and DS weights are neutral.
- The largest per-type step lift is on quantifier ∀/∃ and implication direction, not on added conditions, so P1 fails.
- **Typing fails.**

| typing test | DC | reference |
|---|---|---|
| real panel-unfaithful items, weighted top-1 | 0.213 | majority 0.257; typed judge TJ 0.407 on the same items |
| constructed, contract variant | accuracy 0.26, macro-F1 0.44 | – |

  On constructed items, ∀/∃ is recovered 98% of the time, but negation and implication are rarely typed, because L3 absorbs negation and clusters are built by transitive closure. See amendment A3.

### 2.7 M6: round-2 record and within-sentence recomputation

Files: `results/round2_record.json`, `results/m6_within_sentence.json`, `results/wrong_gold_citation.json`.

exp5's partnered set is rebuilt exactly (n_dropped = 36, n_impl = 24, 246 errors with partners). Weighted detection with CIs:

| primary error (n) | B1 | LC_maj | LC_ds | DC | DC_L2w |
|---|---|---|---|---|---|
| added (65) | 0.59 | 0.63 | 0.60 | 0.65 | **0.71** |
| dropped (36) | 0.58 | 0.56 | 0.49 | **0.44** | 0.58 |
| ∀/∃ (56) | 0.82 | 0.81 | **0.88** | 0.72 | 0.73 |
| implication (24) | 0.58 | 0.64 | 0.67 | 0.58 | **0.71** |
| predicted-visible (188) | 0.67 | 0.67 | 0.67 | 0.62 | **0.69** |

**Wrong-gold citation (arXiv:2606.02837, Brunello et al.)**

| | v1 | v2 (current) |
|---|---|---|
| incorrect FOL (FOLIO / MALLS) | 39% / 36% | **42.5% / 42%** |
| ambiguous NL | 16.4% / 48% | 17.8% / 51% |
| guided review reaching 90% accuracy | "fewer than 24%" of instances reviewed | **"fewer than 20%" (unguided: over 76%)** |

The handbook quotes v1.

### 2.8 M7: gold as a 10th peer, wrong-gold flag (`results/m7_goldflag.json`)

DC(shipped gold) against the 9 system outputs: **AUROC 0.837 [0.809, 0.864]** against L0 `gold_faithful_final`, over 700 golds with a 43% wrong rate. Coverage is 0.966.

| corpus | DC AUROC | note |
|---|---|---|
| ProverQA | 0.891 | P@25 = 0.76 at a 17.5% base wrong rate |
| MALLS | 0.783 | |
| FOLIO | 0.733 | |

Stacked with the judges (cross-fitted): **B1 + DC 0.896 vs B1 0.825 (+0.070 [0.045, 0.096])** and **TJ + DC 0.889 vs TJ 0.841 (+0.048 [0.028, 0.070])**. Agreement-based gold flagging is complementary to judges. The nearest neighbour is Brunello et al.'s LLM-guided relabelling framework.

### 2.9 Complexity, system level, cost (`results/complexity_system_cost.json`)

**Panel AUROC by complexity tercile** (bottom / middle / top):
- DC: 0.767 / 0.772 / 0.764
- LC_ds_binary: 0.754 / 0.825 / 0.777
- B1: 0.798 / 0.671 / 0.779

**By number of conditions** (0 / 1 / 2 / ≥3):
- DC: 0.865 / 0.760 / 0.638 / 0.838
- B1: 0.906 / 0.713 / 0.707 / 0.806

Under solver labels, DC_L2w beats B1 in every tercile (top: 0.812 vs 0.719).

**System level** (9 systems, underpowered): Kendall τ with panel accuracy is DC 0.67, LC_maj 0.78, B1 0.72.

**Cost**: $0 per item. Mean pair time is 0.13 s (L1-decided), 0.18 s (L2) and 0.07 s (L3); p95 is ≤0.76 s. Rates are: timeouts 0.09%, UNKNOWN 0.12%, engine errors 0.05% (recorded as UNKNOWN, counted). Relation methods: unbounded-proved 39.5k, fingerprint-refuted 27.8k, bounded-only 14.

### 2.10 Verdicts (`results/verdicts.json`): 9 PASS, 10 FAIL, 1 NOT_RUN

| prediction | verdict | key number |
|---|---|---|
| M1.P1 DC arm gap < 0.02 | PASS | 0.0015 |
| M1.P2 DC crossed ≥ 0.85 | FAIL | 0.805 (DC_L2w 0.999) |
| M1.P3 VC gap > 0.2 | FAIL | ≈0.01. Ill-posed: F and M share vocabulary within an arm |
| M1.P4 VC crossed < 0.5 | PASS | 0.176 |
| M1.P5 automorphic mutants ≈ 0.5 | PASS | 0.50 (n = 20) |
| M1.P6 L3 absorbs DROP_CONJ | PASS | detection 0.68 vs 0.98 |
| M1b DC adds over [B1, parse, VC] (panel) | FAIL | +0.015 [−0.009, 0.040] |
| M2.P1 FA(0.10) ≤ 0.05 | PASS | max 0.018 (contrapositive) |
| M2.P2 FA(0) = 0 for renames | FAIL | 0.001 (role tie-break) |
| M2.P3 contamination | FAIL | +0.0023 [0.0001, 0.0055] vs B1 +0.096 |
| M3.P1 dose curve | FAIL | only k = 2 misses (0.77) |
| M3.P2 DC+arb > DC | NOT_RUN | OpenRouter run budget exhausted |
| M3.P3 real shared-bias slope < 0 | PASS | −2.08 [−2.55, −1.61] |
| M4.P1 spurious EQUIV ≤ 2% | FAIL | L2 0.0%, L3 11.9% |
| M4.P2 shuffle ≈ 0.5 | FAIL | 0.73 |
| M4.P3 manufactured agreement enriched | PASS | panel 3.7% vs 2.1% |
| M5.P1 largest lift on added_condition | FAIL | implication / ∀∃ |
| M5.P2 typing > majority | FAIL | 0.213 vs 0.257 |
| M6 partnered counts 36 / 24 | PASS | exact |
| M7 gold-flag AUROC > 0.5 | PASS | 0.837 [0.809, 0.864] |

**Reading for the paper.** DC is exactly name-free and contamination-proof, and it is a strong wrong-gold flag. But as frozen it is not better than simple L1/L2 cluster agreement:
- Its L3 granularity layer manufactures agreement, absorbing negations and dropped restrictors.
- Most of its item-level AUROC is between-sentence structure.
- It adds nothing over LC_maj.
- It inherits the automorphism blind spot, and the shared-bias boundary is exactly the arithmetic of peer mass.

The recommended configuration for confirmation is **DC_L2w**, with the name-free role tie-break (amendments A1 and A2).

## 3. Deviations from the plan (honest list)

1. **Arbiter (M3b and M3c DC+arb) not run.** The run-level OpenRouter cap returned 403 for every call. This follows fallback 8: 60 min of polling, then the rows are marked NOT RUN. No substitute model was used.
2. **The L3 cap stayed at 300.** No time fallback was needed. M0 pairs took 136 s; all 73,994 cached pairs about 12 min of 22-worker CPU.
3. **Selection rule refined before the freeze.** COMPATIBLE and CONTRADICTORY are decided at the lowest level that has a map. Without this, partial L2 maps overrode a genuine L1 CONTRADICTORY. The frozen `selection_rule` records the refinement.
4. **L3 definitions restricted before the freeze.** Bodies may use only the other side's unmapped predicates, a single positive same-order literal is excluded (that case is a plain map), and a definition set must cover every unmapped predicate. The original, looser version made `Brown := Dog` merges. Negated single literals stayed allowed, which produced the M1 NEG blind spot.
5. **T0 tests were written into `tests/test_dc.py` after the M0 run.** A hand smoke test (`scripts/scratch_test.py`) ran before scoring. The pytest suite (12 tests) tests the frozen code and passes (`results/pytest_result.txt`). Blind spots are asserted as blind spots.
6. **M1 used 223 sentences instead of 300.** Only 251 met the S1 criterion, and 28 had no renderable mode member.
   - B1 was run on all three arms, since each arm cost $0.03.
   - ADD_CONJ with a fresh predicate occurred in 113 sentences. Those mutants were excluded from the conf arm and from the paired arm comparison.
7. **DS weights are extreme.** Four systems are at the 0.05 floor. The fit is not degenerate across 3 seeds, so the one-coin weights were frozen per plan.
8. **The dataset parser universally closes single-letter free terms** (e.g. `D(r)` becomes `∀r D(r)`). This is inherited front-end behaviour, kept unchanged.
9. **M2 used 999 candidates**: 595 panel items plus 404 others.

## 4. Layout

| path | content |
|---|---|
| `dc/` | The DC package. **Frozen engine files** (sha256 in `frozen_dc_config.json`): `front.py`, `fp.py`, `align.py`, `relation.py`, `pairs.py`, `core.py`, `common.py`, `stats.py`, `__init__.py`. Added after the freeze (no scoring logic): `probes.py` (constructed-truth builders) and `llm.py` (capped client). |
| `method.py` | Entry point: `uv run method.py all` runs every stage; `uv run method.py export` writes `method_out.json` |
| `scripts/prep.py` | Frame + canonical strings (`work/frame.jsonl`, `work/canon.jsonl`) |
| `scripts/m0_pairs.py`, `m0_score.py`, `m0_anchor.py` | M0: pairs, DS weights and DC scoring, dev anchor and **freeze** |
| `scripts/prereg.py` | Writes `results/prereg.json` (refuses to overwrite) |
| `scripts/m1_build_score.py`, `m1_b1.py`, `m1_analyze.py` | M1 |
| `scripts/m2_invariance.py`, `m2_diagnose.py` | M2 + rename diagnosis |
| `scripts/m3_boundary.py`, `m3_ask.py`, `m3_analyze.py` | M3. `m3_ask.py` re-asks the arbiter from the saved prompts |
| `scripts/m4_placebo.py` | M4 |
| `scripts/m5_m6_m7.py`, `scripts/m6_record.py` | M5 / M6 / M7 |
| `scripts/extra_analyses.py`, `scripts/verdicts.py`, `audit_rederive.py`, `audit_rederive2.py`, `reproducibility.md` | Complexity, system and cost; verdicts, amendments and integrity; T5 independent re-derivation (`audit_rederive2.py` also re-derives the M7, M1 per-op, M2 FA and M4b numbers and confirms the placebos fail) |
| `tests/test_dc.py` | 12 unit tests (T0) |
| `vendor/` | Read-only copies of round-1/2 code with a sha1 `manifest.json`:<br>- `ds/`: the dataset parser, L1 and L2;<br>- `armB/`: `fol_core`, `mutants`, `tvjt`, `verbalize`, `latent_class`;<br>- `exp3/`: stats, analysis, the armB worker and the frozen prompts;<br>- `exp5/`: `analyze.py` |
| `frozen_dc_config.json` (+ `.sha256`) | Limits, ordering and selection rules, weights, DS fit, code sha256, dev anchor |
| `results/*.json` | All results (§2); `verdicts.json`; `proposed_amendments.json`; `integrity.json`. Integrity covers:<br>- vendor unchanged, frozen engine code unchanged, frozen config sha unchanged since the pre-registration;<br>- ledger $0.0883 = reported;<br>- T0 12/12 tests pass;<br>- T3: DC and relation vectors identical across conf/tok/syn for 99.6% of the 223 M1 sentences (the exception is the A2 tie-break);<br>- T5: the audit re-derives 3 headline numbers to 1e-16 |
| `work/pairs_dc.jsonl` | **Kept.** 73,994 best-relation records (50 MB): the CPU-heavy cache, reusable by the confirmation artifact |
| `work/dc_scores.jsonl`, `work/gold_dc_scores.jsonl`, `work/m1_probes.jsonl`, `work/m1_b1.jsonl`, `work/m2_*.jsonl`, `work/m3_*.jsonl` | Per-item scores, probes and arbiter prompts |
| `work/llm_cache/`, `cost_ledger.jsonl` | **Kept.** Irreproducible API outputs (3,175 B1 calls, $0.088) |
| `method_out.json` (= `full_method_out.json`), `mini_`/`preview_` | exp_gen_sol_out (see below) |
| `logs/` | Run logs |

`method_out.json` holds 3 datasets and 10,175 examples. The format is validated (`exp_gen_sol_out`: PASSED).
- `heldout_confirm_dev`: 6,300 greedy rows. Output is the dataset label, and unknown labels are kept. Predictions: `predict_DC`, `_DC_L2w`, `_DC_lex`, `_S0_L1`, `_S1_L2`, `_S2_L3`, `_LC_maj_star`, `_VC`, and `_DC_arb` (= DC). Frozen baselines appear as `predict_baseline_*`. Metadata: error type, strength profile, coverage, peer relations, seconds.
- `m1_constructed_probes`: 3,175 rows.
- `m7_gold_as_peer`: 700 rows.

## 5. How to run

```bash
bash restore.sh                   # venv + WordNet + unit tests
uv run method.py all              # every stage (about 20 min on 23 CPUs; the arbiter needs an OpenRouter key)
uv run method.py export           # method_out.json only
```
Every stage is resumable: pair results are cached in `work/pairs_dc.jsonl`, and LLM calls in `work/llm_cache/`. The frozen config and the pre-registration refuse to be overwritten. The dataset is read in place from `/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_dataset_1/full_data_out/`.

## 6. Restoring removed files

| removed path | restore |
|---|---|
| `.venv/` | `uv venv .venv --python=3.12 && uv pip install --python=.venv/bin/python z3-solver numpy scipy scikit-learn pandas nltk loguru aiohttp tenacity pytest orjson psutil spacy "en_core_web_sm @ https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"` |
| `nltk_data/` | `mkdir -p nltk_data/corpora && curl -sL -o nltk_data/corpora/wordnet.zip https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/packages/corpora/wordnet.zip && (cd nltk_data/corpora && unzip -q -o wordnet.zip)`. The `nltk.download` route refuses the world-writable workspace. |
| `__pycache__/` | Recreated automatically on import |
| `.pytest_cache/` | `.venv/bin/python -m pytest -q -c pytest.ini tests/test_dc.py` |

`restore.sh` performs all of the above and runs the unit tests.
