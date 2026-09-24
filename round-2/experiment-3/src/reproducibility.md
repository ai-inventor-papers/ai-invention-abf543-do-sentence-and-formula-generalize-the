# Reproducing this artifact: DC freeze-then-confirm, run_ujABDGgoK_5Q, iter 2, exp 3

These instructions describe what was **actually run** on 2026-09-24 between 03:52 and 05:15 UTC.

Two replay paths:
- **$0 path.** The per-request caches (`work/llm_cache/`, `work/generations/`, `work/local_llm/`) are shipped, so every paid step replays for free. `uv run method.py --stage all_offline` rebuilds every result from them.
- **From scratch.** Paid steps re-bill: about $2.4 at September 2026 OpenRouter prices. Temperature-0 answers are not bit-identical across providers.

## 1. Copy the artifact

```bash
cp -r . ~/dc_repro
cd ~/dc_repro
```

The dev data is a READ-ONLY dependency. The scripts read it at this absolute path:
`../../../round-1/dataset-1/src`
(dataset art_iyzYyaqlqpSX: `full_data_out/`, `work/{pool,heldout_sentences,screen_sentences,calibration_set}.json`).

Round-2 dev scores are read from:
`/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_2/gen_art/gen_art_experiment_3`
(`results/heldout_scores.jsonl`, `work/pairs_cache.jsonl`).

If you move machines, copy both directories to the same paths, or edit `DEP` and `R2` in `src/common.py`. The vendored code copies are already inside `vendor/`; their sha1s are in `results/vendor_manifest.json`.

## 2. System, Python and libraries

- **OS and hardware:** Debian 12 container (Ubuntu works the same). 14 vCPUs (cgroup quota), 56 GB RAM. One NVIDIA RTX 4090 (24 GB); the driver supports CUDA 12.8.
- **Packages:** `curl` and `unzip`, plus `uv` (0.8+). No other system packages.
- **Python:** 3.12, via `uv venv .venv --python 3.12`.
- **Libraries:** exact versions are in `requirements.lock.txt` (128 packages, from `uv pip freeze`; the venv has no pip) and are mirrored as `==` pins in `pyproject.toml`. Key pins:

  | package | version |
  |---|---|
  | z3-solver | 5.1.0.0 |
  | numpy | 2.5.3 |
  | scipy | 1.18.1 |
  | scikit-learn | 1.9.1 |
  | pandas | 3.0.6 |
  | loguru | 0.7.3 |
  | aiohttp | 3.14.3 |
  | nltk | 3.10.3 |
  | crowd-kit | 1.4.2 |
  | transformers | 5.17.0 |
  | sentence-transformers | 6.1.0 |
  | torch | 2.11.0+cu128 |
  | triton | 3.6.0 |

- **Setup:**
  ```bash
  bash restore.sh
  ```
  This creates `.venv` from `requirements.lock.txt` using the PyTorch cu128 index, downloads WordNet and omw-1.4 into `.nltk_data/`, and runs the 16 DC unit tests.
  - What was actually done: `.venv` was first built from the round-2 pins, which included torch 2.14.0 (CUDA 13). That build cannot see a 12.8 driver, so it was replaced with `uv pip install --reinstall-package torch torch --index-url https://download.pytorch.org/whl/cu128`, which resolved to 2.11.0+cu128. The lockfile records the final state.
- **Unit tests:** `.venv/bin/python -m pytest -q -c pytest.ini tests/test_dc.py` gives 16 passed. `cd vendor/ds && ../../.venv/bin/python -m pytest -q -c pytest.ini tests/test_fol.py` gives 29 passed.

## 3. Downloads, environment variables, keys

- Environment variables, **by name only:** `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL` (all LLM calls go through the run's OpenRouter proxy), and `HF_HOME` / `HF_HUB_CACHE` (the shared HF cache). `AII_COST_LEDGER` is optional; it mirrors ledger lines.
- HF models are downloaded on first use: `sentence-transformers/all-MiniLM-L6-v2`, `MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli`.
- `Qwen/Qwen3-8B` (revision `b968826d9c46dd6066d109eabc6255188de91218`, 16 GB) was read from a local snapshot. Its path is `SNAP` in `src/s09b_local.py`. Elsewhere, run `huggingface-cli download Qwen/Qwen3-8B --revision b968826d…` and point `SNAP` at the snapshot directory.

## 4. Commands, in the order actually run

All scripts run from `src/` with `../.venv/bin/python` (`method.py` wraps them). Seeds: fresh sampling 20260924; L0 full-panel subset 20260924; L3 sampler 0; L3 full subset 7; bootstraps 0; oof folds 100–104; invariance and perturbations 20260924.

| # | command | what / notes | wall time | $ |
|---|---|---|---|---|
| 1 | `s01_sample_fresh.py` | 450 fresh sentences; overlap with the exclusions asserted as 0 | 5 s | 0 |
| 2 | `s02_generate.py --limit 10`, then `s02_generate.py --cap 0.9 --concurrency 32` | 9 systems greedy + 2 × 5 samples; 8,550 outputs | 9 min | 0.4535 |
| 3 | `s03_dev_frame.py`; `pairs.py ../work/dev_pair_jobs.jsonl --workers 12`; `pairs.py ../work/dev_within_jobs.jsonl --workers 12` | Dev relation cache. It was computed twice: the first cache (`work/pair_cache_v0_asymmetric_share.jsonl`) predates the symmetric-share fix and is kept for audit | 2 min | 0 |
| 4 | `s04_freeze.py` | 12-config grid → `results/frozen_config.json` + `.sha256` at 04:14:11 UTC | 1 min | 0 |
| 5 | `s05_fresh.py frame` / `dcpairs` / `lcpairs` / `lc` / `b7` / `vc` | Fresh caches and the frozen neighbours. VC was re-run after WordNet was installed | 3 min | 0 |
| 6 | `s06_labels.py gate --cap 0.35` | Calibration gate: 0.90 / 0.90 / 0.85 | 1 min | 0.1502 |
| 7 | `s06_labels.py l0 --cap 0.9` | Gold audit (glm-first cascade) | 3 min | 0.8761 |
| 8 | `s09_llm_baselines.py b1 --cap 0.25` | B1 on 4,050 rows | 1 min | 0.0995 |
| 9 | `s06_labels.py l1 --workers 12` | Solver labels | 6 s | 0 |
| 10 | `s06_labels.py l3 --n 272 --n_unparse 12 --limit 20 --cap 0.2` (pilot), then the same without `--limit` and with `--cap 1.05` | Panel: 256 majorities | 2 min | 0.8056 |
| 11 | `s09_llm_baselines.py tj` / `b3` | **Failed**: the shared key was exhausted at 04:22 UTC. Outputs moved to `work/failed_api/` | – | 0 |
| 12 | `s09b_local.py` | Qwen3-8B B3L / TJ_L on the RTX 4090 (about 16.4 GB VRAM), DeBERTa NLI + MiniLM | 2 min | 0 |
| 13 | `s10_scores.py`; `s11_tests.py`; `s12_secondary.py`; `s12b_extra.py`; `s12c_perturb.py`; `report_tables.py`; `s13_export.py` | Scores, T1–T4, secondaries, export | 12 min | 0 |
| 14 | `cd .. && .venv/bin/python audit_rederive.py && .venv/bin/python rederive_headline.py` | Integrity and independent re-derivation | 5 min | 0 |
| 15 | `uv run method.py --stage all_offline` | Full $0 rerun from caches (ran 04:57–05:05 UTC) | 8 min | 0 |
| 16 | aii-json `aii_json_format_mini_preview.py --input method_out.json` + `aii_json_validate_schema.py --format exp_gen_sol_out` | Output variants and schema check | – | 0 |

The step-15 rerun reproduced `tests.json`, `analysis_extra.json` and `perturbation_sensitivity.json` byte for byte. `analysis.json` changed in one number: random-rename typing flips went from 1 to 2 of 399, because typing searches under wall-clock limits.

The total spend, $2.3848, is the sum of `cost_ledger.jsonl`. The $7.00 OpenRouter key was shared with two sibling experiments; see `results/deviations.json`.

## 5. What you should get

| number | value | file |
|---|---|---|
| Frozen config | L3off_UAin_DS_caps1, rule_1b off; dc/ sha256 `7f805769…df965` | `results/frozen_config.json`, `results/integrity.json` |
| Dev AUROC of the frozen config (panel / solver) | 0.777 / 0.855 | frozen_config grid |
| Fresh DC AUROC, panel (n=256, raked weights) | 0.827 [0.770, 0.877] | `results/tests.json` `auroc["DC\|panel"]` |
| Fresh DC AUROC, solver (n=3,720) | 0.874 [0.849, 0.897] | `results/tests.json` `auroc["DC\|solver"]` |
| Fresh LC_ds_binary AUROC (panel / solver) | 0.830 / 0.865 | `results/tests.json` |
| Fresh B1 AUROC (panel / solver) | 0.791 / 0.727 | `results/tests.json` |
| T1 Δ | panel +0.033 (LB5 +0.005); solver +0.118 (LB5 +0.060) → **PASS** | `tests.json` T1 |
| T2 | DC − LC_ds_binary on panel = −0.003 → **label-dependent** | `tests.json` T2 |
| T3 | **fail** (top-1 0.122 vs majority 0.255) | `tests.json` T3 |
| T4 | **fail** for both systems | `tests.json` T4 |
| Wrong gold | MALLS 0.553, FOLIO 0.620, ProverQA 0.146 | `results/analysis.json` label_quality |
| Correct-but-inequivalent | 0.438 | `results/analysis.json` label_quality |
| Shared bias: DC AUROC in mode-wrong sentences | 0.419 | `results/analysis.json` |
| Wrong-gold flag AUROC | 0.859 | `results/analysis.json` |
| Invariance false alarms | ≤ 0.5% | `results/analysis.json` |
| Perturbation detection | 0.87–0.93 (arg swap 0.65) | `results/perturbation_sensitivity.json` |
| Independent re-derivation | AUROCs identical; T1 panel +0.029 (refit LB5 +0.0035); placebos fail | `results/rederive_headline.json` |

All tables are in `results/report_tables.md` and README §1. In the paper these are the confirmation table (T1–T4), the fresh-AUROC table, and the secondary sections on circularity, shared bias, complexity, invariance, wrong-gold, perturbations and system level.
