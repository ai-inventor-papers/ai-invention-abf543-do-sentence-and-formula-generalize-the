# Reproducibility: Held-out NL→FOL Faithfulness Meta-Evaluation Set

Everything below is taken from the workspace files (`README.md` §8/§9, `data.py`, `restore.sh`, `pyproject.toml`, `src/*.py`, `logs/*.out`, `label_report.json`, `work/panel_config.json`). Nothing was re-run when writing this file.

**What is reproducible and what is not.** The solver stages (L1/L2 labels, parsing, complexity features, sampling, assembly, source verification, splitting) are deterministic and cost $0. The LLM stages (generation by 9 systems, panel calibration, gold audit, L3 adjudication, E1 paraphrasing) call OpenRouter, whose outputs are not bit-reproducible. Their raw outputs are kept (`raw/generations/`, `work/panel_cache.jsonl`, `cost_ledger.jsonl`), and the documented pipeline reads those caches instead of re-calling the API. If the caches are present, re-running the labelling steps costs $0 (README §8).

## 1. Copy the artifact

```bash
cp -r . ~/nl2fol_heldout
cd ~/nl2fol_heldout
```
Keep the caches: `raw/generations/*.jsonl`, `work/panel_cache.jsonl`, `work/l1_cache.jsonl`, `cost_ledger.jsonl`. Deleting them means re-paying the API cost and getting different LLM outputs.

## 2. System, Python, environment

- Ubuntu (the run used Linux 6.17); `curl`, `git` and `uv` are needed (`restore.sh` uses `curl` and `uv venv`).
- Python **3.12** (`requires-python = ">=3.12"` in `pyproject.toml` and `data.py`).
- Dependencies are **not version-pinned** anywhere in the workspace. `pyproject.toml` lists unpinned names: `z3-solver, nltk, aiohttp, loguru, huggingface_hub, numpy, scipy, tenacity, requests, pyyaml, pytest`. The installed versions were not recorded (no lock file, no `pip freeze`). Install the current releases of these names; a different z3 version could change solver timeouts (`unknown_timeout`) on hard pairs.

```bash
uv venv .venv --python=3.12
uv pip install --python=.venv/bin/python z3-solver nltk aiohttp loguru huggingface_hub numpy scipy tenacity requests pyyaml pytest
```
- Hardware: **not recorded**. The pipeline is CPU-only (z3 plus API calls; no GPU is used). `label_l1.py` uses 4 spawn workers by default (`--workers 4`).

## 3. Downloads, keys, env vars

- Env var (name only): `OPENROUTER_API_KEY` (required by `src/or_client.py`, only for the API stages). `AII_COST_LEDGER` is optional (an external cost-ledger path). `NLTK_DATA` defaults to `<workspace>/nltk_data`. HuggingFace downloads used the ambient HF login; the token name was not recorded. README notes `yale-nlp/FOLIO` was gated for this token, hence the `tasksource/folio` mirror.
- `bash restore.sh` (run from the workspace root) recreates the deleted paths:
  - `.venv` (if missing), then `raw/hf_downloads/` from HF: `tasksource/folio`, `yuan-yang/MALLS-v0`, `DSAVlab-UNIUD/MALLS_test_subset-CURATED`, `DSAVlab-UNIUD/FOLIO_validation-curated`, `opendatalab/ProverQA` (dev easy/medium/hard), `yfxiao/folio-refined`.
  - `temp/datasets/` ccg2lambda files (`kenken6696/folio_by_ccg2lambda`, `kenken6696/MALLS_by_ccg2lambda`; downloaded but not used).
  - `raw/github/` (FOLIO v0.0 train/validation from Yale-LILY/FOLIO; Logic-LM `FOLIO_dev_{gpt-3.5-turbo,gpt-4,text-davinci-003}.json` from teacherpeterpan/Logic-LM) via `curl`.
  - `raw/pilot/`, the extraction of `/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/user_uploads/dpv_pilot_study.zip`. This zip is the user's private upload and is only needed for the E2 `transfer_unlabeled` group and its check in `data.py`.
  - `nltk_data/` (`wordnet`, `omw-1.4`).
  - The `temp/datasets/*` symlinks that `data.py` reads.
- Exact search queries and download URLs for HF datasets were not recorded as commands; the search evidence is in `temp/hf_search.txt`, `temp/previews/`, `temp/websearch/`, and README §7 lists the 10 kept and the discarded datasets.

## 4. Commands, in the order the README records them

Seeds recorded in code: `random.Random(0)` in `prep_sources.py` (sample, calibration set), `calibrate.py`, `audit.py` (20% full-panel subset), `e1_contamination.py`, `l3_adjudicate.py` (`build_sample` seed 0); `random.Random(1)` in `l3_extra.py`; bootstrap `seed=0` (B=2000) in `assemble.py`; `fol_equiv.py` `seed=0`. Generation samples use API `seed = sample_idx` at T=0.8 (`generate.py`); greedy uses T=0. Sampled systems: gpt-4.1-mini and llama-3.1-8b, 5 samples each.

```bash
.venv/bin/python -m pytest -q -c pytest.ini tests/test_fol.py        # 29 unit tests (README)
.venv/bin/python src/prep_sources.py                                  # steps 1-3, no API
.venv/bin/python src/generate.py --concurrency 24                     # step 4, ~$0.72, resumable
.venv/bin/python src/reextract.py                                     # extractor v2 (LaTeX unwrapping)
.venv/bin/python src/label_l1.py --stage orig
.venv/bin/python src/calibrate.py && .venv/bin/python src/calibrate_variants.py   # ~$0.88
.venv/bin/python src/audit.py --cap 4.0                               # L0 + L4 gold audit, ~$3.43
.venv/bin/python src/fix_varlike_patch.py                             # only for artefacts produced by parser v1
.venv/bin/python src/label_l1.py --stage audited
.venv/bin/python src/l3_adjudicate.py --n-non 400 --n-eq 60 --cap 2.8 # ~$2.46
.venv/bin/python src/l3_extra.py --n 150 --cap 0.85                   # ~$0.88
.venv/bin/python src/e1_contamination.py --n 203 --cap 0.75           # ~$0.86
.venv/bin/python src/e2_transfer.py
.venv/bin/python src/assemble.py            # -> work/assembled_data_out.json.gz + label_report.json
uv run data.py                              # source-verifies every row -> full_data_out.json (written to the workspace root)
.venv/bin/python src/split_outputs.py       # -> full_data_out/full_data_out_{1,2,3}.json + mini/preview files
```
Notes:
- The README lists this sequence, but the logs and code hint that the run itself was interleaved, and the exact shell history was not recorded. The `logs/*.out` files show background runs (`gen.pid`: generation, audit, L3, E1 PIDs).
- The parser bug fix (README §6.5) means the real run went: parse v1 → L0 audit → fix → recompute L1/L2 from scratch. A fresh run with the fixed parser does not need `fix_varlike_patch.py`. The buggy artefacts are kept as `work/l1_cache_v1_buggy.jsonl` and `work/fol_parse_v1_buggy_varlike.py`.
- `uv run data.py` uses the inline script metadata (`loguru`; Python >=3.12). It needs `temp/datasets/` (from `restore.sh`) and `work/assembled_data_out.json.gz`.
- `src/l3_adjudicate.py` defaults are `--n-non 250 --n-eq 50`; the run passed `--n-non 400 --n-eq 60`.
- LLM systems (OpenRouter ids from `src/generate.py`): meta-llama/llama-3.1-8b-instruct, qwen/qwen-2.5-7b-instruct, mistralai/mistral-small-3.2-24b-instruct, openai/gpt-4.1-mini, google/gemini-2.5-flash (reasoning max_tokens 0), deepseek/deepseek-chat-v3.1 (reasoning disabled), google/gemma-3-27b-it, microsoft/phi-4, openai/gpt-oss-120b (reasoning effort low, max_tokens 2048). Panel (`work/panel_config.json`, all T=0): anthropic/claude-haiku-4.5, x-ai/grok-4.3 (reasoning low), z-ai/glm-4.6 (reasoning disabled). Prompts: `prompts/`.
- Runtime: not recorded as a total. `logs/generate_full.out` shows generation of 13,120 calls from 12:20:40 to 12:36:03 (~15 min, concurrency 24); the audit ran roughly 12:33 to 12:42 and L3/E1 finished around 12:45 to 12:49 (times as logged; the audit and L3 logs are from concurrent background jobs). Solver labelling costs about 6 ms per pair (README).
- A hard spend cap of $9.30 is enforced in `src/or_client.py`; a re-run that re-calls the API will differ in outputs and cost.

## 5. Expected outputs and numbers

Files: `full_data_out/full_data_out_{1,2,3}.json` (15,606 examples; 6,300 + 7,000 + 1,003 + 936 + 367), `mini_*`/`preview_*` variants, `label_report.json`, `work/assembled_data_out.json.gz`. `data.py` should report 15,606/15,606 rows with `metadata_source_verified = true`.

From `label_report.json` / README (should reproduce from the caches):
- Wrong-gold (L0) rates: MALLS 45.6%, FOLIO-train 62.0%, screen 44.2%, ProverQA 17.5%.
- Panel vs human on MALLS (n=99): κ = 0.57.
- Correct-but-gold-inequivalent share: **43.9% [39.5, 48.6]** (n=546, weighted).
- Solver-only (L1) labels vs panel majority: 67.6%.
- Greedy label sources: panel3 609, equiv_audited_gold 3,915, equiv_synthetic_gold 1,323, unknown 453. 62.1% unfaithful among labelled greedy rows.
- Fleiss κ: L3 0.63 (candidate); L0 0.55.
- Scope + cardinality share of real errors: 6.9%.
- Cost: $9.2232 total over 18,566 API calls (`label_report.json`; the README rounds to "18k"). By phase: generation $0.72, calibration $0.88, gold audit $3.43, L3 $2.46 + $0.88, E1 $0.86.
- Panel calibration gate: haiku-4.5 0.90, grok-4.3 0.90, glm-4.6 (non-thinking) 0.875; claude-sonnet-4.5 failed at 0.775.

Paper correspondence: no paper text is in this workspace, so where these appear in the paper was not recorded. The numbers are documented in `README.md` §1 and `label_report.json`.

Reproduction caveats: fresh API calls will not reproduce the same generations, panel votes or costs (OpenRouter provider routing, non-deterministic even at T=0; provider is recorded per row). Solver outputs should match given the same z3 behaviour, but the z3 version is not recorded.
