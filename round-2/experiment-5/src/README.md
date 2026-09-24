# Directional consensus on long legal definitions (secondary transfer test, panel-only labels)

This is the run's first **labelled** exception-heavy NL→FOL set. It tests whether **directional consensus (DC)** transfers to long, condition-heavy legal sentences. DC is a gold-free, text-blind metric: the solver-checked share of other systems' formalizations that are logically equivalent to a candidate under name-blind vocabulary alignment. DC is compared with every field-standard baseline on the same items.

**Label source for every number: the 3-member family-disjoint panel, judging from the sentence only (no gold).** These are secondary transfer results.
Workspace: `.`

## What was done
1. **Sentences (S1).** 158 sentences:
   - the 68 AI-Act Art. 3 definitions, from the user's pilot upload;
   - 59 public statutory items: GDPR Art. 4, DSA Art. 3, DMA Art. 2, Data Act Art. 2 (EUR-Lex), and 19 clauses from SARA/US-IRC;
   - 31 AI-Act non-Art.-3 sentences, used as the pre-declared F1 top-up where a marker bin ran out.

   Marker bins are B0 91, B1 51, B2 16. Items with ≥4 markers (B2) are rare in statutory text across all sources.
2. **Candidates (S2).** The 9 OpenRouter systems were run with the frozen round-1 prompt (sha1 `afabb41e…`) and extractor v2. The only change is max_tokens raised to 1024 (D4). Greedy parse rate is 73.3%; 0.6% of outputs were truncated. There are also 2×5 T=0.8 samples, and the user's 367 pilot formulas as the `pilot` family.
3. **DC (S3, `dc/`).** Contract v1 with its defaults: L1 bijections, then L2 partial maps, then L3 positive granularity definitions. Relations are decided by a numpy refutation filter, then z3 bounded and unbounded checks. The code covers 5,949 pairs in 14 minutes on 6 CPUs. The **freeze** (`results/dc_config.json`, `results/dc_scores_frozen.jsonl`) was written at 04:42:48, before the first panel label was read (asserted in `src/analysis.py`).
4. **Baselines (S4):**
   - B1 cheap judge: the exact frozen prompt, run on all 1,789 candidates;
   - B1plus: gemini-2.5-pro;
   - B3 round trip;
   - B2 parse;
   - B7: the user's structural metrics;
   - VC: vocabulary conformity, name-based on purpose;
   - LC_maj and DS_bin: round-2 definitions via vendor L1;
   - B8 self-consistency, DC_lone, and DC+arb;
   - variants DC_noL3 and DC_fp.
5. **Labels (S5).** The panel is claude-haiku-4.5, grok-4.3 and glm-4.6. The calibration gate was passed (0.875 / 0.950 / 0.850). An adjudication sample of 480 system items and 200 pilot items was drawn with a seed before any label existed. Weights are post-stratified.
6. **Analysis (S6).** Pre-registered tests X1–X5, with 2,000 sentence-clustered bootstrap draws and vendor `stats.py`. It also covers coverage, system level, error distribution, the shared-bias boundary, label robustness, invariance, a placebo, the dev anchor, cross-implementation agreement and cost.

## Headline results (`results/tests.json`, `results/analysis.json`)
The table gives weighted AUROC against the panel-majority label on 655 labelled items. 67 are faithful (weighted 9.4%, below 12%, so F7 applies: imbalanced).

| metric | AUROC [95% CI] | | metric | AUROC [95% CI] |
|---|---|---|---|---|
| **DC** | **0.705 [0.608, 0.792]** | | B1 cheap judge | **0.927 [0.900, 0.949]** |
| DC_fp | 0.712 [0.615, 0.799] | | B1plus gemini-2.5-pro | 0.852 [0.786, 0.904] |
| DC_noL3 | 0.672 [0.574, 0.763] | | B3 NLI (local back-translation) | 0.694 [0.601, 0.773] |
| LC_maj | 0.754 [0.670, 0.828] | | B3 cosine | 0.691 [0.620, 0.762] |
| DS_bin | 0.729 [0.630, 0.824] (n=464) | | VC vocabulary control | 0.685 [0.599, 0.766] |
| DC+arb (local judge) | 0.610 [0.530, 0.690] | | B7 structural | 0.597 [0.540, 0.650] |
| DC_lone | 0.742 [0.615, 0.866] (n=315) | | B2 parse | 0.569 [0.515, 0.615] |
| B8 self-consistency | 0.821 [0.676, 0.942] (n=124) | | placebo (peers shuffled) | 0.506 [0.460, 0.554] |

The pre-registered tests:
- **X1 PASS.** DC = 0.705, with one-sided 95% lower bound 0.62 > 0.5.
- **X2 PASS (marginal).** Adding DC to [B1, parse] raises cross-fitted AUROC by ΔAUROC = +0.021 [−0.001, +0.046], one-sided bound +0.002. On covered items only it is +0.034 [0.007, 0.067]. Over the full base [B1, parse, B3nli, B3cos, B7] it is +0.008 [−0.012, 0.028], so **no increment over the full base**. The random-feature placebo gives Δ ≈ 0.003, with a CI containing 0.
- **Comparison with the cheap judge.** B1 dominates everything here. The frontier judge (pro) is *worse* than B1 against these panel labels (−0.075 [−0.134, −0.026]); stacking [B1, parse, DC] beats pro by +0.075.
- **DC vs LC_maj.** DC is not better: −0.049 [−0.113, 0.016]. On parseable items only, DC is 0.796 vs LC_maj 0.786 (+0.010 [−0.022, 0.049]). Part of the gap is the contract's 0.5 score for unparseable candidates; LC_maj and DS_bin score them 0. The post-hoc variant DC_unparse0 reaches 0.764 (`analysis.json: posthoc_DC_unparse0`, not pre-registered).
- **X3, complexity.** DC trails B1 in every marker bin:

  | bin | DC − B1 gap [95% CI] |
  |---|---|
  | B0 | −0.197 [−0.299, −0.108] |
  | B1 | −0.365 [−0.583, −0.084] |
  | B2 | −0.224 [−0.655, −0.105] |

  The B1 and B2 bins are underpowered (6 and 5 positives). The within-sentence gap slope on marker count is −0.046 [−0.133, 0.113], so the prediction slope ≥ 0 is not supported (inconclusive). Coverage falls with markers: B0 77%, B1 70%, B2 52% (mostly parse failures).
- **X4, error types.** Within-sentence detection is underpowered: at most 44 pairs per type. For exception-involved errors, DC orders 0.878 of pairs correctly vs B1 0.716 (37 pairs). DC's error naming fails: weighted top-1 is 0.044 vs 0.219 for the majority class, and most errors come out as "other".
- **X5, lone output.** DC_lone 0.828 vs B8 0.821 on gpt-4.1-mini and llama (Δ +0.006 [−0.041, 0.075]). On pilot rows, DC_lone 0.633 vs the user's metric5 Jaccard 0.436.
- **Shared-bias boundary.** When the modal cluster is panel-faithful, DC reaches 0.889. When it is unfaithful (76% of labelled sentences), DC falls to 0.624 while B1 stays at 0.946. This is the predicted failure mode of consensus.
- **DS weights degenerate.** All sensitivities are below 0.5, so all weights sit at the 0.05 floor and DC is effectively unweighted. EQUIV agreement is rare on long text: 6% of pairs, versus 19% on the short dev anchor.
- **Sanity checks.**
  - Dev anchor (700 short sentences, 609 round-1 panel items): DC 0.774 [0.721, 0.824], within ±0.05 of DS 0.787 / LC 0.756.
  - Invariance false-alarm rates: rename 0%, reorder 1%, contrapositive 2%.
  - Cross-implementation agreement with the sibling `dc/` (this run's exp_3): 80% exact relation agreement on dev pairs and 97% on EQUIV-vs-not. On legal pairs it is 67% exact and 99% on EQUIV-vs-not.
  - T5 re-derivation with sklearn matches to 1e-15.
- **Panel quality caveats.** Fleiss κ = 0.38 (lower than on public corpora). Label robustness per member: DC ranges from 0.587 (M2 only) to 0.814 (M3 only), and is 0.866 on unanimous items only. The **long-text exception-sensitivity check could not be run** (budget; see below), so the panel's ability to see exception errors is uncertified.
- **Legal error mix.** The mix differs from public corpora (TVD 0.35 [0.32, 0.39]). implication_direction_or_only accounts for 17.6%, largely "X means Y" formalised with → instead of ↔. 24% of unfaithful items are exception-involved.
- **Cost.** DC needs $0 per item when peers exist and 1.3 CPU-s per item. B1 costs $0.00006 per item, pro $0.0011 per item, and the panel $0.0051 per item. The total API spend of this artifact is $4.65.

## Deviations (full list: `results/deviations.json`)
**D-BUDGET.** The run-level OpenRouter budget, shared by all sibling experiments, was exhausted at 04:22 UTC (HTTP 403 `aii_run_budget_exhausted`). As a result:
- 25 of the 680 sampled items are unlabelled, and 10 have only 2 votes;
- B3 back-translations were produced by local **Qwen3-8B** as a substitute (40 of 680 flash calls had completed);
- DC+arb verdicts also come from local Qwen3-8B;
- the exception-sensitivity check, the F7 minority top-up and the sonnet 4th voter were not run.

Other deviations:
- **D-L3.** L3 was restricted to positive literals before any label was read.
- **D-WEIGHTS.** The DS weights degenerate (see above).
- **D-SET.** B2 is scarce (16 sentences), and the AI Act has 68 Art. 3 definitions, not 63.
- **D-KILL.** One sentence hit the per-sentence watchdog; 71 of its pairs are UNKNOWN.
- **D-SAMPLE.** The adjudication sample was redrawn once before any label existed, to meet the minimum of 60 items for llama.

Unit tests (`results/unit_tests.json`): 16/20 pass. The 4 failures are documented identifiability limits: positive granularity vs a dropped conjunct, CONTRADICTORY being outranked, and one implication-swap case typed "other".

## Layout
| path | content |
|---|---|
| `method.py` | Entry point: re-exports the reusable API (`align_pair`, `pair_relation`, `directional_consensus`, `ds_weights`, `error_type`); `--demo` runs a toy example; `--stages all` runs the pipeline |
| `dc/` | The DC package, contract v1: `core.py` (alignment and relations), `api.py` (scores, error types, weights), `worker.py`, and `README.md` (one-line MEASURES per function) |
| `src/` | Pipeline stages: build_sentences, generate_long, panel_nogold, run_dc, dc_score, baselines, local_judge, extra_dc, dev_anchor, crossimpl, analysis, export, deviations, alignment_audit; `llm.py` is the capped client; `stats_ext.py` is a byte-identical copy of the vendor stats |
| `vendor/` | Read-only copies of round-1/round-2 code; sha1s in `results/frozen_manifest.json` |
| `prompts/adjudication_nogold.txt` | Panel prompt |
| `work/sentences.json` | The 158 sentences with provenance, licence and marker features |
| `work/candidates.jsonl`, `work/generations.jsonl` | All 3,369 candidates plus raw outputs (irreproducible API output) |
| `work/panel_votes.jsonl`, `work/panel_sample.json` | Every panel vote; the pre-drawn sample |
| `work/llm_cache.jsonl`, `work/cost_ledger.jsonl` | LLM response cache; per-call spend |
| `work/dc_pairs/`, `work/dc_tasks/` | Every DC pair relation with its map and definitions (legal, legal_fp, dev, invariance, placebo) |
| `results/tests.json` | X1–X5 with point estimates, CIs, n, pass/fail and label source |
| `results/analysis.json` | All secondary analyses |
| `results/exception_set.jsonl` | The labelled meta-evaluation set: one row per sampled candidate, with provenance, licence, complexity, parse status, all member votes, label, weight and stratum |
| `results/scores.jsonl` | Every candidate × every metric, with missing-value reasons |
| `results/dc_scores_frozen.jsonl`, `results/dc_config.json` | Frozen DC scores and configuration (code sha1, limits, DS weights) |
| `results/unit_tests.json`, `results/audit_rederive.json`, `results/cross_impl.json`, `results/invariance.json`, `results/dev_anchor.json` | Checks |
| `method_out.json` (+ `full_`/`mini_`/`preview_`) | exp_gen_sol_out: `legal_panel_labelled` (655) and `legal_all_candidates` (1,789) |
| `logs/alignment_audit.txt` | Sample of L2/L3 EQUIV verdicts with their maps |

## How to run
```bash
bash restore.sh                       # venv + raw sources
.venv/bin/python method.py --demo     # toy example, no API
.venv/bin/python method.py --stages all   # full pipeline; LLM calls are cached, so a re-run costs $0
```

## Restoring removed files
| deleted path | restore |
|---|---|
| `.venv/` | `uv venv .venv --python=3.12 && uv pip install --python .venv/bin/python z3-solver numpy scipy scikit-learn pandas aiohttp loguru tenacity beautifulsoup4 lxml requests torch transformers sentence-transformers safetensors huggingface_hub psutil pyyaml sentencepiece protobuf tiktoken` |
| `raw/pilot/` | `unzip -q -o /ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/user_uploads/dpv_pilot_study.zip -d raw/pilot/` |
| `**/__pycache__/` | Regenerated automatically by Python |
| HF models (shared cache, not in this dir) | `huggingface-cli download Qwen/Qwen3-8B`; `MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli`; `sentence-transformers/all-MiniLM-L6-v2` |

`restore.sh` does all of the above.
