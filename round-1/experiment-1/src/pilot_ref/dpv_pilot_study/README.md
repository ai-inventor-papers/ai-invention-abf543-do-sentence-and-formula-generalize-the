# DPV-grounded NL→FOL pilot — recovered package

Recovered 2026-09-23 from git commit `08dbb26` ("Initialize repository", 2026-07-06), the last
commit in which the pilot was tracked. Commit `58c485c` untracked `tests_and_scripts/`; the
on-disk copies of `Adapted_NL2FOL_prototype/` and `Prolog_parser_and_metrics/` are no longer
present in the working tree (only `.env` and a `.pyc` remain), so git history is the only source.
Content is byte-identical to that commit; nothing was edited. No `.env`/API key is included.

## Layout
- `pipeline_Adapted_NL2FOL_prototype/` — was `tests_and_scripts/Adapted_NL2FOL_prototype/`
  - `main.py` (sync pipeline), `main_async.py` (async variant)
  - prompts: `*_legal_examples.txt` (ungrounded), `*_with_DPV.txt` (grounded), `FOL_to_Prolog.txt`
  - `DPV_terms.txt` — the 151-term DPV-AIAct list injected in the grounded condition
  - `euaiact_enacting_terms.json` — input: parsed EU AI Act enacting terms (Art. 3 definitions)
  - `pilot_results/<NN_term>/{grounded,ungrounded}/run_{1,2,3}/` — the pilot outputs
  - `pilot_results_metrics/` — metric JSONs + headline summaries as produced at the time
  - `test_results/` — small smoke-test runs (defs 1–3 + one RFS example, K=1)
- `metrics_Prolog_parser_and_metrics/` — was `tests_and_scripts/Prolog_parser_and_metrics/`
  - `prolog_parser.py`, `metric{1..5}*.py` (`*_pilot_v2.py` are the versions used), `dpv_terms.json`
  - `metric*_...py` without `_pilot` + `test_example_1/` — earlier per-definition ontology
    experiment (baseline motivation), `metric1_warnings*.{csv,txt}`, `metric2/3*.json` for it
- `notes/` — `dpv_pilot_status_report.md` and `conversation_memory_log.md` (current repo),
  `conversation_memory_dpv_pilot.md` (deleted from repo 2026-07-27, recovered from `08dbb26`)
- `verification/` — metrics 2–5 re-run on 2026-09-23 from the recovered results

## Re-running metrics
```
cd metrics_Prolog_parser_and_metrics
P=../pipeline_Adapted_NL2FOL_prototype/pilot_results
python3 metric5_inter_run_Jaccard.py           --pilot-dir $P
python3 metric4_DPV_coverage.py                --pilot-dir $P --dpv-terms dpv_terms.json
python3 metric2_shape_consistency_pilot_v2.py  --pilot-dir $P
python3 metric3_dangling_refs_pilot_v2.py      --pilot-dir $P --dpv-terms dpv_terms.json
python3 metric1_load_warnings_pilot_v2.py      --pilot-dir $P   # needs swipl on PATH
```
Metrics 2–5 reproduce the recorded headlines exactly. Metric 1 was not re-run (no swipl).

## Discrepancies between the recovered artifacts and `dpv_pilot_status_report.md`
1. Scope: results cover 65 Art. 3 definitions (1–68 minus seeds 4, 7, 22) × 2 conditions × K=3
   = 390 run dirs — not "3 sentences, 18 executions". The seeds were excluded from the test
   inputs (`main.py` skips them), so "seed = test input" is not what ran.
2. Failures: 23/390 runs errored — 16 are OpenRouter HTTP 402 (credits exhausted; defs 66–68),
   7 are LLM JSON-parse failures. 2 more ended `still_invalid` after 3 Prolog attempts.
3. Temperature: `llm()` sets no `temperature`, so runs used the provider default, not T=0.
4. DPV list: 151 terms, not "~600" (report) or "~200 classes + 3 properties" (memory log).
5. Metric 3 arity split (listed as a next step) is already implemented in `_pilot_v2`.
6. `main.py`'s `__main__` block as committed is a debug config (defs 1–3, K=1, `test_results/`),
   not the configuration that produced `pilot_results/`.
