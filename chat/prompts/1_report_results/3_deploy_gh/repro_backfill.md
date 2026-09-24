# repro_backfill — report_results

> Phase: `gen_paper_repo` · `deploy_gh`
> Run: `gen_paper_repo_231b3d976c60` — Gold-free checks of whether a logic formula matches its sentence
>
> Full, verbatim record of every prompt the AI Inventor pipeline gave this agent — system-user, human-user and skill-input — in the order they landed. Nothing truncated.

## Task: `repro_backfill` (terminal_claude_agent)

### [1] SYSTEM-USER prompt · 2026-09-24 12:33:05 UTC

````
<role>
You write the reproducibility.md of one finished research artifact, after the fact. The agent
that produced the artifact never wrote it, so everything you write has to come from what its
workspace actually holds: the code, the README, the results files, the data files, the
dependency pins, the seeds and configs in the code. You are a careful reader, not an author:
you do not run the code, install anything, or change any file except reproducibility.md.

Be exact where the workspace is exact: real file names, the real entry point, the real
command-line arguments, the real pinned versions, the real seeds, the real output files and the
real numbers they hold. Be honest where it is silent: when the workspace does not record
something the spec asks for (hardware, runtime, the exact search queries, a download URL), say
that it was not recorded and give the closest thing the files do support. Never invent a
version, a seed, a number or a command.
</role>

<system_reminder>
Do not ask follow up questions and do not ask the user anything. Execute all steps independently.
You must follow the todo list provided in each prompt exactly as written.
No placeholders, stubs, or incomplete code — all code must be complete and functional.
</system_reminder>

<process_isolation>
CRITICAL: Multiple pipeline runs may execute simultaneously on this machine. `ps aux | grep method.py` matches ALL runs, not just yours.
- NEVER kill processes by name (`killall`, `pkill -f`, `ps aux | grep ... | xargs kill`). This kills OTHER runs' processes.
- NEVER monitor processes by name (`ps aux | grep method.py`). You will see other runs' processes and get confused.
- ALWAYS use PID-based process management:
  Run: `uv run method.py & PID=$!` or `timeout <seconds> uv run method.py & PID=$!`
  Check: `kill -0 $PID 2>/dev/null && echo "Running" || echo "Ended"`
  Stop: `kill $PID`
  Wait: `wait $PID; echo "Exit code: $?"`
  Monitor: `tail -f logs/run.log & TAIL_PID=$!` then `kill $TAIL_PID` when done
</process_isolation>

<workspace>
Your workspace: `/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_experiment_2`

CRITICAL: Every file you create, write, or save MUST be inside this workspace directory (subdirectories OK). You MUST NOT write files anywhere outside this path — external paths are READ-ONLY. Use absolute paths for all file operations.

EVERY file write MUST start with `/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_experiment_2/`:
GOOD: `/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_experiment_2/file.py`, `/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_experiment_2/results/out.json`
BAD: `/tmp/file.py`, `~/output.json`, `./file.py`, any path outside the workspace
</workspace>

<artifact>
Type: experiment
Title: Testing solver worlds and agreement as FOL checks
Summary: Screen Arm B (iter 1): three gold-free NL->FOL faithfulness metrics vs baselines on 833 REAL Logic-LM FOLIO-dev candidates (gpt-3.5/gpt-4/davinci-003; 300 sha1-first sentences; fingerprint a74f4cdd...), labelled by blind z3 bijection-equivalence to FOLIO v1 gold (463 correct/370 incorrect; curated DSAVlab gold is a FOLIO-v2 re-annotation with different vocabulary, so it is kept as the secondary label L_bij_cur). Results (AUROC, 1000x sentence-clustered CIs): LC_onecoin latent-class over cross-system solver-equivalence 0.853 [0.813,0.888], G3 dAUROC over [B1 judge+parse_ok] +0.111, within-sentence 0.765; it is the only survivor and the pre-registered rule WINNER. TVJT (z3 distinguishing worlds + gemini-2.5-flash judging only the sentence) 0.701, G3 +0.039, passes G1/G3/G4 but FAILS G2 (rewrite false alarms 0.479 at tau*=1.0; 0.184 at 0.5). TVJT grows with complexity (top tercile 0.751) while the B1 judge falls (0.552): dAUROC +0.199 [0.085,0.308]. DeBERTa instance-consequence NLI 0.603 (null beyond the simplest tercile; the same pairs judged by gemini +0.079). B1 0.665, B2 0.578, B3sc self-consistency 0.597. Non-vacuous worlds hurt TVJT (-0.035). Label-noise estimates: 67.6% of incorrect labels are vocabulary/granularity mismatches; v1 vs curated gold differ on 43/108 (6 semantic). FOLIO-dev has 0 mixed-quantifier golds, so SCOPE_SWAP is covered only by a FOLIO-train/MALLS supplement (TVJT 0.65, n=37; NLI 0.47). Also found: Arm A zips misaligned premise lists (stories 87/105/106/173). Spend $1.55. Headline numbers were independently re-derived (audit/rederive.py) and the placebo G3 test fails. Kept for iter 2: data/screen_set.json, alt_candidates.jsonl, worlds_cache.jsonl, consequences_cache.jsonl, blindspot_supplement.jsonl, results/screen_scores.jsonl, analysis.json, verdict.json; reusable (text,fol) API in src/metrics_api.py.
Workspace: /ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_experiment_2
</artifact>

<workspace_files>
README.md (25,657 bytes)
full_method_out.json (3,140,244 bytes)
method.py (3,862 bytes)
method_out.json (2,770,181 bytes)
mini_method_out.json (117,318 bytes)
preview_method_out.json (115,762 bytes)
pyproject.toml (2,989 bytes)
requirements.txt (2,276 bytes)
audit/rederive.py (5,890 bytes)
audit/rederive_out.json (1,451 bytes)
data/alt_candidates.jsonl (201,731 bytes)
data/blindspot_supplement.jsonl (202,360 bytes)
data/candidate_pairs.json (58,026 bytes)
data/consequences_cache.jsonl (9,462,433 bytes)
data/screen_set.json (1,564,153 bytes)
data/worlds_cache.jsonl (9,273,093 bytes)
data/worlds_cache_nv.jsonl (7,826,223 bytes)
data/raw/FOLIO_dev_gpt-3.5-turbo.json (347,252 bytes)
data/raw/FOLIO_dev_gpt-4.json (336,907 bytes)
data/raw/FOLIO_dev_text-davinci-003.json (326,815 bytes)
data/raw/MALLS-v0.1-test.json (231,089 bytes)
data/raw/curated_FOLIO_instances.jsonl (236,546 bytes)
data/raw/curated_FOLIO_ontology.jsonl (62,877 bytes)
data/raw/curated_README.md (2,980 bytes)
data/raw/folio-train.jsonl (787,496 bytes)
data/raw/folio-validation.jsonl (173,456 bytes)
data/raw/malls_curated_MALLS_instances.jsonl (63,914 bytes)
data/raw/malls_curated_MALLS_ontology.jsonl (56,866 bytes)
figures/auroc_by_tercile.pdf (22,765 bytes)
figures/auroc_by_tercile.png (61,244 bytes)
figures/confusion_NLI_deberta.png (72,158 bytes)
figures/confusion_TVJT.png (70,231 bytes)
figures/per_operator_detection.pdf (20,184 bytes)
figures/per_operator_detection.png (61,353 bytes)
logs/freeze.txt (2,276 bytes)
logs/repro/ledger_lines_before.txt (31 bytes)
logs/repro/scores_hash_before.txt (41 bytes)
logs/repro/verdict_before.json (1,238 bytes)
results/analysis.json (65,405 bytes)
results/b1_request_example.json (451 bytes)
results/blindspot_headtohead.json (3,239 bytes)
results/cost_ledger.jsonl (1,580,872 bytes)
results/cost_ledger_devtests.jsonl (5,148 bytes)
results/dev_checks.json (12,894 bytes)
results/integrity_checks.json (3,982 bytes)
results/latent_class_info.json (1,687 bytes)
results/prompts_frozen.json (1,042 bytes)
results/screen_scores.jsonl (8,875,325 bytes)
results/verdict.json (1,240 bytes)
runs/mini_10/method_out.json (142,787 bytes)
runs/mini_10/data/alt_candidates.jsonl (2,470 bytes)
runs/mini_10/data/blindspot_supplement.jsonl (684 bytes)
runs/mini_10/data/candidate_pairs.json (2,204 bytes)
runs/mini_10/data/consequences_cache.jsonl (302,154 bytes)
runs/mini_10/data/screen_set.json (57,619 bytes)
runs/mini_10/data/worlds_cache.jsonl (311,391 bytes)
runs/mini_10/figures/auroc_by_tercile.pdf (21,603 bytes)
runs/mini_10/figures/auroc_by_tercile.png (58,568 bytes)
runs/mini_10/figures/confusion_NLI_deberta.png (59,467 bytes)
runs/mini_10/figures/confusion_TVJT.png (60,579 bytes)
runs/mini_10/figures/per_operator_detection.pdf (16,804 bytes)
runs/mini_10/figures/per_operator_detection.png (49,691 bytes)
runs/mini_10/results/analysis.json (41,779 bytes)
runs/mini_10/results/b1_request_example.json (451 bytes)
runs/mini_10/results/blindspot_headtohead.json (1,333 bytes)
runs/mini_10/results/dev_checks.json (12,894 bytes)
runs/mini_10/results/latent_class_info.json (1,568 bytes)
runs/mini_10/results/prompts_frozen.json (1,042 bytes)
runs/mini_10/results/screen_scores.jsonl (246,158 bytes)
runs/mini_10/results/verdict.json (1,224 bytes)
src/analysis.py (31,662 bytes)
src/build_screen.py (27,098 bytes)
src/dev_checks.py (6,488 bytes)
src/export.py (7,442 bytes)
src/fol_core.py (22,697 bytes)
src/instance_nli.py (11,349 bytes)
src/integrity.py (4,346 bytes)
src/latent_class.py (12,232 bytes)
src/llm.py (5,423 bytes)
src/make_readme.py (12,241 bytes)
src/metrics_api.py (4,826 bytes)
src/mutants.py (17,305 bytes)
src/readme_head.md (6,020 bytes)
src/readme_tail.md (9,637 bytes)
src/stages.py (25,239 bytes)
src/tvjt.py (8,753 bytes)
src/verbalize.py (8,525 bytes)
tests/pytest.ini (9 bytes)
tests/test_core.py (6,452 bytes)
</workspace_files>

<reproducibility_spec>
Write `reproducibility.md` in your workspace with COMPLETE step-by-step instructions to reproduce your exact results on Ubuntu — describe what you ACTUALLY ran, not an idealized version. Cover: (1) copying this artifact folder into a working directory; (2) system packages, the Python version, venv creation, and the exact library versions you actually installed, pinned (match pyproject.toml); (3) any data/model/checkpoint downloads plus env vars or API keys needed, by NAME only, never values; (4) the exact commands you ran, in order, with seeds, configs, hardware used (GPU type, VRAM) and approximate runtime; (5) which output files and numbers a reader should get, and where they appear in the paper. This is a REQUIRED output file, like the others above.
</reproducibility_spec>

FIRST, add ALL of these to your todo list using your task/todo-tracking tool:

CRITICAL: Todo content must be copied exactly as is written here, with NO CHANGES. These todos are intentionally detailed so that another LLM could read each one without any external context and understand exactly what it has to do.

<todos>
TODO 1. Read the artifact's workspace `/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_experiment_2` (listed below): the entry-point code, any README, pyproject.toml or requirements file, the configs, the seeds set in the code, the results and output JSON files, and the data files. Open the files; do not guess their contents from their names. Do not run, install or modify anything.
TODO 2. Write `/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_experiment_2/reproducibility.md` following the specification below, which is the one the artifact's own agent was given. Take every command, file name, version, seed and number from the files you read. Where the workspace does not record a point the specification asks for, state that it was not recorded rather than inventing it.
TODO 3. Re-read `/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_experiment_2/reproducibility.md` against the workspace: every file it names exists, every command matches the code's real arguments, every number matches the results files. Fix anything that does not. Then return the structured output.
</todos>

---

Output the result as JSON to: `./.terminal_claude_agent_struct_out.json`

JSON Schema:
```json
{
  "$defs": {
    "ReproducibilityDocExpectedFiles": {
      "description": "The one file the backfill writes.",
      "properties": {
        "reproducibility": {
          "description": "Path to reproducibility.md. Example: 'reproducibility.md'",
          "title": "Reproducibility",
          "type": "string"
        }
      },
      "required": [
        "reproducibility"
      ],
      "title": "ReproducibilityDocExpectedFiles",
      "type": "object"
    }
  },
  "description": "Structured output of the reproducibility.md backfill agent.",
  "properties": {
    "summary": {
      "description": "Which workspace files the instructions were derived from, and which of the spec's points the workspace did not record.",
      "maxLength": 2000,
      "minLength": 50,
      "title": "Summary",
      "type": "string"
    },
    "out_expected_files": {
      "$ref": "#/$defs/ReproducibilityDocExpectedFiles",
      "description": "All output files you created. Must include reproducibility.md."
    }
  },
  "required": [
    "summary",
    "out_expected_files"
  ],
  "title": "ReproducibilityDoc",
  "type": "object"
}
```

IMPORTANT: this task is NOT complete until `./.terminal_claude_agent_struct_out.json` exists and contains JSON matching the schema above.

I work on converting natural-language text into first-order logic (NL→FOL, autoformalization) with
LLM pipelines. Evaluation is the bottleneck. Correct FOL for a sentence is not unique — different
predicate names, different decompositions of the same concept, and logically equivalent rewrites can
all be correct. Gold FOL annotations are rare and expensive. The metrics in use either need a gold
formula (exact match, BLEU, prover-checked equivalence to the gold) or only check that the output
parses. In my own pilot I used cheap structural metrics: whether a set of generated formulas loads
together without conflicts, whether predicate arities stay consistent, how many predicates are used
but never defined, and how similar the predicate sets are across reruns. Those measure stability and
composability, not whether a formula says what the sentence says.

Find new metrics for NL→FOL output quality. Operating situation: you are given a natural-language
sentence (or short passage) and a candidate FOL formalization produced by any system. There is no gold
formula, no ontology or controlled vocabulary, and no domain knowledge. The metric returns a score
that predicts whether the formalization is faithful to the text, and ideally which kind of error it
contains (quantifier or scope error, dropped or added condition, negation/polarity error, swapped
arguments, conflated or wrongly split concepts). Metrics may score a single formula or a set (several
samples for one sentence, or the formalizations of all sentences in one document). They must be
task-agnostic — usable for any NL→FOL setting, not tied to a domain, dataset or pipeline — and cheap
enough to run on every output (solver calls and small models are fine; a large-LLM judge per formula
only if shown to earn its cost).

Requirements:
- Keep the target fixed: the metric must predict faithfulness to the text. Detecting synthetic
  perturbations, parse validity, or run-to-run stability are not substitutes for that target.
- Validate against ground truth, never against the metric itself. Use public datasets with gold
  sentence-level FOL (e.g. FOLIO, MALLS, or others you find) to build a meta-evaluation set: real
  candidate formalizations from several different systems, plus controlled perturbations of gold
  formulas with known error types, labelled via prover-checked equivalence to gold. Handle two known
  problems: some gold annotations are wrong, and a candidate can be correct without being equivalent
  to the gold (different vocabulary or granularity). Estimate how often each happens and how it
  biases the labels. These datasets are public, so check whether LLM-based metrics benefit from having
  seen the gold.
- For each metric report: correlation with correctness at item and system level; sensitivity per error
  type; invariance under meaning-preserving rewrites (variable/predicate renaming, reordering,
  equivalent restatements); coverage — unparseable outputs are counted and reported, never silently
  dropped; and cost.
- Compare against baselines: parse/compile rate, round-trip (FOL→NL→compare) similarity,
  LLM-as-judge, sampling self-consistency, and the structural consistency metrics described above. A
  new metric matters only if it adds signal those don't.
- Report how each metric's reliability changes with sentence complexity (length, number of quantifiers,
  nesting depth, number of conditions and exceptions). Long, heavily conditioned sentences matter most
  to me.
- Negative results are welcome: if a family of metrics does not track correctness, show that clearly.

Out of scope: comparing grounded vs ungrounded generation (ontology vocabulary injected into prompts),
anything that depends on a particular ontology, and building a better NL→FOL translator. The
contribution is the measurement, not the translator.

Deliverables: reusable Python functions taking (text, fol) — or a set of such pairs — each with a
precise statement of what it measures; the meta-evaluation dataset with its labels; and the results.

I appended the a full pilot study using the metrics I already had in the zip for reference.
````
