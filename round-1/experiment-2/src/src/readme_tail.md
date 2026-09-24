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

- `/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_experiment_2/data/screen_set.json`, `/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_experiment_2/data/alt_candidates.jsonl`, `/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_experiment_2/data/worlds_cache.jsonl`,
  `/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_experiment_2/data/consequences_cache.jsonl`, `/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_experiment_2/data/blindspot_supplement.jsonl`
- `/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_experiment_2/results/screen_scores.jsonl`, `/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_experiment_2/results/cost_ledger.jsonl`, `/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_experiment_2/results/analysis.json`, `/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_experiment_2/results/verdict.json`
- `/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_experiment_2/cache/llm/` (paid LLM responses; excluded from the GitHub upload, kept on the volume)

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
