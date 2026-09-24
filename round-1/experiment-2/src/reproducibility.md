# Reproducibility: Screen Arm B (TVJT, instance-consequence NLI, latent class vs baselines)

Everything below is taken from the files in this artifact folder (`method.py`, `src/*.py`, `README.md`,
`pyproject.toml`, `requirements.txt`, `results/*.json`, `audit/*`, `logs/*`). Items the workspace does not record are
marked **not recorded**.

## 1. Copy the artifact

```bash
cp -r <path-to>/gen_art_experiment_2 ~/armb && cd ~/armb
```

The folder already holds the public raw inputs (`data/raw/`), the built screen set (`data/screen_set.json`, fingerprint
`a74f4cdd6586fce69e33aa3882e44faeab848d6e`), the world/consequence caches, `results/screen_scores.jsonl`,
`results/analysis.json` and `results/verdict.json`. `cache/llm/` holds the sha1-keyed paid LLM responses; with it in place,
re-running costs $0 (README). The README says `cache/llm/` is excluded from the GitHub upload and kept only on the
volume; without it, the LLM stages make fresh, paid OpenRouter calls.

## 2. System and Python environment

- OS: Ubuntu (the run's host was Linux 6.17). Other system packages: **not recorded** beyond `curl` and `unzip`, which
  the README's WordNet restore command uses.
- Python: `>=3.12,<3.13` (`pyproject.toml`); the README creates the venv with `--python=3.12`.
- Package manager: `uv`.

```bash
uv venv .venv --python=3.12
uv pip install --python .venv/bin/python -r requirements.txt
```

`requirements.txt` pins every package and is identical to the `dependencies` list in `pyproject.toml`. Key pins:
z3-solver==5.1.0.0, torch==2.14.0 (CUDA 13 wheels, nvidia-*-cu13 pins), transformers==5.17.0, numpy==2.5.3,
scipy==1.18.1, scikit-learn==1.9.1, pandas==3.0.6, matplotlib==3.11.2, spacy==3.8.16, nltk==3.10.3, crowd-kit==1.4.2,
aiohttp==3.14.3, loguru==0.7.3, pytest==9.1.1. The spaCy model is installed from the wheel URL pinned in
`requirements.txt` (`en_core_web_sm-3.8.0`).

WordNet (used by the verbalizer and the RENAME rewrites), restored into `nltk_data/` (`method.py` sets `NLTK_DATA` to it):

```bash
mkdir -p nltk_data/corpora && curl -sfL -o nltk_data/corpora/wordnet.zip https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/packages/corpora/wordnet.zip && (cd nltk_data/corpora && unzip -q -o wordnet.zip)
```

## 3. Data, models and credentials

- Public inputs are already in `data/raw/` (the build stage reads them from disk; it does not download). Sources, per the README:
  - Logic-LM outputs: `raw.githubusercontent.com/teacherpeterpan/Logic-LLM/main/outputs/logic_programs/FOLIO_dev_*.json`
    (gpt-3.5-turbo, gpt-4, text-davinci-003)
  - FOLIO v1 gold: `raw.githubusercontent.com/Yale-LILY/FOLIO/main/data/v0.0/folio-{validation,train}.jsonl`
  - Curated gold: HF `DSAVlab-UNIUD/FOLIO_validation-curated` and `DSAVlab-UNIUD/MALLS_test_subset-CURATED`
  - MALLS test: HF `yuan-yang/MALLS-v0` (`MALLS-v0.1-test.json`)
  - Exact commit hashes or download dates of these sources: **not recorded**.
- NLI model: `MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli`, loaded by `src/stages.py` via `from_pretrained`
  (fp16 on CUDA, fp32 on CPU). The README says it came from the run's shared HF cache; to fetch it yourself, run
  `huggingface-cli download MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli`.
- LLM: `google/gemini-2.5-flash` via OpenRouter, temperature 0, reasoning disabled (`src/llm.py`). It serves B1, TVJT and
  NLI_gemini.
- Env var (name only): `OPENROUTER_API_KEY` (`src/llm.py` reads `os.environ["OPENROUTER_API_KEY"]`). It is needed only for
  uncached calls. `src/llm.py` has a $6.50 spend breaker.

## 4. Commands, seeds, hardware, runtime

Commands from the README, in order:

```bash
.venv/bin/python method.py --stage all --limit 10     # mini run -> runs/mini_10/
.venv/bin/python method.py --stage all                # full screen
.venv/bin/python src/dev_checks.py                    # T1/T2 prompt checks (prompt frozen afterwards)
.venv/bin/python src/integrity.py                     # T6 integrity checks
.venv/bin/python -m pytest -q -c tests/pytest.ini tests/
.venv/bin/python audit/rederive.py                    # independent re-derivation -> audit/rederive_out.json
```

`method.py` arguments: `--stage` (default `all`, which expands to `build,b1,tvjt,nli,lc,tvjt_nv,analysis,export`, or a
comma list of those), `--limit N` (first N screen sentences; outputs go to `runs/mini_N/`), `--workers` (default 6).
Stages resume from their caches. The README lists `figures/*` as produced by the analysis stage and `method_out.json` by the
export stage. `audit/rederive.py` takes no arguments (it uses fixed paths under the artifact root). Whether `src/make_readme.py`
was run to regenerate the README is stated by its docstring only; the exact invocation was **not recorded**.

Seeds and determinism (all from the code):
- Bootstrap: 1000 sentence-clustered resamples, seed 0 (`src/analysis.py`: `N_BOOT = 1000`, `seed=0`; `results/integrity_checks`
  records `bootstrap_seed` 0). The out-of-fold G3 stack is a `LogisticRegression(C=1.0)` under 5-fold `GroupKFold` by sentence (deterministic split, no seed); its bootstrap uses seed 0.
- Latent-class EM: 10 restarts, seed 0 (`src/latent_class.py`).
- Random interpretations for fingerprinting in equivalence checks: seed 12345 (`src/fol_core.py`).
- Mutants, worlds and NLI pair selection are seeded per item from `seed_key = item_id` (sha1-derived `random.Random`).
- Screen selection: the 300 eligible sentences that come first by sha1 of the normalised sentence text.
- Caveat: gemini-2.5-flash at T=0 was not fully deterministic. The final numbers come from a second, cache-consistent
  pass (README; `logs/repro/verdict_before.json` holds the first-pass verdict). The AUROC shift was <=0.002 for TVJT.
  Fresh LLM calls may therefore differ slightly from the reported numbers.

Hardware and runtime:
- GPU: one GPU was used for DeBERTa (`method.py` comment; README: "6 CPU workers + 1 GPU"). The GPU type and VRAM were **not
  recorded** (no GPU is visible on the machine where this document was written). Memory: container limit 42 GB per the
  `method.py` comment, an `RLIMIT_AS` of 60 GB is set in code, and the pipeline needs <12 GB RSS.
- The full run takes about 15 minutes on 6 CPU workers plus 1 GPU (README estimate). DeBERTa falls back to CPU if no CUDA.
- Cost: total OpenRouter spend $1.5501 (`audit/rederive_out.json`, README: $1.55), covering dev checks, the mini run and the full screen.

## 5. Expected outputs and numbers

Files: `data/screen_set.json`, `data/alt_candidates.jsonl`, `data/candidate_pairs.json`, `data/worlds_cache.jsonl`,
`data/worlds_cache_nv.jsonl`, `data/consequences_cache.jsonl`, `data/blindspot_supplement.jsonl`,
`results/screen_scores.jsonl`, `results/analysis.json`, `results/verdict.json`, `results/blindspot_headtohead.json`,
`results/latent_class_info.json`, `results/integrity_checks.json`, `results/dev_checks.json`, `results/cost_ledger.jsonl`,
`figures/{auroc_by_tercile,per_operator_detection,confusion_TVJT,confusion_NLI_deberta}.{png,pdf}`, `method_out.json`,
`audit/rederive_out.json`.

Headline numbers (`results/analysis.json`, `results/verdict.json`, `README.md`):
- Screen: 300 sentences, 833 real candidates (463 correct / 370 incorrect under primary label `L_bij`); 58 unparseable (7.0%)
  are kept and scored 0.5.
- AUROC [95% CI]: LC_onecoin 0.853 [0.813, 0.888]; TVJT 0.701 [0.656, 0.745]; NLI_deberta 0.603 [0.550, 0.647];
  B1 0.665 [0.616, 0.711]; B2 0.578; B3sc 0.597.
- G3 dAUROC: LC_onecoin +0.111; TVJT +0.039; NLI_deberta +0.001. TVJT fails G2 (rewrite false alarms 0.479 at tau*=1.0,
  0.184 at 0.5). The rule outcome is `winner`, with survivor LC_onecoin (`results/verdict.json`).
- Tercile AUROC (0/1/2): TVJT 0.669/0.684/0.751; B1 0.718/0.646/0.552. TVJT minus B1 on the top tercile: +0.199 [+0.085, +0.308].
- Label-noise: 67.6% of incorrect labels are vocabulary mismatches (250/370); v1 vs curated gold differ on 43/108 sentences (6 semantic).
- Independent audit (`audit/rederive_out.json`): headline point estimates match; the placebo (permuted labels) gives AUROC 0.506
  (LC) and 0.520 (TVJT), and G3 on the placebo fails (LC CI [-0.032, +0.043]). CIs differ in the third decimal.

Where they appear in a paper: **not recorded**. The workspace contains no paper text or table numbering. The README's
Results tables and the `figures/` files are the closest supported mapping.

## 6. Not recorded

GPU model and VRAM; the wall-clock time of the original full run (only the README's ~15 min estimate); the exact system
package list; dates and commit hashes of the downloaded public sources; the exact search queries (none were used; inputs are
fixed public files); a paper location for each number.
