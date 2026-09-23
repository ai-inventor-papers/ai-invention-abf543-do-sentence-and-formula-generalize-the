# TVJT crossover deep test (iter 2) — repaired small-world truth judgments vs the LLM judge

**Question.** In iter 1, TVJT was the only gold-free NL→FOL faithfulness metric whose advantage over an LLM judge
*grew* with sentence complexity. On the screen's top tercile it scored .751 against B1's .552, a gap of Δ +.20. It
failed only the rewrite-invariance gate G2.

TVJT works like this. z3 builds small worlds that separate a candidate formula F from its own typed mutants, and
`gemini-2.5-flash` judges only whether the **sentence** is true in each world. The formula itself is never shown
to the judge.

This artifact (1) repairs the instrument noise behind the G2 failure, (2) freezes the repaired protocol, and (3)
tests the complexity crossover on the held-out dataset `art_iyzYyaqlqpSX`.

**Answer: the crossover does NOT replicate — it REVERSES.**
- On the 389 panel-labelled top-tercile items, repaired TVJT\* scores AUROC_w .674 against B1's .772:
  **Δ −.098 [−.184, −.014]**. Against the compute-matched B1x3 it is **Δ −.120 [−.208, −.035]**.
- The repair itself works for everything except predicate renaming. Every non-RENAME meaning-preserving rewrite
  now has paired false-alarm rate **0.000** (screen and held-out). RENAME stays at .39 on the screen and .26
  held-out: a verbaliser and synonym limitation.

All numbers below are read from `results/analysis.json` (held-out), `results/canon_diagnostic.json`,
`results/screen_replay.json` and `results/heldout_g2_canon.json` (zero-cost diagnostics). CIs are 2000×
sentence-cluster bootstraps with corpus strata, seed 0, paired across metrics. `audit/rederive.py` re-derives
every point estimate with sklearn and gets an exact match (`results/audit_rederive.json`).

## What was built

| component | file | what it does |
|---|---|---|
| R1 canonical form | `src/canon.py` | NNF with ↔/⊕ parity, a restricted-implication normal form (A→B, ¬B→¬A, ¬A∨B map to one form), name-blind operand sorting, alpha-renaming, prenexing. Every form is verified bounded-equivalent (n≤4) to its source; there were 0 fallbacks on the 300 screen golds. |
| R1 canonical worlds | `src/canon.py::canonical_worlds` | Mutants of canon(F) are generated with a **name-blind seed** on a **name-normalised** copy (Q1…, k1…). z3 minimal distinguishing worlds are deduplicated by isomorphism and ordered by key. `find_world` is **deterministic** (see "Bug found" below). |
| R2+R3 judge protocol | `src/judge.py` | A world-level answer cache keyed by `sha1(model∣prompt_version∣sentence∣world_text∣vote)`, 3 votes over fixed world orders (canonical, reversed, rotated), and prompt `tvjt_v2_conf` with `[v, confidence]` answers. Scores: C1 = vote-0 binary; C2 = majority; **C3 = confidence-weighted, the frozen score**. |
| B1 / B1x3 | `src/judge.py` | The EXACT iter-1 B1 prompt and payload (`gemini-2.5-flash`, T=0, reasoning off). B1x3 = the mean of 3 independent calls (compute-matched). |
| syntax bridge | `src/bridge.py` | Maps held-out candidates in ASCII/LaTeX/snake_case, quoted or hyphenated constants and upper-case variables into `fol_core`. It loses **0** of the dataset-parseable candidates for all 9 systems (`results/bridge_coverage.json`). |
| zero-LLM baselines | `src/stage_lc.py`, `src/run_a3.py` | LC_onecoin (a one-coin latent class over 9 systems, 22,951 pairwise blind-bijection checks), LC_maj, B3sc (5-sample self-consistency; gpt-4.1-mini and llama-3.1-8b only), and the Arm-A A3 signature. |
| freeze | `src/freeze.py`, `src/labels.py` | `frozen_config.json` + `prereg.json` are hashed into `freeze_receipt.json` (14:41:27 UTC). The label loader raises unless the receipt hashes match. |
| analyses | `src/analysis2.py`, `audit/rederive.py`, `src/figures.py` | Plan §7 A–I plus the decision table → `results/analysis.json`, `results/verdict.json`, `figures/*.pdf/png`. |
| API | `src/metrics_api2.py` | `canon(fol)`, `distinguishing_worlds(fol)`, `tvjt_score(text, fol)`, with docstrings. |
| orchestrator | `method.py` | `--stage setup\|canon_diag\|targets\|worlds\|zero_llm\|freeze\|score_heldout\|analysis\|export\|all` |

## Phase 1 — repair on the screen (iter-1 FOLIO-dev screen, screen labels only)

**World-set identity: equivalent rewrites now get the gold's exact world set** (`canon_diagnostic.json → T1`):

| rewrite kind | n | iter-1 worlds | canonical worlds |
|---|---|---|---|
| REORDER | 66 | .182 | **1.000** |
| DEMORGAN | 55 | .018 | **1.000** |
| CONTRAPOSITIVE | 104 | .125 | **1.000** |
| RENAME (up to renaming) | 274 | .628 | **.996** |

The same holds on held-out (99 audited golds → 197 solver-verified rewrites; `heldout_g2_canon.json`):
- REORDER, CONTRAPOSITIVE, DEMORGAN and PRENEX: 137/137 identical canonical strings, world sets **and verbalisations**.
- RENAME: 59/60.

**Where the iter-1 false alarms came from.** These are zero-cost diagnostics over iter-1's cached gemini answers:
- **Judge inconsistency.** gemini-2.5-flash at T=0 gave *different* verdicts to the same (sentence, verbalised
  world) in **13.7%** of the 1,186 cases judged inside ≥2 different prompts.
- **World-set changes.** iter-1's non-RENAME false alarms occurred only when the rewrite's world set changed. The
  paired FA was 0 on the 26 non-RENAME rewrites whose iter-1 world set was identical to the gold's.
- **Verbalisation.** RENAME kept FA .34 even with identical worlds, which points to the verbaliser (synonym or
  `Pred_k` names).

**Repaired protocol, judged by gemini on the screen** (`analysis.json → screen_repair`; $0.54):

| | C1 (1 vote, binary) | C2 (majority) | **C3 (frozen)** | iter-1 TVJT (C0) | iter-1 B1 |
|---|---|---|---|---|---|
| AUROC_real (L_bij, 833 items) | .698 | .684 | **.735 [.686, .778]** | .701 | .666 |
| paired G2 FA, non-RENAME (n=225) | .000 | .000 | **.000** | .102* | — |
| paired G2 FA, RENAME (n=274) | .376 | .369 | .387 | .372* | — |
| paired G2 FA, all | .206 | .202 | .212 | .251* | — |

\*iter-1 values: `canon_diagnostic.json → D2`.

- C3 − C0 = +.033 [−.005, +.068]; C3 − B1 = +.069 [+.014, +.130].
- Test-retest on 141 items (351 worlds): world-verdict κ **.94**; C1 ICC(2,1) **.96**. Malformed JSON 0.1%.
- **Freeze rule, applied ex post** (the judge was unavailable before the freeze, see "Deviations"):
  - No configuration passes G2 ≤ .10 overall. All three pass on non-RENAME rewrites, which triggers the plan's
    `G2_all_failed_by_RENAME` branch.
  - That branch picks by AUROC, and it picks **C3 — the configuration that was frozen by default.** So the frozen
    choice agrees with the rule.

## Phase 2 — held-out confirmation (label-blind scoring; labels only through the guarded loader)

Items:
- **P** = 609 panel3 items with post-stratified weights. 389 are in the top tercile, which is ≥150, so the
  pre-registered H1 runs on P-top.
- **T** = all 2,826 top-tercile rows.
- **Ccon** = 936 entity-renamed contamination rows plus their originals.

Every metric is scored on identical items. Unparseable candidates keep score .5 and stay in every AUROC.

### Weighted AUROC on P (`analysis.json → P_main`)

| metric | all P (609) | bottom (105) | middle (115) | **top (389)** | within-sentence acc |
|---|---|---|---|---|---|
| **TVJT\*** (repaired, C3, 3 votes) | .665 [.607, .718] | .655 | .657 | **.674 [.597, .744]** | .475 |
| TVJT vote-0 binary (1 call) | .669 | .655 | .678 | .653 | .504 |
| TVJT iter-1 (unrepaired, 1 vote) | .685 | .675 | .690 | .671 | .537 |
| TVJT\* judged by flash-lite | .565 | .525 | .604 | .533 | .484 |
| **B1** (exact iter-1 judge) | .749 [.702, .795] | .780 | .654 | **.772 [.711, .824]** | .758 |
| **B1x3** (compute-matched) | .774 [.728, .817] | .808 | .684 | **.794** | .783 |
| LC_onecoin (zero-LLM) | .756 [.701, .809] | .758 | .810 | .710 | .668 |
| LC_maj (zero-LLM) | .772 | .783 | .811 | .739 | .648 |
| A3 signature (zero-LLM) | .640 [.585, .691] | .638 | .694 | .585 | .615 |
| parse_ok | .500 | — | — | — | — (constant on P: the panel adjudicated parseable items only) |

The same ordering holds on the jointly covered subset (582 items) and after excluding gemini-generated candidates
(the judge is also a generator). There, TVJT\* scores .655 and B1 .752.

### Pre-registered tests and decision table (`results/verdict.json`)

- **H1** (P-top): Δ(TVJT\* − B1) = **−.098 [−.184, −.014]**. The upper bound is below 0, so the label is
  **REVERSED**.
- **H2** growth, Δ_top − Δ_bottom = +.028 [−.126, +.186], not significant. Δ by n_conditions bin is −.003, −.157
  and −.060, which is not monotone.
- **H2b** weighted-GLM interaction slopes: TVJT\* +.104 [−.150, +.348]; B1 −.166 [−.442, +.177]. Joint contrast
  β(TVJT:c) − β(B1:c) = +.375 [−.081, +.803], n.s. The slopes lean in the predicted direction, but TVJT\* is below
  B1 at every level.
- **JUDGE_MATCHED** = false: TVJT\* − B1x3 on top = −.120 [−.208, −.035].
- **Repair ablation**: TVJT\* − TVJT_iter1 = −.020 [−.066, +.023] on all P and +.004 on top. The repair removed the
  false alarms without adding discrimination on held-out.
- **STACK_INCREMENT** = false. S2 − S0z = −.002 [−.008, +.003]; S1 − S0 (TVJT\* on top of B1 + parse) = +.011
  [−.017, +.039]. The placebo passes (−.003 [−.028, +.023]). The zero-LLM stack S0z (B1 + parse + LC + A3) =
  .802 against S0 = .741, a gain of +.061 [+.013, +.106]: LC and A3 add to the judge, TVJT does not.
- **REPAIR_OK** = false, through RENAME only:
  - screen: paired FA .212 overall = .000 non-RENAME + .387 RENAME;
  - held-out judged replication (99 golds → 183 scored rewrites, $0.12): .077 overall = 0.000 on REORDER,
    CONTRAPOSITIVE, DEMORGAN and PRENEX + .264 on RENAME (n=53).
- **Error types** (P, detection = P(error item scores below a same-sentence faithful candidate)):
  - TVJT\* is below B1 on every well-populated type: ∀/∃ .551 vs .795; added condition .600 vs .686;
    implication direction .577 vs .695; negation .663 vs .868.
  - On the blind-spot head-to-head (scope ∪ cardinality, n=17; Wilson CIs are wide), TVJT\* .743 beats A3 .614
    but not B1 .812 or LC .806.
  - TVJT's error-type *naming* is below the majority-class baseline: accuracy .077 vs .273, macro-F1 .079,
    n=271.
- **T** (2,826 top-tercile rows):
  - Soft-label AUROC: TVJT\* .609 [.590, .626] ≈ B1 .608 [.593, .624]; LC .646. Multiple imputation gives the same.
  - Hard solver labels (biased toward gold vocabulary): TVJT\* .679 vs B1 .718.
- **Contamination** (entity-renamed paraphrases, 936 pairs):
  - AUROC shift: TVJT\* +.002 [−.040, +.040]; B1 +.009 [−.038, +.055]. Neither metric is contamination-sensitive.
  - Mean score shift: A3 −.144 (its lexical aligner is name-sensitive); LC ≈ 0.
- **System level**: Kendall τ (9 systems; |τ| ≥ .61 needed for p < .05), descriptive only. The table is in
  `analysis.json → system_level`.
- **Cost**: TVJT\* costs $0.00066 per item (3 votes; median 2.9 s) and B1 $0.000028 (0.6 s): TVJT\* is **24×
  more expensive and less accurate** (`figures/fig5_cost_accuracy`). Total OpenRouter spend for this artifact
  is **$4.10** (`results/cost_ledger.jsonl`), within the plan's ≤$10 budget.

### Reading

On the screen, the repaired protocol does what it was built for:
- it is deterministic (κ .94);
- it is invariant to every non-lexical meaning-preserving rewrite (FA 0);
- it scores slightly higher than iter-1 on the screen (C3 .735 against the unrepaired .701).

On held-out data from 9 modern systems over FOLIO-train, MALLS and ProverQA, however, the fixed-prompt judge is
**strong in the top tercile**: .772 here, against .552 on the iter-1 screen. So the iter-1 crossover, where B1 fell
with complexity, looks like a property of the old Logic-LM FOLIO-dev screen and its L_bij labels, not of long
sentences.

TVJT's world-truth signal is also nearly useless *within* a sentence: pairwise accuracy .475, while B1 reaches .758.
Its discrimination mostly separates sentences, not candidates.

## How to run

```bash
python method.py --stage setup          # .venv (uv, Python 3.12) + WordNet/OMW into nltk_data/
python method.py --stage all            # canon_diag → targets → worlds → zero_llm → freeze → analysis → export
# gemini-judged stages (need OPENROUTER_API_KEY; cached + ledgered, hard cap $9.50):
cd src && ../.venv/bin/python stage_screen_judge.py                              # Phase-1 screen C1/C2/C3 + retest
../.venv/bin/python stage_judge.py gemini --sets P --votes 3 --b1x3             # TVJT*, B1, B1x3 on panel
../.venv/bin/python stage_judge.py gemini --sets P,Ccon,T --votes 3             # + contamination + top tercile
../.venv/bin/python stage_judge.py gemini --lite --sets P --votes 3             # flash-lite TVJT variant
../.venv/bin/python stage_iter1.py P                                            # unrepaired iter-1 TVJT ablation
../.venv/bin/python stage_heldout_g2_judge.py                                   # judged held-out G2 replication
cd .. && python method.py --stage analysis && python method.py --stage export
.venv/bin/python -m pytest -q -c pytest.ini tests/test_core.py                  # 11 unit tests
```
With the committed `cache/` every LLM call above is a cache hit ($0).

## Layout

- `method.py` — stage orchestrator; `src/` — all code (canon, worlds, judge, bridge, stages, analysis2, figures, export,
  metrics_api2); `tests/` — unit tests; `audit/rederive.py` — independent re-derivation.
- `third_party/` — read-only copies of iter-1 Arm B (TVJT code + screen data), Arm A (A3), the dataset parser.
- `data/`, `results/`, `cache/`, `figures/` — see "Files" below; `logs/` — run logs.
- `method_out.json`, `full_/mini_/preview_method_out.json` — exp_gen_sol_out output.

## Restoring removed files

Deleted before upload (see `.aii/manifest.yaml`):

| path | restore with |
|---|---|
| `.venv/` | `python method.py --stage setup` (uv venv .venv --python 3.12; uv pip install -r pyproject.toml; torch CPU + sentence-transformers) |
| `nltk_data/` | `.venv/bin/python -c "import nltk; [nltk.download(p, download_dir='nltk_data') for p in ('wordnet','omw-1.4')]"` then `cd nltk_data/corpora && unzip -o wordnet.zip && unzip -o omw-1.4.zip` |
| `.pytest_cache/` | regenerated by `.venv/bin/python -m pytest -q -c pytest.ini tests/test_core.py` |
| `**/__pycache__/` | regenerated automatically by Python on import |

## Figures (`figures/`, PDF + PNG, drawn only from results JSON)

1. `fig1_auroc_by_complexity` — AUROC_w by tercile and n_conditions for TVJT\*, TVJT iter-1, B1, B1x3, LC and A3.
2. `fig2_delta_forest` — ΔAUROC(TVJT\* − B1 / B1x3) overall and per bin.
3. `fig3_rewrite_invariance` — world-set identity and paired FA per rewrite kind, iter-1 vs repaired.
4. `fig4_error_type_detection` — detection by real L3 error type (Wilson CIs).
5. `fig5_cost_accuracy` — $/item vs AUROC_w.

## Bug found and fixed (documented in `results/freeze_amendment.json`)

iter-1 `tvjt.find_world` tags every z3 Grounder with a global counter (`g0, g1, …`), and z3's main context carries
solver state across calls. Together these make the choice among *equally minimal* worlds depend on call history:
the same formula could get different worlds. Unit test T0(f) caught it.

`canon.find_world` fixes it with a fixed tag and a fresh z3 context per call. The fix changed 57 of 1,039 screen
world sets and raised RENAME identity from .971 to .996 (screen) and from .817 to .983 (held-out). The iter-1 worlds
were affected by the same non-determinism.

A second bug was fixed before the final numbers: an alias record could shadow a world record in the cache loader.
It affected 9 held-out items (5 TVJT\*, 4 lite), which were re-scored at $0.

## Deviations from the plan (all logged)

1. **The judge was unavailable at freeze time.** The shared OpenRouter key was at its $50 daily limit (HTTP 403)
   from 14:03 to 15:08 UTC. Per F4, the freeze (14:41) used the pre-declared default C3, not the screen freeze
   rule. The key was replaced at about 15:08.
   - All gemini scoring ran **after** the freeze with the frozen C3 protocol: screen Phase-1 numbers, then held-out.
   - The ex-post freeze rule picks the same C3.
   - Held-out labels had been loaded at 14:4x for zero-LLM analyses only. No TVJT/B1 held-out score existed then.
2. **Label marginals seen during setup.** During setup, the aggregate panel label marginals (307/302) and the
   error-type counts were printed once while counting item sets. No per-item label was used before the freeze.
3. **A local-judge variant was tried and dropped** while OpenRouter was down. Qwen2.5-1.5B/3B via llama.cpp reached
   chance-level world agreement (.54/.44) on 8 panel items, so no local results are reported. The cached files are
   excluded from upload.
4. **World-generator determinism fix after the freeze.** This is the label-independent bug fix above; the frozen
   prompt, scoring, votes and model are unchanged.
5. **Cuts made under the plan's F3 order to save the shared key.** B1x3 runs on P only. TVJT_iter1 and
   TVJT_lite run on P only. The contamination fold covers all 9 systems.
6. **Pairwise mutant dedup uses the canonical mutant string**, not pairwise bounded-equivalence. Worlds are
   deduplicated by isomorphism, which covers the plan's intent at a fraction of the z3 cost.
7. **Stacking uses B1 in S0**, as planned. With no judge, parse_ok alone is constant on P, so an extra
   `S0z − LC_raw` row is also reported.
8. **The prompt's "pilot study in the zip" was not available to this session.** The prompt arrived truncated, and
   this artifact was reconstructed from `gen_plan_experiment_2`.

## Files

- `method.py`, `src/`, `tests/test_core.py` (11 unit tests pass), `audit/rederive.py`.
- `results/`: `frozen_config.json`, `prereg.json`, `freeze_receipt.json`, `freeze_amendment.json`,
  `analysis.json`, `verdict.json`, `heldout_llm_scores.jsonl`, `screen_repair_scores.jsonl`,
  `heldout_g2_judged.jsonl`, `zero_llm_scores.jsonl`, `a3_scores.jsonl`, `canon_diagnostic.json` (and the `_v1`
  pre-fix copy), `screen_replay.json`, `heldout_g2_canon.json`, `lc_info.json`, `bridge_coverage.json`,
  `audit_rederive.json` and `cost_ledger.jsonl`.
- `data/`:
  - `worlds_canon.jsonl`: deterministic canonical worlds with verbalisations;
  - `worlds_canon_v1_nondeterministic.jsonl`: the pre-fix worlds;
  - `worlds_iter1_heldout.jsonl`;
  - `heldout_targets.jsonl`: label-blind;
  - `lc_pairs.jsonl`;
  - `heldout_g2_items.jsonl`.
- `cache/`: the paid gemini answers (world-level and call-level) and the copied iter-1 cache. Keep these: they
  cannot be reproduced for free.
- `method_out.json` / `full_`/`mini_`/`preview_method_out.json` (exp_gen_sol_out; validated). It has 5 datasets
  (screen_real 833, screen_rewrites 499, heldout_panel 609, heldout_top 2826, contamination 936) with `predict_*`
  per metric.
- Regenerable, excluded from upload: `.venv` (`python method.py --stage setup`), `nltk_data`, `__pycache__`.
