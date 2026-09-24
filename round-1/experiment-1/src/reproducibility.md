# Reproducibility: Arm A of the iter-1 NL→FOL faithfulness screen

This file was written after the fact from the workspace files (README.md, method.py, the stage scripts, pyproject.toml, requirements.txt, logs/, results/). Nothing was re-run. Anything the workspace does not record is marked **not recorded**.

## 1. Copy the artifact

```bash
cp -r /ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_experiment_1 ~/arm_a
cd ~/arm_a
```

All commands below run from this folder. The folder already holds the frozen inputs (`data/raw/`, `data/screen_set.json`) and all LLM responses (`results/llm_cache/`), so a rerun can cost $0.

## 2. System, Python, environment

- Ubuntu Linux (kernel 6.17 on the authoring machine). No system packages beyond a standard toolchain are named in the workspace. `uv` is used for the venv.
- Python 3.12 (`requires-python >= 3.12`). The `.venv` path in `logs/b3.out` shows `python3.12`.
- Hardware was **not recorded**: no GPU type, VRAM or RAM is logged. The machine had 2 CPU cores (`nproc`, checked while writing this file, so it may not match the original run). `requirements.txt` includes CUDA-13 torch wheels. `run_baselines.py` picks DeBERTa-v3-large-mnli-fever-anli-ling-wanli if CUDA is available and DeBERTa-v3-base-mnli-fever-anli otherwise. `logs/b3.out` shows a large-sized load (394 weight tensors), so a CUDA device was probably present. That is an inference, not a record.
- Runtimes recorded in logs:
  - build_screen_set: about 1.5 min (12:20:50 to 12:22:04 timestamps).
  - run_sigs: 19 s for 2,645 formulas.
  - probe: about 5 min.
  - B1: 62 s. B1 on mutants: 58 s.
  - B3: about 2.5 min.
  - B4 real+gold: about 9 min. B4 mutants+rewrites: about 4 min.
  - analyze: about 4 min (bootstrap).
  - Total wall clock of the original session: not recorded.

```bash
uv venv .venv --python=3.12
uv pip install --python .venv/bin/python -r requirements.txt     # exact pins, identical to pyproject.toml
# en_core_web_sm 3.8.0 is already in the pins; only needed for an unpinned install:
uv pip install --python .venv/bin/python "en_core_web_sm @ https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"
export NLTK_DATA=$PWD/.nltk_data
.venv/bin/python -c "import nltk; nltk.download('wordnet', download_dir='$NLTK_DATA'); nltk.download('omw-1.4', download_dir='$NLTK_DATA')"
```

Key pins (full list in `requirements.txt` / `logs/pip_freeze.txt`): z3-solver==5.1.0.0, spacy==3.8.16, en-core-web-sm 3.8.0, nltk==3.10.3, numpy==2.5.3, scipy==1.18.1, pandas==3.0.6, scikit-learn==1.9.1, torch==2.14.0, transformers==5.17.0, sentence-transformers==6.1.0, matplotlib==3.11.2, aiohttp==3.14.3, loguru==0.7.3, stanza==1.14.0, udapi==0.5.2.

## 3. Data, models, keys

- Public inputs are already in `data/raw/`. Sources named in the README and `build_screen_set.py`:
  - the Logic-LM raw GitHub outputs `FOLIO_dev_{gpt-3.5-turbo,gpt-4,text-davinci-003}.json`;
  - FOLIO v0.0 `data/v0.0/folio-validation.jsonl`;
  - the curated gold `https://huggingface.co/datasets/DSAVlab-UNIUD/FOLIO_validation-curated/resolve/main/FOLIO_instances.jsonl` (files `dsav_*`);
  - `MED.tsv` and `HELP_pmb_train_v1.0.tsv` (from `verypluming/{MED,HELP}`);
  - `yfxiao_validation.csv` (refined FOLIO).
  - The exact download commands and URLs for the Logic-LM, MED, HELP and yfxiao files are **not recorded** beyond these names; the files themselves are kept.
- HF models, downloaded on first use of B3: `sentence-transformers/all-MiniLM-L6-v2` and `MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli` (base variant on CPU). Their revisions are **not recorded**.
- Environment variable: `OPENROUTER_API_KEY` (name only). It is needed only for LLM calls that are not in `results/llm_cache/`. `src/llm.py` has a hard budget cap `CAP_USD = 5.80` and a persistent ledger (`results/cost_ledger.jsonl`, 5,504 lines).
- LLM models: `google/gemini-2.5-flash` for the probe (thinking `max_tokens` 1024, per `results/probe_config.json`), for B1 (thinking off) and for B4. The pre-registered fallback to `openai/gpt-4.1-mini` was piloted and rejected (downward accuracy 0.32 vs 0.64). Temperature defaults to 0.0 in `src/llm.py`. Model version snapshots are **not recorded**, and hosted LLM responses may differ on a fresh call.

## 4. Commands, in order

Unit tests and a zero-LLM demo:

```bash
.venv/bin/python tests/test_units.py
.venv/bin/python method.py --demo
```

Full pipeline. This runs the stages of `method.py` (`STAGES`) in order, each as a subprocess:

```bash
.venv/bin/python method.py --stages all
```

The stages, with the exact arguments in `method.py`:

```bash
.venv/bin/python build_screen_set.py --n_sent 300
.venv/bin/python run_sigs.py
.venv/bin/python run_text.py --stage pilot
.venv/bin/python run_text.py --stage probe
.venv/bin/python run_text.py --stage b6
.venv/bin/python run_baselines.py --stage b1 --sets real,gold,rewrite
.venv/bin/python run_baselines.py --stage b1_mutants
.venv/bin/python run_baselines.py --stage b3
.venv/bin/python run_baselines.py --stage b4 --sets real,gold
.venv/bin/python run_baselines.py --stage b4 --sets mutant,rewrite --n_mut_per_op 20 --n_rew 120
.venv/bin/python run_selfcons.py
.venv/bin/python run_metrics.py
.venv/bin/python analyze.py
.venv/bin/python audit_rederive.py      # independent check, not part of --stages
```

A subset can be run with `--stages build_screen_set,run_sigs,...` (names: build_screen_set, run_sigs, text_pilot, text_probe, b6, b1, b1_mutants, b3, b4_real_gold, b4_mut_rew, selfcons, metrics, analyze). The B1+ tuned judge (`--stage b1plus`) was skipped for budget.

Seeds and configs found in the code:
- Screen sentences: the first 300 matched sentences in sha1 order. The per-sentence seed for labels, mutants and rewrites is `int(sha1[:8], 16)`. Rewrite and mutation RNGs are `random.Random(f"{seed}:{op}")`.
- `run_text.py` uses `random.Random(0)` (line 80) and `random.Random(1)` (line 128). `run_baselines.py` uses `random.Random(0)` (line 204). B6 sampling seed is 0.
- `analyze.py` bootstrap: 1000 sentence-clustered draws, `np.random.default_rng(0)`. The G3 folds use `default_rng(100 + r)`.
- `audit_rederive.py`: 500 bootstrap draws, seed 12345; placebo RNG `default_rng(7)`.
- Solver settings: monotonicity signatures use domain sizes 1..3 (`signature(..., N=3, timeout_ms=5000)`). Equivalence labels are bounded (1..4) and unbounded z3, which agree on 389/389.
- The metric hyper-parameters (thresholds, weights) are in `src/score.py`. They were not restated here.

## 5. Expected outputs and numbers

Primary outputs:
- `data/screen_set.json` (the meta-evaluation set), `data/screen_set_ids.txt`
- `results/method_out.json` (also `method_out.json`)
- `results/summary.json`, `results/screen_scores.jsonl`, `results/audit_rederive.json`
- `figures/roc_real`, `figures/delta_vs_b1_tercile`, `figures/mutant_detection_heatmap` (png and pdf)

Numbers that a rerun should reproduce (from `logs/analyze.out`, `logs/build_full.out`, `README.md`, `results/audit_rederive.json`):

| item | value |
|---|---|
| screen set | 300 sentences; 835 real candidates (gpt-3.5-turbo 265, gpt-4 298, text-davinci-003 272) |
| labels | 389 equivalent, 446 not; 811 parse; 1,375 mutants; 412 rewrites |
| AUROC A1 / A2 / A3 | 0.711 [0.663, 0.756] / 0.711 / 0.718 [0.673, 0.763] |
| AUROC B1 / B3nli / B4 / B5 | 0.644 / 0.660 / 0.715 / 0.741 |
| AUROC A0 / Ccov / B7 / B8 | 0.674 / 0.661 / 0.537 / 0.608 |
| G3 over judge+parse | A1 +0.084 [0.037, 0.138]; A3 +0.093 [0.048, 0.143] |
| G2 false alarms | A1 0.131; A3 0.143; B1 0.308 |
| top-tercile AUROC | A1 0.507; B1 0.533 |
| verdict | `advance_without_survivor`, A3 advances |
| spend | $5.67 |

The audit gives A1 0.7113, A3 0.7182 and G3 A1 +0.078, A3 +0.090. The bootstrap and folds differ, so the point values differ slightly from `analyze.py`. Reruns with LLM calls served from `results/llm_cache/` should match. Fresh LLM calls may not, for the reasons in section 3. The LLM-based numbers (A1, A2, B1, B4, B6) depend on those cached responses.

Where the numbers appear in a paper: **not recorded**. The workspace has no paper text or section mapping. The headline table is in `README.md` and `results/summary.json`.
