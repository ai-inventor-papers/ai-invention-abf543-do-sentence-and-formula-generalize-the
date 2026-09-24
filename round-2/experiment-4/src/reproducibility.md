# Reproducing this artifact (what was actually run)

Original workspace: `/ai-inventor/aii_data/runs/run_ujABDGgoK_5Q/3_invention_loop/iter_2/gen_art/gen_art_experiment_4`

## 1. Copy the folder
```bash
cp -r gen_art_experiment_4 ~/dc_repro && cd ~/dc_repro
```
The scripts derive every path from their own location. The only external read-only inputs are:
- the dataset: `/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_dataset_1/full_data_out/full_data_out_{1,2,3}.json`;
- round-2 results (baselines and records), under `/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_2/gen_art/gen_art_experiment_{3,4,5}/`.

If those paths differ on your machine, edit `DS_DIR`, `R2` and `EXP3/4/5` in `dc/common.py`. Note that `dc/common.py` is part of the frozen engine hash.

## 2. System, Python, environment
- Ubuntu (Linux 6.8). Needs `curl` and `unzip`. Python **3.12.14**; `uv` is the package manager (pip is not used).
- Commands actually used:
```bash
uv venv .venv --python=3.12
uv pip install --python=.venv/bin/python z3-solver numpy scipy scikit-learn pandas nltk loguru aiohttp tenacity pytest orjson psutil
uv pip install --python=.venv/bin/python spacy "en_core_web_sm @ https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"
```
- Exact versions are pinned in `pyproject.toml`, taken from `uv pip freeze`. Key pins: z3-solver==5.1.0.0, numpy==2.5.3, scipy==1.18.1, scikit-learn==1.9.1, nltk==3.10.3, spacy==3.8.16, en_core_web_sm 3.8.0. To install exactly those: `uv pip install --python=.venv/bin/python -r <(python3 -c "import tomllib;print('\n'.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))")`
- WordNet (`nltk.download` refuses world-writable directories, so it was fetched manually):
```bash
mkdir -p nltk_data/corpora && curl -sL -o nltk_data/corpora/wordnet.zip https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/packages/corpora/wordnet.zip && (cd nltk_data/corpora && unzip -q -o wordnet.zip)
```
`bash restore.sh` performs the three installs plus WordNet and runs the unit tests.

## 3. Environment variables and keys (names only)
- `OPENROUTER_BASE_URL`, `OPENROUTER_API_KEY` are used only by `scripts/m1_b1.py` and the M3 arbiter (`scripts/m3_boundary.py`, `scripts/m3_ask.py`). Every other stage costs $0 and works offline.
- `NLTK_DATA` and the BLAS thread caps are set automatically by `dc/common.py`.

## 4. Commands, in the order they were run
Hardware: a CPU container with 23.8 cgroup CPUs (22 spawn workers, RLIMIT_AS 3–4 GB each) and about 250 GB RAM. No GPU was used. Seeds are fixed in code:
- S1 sample: seed 0; M2 sample: seed 1; M3 sample: seed 2; M4 draws: seed 4;
- bootstraps: exp3 StratBoot seed 0, 2,000 draws;
- the fingerprint bank is fixed; tokens and synonyms are seeded by sentence id.

| # | command | wall time | output |
|---|---|---|---|
| 1 | `.venv/bin/python scripts/prep.py` | 3 s | `work/frame.jsonl`, `work/canon.jsonl` |
| 2 | `.venv/bin/python scripts/m6_record.py` (after the arXiv grep; see note 1) | 2 s | `results/round2_record.json`, `results/wrong_gold_citation.json` |
| 3 | `.venv/bin/python scripts/m0_pairs.py 20 22`, then `... all 22` | 20 s + 136 s | `work/pairs_dc.jsonl` |
| 4 | `.venv/bin/python scripts/m0_score.py 20`, then `... all` | 40 s + 50 s | `work/dc_scores.jsonl`, `work/gold_dc_scores.jsonl`, `work/m0_info.json` |
| 5 | `.venv/bin/python scripts/m0_anchor.py` | 40 s | `results/m0_anchor.json`, **`frozen_dc_config.json` + `.sha256`** (written once; never overwritten) |
| 6 | `.venv/bin/python scripts/prereg.py` | 1 s | `results/prereg.json` (refuses to overwrite) |
| 7 | `.venv/bin/python scripts/m1_build_score.py 10`, then `... all` | 40 s + 110 s | `work/m1_probes.jsonl`, `work/m1_build_info.json` |
| 8 | `.venv/bin/python scripts/m1_b1.py` | 2 min, $0.088 | `work/m1_b1.jsonl`, `cost_ledger.jsonl`, `work/llm_cache/` |
| 9 | `.venv/bin/python scripts/m2_invariance.py 1000` | 6 min | `work/m2_rows.jsonl`, `work/m2_contam.jsonl`, `results/m2_invariance.json` |
| 10 | `.venv/bin/python scripts/m1_analyze.py` | 1 min | `results/m1_confound.json` |
| 11 | `.venv/bin/python scripts/m3_boundary.py` | 3 min (arbiter calls returned 403) | `work/m3_dose.jsonl`, `work/m3_real.jsonl`, `work/m3_arbiter_answers.json` |
| 12 | `.venv/bin/python scripts/m3_ask.py --poll` (background; 7 probes 10 min apart) | 60 min | `work/key_status.jsonl` |
| 13 | `.venv/bin/python scripts/m4_placebo.py` | 1.5 min | `results/m4_placebo.json` |
| 14 | `.venv/bin/python scripts/m5_m6_m7.py` | 1 min | `results/m5_ladder_typing.json`, `results/m6_within_sentence.json`, `results/m7_goldflag.json` |
| 15 | `.venv/bin/python scripts/m3_analyze.py` | 1 min | `results/m3_boundary.json` |
| 16 | `.venv/bin/python -m pytest -q -c pytest.ini tests/test_dc.py` | 5 s | `results/pytest_result.txt` (12 passed) |
| 17 | `.venv/bin/python scripts/m2_diagnose.py` | 30 s | `results/m2_rename_diagnosis.json` |
| 18 | `.venv/bin/python audit_rederive.py`; `.venv/bin/python audit_rederive2.py` | 30 s | `results/audit_rederive.json`, `results/audit_rederive2.json` |
| 19 | `.venv/bin/python scripts/extra_analyses.py` | 2 min | `results/complexity_system_cost.json` |
| 20 | `.venv/bin/python scripts/verdicts.py`; `.venv/bin/python scripts/t3_check.py` | 5 s | `results/verdicts.json`, `results/proposed_amendments.json`, `results/integrity.json` |
| 21 | `.venv/bin/python method.py export`, then the aii-json format script on `method_out.json` | 30 s | `method_out.json`, `full_/mini_/preview_method_out.json` |

Notes:
1. Step 2 needs the arXiv grep evidence in `work/web/`. It was produced with the aii-web-tools `aii_fast_web_fetch.py grep` script on `https://arxiv.org/abs/2606.02837v1`, `…v2`, the unversioned abstract and `https://arxiv.org/pdf/2606.02837`, using the pattern `(39|36|42\.5|42|24|20)\s?%|incorrect FOL|fewer than \d+%`.
2. `uv run method.py all` chains steps 1 and 2 through 20, then exports. Pair computations are cached, so a re-run reuses `work/pairs_dc.jsonl`. Delete that file to recompute from scratch (about 12 min of CPU in total).
3. Order matters for the freeze. The pre-registration (step 6) was written after the freeze (step 5) and before any M1–M5/M7 scoring. `scripts/verdicts.py` checks both sha256 values in `results/integrity.json`.
4. The arbiter (M3b/M3c) did not run. The run-level OpenRouter cap returned HTTP 403 `aii_run_budget_exhausted`. With a working key, run `.venv/bin/python scripts/m3_ask.py && .venv/bin/python scripts/m3_analyze.py && .venv/bin/python scripts/verdicts.py`. That is about 1,400 calls to google/gemini-2.5-flash, roughly $0.1.

## 5. What you should get

| number | value | file |
|---|---|---|
| L1 agreement with exp3 bijection cache | 1.000 (22,198 pairs) | `results/m0_anchor.json` → `l1_crosscheck` |
| DC dev AUROC, panel (weighted) / solver | 0.769 [0.717, 0.819] / 0.815 | `results/m0_anchor.json` |
| DC_L2w dev AUROC, panel / solver | 0.774 / 0.833 | same |
| M1 AUROC F vs M, DC / DC_L2w / B1 (conf, tok, syn) | 0.805 / 0.999 / 0.945, 0.794, 0.890 | `results/m1_confound.json` |
| M1 tok-arm NEG and DROP_CONJ AUROC, DC vs DC_L2w | 0.511 vs 1.000; 0.659 vs 0.995 | `results/m1_confound.json` → `per_operator` |
| M2 rename FA(δ = 0.10) / FA(δ = 0) | 0.000 / 0.001 | `results/m2_invariance.json` |
| Contamination Δ, DC vs B1 | +0.0023 [0.0001, 0.0055] vs +0.096 | same |
| M3 dose detection, k = 0/2/4/6/8 | 0.934 / 0.771 / 0.434 / 0.138 / 0.058 (= analytic) | `results/m3_boundary.json` |
| M3c slope | −2.08 [−2.55, −1.61] | same |
| M4 within-sentence shuffle AUROC, panel / solver | 0.73 / 0.70 | `results/m4_placebo.json` |
| M7 DC(gold) AUROC; + B1 stacking Δ | 0.837 [0.809, 0.864]; +0.070 [0.045, 0.096] | `results/m7_goldflag.json` |
| Verdicts | 9 PASS, 10 FAIL, 1 NOT_RUN | `results/verdicts.json` |

These appear in the paper's DC stress-test section: the main table (M0), the confound figure (M1), invariance (M2), the boundary figure (M3), placebos (M4) and wrong-gold flagging (M7). README §2 has the full tables.

Small non-determinism is possible. z3 timeouts are wall-clock based, and 0.09% of pairs hit the 12 s cap. Under heavy CPU contention, a few pair relations could differ.
