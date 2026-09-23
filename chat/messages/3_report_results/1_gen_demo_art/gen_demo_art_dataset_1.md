# gen_demo_art_dataset_1 — report_results

> Phase: `gen_paper_repo` · `gen_demo_art`
> Run: `run_qY2a2IS-WLIs` — Do sentence and formula generalize the same way?
>
> Full, verbatim transcript of this agent task — every system/user prompt, assistant response, thinking block, tool call and tool result — in the order they occurred. Nothing truncated.

## Task: `gen_demo_art_dataset_1` (terminal_claude_agent, claude-opus-5-5)

### [1] CONFIG · 2026-09-23 18:39:04 UTC

```
model: claude-opus-5-5 | effort: high | permission: bypassPermissions
```

### [2] SYSTEM-USER prompt · 2026-09-23 18:39:10 UTC

````


<pasted_content id="49e8">
<system-prompt>
<conversion_philosophy>
**MINIMAL CHANGES — PRESERVE THE ORIGINAL CODE**

The goal is to make the artifact's code READABLE, UNDERSTANDABLE, and RUNNABLE in a short time
to someone reviewing the research, with the option to easily scale parameters back to original
values for a full run (which can take much longer). Think of this as annotating and reformatting,
not refactoring.

**DO:**
- Split the original script into logical notebook cells (imports, setup, processing, results)
- Add markdown cells BETWEEN code cells explaining what each section does and why
- Add inline comments where the logic is non-obvious
- Add a visualization/summary cell at the end showing key outputs
- Fix hardcoded file paths to use the GitHub data loading pattern

**DO NOT:**
- Rewrite functions or change algorithms
- Rename variables or restructure logic
- Add error handling, type hints, or "improvements" that weren't in the original
- Simplify or "clean up" the original code
- Remove any original comments or logic
- Change the computational approach

The reader should recognize the original script when looking at the notebook — it's the
same code, just split into cells with explanatory markdown between sections.
</conversion_philosophy>

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
Your workspace: `/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/4_gen_paper_repo/_4_gen_demo_art/notebook_workspaces/iter_1/art_iyzYyaqlqpSX`

CRITICAL: Every file you create, write, or save MUST be inside this workspace directory (subdirectories OK). You MUST NOT write files anywhere outside this path — external paths are READ-ONLY. Use absolute paths for all file operations.

EVERY file write MUST start with `/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/4_gen_paper_repo/_4_gen_demo_art/notebook_workspaces/iter_1/art_iyzYyaqlqpSX/`:
GOOD: `/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/4_gen_paper_repo/_4_gen_demo_art/notebook_workspaces/iter_1/art_iyzYyaqlqpSX/file.py`, `/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/4_gen_paper_repo/_4_gen_demo_art/notebook_workspaces/iter_1/art_iyzYyaqlqpSX/results/out.json`
BAD: `/tmp/file.py`, `~/output.json`, `./file.py`, any path outside the workspace
</workspace>
<disposable_outputs>
A SHARED CACHE ALREADY EXISTS FOR THIS RUN: `/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/.shared_cache`
`HF_HOME`, `HF_HUB_CACHE`, `TRANSFORMERS_CACHE`, `HF_DATASETS_CACHE`,
`TORCH_HOME`, `PIP_CACHE_DIR` and `UV_CACHE_DIR` are ALREADY set to point
there. Every step and every iteration of this run shares it, so a model or
dataset an earlier experiment downloaded is already on disk for you.

DO NOT override those variables. In particular do NOT write the common
pattern `os.environ["HF_HOME"] = <workspace>/hf_cache` — `HF_HOME` and
`TRANSFORMERS_CACHE` are read differently by `huggingface_hub` (one has
`/hub` appended, the other does not), so pointing both at one directory
stores every weight TWICE. That mistake cost one run 25 GB of identical
blobs. If you must set them, use the values above verbatim.

YOUR WORKING DIRECTORY IS A DELIVERABLE. When this module ends it must read
like a GitHub repository someone else can fork, resume and run — and the bulk
it holds must be either worth keeping or restorable. This run shares a storage
volume with the database; a run that fills it stops every other run on the box.

So before you finish, produce TWO files:

1. `.aii/manifest.yaml` — one entry per heavy path, each with EXACTLY ONE decision.
   The `.aii/` directory ALREADY EXISTS in your cwd: write the file into
   it. Do not create, replace or `touch` `.aii` itself — a plain file by
   that name makes the manifest unwritable for the rest of the module.

```yaml
entries:
  - path: results/
    keep: six GPU-hours of sweep output, not reproducible inside this run
  - path: hf_cache/
    delete: redownloadable
    source: "huggingface-cli download meta-llama/Llama-3-8B"
  - path: checkpoints/
    delete: regenerable
    source: "uv run train.py --epochs 3 --seed 0"
```

   - `keep:` takes a ONE-LINE reason. Use it for the expensive and the
     irreproducible: trained weights, long-running results, datasets you
     collected yourself.
   - `delete:` takes `redownloadable` (and a `source:` naming the repo id, URL
     or command) or `regenerable` (and a `source:` that is the command which
     rebuilds it). These are deleted AFTER the round ends, never mid-step.
   - Every path is RELATIVE TO YOUR CWD and must resolve INSIDE it. Absolute
     paths, `..`, and anything resolving outside are rejected.
   - Globs and whole directories are fine. A whole `hf_cache/` is ONE entry —
     do not list files individually.

2. `README.md` — written as if your cwd were a GitHub repository: what you
   did, the layout with a line per important file/directory, how to run it,
   and a **"Restoring removed files"** section giving the install/download
   command for EVERY `delete` entry. An `install.sh` or `restore.sh` beside it
   is welcome.

A CHECKER RUNS WHEN YOU SUBMIT. If anything heavy has no decision it fails
your submission and hands you the uncovered list, grouped by directory with
sizes, and you fix the manifest and submit again.

WHAT NEEDS NO DECISION — do not write entries for these:
- text and code files, at ANY size (source, JSON, CSV, YAML, logs, markdown);
- anything under the auto-keep floor (10 MB), whatever it holds.
Only large binaries and cache directories (`hf_cache/`, `.venv/`,
`node_modules/`, `checkpoints/`, `wandb/`, `__pycache__/`, …) need one.

NEVER mark your results, figures, papers, code, logs or anything a later step
reads as `delete`. If a later step needs it, it is a `keep`.

WHAT A `keep` BUYS YOU. Anything you do not mark `delete` stays exactly where
you wrote it, on this run's storage volume, at the path it already has — it is
not moved, renamed or copied. A later round reads it there, by that absolute
workspace path, so a checkpoint you keep is a checkpoint the next round can
load instead of retraining. It is also the ONLY copy: the publish step pushes
your cwd to GitHub but skips every file of 100 MB or
more, so trained weights and large binary artifacts never leave the volume.
Write the workspace path of each kept artifact into your results and your
`README.md`, so the paper can cite it by path rather than by a link that
was never pushed.
</disposable_outputs>
</system-prompt>

<prompt>
<tool_use>
Maximize parallel tool calls. Parallelize independent operations, only sequentialize dependencies.
- Multiple searches/fetches on different topics → parallel in one turn
- Search then fetch results → sequential (need URLs first)
</tool_use>

<task>
Convert this artifact's Python script into a demo notebook with MINIMAL changes to the original code.
Split into cells, add markdown explanations between sections, add a visualization cell at the end.
Output: mini_demo_data.json + code_demo.ipynb (notebook that loads data from GitHub URL)
</task>

<artifact_info>
id: art_iyzYyaqlqpSX
type: dataset
title: Held-out NL-to-FOL Faithfulness Meta-Evaluation Set
summary: |-
  full_data_out/full_data_out_{1,2,3}.json (exp_sel_data_out, 15,606 examples, ~62MB split in 3 parts <21MB; built by `uv run data.py`, which source-verifies every row against temp/datasets/, 15,606/15,606) holds 5 groups:
  - heldout_confirm: 6,300 greedy candidates = 700 sentences (MALLS-v0.1-test 250, incl. 99 human-corrected by arXiv:2606.02837 via HF DSAVlab-UNIUD; FOLIO-v2-train 250 from stories disjoint from both FOLIO validation versions; ProverQA-dev hard 120 / medium 80; 45.1% top complexity tercile) x 9 OpenRouter systems (llama-3.1-8b, qwen-2.5-7b, mistral-small-3.2, gpt-4.1-mini, gemini-2.5-flash no-thinking, deepseek-v3.1, gemma-3-27b, phi-4, gpt-oss-120b); unparseable outputs kept (301).
  - heldout_samples: 7,000 T=0.8 samples (gpt-4.1-mini, llama-3.1-8b).
  - screen_gold_audit: 1,003 Logic-LM FOLIO-dev candidates for the sha1-first-360 screen sentences, labelled against audited gold.
  - contamination: 936 entity-renamed paraphrase rows (104 verified pairs).
  - transfer_unlabeled: 367 of the user's EU-AI-Act pilot formulas.
  Labels: output in {faithful, unfaithful, unknown}.
  - L0: cascaded family-disjoint panel (claude-haiku-4.5 / grok-4.3 / glm-4.6; sonnet-4.5 failed the 40-item calibration gate) audits the gold. Wrong-gold rates: MALLS 45.6%, FOLIO-train 62%, screen 44%, ProverQA 17.5%. Panel vs human on MALLS: kappa 0.57.
  - L1: lexical-free z3 equivalence up to an arity-preserving bijection (propositional grounding over domains 1-4, then unbounded proof).
  - L2: WordNet granularity definitions.
  - L3: blinded A/B 3-model adjudication of 610 greedy items (Fleiss kappa 0.63) with post-stratified weights.
  Key finding: 43.9% [39.5, 48.6] of solver-non-equivalent candidates are panel-faithful. Solver-only labels agree with the panel 67.6%, so use the panel3 labels (label_source) or metadata_L3_stratum_p_faithful. Real errors are mostly added/dropped condition and forall/exists; scope + cardinality is only 6.9%.
  Every row carries provenance, gold_source, L0/L1/L2/L3 lineage, complexity features and cost.
  Documentation: label_report.json (all rates with CIs, kappas, costs; $9.22 of $10 spent), README.md (deviations, schema, restore). Kept irreproducible API outputs: raw/generations/, work/panel_cache.jsonl, cost_ledger.jsonl at /ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_dataset_1.
workspace_path: >-
  /ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_dataset_1
out_expected_files:
- data.py
- full_data_out.json
- preview_data_out.json
- mini_data_out.json
out_demo_files:
- path: data.py
  description: Dataset fetching/generation script
</artifact_info>

<github_repo>
Repo URL: https://github.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the
Raw data URL: https://raw.githubusercontent.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/main/round-1/dataset-1/demo/mini_demo_data.json

URLs won't work yet — files pushed to GitHub AFTER notebook creation.
Use local fallback pattern so notebook works locally (now) and in Colab (after deployment).
</github_repo>

<data_file_sizes>
Data files come in three sizes:
- preview_*_out.json — READ THIS to inspect the data structure
- mini_*_out.json (~3 examples) — use for prototyping/testing
- full_*_out.json (complete) — use for the final production run. NEVER open it directly (too large to read into context). Instead, extract values programmatically with shell commands (e.g. grep) or a Python script (use aii-long-running-tasks skill for scripts).
</data_file_sizes>

<install_dependencies_pattern>
Follow the aii-colab skill exactly. It has the install cell pattern, pre-installed package list, numpy 2.0 compat shims, and all Colab-specific rules.
</install_dependencies_pattern>

<data_loading_pattern>
`mini_demo_data.json` = curated subset for the demo.
Use this pattern for Colab compatibility (GitHub URL with local fallback):
```python
GITHUB_DATA_URL = "https://raw.githubusercontent.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/main/round-1/dataset-1/demo/mini_demo_data.json"
import json
from pathlib import Path

def load_data():
    try:
        import urllib.request
        with urllib.request.urlopen(GITHUB_DATA_URL) as response:
            return json.loads(response.read().decode())
    except Exception: pass
    local = Path("mini_demo_data.json")
    if local.exists(): return json.loads(local.read_text())
    raise FileNotFoundError("Could not load mini_demo_data.json")
```
</data_loading_pattern>

<notebook_structure>
--- Setup ---
Cell 1 (markdown): Title, description, what this artifact does.
Cell 2 (code): Install dependencies — follow the aii-colab skill's install cell pattern exactly. Fill in all packages imported by the artifact's code.
Cell 3 (code): Imports — copy original import block as-is, plus any additional imports needed for the notebook (e.g. matplotlib for visualization).
Cell 4 (code): Data loading helper — use the <data_loading_pattern> above.
Cell 5 (code): `data = load_data()`

--- Config ---
Config cell (code): Define ALL tunable parameters (iterations, epochs, n_samples, hidden_size, etc.) as variables at the top of this cell. Start with the ABSOLUTE MINIMUM values — the smallest that produce any output at all (e.g. 1 iteration, 2 samples, smallest array size). These get gradually increased during testing — see TODOs.

--- Processing ---
Remaining cells: One code cell per logical section of the original script. Add a markdown cell BEFORE each code cell. Copy code as closely as possible, with these changes:
  1. Replace file paths to use the loaded `data` variable.
  2. Use the config variables from the config cell (NOT hardcoded values).
  3. Minimal fixes are allowed if something doesn't work in notebook context (e.g. adjusting paths, removing CLI args, fixing imports), but keep changes to the absolute minimum.

--- Results ---
Visualization cell (code): Print key results in a readable table, plot numeric data with matplotlib if appropriate.
</notebook_structure>

<priority>
WORKING > OPTIMIZED. A small-scale demo that runs correctly is the goal. Once the notebook passes with minimum config values, scale up only if time permits — do NOT spend multiple retries chasing larger parameters. If a working version exists, finish and move on.
</priority>

<max_notebook_total_runtime>600s (10 min)</max_notebook_total_runtime>

<test_environment>
To test-run the notebook in a clean environment (simulating Colab), create a disposable `.nb_env` in your workspace:
```bash
/usr/local/bin/python3.12 -m venv .nb_env
.nb_env/bin/pip install -q pip jupyter ipykernel
.nb_env/bin/jupyter nbconvert --to notebook --execute --ExecutePreprocessor.timeout=600 code_demo.ipynb --output code_demo.ipynb
rm -rf .nb_env
```
The timeout is set to <max_notebook_total_runtime>. The entire notebook must finish within this time.

What happens: the .venv starts empty (just jupyter). When the notebook's install cell runs, `google.colab` is NOT in sys.modules, so ALL packages get installed — non-Colab packages unconditionally, and Colab packages (numpy, pandas, etc.) at Colab's exact versions via the guard block. The result mirrors Colab's environment as closely as possible. If a cell fails, fix the notebook and re-run.
</test_environment>

FIRST, add ALL of these to your todo list using your task/todo-tracking tool:

CRITICAL: Todo content must be copied exactly as is written here, with NO CHANGES. These todos are intentionally detailed so that another LLM could read each one without any external context and understand exactly what it has to do.


<todos>
TODO 1. Read and STRICTLY follow these skills: aii-colab, aii-long-running-tasks.
TODO 2. Read demo file and relevant preview_* files (preview only). Understand script structure: imports, setup, processing, output. Identify ALL tunable parameters (iterations, epochs, n_samples, hidden_size, batch_size, etc.) — these go in the config cell.
TODO 3. Create `mini_demo_data.json`: curated subset from at most ONE dataset (no more than 100 diverse examples). CRITICAL: do NOT read/grep full output file — may crash. Use `head -c 5000` or stream first entries with Python to pick examples.
TODO 4. Create `code_demo.ipynb` via NotebookEdit following <notebook_structure>. Set ALL config parameters to ABSOLUTE MINIMUM values — the smallest that produce any output (e.g. 1 iteration, 2 samples, smallest array sizes). Test-run using <test_environment>. Fix all errors until it passes.
TODO 5. GRADUALLY SCALE (but don't overdo it): increase config params step by step (e.g. ~2x each round). After each increase: test-run, record runtime, fix errors. STOP SCALING as soon as results look meaningful — a working small-scale demo beats a failed large-scale one. If full original params fit within <max_notebook_total_runtime> (10% margin), use them. Otherwise keep whatever works and comment out the true original values. Do NOT spend more than 2-3 scaling rounds.
TODO 6. Verify: (1) code_demo.ipynb contains GITHUB_DATA_URL = "https://raw.githubusercontent.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/main/round-1/dataset-1/demo/mini_demo_data.json" exactly, (2) mini_demo_data.json exists, (3) uses GitHub URL pattern not just open('mini_demo_data.json').
</todos>

---

Output the result as JSON to: `./.terminal_claude_agent_struct_out.json`

JSON Schema:
```json
{
  "$defs": {
    "DemoExpectedFiles": {
      "description": "Expected output files from code demo notebook generation.",
      "properties": {
        "notebook": {
          "default": "",
          "description": "Path to the generated demo notebook. Example: 'code_demo.ipynb'",
          "title": "Notebook",
          "type": "string"
        },
        "mini_data_file": {
          "default": "",
          "description": "Path to the mini demo data JSON (curated subset). Example: 'mini_demo_data.json'",
          "title": "Mini Data File",
          "type": "string"
        }
      },
      "title": "DemoExpectedFiles",
      "type": "object"
    }
  },
  "description": "Dataset/experiment/evaluation \u2192 Jupyter notebook demo.\n\nTitle and summary come from the parent artifact (gen_art step),\nnot from the demo agent. The agent only outputs expected files.",
  "properties": {
    "out_expected_files": {
      "$ref": "#/$defs/DemoExpectedFiles",
      "description": "All output files you created. Must include the demo notebook."
    }
  },
  "required": [],
  "title": "CodeDemo",
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
</prompt>
</pasted_content id="49e8">
````

### [3] TOOL CALL — Skill · 2026-09-23 18:39:14 UTC

```
aii-colab
```

### [4] TOOL CALL — Skill · 2026-09-23 18:39:14 UTC

```
aii-long-running-tasks
```

### [5] TOOL RESULT — Skill · 2026-09-23 18:39:14 UTC

```
{"success": true, "commandName": "aii-colab"}
```

### [6] TOOL RESULT — Skill · 2026-09-23 18:39:14 UTC

```
{"success": true, "commandName": "aii-long-running-tasks"}
```

### [7] TOOL CALL — Bash · 2026-09-23 18:39:16 UTC

```
W=/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_dataset_1; ls -la $W; ls $W/full_data_out; wc -l $W/data.py; ls -la .; ls .aii
```

### [8] TOOL RESULT — Bash · 2026-09-23 18:39:16 UTC

```
{"stdout": "total 26138\ndrwxr-xr-x 11 root root 2012665 Sep 23 13:49 .\ndrwxr-xr-x  5 root root 2023329 Sep 23 12:03 ..\ndrwxr-xr-x  2 root root 1000106 Sep 23 13:09 .aii\n-rw-r--r--  1 root root 2428700 Sep 23 12:53 .aii_cost_ledger.jsonl\n-rw-r--r--  1 root root 2021084 Sep 23 13:09 .repl_agent.ptylog\n-rw-r--r--  1 root root    3131 Sep 23 13:07 .terminal_claude_agent_struct_out.json\n-rw-r--r--  1 root root   25641 Sep 23 13:09 README.md\n-rw-r--r--  1 root root 5059191 Sep 23 12:53 cost_ledger.jsonl\n-rw-r--r--  1 root root    8770 Sep 23 13:01 data.py\ndrwxr-xr-x  2 root root 2005903 Sep 23 13:04 full_data_out\n-rw-r--r--  1 root root   29017 Sep 23 13:03 label_report.json\ndrwxr-xr-x  2 root root 1003145 Sep 23 13:01 logs\n-rw-r--r--  1 root root   56422 Sep 23 13:04 mini_full_data_out.json\n-rw-r--r--  1 root root   53404 Sep 23 13:04 preview_full_data_out.json\ndrwxr-xr-x  2 root root 1000541 Sep 23 12:21 prompts\n-rw-r--r--  1 root root     226 Sep 23 12:04 pyproject.toml\n-rw-r--r--  1 root root       9 Sep 23 12:14 pytest.ini\ndrwxr-xr-x  5 root root 2002435 Sep 23 13:49 raw\n-rwxr-xr-x  1 root root    2915 Sep 23 12:58 restore.sh\ndrwxr-xr-x  2 root root 1018158 Sep 23 13:49 src\ndrwxr-xr-x  5 root root 2000565 Sep 23 12:11 temp\ndrwxr-xr-x  2 root root 1000380 Sep 23 13:49 tests\ndrwxr-xr-x  2 root root 2002815 Sep 23 13:00 work\nfull_data_out_1.json\nfull_data_out_2.json\nfull_data_out_3.json\nmini_full_data_out_1.json\nmini_full_data_out_2.json\nmini_full_data_out_3.json\npreview_full_data_out_1.json\npreview_full_data_out_2.json\npreview_full_data_out_3.json\n186 /ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_dataset_1/data.py\ntotal 2007\ndrwxr-xr-x 3 root root 1003018 Sep 23 18:39 .\ndrwxr-xr-x 5 root root 1019141 Sep 23 18:37 ..\ndrwxr-xr-x 2 root root       1 Sep 23 18:37 .aii\n-rw-r--r-- 1 root root   30907 Sep 23 18:39 .repl_agent.ptylog", "stderr": "", "interrupted": false, "isImage": false, "noOutputExpected": false}
```

### [9] TOOL CALL — Bash · 2026-09-23 18:39:20 UTC

```
W=/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_dataset_1; cat $W/data.py; ls $W/src $W/temp $W/temp/*| head -50; cat $W/pyproject.toml
```

### [10] TOOL RESULT — Bash · 2026-09-23 18:39:20 UTC

```
{"stdout": "# /// script\n# requires-python = \">=3.12\"\n# dependencies = [\"loguru\"]\n# ///\n\"\"\"Build full_data_out.json (exp_sel_data_out) for the held-out NL->FOL faithfulness dataset.\n\nInputs\n- work/assembled_data_out.json.gz : the 5 labelled groups produced by the pipeline in src/\n  (prep_sources -> generate -> label_l1 -> calibrate -> audit -> l3_adjudicate/l3_extra -> e1 -> e2 -> assemble).\n- temp/datasets/ : the source datasets. EVERY row is re-verified against them here:\n    heldout_confirm / heldout_samples : sentence + original gold == the MALLS-v0.1-test / FOLIO-v2-train /\n                                        ProverQA-dev source record named by metadata_source_id; paper-corrected\n                                        gold == DSAVlab-UNIUD curated record\n    screen_gold_audit                 : sentence + gold in FOLIO v0.0 validation; the Logic-LM line exists in\n                                        FOLIO_dev_<system>.json\n    contamination                     : original sentence == the held-out sentence it was derived from\n    transfer_unlabeled                : candidate formula == the pilot 04_fol.json it came from\n  Result stored per row as metadata_source_verified (+ metadata_source_file). Rows are never dropped.\n\nOne example per data row (candidate formalization); grouped by dataset (= split).\nRun: uv run data.py\n\"\"\"\nfrom __future__ import annotations\n\nimport ast\nimport gzip\nimport json\nimport re\nimport sys\nfrom collections import Counter\nfrom pathlib import Path\n\nfrom loguru import logger\n\nROOT = Path(__file__).resolve().parent\nTD = ROOT / \"temp\" / \"datasets\"\n(ROOT / \"logs\").mkdir(exist_ok=True)\nlogger.remove()\nlogger.add(sys.stdout, level=\"INFO\", format=\"{time:HH:mm:ss}|{level:<7}|{message}\")\nlogger.add(ROOT / \"logs\" / \"data_py.log\", rotation=\"30 MB\", level=\"DEBUG\")\n\nGROUP_ORDER = [\"heldout_confirm\", \"heldout_samples\", \"screen_gold_audit\", \"contamination\", \"transfer_unlabeled\"]\nFORBIDDEN = {\"split\", \"dataset\", \"context\"}\n\n\ndef norm(s: str) -> str:\n    s = re.sub(r\"\\s+\", \" \", s.strip().lower())\n    return s[:-1].strip() if s.endswith(\".\") else s\n\n\ndef ws(s: str) -> str:\n    return re.sub(r\"\\s+\", \" \", (s or \"\").strip())\n\n\ndef read_jsonl(p: Path) -> list[dict]:\n    return [json.loads(l) for l in p.read_text(encoding=\"utf-8\").splitlines() if l.strip()]\n\n\ndef load_sources() -> dict:\n    src = {}\n    src[\"malls\"] = json.loads((TD / \"yuan-yang__MALLS-v0\" / \"MALLS-v0.1-test.json\").read_text())\n    src[\"malls_cur\"] = {c[\"id\"] - 1: c for c in read_jsonl(TD / \"DSAVlab-UNIUD__MALLS_test_subset-CURATED\" / \"MALLS_instances.jsonl\")}\n    src[\"folio_train\"] = {str(r[\"example_id\"]): r for r in read_jsonl(TD / \"tasksource__folio\" / \"folio_v2_train.jsonl\")}\n    src[\"proverqa\"] = {}\n    for lvl in (\"medium\", \"hard\"):\n        for it in json.loads((TD / \"opendatalab__ProverQA\" / \"dev\" / f\"{lvl}.json\").read_text()):\n            d = it[\"nl2fol\"]\n            d = ast.literal_eval(d) if isinstance(d, str) else d\n            src[\"proverqa\"][(lvl, str(it[\"id\"]))] = list(d.items())\n    gh = TD / \"github_FOLIO_v0.0_and_LogicLM_outputs\"\n    val = {}\n    for s in read_jsonl(gh / \"folio-validation_v0.0.jsonl\"):\n        p = s[\"premises\"]\n        p = ast.literal_eval(p) if isinstance(p, str) and p.startswith(\"[\") else p\n        pf = s[\"premises-FOL\"]\n        pf = ast.literal_eval(pf) if isinstance(pf, str) and pf.startswith(\"[\") else pf\n        for nl, f in list(zip(p, pf)) + [(s[\"conclusion\"], s[\"conclusion-FOL\"])]:\n            val.setdefault(norm(nl), set()).add(ws(f))\n    src[\"folio_v1_val\"] = val\n    src[\"logiclm\"] = {}\n    for sysname in (\"gpt-3.5-turbo\", \"gpt-4\", \"text-davinci-003\"):\n        txt = \"\\n\".join(ex[\"raw_logic_programs\"][0] for ex in json.loads((gh / f\"FOLIO_dev_{sysname}.json\").read_text())\n                        if ex.get(\"raw_logic_programs\"))\n        src[\"logiclm\"][f\"logiclm_{sysname}\"] = {ws(l) for l in txt.split(\"\\n\") if \":::\" in l}\n    return src\n\n\ndef verify_heldout(ex: dict, src: dict) -> tuple[bool, str]:\n    inp = json.loads(ex[\"input\"])\n    sent, gold, sid = inp[\"sentence\"], ex[\"metadata_gold_fol_original\"], ex[\"metadata_source_id\"]\n    m = re.match(r\"malls_test_(\\d+)$\", sid)\n    if m:\n        i = int(m.group(1))\n        rec = src[\"malls\"][i]\n        ok = ws(rec[\"NL\"]) == ws(sent) and ws(rec[\"FOL\"]) == ws(gold)\n        if ex.get(\"metadata_gold_fol_paper\"):\n            ok = ok and ws(src[\"malls_cur\"][i][\"FOL_sentence_new\"]) == ws(ex[\"metadata_gold_fol_paper\"])\n        return ok, f\"yuan-yang__MALLS-v0/MALLS-v0.1-test.json[{i}]\"\n    m = re.match(r\"folio_train_story(\\w+)_ex(\\w+)_(p\\d+|c)$\", sid)\n    if m:\n        rec = src[\"folio_train\"].get(m.group(2))\n        if rec is None:\n            return False, \"tasksource__folio/folio_v2_train.jsonl (example missing)\"\n        pos = m.group(3)\n        if pos == \"c\":\n            nl, fol = rec[\"conclusion\"], rec[\"conclusion-FOL\"]\n        else:\n            j = int(pos[1:])\n            nl = [l for l in rec[\"premises\"].split(\"\\n\") if l.strip()][j]\n            fol = [l for l in rec[\"premises-FOL\"].split(\"\\n\") if l.strip()][j]\n        return ws(nl) == ws(sent) and ws(fol) == ws(gold), f\"tasksource__folio/folio_v2_train.jsonl[example_id={m.group(2)},{pos}]\"\n    m = re.match(r\"proverqa_dev_(medium|hard)_(\\w+)_(\\d+)$\", sid)\n    if m:\n        items = src[\"proverqa\"].get((m.group(1), m.group(2)))\n        if items is None:\n            return False, \"opendatalab__ProverQA (item missing)\"\n        nl, fol = items[int(m.group(3))]\n        return ws(nl) == ws(sent) and ws(fol) == ws(gold), f\"opendatalab__ProverQA/dev/{m.group(1)}.json[id={m.group(2)}][{m.group(3)}]\"\n    return False, \"unknown source_id pattern\"\n\n\ndef verify_screen(ex: dict, src: dict) -> tuple[bool, str]:\n    inp = json.loads(ex[\"input\"])\n    golds = src[\"folio_v1_val\"].get(norm(inp[\"sentence\"]), set())\n    ok_gold = ws(ex[\"metadata_gold_fol_original\"]) in golds\n    ok_line = ws(ex[\"metadata_raw_output\"]) in src[\"logiclm\"].get(ex[\"metadata_system\"], set())\n    return ok_gold and ok_line, f\"github FOLIO v0.0 validation + Logic-LLM FOLIO_dev_{ex['metadata_system'].replace('logiclm_', '')}.json\"\n\n\ndef verify_transfer(ex: dict) -> tuple[bool, str]:\n    rel = ex[\"metadata_source_path\"].replace(\"raw/pilot/\", \"\", 1)\n    p = TD / \"user_dpv_pilot\" / rel\n    if not p.exists():\n        return False, str(p.relative_to(ROOT))\n    try:\n        fol = json.loads(p.read_text()).get(\"fol\", \"\")\n    except json.JSONDecodeError:\n        fol = p.read_text()\n    return ws(fol) == ws(json.loads(ex[\"input\"])[\"candidate_fol\"]), f\"temp/datasets/user_dpv_pilot/{rel}\"\n\n\n@logger.catch(reraise=True)\ndef main() -> None:\n    with gzip.open(ROOT / \"work\" / \"assembled_data_out.json.gz\", \"rt\", encoding=\"utf-8\") as fh:\n        data = json.load(fh)\n    src = load_sources()\n    logger.info(f\"sources loaded: malls={len(src['malls'])} folio_train={len(src['folio_train'])} proverqa_items={len(src['proverqa'])}\")\n    groups = {d[\"dataset\"]: d[\"examples\"] for d in data[\"datasets\"]}\n    held_sent = {}\n    for ex in groups.get(\"heldout_confirm\", []):\n        held_sent[ex[\"metadata_sentence_id\"]] = json.loads(ex[\"input\"])[\"sentence\"]\n    stats = {}\n    out = []\n    for g in GROUP_ORDER:\n        rows = groups.get(g, [])\n        c = Counter()\n        for ex in rows:\n            assert isinstance(ex[\"input\"], str) and isinstance(ex[\"output\"], str), ex.get(\"metadata_item_id\")\n            bad = FORBIDDEN & set(ex)\n            assert not bad, bad\n            assert all(k in (\"input\", \"output\") or k.startswith(\"metadata_\") for k in ex), ex.keys()\n            if g in (\"heldout_confirm\", \"heldout_samples\"):\n                ok, f = verify_heldout(ex, src)\n            elif g == \"screen_gold_audit\":\n                ok, f = verify_screen(ex, src)\n            elif g == \"contamination\":\n                ok = held_sent.get(ex[\"metadata_sentence_id\"]) == ex[\"metadata_original_sentence\"]\n                f = \"derived from heldout_confirm sentence \" + ex[\"metadata_sentence_id\"]\n            else:\n                ok, f = verify_transfer(ex)\n            ex[\"metadata_source_verified\"] = bool(ok)\n            ex[\"metadata_source_file\"] = f\n            c[ok] += 1\n        stats[g] = {\"rows\": len(rows), \"source_verified\": c[True], \"not_verified\": c[False],\n                    \"labels\": dict(Counter(ex[\"output\"] for ex in rows))}\n        logger.info(f\"{g}: {stats[g]}\")\n        out.append({\"dataset\": g, \"examples\": rows})\n    meta = dict(data[\"metadata\"])\n    meta[\"source_verification\"] = stats\n    meta[\"groups\"] = GROUP_ORDER\n    (ROOT / \"full_data_out.json\").write_text(json.dumps({\"metadata\": meta, \"datasets\": out}, ensure_ascii=False))\n    logger.info(f\"wrote full_data_out.json: {sum(len(d['examples']) for d in out)} examples in {len(out)} datasets\")\n\n\nif __name__ == \"__main__\":\n    main()\n/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_dataset_1/temp/bg_preview_search.log\n/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_dataset_1/temp/hf_search.txt\n\n/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_dataset_1/src:\n_jl.py\nassemble.py\naudit.py\ncalibrate.py\ncalibrate_variants.py\ne1_contamination.py\ne2_transfer.py\nfix_varlike_patch.py\nfol_equiv.py\nfol_granular.py\nfol_parse.py\ngenerate.py\nl3_adjudicate.py\nl3_extra.py\nlabel_l1.py\nor_client.py\npanel.py\nprep_sources.py\npreview_candidates.py\nreextract.py\nsplit_outputs.py\n\n/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_dataset_1/temp:\nbg_preview_search.log\ndatasets\nhf_search.txt\npreviews\nwebsearch\n\n/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_dataset_1/temp/datasets:\nDSAVlab-UNIUD__FOLIO_validation-curated\nDSAVlab-UNIUD__MALLS_test_subset-CURATED\ngithub_FOLIO_v0.0_and_LogicLM_outputs\nkenken6696__MALLS_by_ccg2lambda\nkenken6696__folio_by_ccg2lambda\nopendatalab__ProverQA\ntasksource__folio\nuser_dpv_pilot\nyfxiao__folio-refined\nyuan-yang__MALLS-v0\n\n/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_dataset_1/temp/previews:\nDSAVlab-UNIUD_FOLIO_validation-curated.txt\nDSAVlab-UNIUD_MALLS_test_subset-CURATED.txt\nIsotonic_symbolic_data_first_order_logic.txt\nbenlipkin_folio.txt\n[project]\nname = \"nl2fol-heldout-dataset\"\nversion = \"0.1.0\"\nrequires-python = \">=3.12\"\ndependencies = [\"z3-solver\", \"nltk\", \"aiohttp\", \"loguru\", \"huggingface_hub\", \"numpy\", \"scipy\", \"tenacity\", \"requests\", \"pyyaml\", \"pytest\"]", "stderr": "", "interrupted": false, "isImage": false, "noOutputExpected": false}
```

### [11] TOOL CALL — Bash · 2026-09-23 18:39:28 UTC

```
W=/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_dataset_1; cd $W; ls -la full_data_out work; python3 -c "
import json
d=json.load(open('full_data_out/preview_full_data_out_1.json'))
print(d.keys()); print(json.dumps(d['metadata'])[:3000])
for g in d['datasets']:
  print(g['dataset'], len(g['examples']))
ex=d['datasets'][0]['examples'][0]
print(json.dumps(ex,indent=1)[:6000])
"
```

### [12] TOOL RESULT — Bash · 2026-09-23 18:39:28 UTC

```
{"stdout": "full_data_out:\ntotal 64379\ndrwxr-xr-x  2 root root  2005903 Sep 23 13:04 .\ndrwxr-xr-x 11 root root  2012665 Sep 23 13:49 ..\n-rw-r--r--  1 root root 20970804 Sep 23 13:04 full_data_out_1.json\n-rw-r--r--  1 root root 20972626 Sep 23 13:04 full_data_out_2.json\n-rw-r--r--  1 root root 19777436 Sep 23 13:04 full_data_out_3.json\n-rw-r--r--  1 root root    18295 Sep 23 13:04 mini_full_data_out_1.json\n-rw-r--r--  1 root root    32616 Sep 23 13:04 mini_full_data_out_2.json\n-rw-r--r--  1 root root    42101 Sep 23 13:04 mini_full_data_out_3.json\n-rw-r--r--  1 root root    17977 Sep 23 13:04 preview_full_data_out_1.json\n-rw-r--r--  1 root root    32255 Sep 23 13:04 preview_full_data_out_2.json\n-rw-r--r--  1 root root    38706 Sep 23 13:04 preview_full_data_out_3.json\n\nwork:\ntotal 32757\ndrwxr-xr-x  2 root root 2002815 Sep 23 13:00 .\ndrwxr-xr-x 11 root root 2012665 Sep 23 13:49 ..\n-rw-r--r--  1 root root 1976932 Sep 23 13:03 assembled_data_out.json.gz\n-rw-r--r--  1 root root 1447356 Sep 23 12:46 audit_results.json\n-rw-r--r--  1 root root   20888 Sep 23 12:32 calibration_results.json\n-rw-r--r--  1 root root   16333 Sep 23 12:18 calibration_set.json\n-rw-r--r--  1 root root   10168 Sep 23 12:27 calibration_variants.json\n-rw-r--r--  1 root root  792878 Sep 23 12:50 e1_results.json\n-rw-r--r--  1 root root  460963 Sep 23 12:40 e2_rows.json\n-rw-r--r--  1 root root   18747 Sep 23 12:46 fol_parse_v1_buggy_varlike.py\n-rw-r--r--  1 root root 5157578 Sep 23 12:18 gold_checks.json\n-rw-r--r--  1 root root  619662 Sep 23 12:46 heldout_sentences.json\n-rw-r--r--  1 root root 4385723 Sep 23 12:47 l1_cache.jsonl\n-rw-r--r--  1 root root 4413160 Sep 23 12:43 l1_cache_v1_buggy.jsonl\n-rw-r--r--  1 root root  976977 Sep 23 12:53 l3_results.json\n-rw-r--r--  1 root root  802111 Sep 23 12:18 openrouter_catalog.json\n-rw-r--r--  1 root root 4487397 Sep 23 12:53 panel_cache.jsonl\n-rw-r--r--  1 root root     959 Sep 23 12:32 panel_config.json\n-rw-r--r--  1 root root 3366156 Sep 23 12:18 pool.json\n-rw-r--r--  1 root root    3063 Sep 23 12:18 prep_report.json\n-rw-r--r--  1 root root  565778 Sep 23 12:18 screen_sentences.json\ndict_keys(['metadata', 'datasets'])\n{\"description\": \"Held-out NL->FOL faithfulness meta-evaluation dataset (run_qY2a2IS-WLIs iter 1): real candidates from 9 current systems on MALLS-test / FOLIO-v2-train / ProverQA-dev sentences, audited gold, layered l\", \"generation_prompt_sha1\": \"afabb41eedb31b3ee96e32419bd8e4abd727f758\", \"systems\": {\"llama-3.1-8b\": \"meta-llama/llama-3.1-8b-instruct\", \"qwen-2.5-7b\": \"qwen/qwen-2.5-7b-instruct\", \"mistral-small-3.2-24b\": \"mistralai/mistral-small-3.2-24b-instruct\", \"gpt-4.1-mini\": \"openai/gpt-4.1-mini\", \"gemini-2.5-flash\": \"google/gemini-2.5-flash\", \"deepseek-v3.1\": \"deepseek/deepseek-chat-v3.1\", \"gemma-3-27b\": \"google/gemma-3-27b-it\", \"phi-4\": \"microsoft/phi-4\", \"gpt-oss-120b\": \"openai/gpt-oss-120b\"}, \"panel\": {\"M1\": \"anthropic/claude-haiku-4.5\", \"M2\": \"x-ai/grok-4.3\", \"M3\": \"z-ai/glm-4.6\"}, \"complexity_params\": {\"z_params\": {\"n_tokens\": {\"mean\": 14.151756129887342, \"sd\": 5.718208691194396}, \"n_quantifiers\": {\"mean\": 0.8212944554892865, \"sd\": 0.7597397068171663}, \"nesting_depth\": {\"mean\": 3.075988513364259, \"sd\": 1.4701222328271382}, \"n_conditions\": {\"mean\": 2.559752595537884, \"sd\": 1.7485292679079376}}, \"tercile_cutpoints\": [-0.25394332419591126, 0.09037598003908619], \"pool_size\": 4527, \"composite\": \"mean of 4 z-scores\", \"features\": [\"n_tokens\", \"n_quantifiers\", \"nesting_depth\", \"n_conditions\"]}, \"label_precedence\": [\"panel3\", \"equiv_synthetic_gold\", \"equiv_audited_gold\", \"unknown\"], \"source_verification\": {\"heldout_confirm\": {\"rows\": 6300, \"source_verified\": 6300, \"not_verified\": 0, \"labels\": {\"unknown\": 453, \"faithful\": 2217, \"unfaithful\": 3630}}, \"heldout_samples\": {\"rows\": 7000, \"source_verified\": 7000, \"not_verified\": 0, \"labels\": {\"unknown\": 825, \"unfaithful\": 4153, \"faithful\": 2022}}, \"screen_gold_audit\": {\"rows\": 1003, \"source_verified\": 1003, \"not_verified\": 0, \"labels\": {\"faithful\": 488, \"unfaithful\": 461, \"unknown\": 54}}, \"contamination\": {\"rows\": 936, \"source_verified\": 936, \"not_verified\": 0, \"labels\": {\"faithful\": 179, \"unfaithful\": 686, \"unknown\": 71}}, \"transfer_unlabeled\": {\"rows\": 367, \"source_verified\": 367, \"not_verified\": 0, \"labels\": {\"unlabeled\": 367}}}, \"groups\": [\"heldout_confirm\", \"heldout_samples\", \"screen_gold_audit\", \"contamination\", \"transfer_unlabeled\"], \"part\": 1, \"n_parts\": 3}\nheldout_confirm 3\n{\n \"input\": \"{\\\"sentence\\\": \\\"There are no elements with atomic number between 61-63 that are not scarce in China.\\\", \\\"candidate_fol\\\": \\\"\\u00ac\\u2203x (AtomicNumberBetween61And63(x) \\u2227 \\u00acScarceInChina(x))\\\"}\",\n \"output\": \"unknown\",\n \"metadata_fold\": \"heldout_confirm\",\n \"metadata_item_id\": \"00176f9c72:deepseek-v3.1:0\",\n \"metadata_sentence_id\": \"00176f9c72\",\n \"metadata_corpus\": \"folio\",\n \"metadata_corpus_subset\": \"folio_v2_train\",\n \"metadata_source_id\": \"folio_train_story390_ex1044_p0\",\n \"metadata_story_id\": \"390\",\n \"metadata_licence\": \"MIT\",\n \"metadata_system\": \"deepseek-v3.1\",\n \"metadata_model\": \"deepseek/deepseek-chat-v3.1\",\n \"metadata_system_tier\": \"required\",\n \"metadata_provider\": \"AtlasCloud\",\n \"metadata_sample_idx\": 0,\n \"metadata_temperature\": 0.0,\n \"metadata_raw_output\": \"\\u00ac\\u2203x (AtomicNumberBetween61And63(x) \\u2227 \\u00acScarceInChina(x))\",\n \"metadata_parse_ok\": true,\n \"metadata_parse_error\": \"\",\n \"metadata_parse_notes\": [],\n \"metadata_finish_reason\": \"stop\",\n \"metadata_prompt_sha1\": \"afabb41eedb31b3ee96e32419bd8e4abd727f758\",\n \"metadata_extractor_version\": 2,\n \"metadata_gold_fol_original\": \"\\u2200x ((Element(x) \\u2227 \\u2203y(Between(y, num61, num63) \\u2227 AtomicNumber(x, y))) \\u2192 ScarceIn(x, china))\",\n \"metadata_gold_fol_audited\": null,\n \"metadata_gold_source\": \"panel_flagged_uncorrected\",\n \"metadata_gold_parse_ok\": true,\n \"metadata_gold_fol_paper\": null,\n \"metadata_paper_corrected_flag\": null,\n \"metadata_gold_fol_refined\": \"\\u2200x \\u2200y ((Element(x) \\u2227 \\u2203y(Between(y, num61, num63) \\u2227 AtomicNumber(x, y))) \\u2192 ScarceIn(x, china))\",\n \"metadata_gold_audit_votes\": {\n  \"M2\": {\n   \"faithful\": true,\n   \"sentence_ambiguous\": false,\n   \"error_types\": [\n    \"none\"\n   ],\n   \"primary_error\": \"none\",\n   \"explanation\": \"Formula correctly encodes the double negation as universal implication over the stated conditions.\",\n   \"model\": \"x-ai/grok-4.3\"\n  },\n  \"M3\": {\n   \"faithful\": false,\n   \"sentence_ambiguous\": false,\n   \"error_types\": [\n    \"negation_polarity\"\n   ],\n   \"primary_error\": \"negation_polarity\",\n   \"explanation\": \"The sentence asserts non-existence, requiring a negated existential or universal with negated consequent. The formula uses a positive universal, incorrectly stating all such elements are scarce.\",\n   \"model\": \"z-ai/glm-4.6\"\n  },\n  \"M1\": {\n   \"faithful\": false,\n   \"sentence_ambiguous\": false,\n   \"error_types\": [\n    \"negation_polarity\"\n   ],\n   \"primary_error\": \"negation_polarity\",\n   \"explanation\": \"The sentence states 'no elements...that are NOT scarce', meaning all such elements ARE scarce. The formula correctly captures this, but the negation is implicit in the English. The formula is actually\",\n   \"model\": \"anthropic/claude-haiku-4.5\"\n  }\n },\n \"metadata_gold_faithful_final\": false,\n \"metadata_sentence_ambiguous\": false,\n \"metadata_gold_audit_primary_error\": \"negation_polarity\",\n \"metadata_gold_audit_cascade_rule\": \"M1_tiebreak\",\n \"metadata_gold_audit_full_panel_subset\": false,\n \"metadata_gold_correction_status\": \"M1:empty;M3:equivalent_to_original\",\n \"metadata_L1_orig_status\": \"non_equiv_no_bijection\",\n \"metadata_L1_orig_mapping\": null,\n \"metadata_L1_orig_entail_cand_to_gold\": null,\n \"metadata_L1_orig_entail_gold_to_cand\": null,\n \"metadata_L1_orig_method\": null,\n \"metadata_L1_orig_max_domain\": null,\n \"metadata_L1_orig_seconds\": 0.001,\n \"metadata_L1_audited_status\": \"no_audited_gold\",\n \"metadata_L1_audited_mapping\": null,\n \"metadata_L1_audited_entail_cand_to_gold\": null,\n \"metadata_L1_audited_entail_gold_to_cand\": null,\n \"metadata_L1_audited_method\": null,\n \"metadata_L1_audited_max_domain\": null,\n \"metadata_L1_audited_seconds\": null,\n \"metadata_L2_status\": null,\n \"metadata_L2_definitions\": null,\n \"metadata_L2_lexical\": true,\n \"metadata_L2_orig_status\": \"not_applicable\",\n \"metadata_L3_selected\": false,\n \"metadata_L3_sampling_weight\": null,\n \"metadata_L3_design_weight\": null,\n \"metadata_L3_design_stratum\": null,\n \"metadata_L3_poststratum\": null,\n \"metadata_L3_votes\": null,\n \"metadata_L3_majority\": null,\n \"metadata_L3_primary_error\": null,\n \"metadata_L3_dissent\": null,\n \"metadata_L3_gold_shown_as\": null,\n \"metadata_label_source\": \"unknown\",\n \"metadata_L3_stratum_p_faithful\": null,\n \"metadata_n_tokens\": 15,\n \"metadata_n_quantifiers\": 2,\n \"metadata_nesting_depth\": 5,\n \"metadata_n_conditions\": 2,\n \"metadata_complexity_composite\": 0.6721,\n \"metadata_complexity_tercile\": \"top\",\n \"metadata_complexity_gold_used\": \"gold_fol_original\",\n \"metadata_gen_usd\": 6.415e-05,\n \"metadata_gen_seconds\": 1.68,\n \"metadata_source_verified\": true,\n \"metadata_source_file\": \"tasksource__folio/folio_v2_train.jsonl[example_id=1044,p0]\"\n}", "stderr": "\nShell cwd was reset to /ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/4_gen_paper_repo/_4_gen_demo_art/notebook_workspaces/iter_1/art_iyzYyaqlqpSX", "interrupted": false, "isImage": false, "noOutputExpected": false}
```

### [13] TOOL CALL — Bash · 2026-09-23 18:39:42 UTC

```
W=/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_dataset_1; cd $W; python3 -c "
import json,collections
for p in (1,2,3):
  d=json.load(open(f'full_data_out/full_data_out_{p}.json'))
  for g in d['datasets']: print(p,g['dataset'],len(g['examples']))
d=json.load(open('full_data_out/full_data_out_1.json'))
rows=d['datasets'][0]['examples']
C=collections.Counter
print(C(r['metadata_corpus_subset'] for r in rows)); print(C(r['metadata_label_source'] for r in rows)); print(C(r['metadata_parse_ok'] for r in rows)); print(C(bool(r['metadata_gold_fol_paper']) for r in rows)); print(C(r['metadata_L1_orig_status'] for r in rows)); print(C(r['metadata_source_id'].rsplit('_',1)[0][:20] for r in rows).most_common(5))
"; head -c 600 temp/datasets/tasksource__folio/folio_v2_train.jsonl; echo; head -c 800 temp/datasets/opendatalab__ProverQA/dev/hard.json; echo; head -c 500 temp/datasets/DSAVlab-UNIUD__MALLS_test_subset-CURATED/MALLS_instances.jsonl; echo; head -c 300 temp/datasets/yuan-yang__MALLS-v0/MALLS-v0.1-test.json
```

### [14] TOOL RESULT — Bash · 2026-09-23 18:39:44 UTC

```
{"stdout": "1 heldout_confirm 4906\n2 heldout_confirm 1394\n2 heldout_samples 3587\n3 heldout_samples 3413\n3 screen_gold_audit 1003\n3 contamination 936\n3 transfer_unlabeled 367\nCounter({'folio_v2_train': 2052, 'malls_v0.1_test': 1116, 'proverqa_hard': 1018, 'proverqa_medium': 720})\nCounter({'equiv_audited_gold': 2785, 'equiv_synthetic_gold': 1278, 'panel3': 463, 'unknown': 380})\nCounter({True: 4669, False: 237})\nCounter({False: 4744, True: 162})\nCounter({'non_equiv_no_bijection': 2839, 'equiv_proved': 1353, 'non_equiv': 468, 'unparseable': 237, 'unknown_capped': 9})\n[('malls_test', 1116), ('proverqa_dev_medium_', 720), ('proverqa_dev_hard_16', 72), ('proverqa_dev_hard_22', 54), ('proverqa_dev_hard_33', 45)]\n{\"story_id\": 406, \"premises\": \"All people who regularly drink coffee are dependent on caffeine.\\nPeople regularly drink coffee, or they don't want to be addicted to caffeine, or both.\\nNo one who doesn't want to be addicted to caffeine is unaware that caffeine is a drug.\\nRina is either a student who is unaware that caffeine is a drug, or she is not a student and is she aware that caffeine is a drug.\\nRina  is either a student who is dependent on caffeine, or she is not a student and not dependent on caffeine.\", \"premises-FOL\": \"\\u2200x (DrinkRegularly(x, coffee) \\u2192 IsDependentOn(x, caffei\n[\n  {\n    \"id\": 0,\n    \"options\": [\n      \"A) True\",\n      \"B) False\",\n      \"C) Uncertain\"\n    ],\n    \"answer\": \"A\",\n    \"question\": \"Based on the above information, is the following statement true, false, or uncertain? Legend has a distinctive marking.\",\n    \"reasoning\": \"fact1: Legend does not have an athletic build.\\nfact2: Legend is not competitive.\\nrule: If Legend either has strong muscles or has an athletic build, then he is competitive.\\nconclusion: Legend does not have strong muscles.\\n\\nfact1: Legend is well-trained.\\nrule: Legend is either well-trained or has a racing background, but not both.\\nconclusion: Legend does not have a racing background.\\n\\nfact1: Legend has a good temperament.\\nrule: Legend is either fast or has a good temperament, but not both.\\nconclusion: Legend i\n{\"NL_sentence\": \"A vacation is relaxing if it includes beautiful scenery and enjoyable activities.\", \"FOL_sentence_old\": \"∀x (Vacation(x) ∧ Relaxing(x) → (BeautifulScenery(x) ∧ EnjoyableActivities(x)))\", \"FOL_sentence_new\": \"∀x (Vacation(x) → ((BeautifulScenery(x) ∧ EnjoyableActivities(x)) → Relaxing(x)))\", \"corrected\": \"yes\", \"correction_explanation\": \"1. The original formula inverted the implication symbols\", \"id\": 1}\n{\"NL_sentence\": \"A gemstone can be a diamond, a ruby, or an \n[{\"NL\": \"A vacation is relaxing if it includes beautiful scenery and enjoyable activities.\", \"FOL\": \"\\u2200x (Vacation(x) \\u2227 Relaxing(x) \\u2192 (BeautifulScenery(x) \\u2227 EnjoyableActivities(x)))\"}, {\"NL\": \"A gemstone can be a diamond, a ruby, or an emerald, but not more than one type of gemsto", "stderr": "\nShell cwd was reset to /ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/4_gen_paper_repo/_4_gen_demo_art/notebook_workspaces/iter_1/art_iyzYyaqlqpSX", "interrupted": false, "isImage": false, "noOutputExpected": false}
```

### [15] ASSISTANT · 2026-09-23 18:40:02 UTC

```
I'm building the curated 100-row subset from heldout_confirm, with the source records the verification step needs bundled in.
```

### [16] TOOL CALL — Bash · 2026-09-23 18:40:02 UTC

```
mkdir -p /ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/4_gen_paper_repo/_4_gen_demo_art/notebook_workspaces/iter_1/art_iyzYyaqlqpSX/scripts; cat > /ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/4_gen_paper_repo/_4_gen_demo_art/notebook_workspaces/iter_1/art_iyzYyaqlqpSX/scripts/build_mini_demo_data.py <<'EOF'
"""Build mini_demo_data.json: 100 diverse heldout_confirm rows + only the source records data.py needs to verify them."""
import ast, json, random, re
from collections import Counter
from pathlib import Path

W = Path("/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_dataset_1")
TD = W / "temp" / "datasets"
OUT = Path(__file__).resolve().parent.parent / "mini_demo_data.json"
random.seed(0)

d = json.load(open(W / "full_data_out" / "full_data_out_1.json"))
meta = {k: v for k, v in d["metadata"].items() if k not in ("source_verification", "groups", "part", "n_parts")}
rows = d["datasets"][0]["examples"]
assert d["datasets"][0]["dataset"] == "heldout_confirm"

# stratified pick: corpus subset x label, distinct systems where possible, plus special cases
picked, seen = [], set()
def take(r):
    if r["metadata_item_id"] not in seen:
        seen.add(r["metadata_item_id"]); picked.append(r)
random.shuffle(rows)
for sub in ("malls_v0.1_test", "folio_v2_train", "proverqa_hard", "proverqa_medium"):
    for lab in ("faithful", "unfaithful", "unknown"):
        cand = [r for r in rows if r["metadata_corpus_subset"] == sub and r["output"] == lab]
        systems = set()
        for r in cand:
            if len([p for p in picked if p["metadata_corpus_subset"] == sub and p["output"] == lab]) >= 7: break
            if r["metadata_system"] in systems: continue
            systems.add(r["metadata_system"]); take(r)
for pred, n in [(lambda r: not r["metadata_parse_ok"], 4), (lambda r: bool(r["metadata_gold_fol_paper"]), 5),
                (lambda r: r["metadata_label_source"] == "panel3", 6), (lambda r: r["metadata_complexity_tercile"] == "top", 5)]:
    for r in [r for r in rows if pred(r)][:n]: take(r)
picked = picked[:100]
for r in picked:  # data.py recomputes these two fields
    r.pop("metadata_source_verified", None); r.pop("metadata_source_file", None)

# source records referenced by the picked rows
malls = json.loads((TD / "yuan-yang__MALLS-v0" / "MALLS-v0.1-test.json").read_text())
cur = {json.loads(l)["id"] - 1: json.loads(l) for l in (TD / "DSAVlab-UNIUD__MALLS_test_subset-CURATED" / "MALLS_instances.jsonl").read_text().splitlines() if l.strip()}
ft = {str(json.loads(l)["example_id"]): json.loads(l) for l in (TD / "tasksource__folio" / "folio_v2_train.jsonl").read_text().splitlines() if l.strip()}
pq = {lvl: {str(it["id"]): it for it in json.loads((TD / "opendatalab__ProverQA" / "dev" / f"{lvl}.json").read_text())} for lvl in ("medium", "hard")}
S = {"malls_test": {}, "malls_curated": [], "folio_v2_train": [], "proverqa_dev_medium": [], "proverqa_dev_hard": []}
for r in picked:
    sid = r["metadata_source_id"]
    if m := re.match(r"malls_test_(\d+)$", sid):
        i = int(m.group(1)); S["malls_test"][str(i)] = malls[i]
        if r.get("metadata_gold_fol_paper") and cur[i] not in S["malls_curated"]: S["malls_curated"].append(cur[i])
    elif m := re.match(r"folio_train_story(\w+)_ex(\w+)_(p\d+|c)$", sid):
        rec = ft[m.group(2)]
        rec = {k: rec[k] for k in ("story_id", "example_id", "premises", "premises-FOL", "conclusion", "conclusion-FOL")}
        if rec not in S["folio_v2_train"]: S["folio_v2_train"].append(rec)
    elif m := re.match(r"proverqa_dev_(medium|hard)_(\w+)_(\d+)$", sid):
        it = pq[m.group(1)][m.group(2)]; it = {"id": it["id"], "nl2fol": it["nl2fol"]}
        if it not in S[f"proverqa_dev_{m.group(1)}"]: S[f"proverqa_dev_{m.group(1)}"].append(it)
out = {"metadata": meta, "datasets": [{"dataset": "heldout_confirm", "examples": picked}], "sources": S}
OUT.write_text(json.dumps(out, ensure_ascii=False))
C = Counter
print(len(picked), C(r["metadata_corpus_subset"] for r in picked), C(r["output"] for r in picked), C(r["metadata_system"] for r in picked),
      C(r["metadata_parse_ok"] for r in picked), sum(bool(r["metadata_gold_fol_paper"]) for r in picked), C(r["metadata_label_source"] for r in picked),
      {k: len(v) for k, v in S.items()}, OUT.stat().st_size)
EOF
cd /ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/4_gen_paper_repo/_4_gen_demo_art/notebook_workspaces/iter_1/art_iyzYyaqlqpSX && python3 scripts/build_mini_demo_data.py
```

### [17] TOOL RESULT — Bash · 2026-09-23 18:40:04 UTC

```
{"stdout": "88 Counter({'malls_v0.1_test': 25, 'folio_v2_train': 23, 'proverqa_hard': 20, 'proverqa_medium': 20}) Counter({'unfaithful': 34, 'faithful': 28, 'unknown': 26}) Counter({'qwen-2.5-7b': 12, 'deepseek-v3.1': 12, 'gemma-3-27b': 11, 'phi-4': 10, 'llama-3.1-8b': 10, 'gemini-2.5-flash': 9, 'mistral-small-3.2-24b': 9, 'gpt-oss-120b': 8, 'gpt-4.1-mini': 7}) Counter({True: 69, False: 19}) 5 Counter({'equiv_audited_gold': 33, 'unknown': 26, 'equiv_synthetic_gold': 20, 'panel3': 9}) {'malls_test': 23, 'malls_curated': 5, 'folio_v2_train': 23, 'proverqa_dev_medium': 18, 'proverqa_dev_hard': 17} 454581", "stderr": "", "interrupted": false, "isImage": false, "noOutputExpected": false}
```

### [18] TOOL CALL — Bash · 2026-09-23 18:40:06 UTC

```
sed -i 's/>= 7: break/>= 8: break/' scripts/build_mini_demo_data.py && python3 scripts/build_mini_demo_data.py
```

### [19] TOOL RESULT — Bash · 2026-09-23 18:40:08 UTC

```
{"stdout": "98 Counter({'malls_v0.1_test': 28, 'folio_v2_train': 26, 'proverqa_hard': 22, 'proverqa_medium': 22}) Counter({'unfaithful': 38, 'faithful': 32, 'unknown': 28}) Counter({'qwen-2.5-7b': 12, 'deepseek-v3.1': 12, 'phi-4': 11, 'gemma-3-27b': 11, 'gemini-2.5-flash': 11, 'mistral-small-3.2-24b': 11, 'llama-3.1-8b': 11, 'gpt-oss-120b': 10, 'gpt-4.1-mini': 9}) Counter({True: 79, False: 19}) 5 Counter({'equiv_audited_gold': 37, 'unknown': 28, 'equiv_synthetic_gold': 23, 'panel3': 10}) {'malls_test': 24, 'malls_curated': 5, 'folio_v2_train': 25, 'proverqa_dev_medium': 20, 'proverqa_dev_hard': 19} 503832", "stderr": "", "interrupted": false, "isImage": false, "noOutputExpected": false}
```

### [20] ASSISTANT · 2026-09-23 18:41:20 UTC

```
Now writing the notebook (built via a small generator script so cells stay faithful to data.py).
```

### [21] TOOL CALL — Bash · 2026-09-23 18:41:20 UTC

```
cat > scripts/build_notebook.py <<'PYEOF'
"""Generate code_demo.ipynb from data.py (cells copied from the original script, minimal notebook adaptations)."""
import json
from pathlib import Path

cells = []
def md(s): cells.append({"cell_type": "markdown", "metadata": {}, "source": s.strip("\n")})
def code(s): cells.append({"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": s.strip("\n")})

md(r'''
# Held-out NL→FOL Faithfulness Meta-Evaluation Set — `data.py` demo

This notebook walks through **`data.py`**, the final build step of the held-out NL→FOL faithfulness meta-evaluation dataset.
The full dataset (15,606 rows in 5 groups) holds **candidate first-order-logic formalizations** of natural-language sentences, each labelled
`faithful` / `unfaithful` / `unknown` with respect to the sentence. Candidates come from 9 current LLM systems prompted on
MALLS-v0.1-test, FOLIO-v2-train and ProverQA-dev sentences.

Labels are layered:
- **L0** – a family-disjoint 3-model panel (claude-haiku-4.5 / grok-4.3 / glm-4.6) audits the *gold* formula (wrong-gold rates: MALLS 45.6%, FOLIO-train 62%, ProverQA 17.5%).
- **L1** – lexical-free z3 equivalence to the (audited) gold, up to an arity-preserving bijection of predicate names.
- **L2** – WordNet granularity definitions.
- **L3** – blinded 3-model A/B adjudication (`panel3`) of 610 greedy items.

`data.py` itself does **not** call any model. It takes the labelled rows assembled by the upstream pipeline and
**re-verifies every row against the original public source files** (the sentence and gold formula must match the
MALLS / FOLIO / ProverQA record named by `metadata_source_id`), writes `metadata_source_verified` + `metadata_source_file`
on each row, and emits `full_data_out.json` with per-group statistics.

**Demo data.** `mini_demo_data.json` contains 98 diverse rows of the `heldout_confirm` group (all 4 corpus subsets, all 9 systems,
all 3 labels, unparseable outputs, MALLS rows with human-corrected gold) plus *only the source records needed to verify them*
(bundled under `sources`, replacing the multi-GB `temp/datasets/` directory the original script reads).
''')

code(r'''
import subprocess, sys
def _pip(*a): subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-q', *a])

# loguru — NOT pre-installed on Colab, always install
_pip('loguru==0.7.3')

# pandas, matplotlib — pre-installed on Colab, install locally only (at Colab's exact versions)
if 'google.colab' not in sys.modules:
    _pip('numpy==2.0.2', 'pandas==2.2.2', 'matplotlib==3.10.0')
''')

md(r'''
## Imports
The original import block of `data.py`, plus `pandas` / `matplotlib` for the results section.
''')
code(r'''
from __future__ import annotations

import ast
import gzip
import json
import re
import sys
from collections import Counter
from pathlib import Path

from loguru import logger

# notebook-only additions (results / visualization)
import pandas as pd
import matplotlib.pyplot as plt
''')

md(r'''
## Data loading
Loads `mini_demo_data.json` from GitHub, falling back to a local copy. Structure:
`{"metadata": {...}, "datasets": [{"dataset": "heldout_confirm", "examples": [...]}], "sources": {...}}`.
''')
code(r'''
GITHUB_DATA_URL = "https://raw.githubusercontent.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/main/round-1/dataset-1/demo/mini_demo_data.json"
import json
from pathlib import Path

def load_data():
    try:
        import urllib.request
        with urllib.request.urlopen(GITHUB_DATA_URL) as response:
            return json.loads(response.read().decode())
    except Exception: pass
    local = Path("mini_demo_data.json")
    if local.exists(): return json.loads(local.read_text())
    raise FileNotFoundError("Could not load mini_demo_data.json")
''')
code(r'''
data = load_data()
print("groups:", [(d["dataset"], len(d["examples"])) for d in data["datasets"]])
print("bundled source records:", {k: len(v) for k, v in data["sources"].items()})
''')

md(r'''
## Config
`data.py` has no training-style hyper-parameters; the only scale knob is how many rows are verified.
The original script processes **all** rows of every group (15,606); the demo file holds 98 `heldout_confirm` rows.
''')
code(r'''
MAX_EXAMPLES = 2   # rows per group to verify (original: all rows, i.e. None -> 15,606 in the full dataset)
''')

md(r'''
## Setup: paths, logging, constants and string helpers
Copied from `data.py`. `ROOT` is the notebook's working directory (the script used `Path(__file__).parent`).
`GROUP_ORDER` lists the five dataset groups; `FORBIDDEN` keys must never appear in an example (schema rule).
`norm` / `ws` are the whitespace/case normalisers used when comparing sentences and formulas to the source files.
''')
code(r'''
ROOT = Path(".").resolve()   # original: Path(__file__).resolve().parent
TD = ROOT / "temp" / "datasets"
(ROOT / "logs").mkdir(exist_ok=True)
logger.remove()
logger.add(sys.stdout, level="INFO", format="{time:HH:mm:ss}|{level:<7}|{message}")
logger.add(ROOT / "logs" / "data_py.log", rotation="30 MB", level="DEBUG")

GROUP_ORDER = ["heldout_confirm", "heldout_samples", "screen_gold_audit", "contamination", "transfer_unlabeled"]
FORBIDDEN = {"split", "dataset", "context"}


def norm(s: str) -> str:
    s = re.sub(r"\s+", " ", s.strip().lower())
    return s[:-1].strip() if s.endswith(".") else s


def ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def read_jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
''')

md(r'''
## Loading the source datasets
`load_sources` builds lookup tables of the original public records:
- `malls` — MALLS-v0.1-test (`NL`, `FOL`), indexed by position;
- `malls_cur` — the DSAVlab-UNIUD human-corrected MALLS subset (arXiv:2606.02837), keyed by `id - 1`;
- `folio_train` — FOLIO-v2-train stories keyed by `example_id`;
- `proverqa` — ProverQA-dev `nl2fol` (sentence → FOL) pairs keyed by `(level, id)`;
- `folio_v1_val` / `logiclm` — FOLIO v0.0 validation + Logic-LM outputs, only used by the `screen_gold_audit` group.

**Notebook change:** the original read these from files under `temp/datasets/`; here the same records come from
`data["sources"]` (only the ones referenced by the demo rows). The original file-reading lines are kept as comments.
The screen-group tables are empty because that group is not part of the demo subset.
''')
code(r'''
def load_sources() -> dict:
    S = data["sources"]  # notebook: bundled source records replace temp/datasets/
    src = {}
    # src["malls"] = json.loads((TD / "yuan-yang__MALLS-v0" / "MALLS-v0.1-test.json").read_text())
    src["malls"] = {int(i): r for i, r in S["malls_test"].items()}
    # src["malls_cur"] = {c["id"] - 1: c for c in read_jsonl(TD / "DSAVlab-UNIUD__MALLS_test_subset-CURATED" / "MALLS_instances.jsonl")}
    src["malls_cur"] = {c["id"] - 1: c for c in S["malls_curated"]}
    # src["folio_train"] = {str(r["example_id"]): r for r in read_jsonl(TD / "tasksource__folio" / "folio_v2_train.jsonl")}
    src["folio_train"] = {str(r["example_id"]): r for r in S["folio_v2_train"]}
    src["proverqa"] = {}
    for lvl in ("medium", "hard"):
        # for it in json.loads((TD / "opendatalab__ProverQA" / "dev" / f"{lvl}.json").read_text()):
        for it in S[f"proverqa_dev_{lvl}"]:
            d = it["nl2fol"]
            d = ast.literal_eval(d) if isinstance(d, str) else d
            src["proverqa"][(lvl, str(it["id"]))] = list(d.items())
    # --- screen_gold_audit sources (group not in the demo subset; original code kept for reference) ---
    # gh = TD / "github_FOLIO_v0.0_and_LogicLM_outputs"
    # val = {}
    # for s in read_jsonl(gh / "folio-validation_v0.0.jsonl"):
    #     p = s["premises"]
    #     p = ast.literal_eval(p) if isinstance(p, str) and p.startswith("[") else p
    #     pf = s["premises-FOL"]
    #     pf = ast.literal_eval(pf) if isinstance(pf, str) and pf.startswith("[") else pf
    #     for nl, f in list(zip(p, pf)) + [(s["conclusion"], s["conclusion-FOL"])]:
    #         val.setdefault(norm(nl), set()).add(ws(f))
    # src["folio_v1_val"] = val
    # src["logiclm"] = {}
    # for sysname in ("gpt-3.5-turbo", "gpt-4", "text-davinci-003"):
    #     txt = "\n".join(ex["raw_logic_programs"][0] for ex in json.loads((gh / f"FOLIO_dev_{sysname}.json").read_text())
    #                     if ex.get("raw_logic_programs"))
    #     src["logiclm"][f"logiclm_{sysname}"] = {ws(l) for l in txt.split("\n") if ":::" in l}
    src["folio_v1_val"] = {}
    src["logiclm"] = {}
    return src
''')

md(r'''
## Verifying held-out rows (`heldout_confirm`, `heldout_samples`)
`metadata_source_id` encodes where the sentence came from. For each of the three patterns the function looks up the
original record and checks that **both** the sentence and the original gold FOL match (after whitespace normalisation).
For MALLS rows that the curated subset corrected, the paper-corrected gold must also match `FOL_sentence_new`.
Returns `(verified?, source-file pointer)`.
''')
code(r'''
def verify_heldout(ex: dict, src: dict) -> tuple[bool, str]:
    inp = json.loads(ex["input"])
    sent, gold, sid = inp["sentence"], ex["metadata_gold_fol_original"], ex["metadata_source_id"]
    m = re.match(r"malls_test_(\d+)$", sid)
    if m:
        i = int(m.group(1))
        rec = src["malls"][i]
        ok = ws(rec["NL"]) == ws(sent) and ws(rec["FOL"]) == ws(gold)
        if ex.get("metadata_gold_fol_paper"):
            ok = ok and ws(src["malls_cur"][i]["FOL_sentence_new"]) == ws(ex["metadata_gold_fol_paper"])
        return ok, f"yuan-yang__MALLS-v0/MALLS-v0.1-test.json[{i}]"
    m = re.match(r"folio_train_story(\w+)_ex(\w+)_(p\d+|c)$", sid)
    if m:
        rec = src["folio_train"].get(m.group(2))
        if rec is None:
            return False, "tasksource__folio/folio_v2_train.jsonl (example missing)"
        pos = m.group(3)
        if pos == "c":
            nl, fol = rec["conclusion"], rec["conclusion-FOL"]
        else:
            j = int(pos[1:])
            nl = [l for l in rec["premises"].split("\n") if l.strip()][j]
            fol = [l for l in rec["premises-FOL"].split("\n") if l.strip()][j]
        return ws(nl) == ws(sent) and ws(fol) == ws(gold), f"tasksource__folio/folio_v2_train.jsonl[example_id={m.group(2)},{pos}]"
    m = re.match(r"proverqa_dev_(medium|hard)_(\w+)_(\d+)$", sid)
    if m:
        items = src["proverqa"].get((m.group(1), m.group(2)))
        if items is None:
            return False, "opendatalab__ProverQA (item missing)"
        nl, fol = items[int(m.group(3))]
        return ws(nl) == ws(sent) and ws(fol) == ws(gold), f"opendatalab__ProverQA/dev/{m.group(1)}.json[id={m.group(2)}][{m.group(3)}]"
    return False, "unknown source_id pattern"
''')

md(r'''
## Verifying the other groups
- `verify_screen` (`screen_gold_audit`): the gold must be in FOLIO v0.0 validation and the candidate line must literally occur in the Logic-LM output file.
- `verify_transfer` (`transfer_unlabeled`): the candidate formula must equal the user's EU-AI-Act pilot `04_fol.json` it came from.

These are copied unchanged; they are not exercised by the demo subset (only `heldout_confirm` rows are bundled).
''')
code(r'''
def verify_screen(ex: dict, src: dict) -> tuple[bool, str]:
    inp = json.loads(ex["input"])
    golds = src["folio_v1_val"].get(norm(inp["sentence"]), set())
    ok_gold = ws(ex["metadata_gold_fol_original"]) in golds
    ok_line = ws(ex["metadata_raw_output"]) in src["logiclm"].get(ex["metadata_system"], set())
    return ok_gold and ok_line, f"github FOLIO v0.0 validation + Logic-LLM FOLIO_dev_{ex['metadata_system'].replace('logiclm_', '')}.json"


def verify_transfer(ex: dict) -> tuple[bool, str]:
    rel = ex["metadata_source_path"].replace("raw/pilot/", "", 1)
    p = TD / "user_dpv_pilot" / rel
    if not p.exists():
        return False, str(p.relative_to(ROOT))
    try:
        fol = json.loads(p.read_text()).get("fol", "")
    except json.JSONDecodeError:
        fol = p.read_text()
    return ws(fol) == ws(json.loads(ex["input"])["candidate_fol"]), f"temp/datasets/user_dpv_pilot/{rel}"
''')

md(r'''
## Main: schema checks, source verification, per-group stats, write `full_data_out.json`
For every group in `GROUP_ORDER` and every row: assert `input`/`output` are strings, no forbidden keys, all other keys
are `metadata_*`; run the matching verifier (contamination rows are checked against the held-out sentence they were
derived from); store `metadata_source_verified` / `metadata_source_file`; count labels. **Rows are never dropped.**

**Notebook change:** the original read `work/assembled_data_out.json.gz`; here `assembled` is the demo data truncated to
`MAX_EXAMPLES` rows per group (original lines kept as comments). Everything else is unchanged.
''')
code(r'''
# notebook: the demo rows stand in for work/assembled_data_out.json.gz
assembled = {"metadata": data["metadata"],
             "datasets": [{"dataset": d["dataset"], "examples": d["examples"][:MAX_EXAMPLES]} for d in data["datasets"]]}


@logger.catch(reraise=True)
def main() -> None:
    # with gzip.open(ROOT / "work" / "assembled_data_out.json.gz", "rt", encoding="utf-8") as fh:
    #     data = json.load(fh)
    data = assembled
    src = load_sources()
    logger.info(f"sources loaded: malls={len(src['malls'])} folio_train={len(src['folio_train'])} proverqa_items={len(src['proverqa'])}")
    groups = {d["dataset"]: d["examples"] for d in data["datasets"]}
    held_sent = {}
    for ex in groups.get("heldout_confirm", []):
        held_sent[ex["metadata_sentence_id"]] = json.loads(ex["input"])["sentence"]
    stats = {}
    out = []
    for g in GROUP_ORDER:
        rows = groups.get(g, [])
        c = Counter()
        for ex in rows:
            assert isinstance(ex["input"], str) and isinstance(ex["output"], str), ex.get("metadata_item_id")
            bad = FORBIDDEN & set(ex)
            assert not bad, bad
            assert all(k in ("input", "output") or k.startswith("metadata_") for k in ex), ex.keys()
            if g in ("heldout_confirm", "heldout_samples"):
                ok, f = verify_heldout(ex, src)
            elif g == "screen_gold_audit":
                ok, f = verify_screen(ex, src)
            elif g == "contamination":
                ok = held_sent.get(ex["metadata_sentence_id"]) == ex["metadata_original_sentence"]
                f = "derived from heldout_confirm sentence " + ex["metadata_sentence_id"]
            else:
                ok, f = verify_transfer(ex)
            ex["metadata_source_verified"] = bool(ok)
            ex["metadata_source_file"] = f
            c[ok] += 1
        stats[g] = {"rows": len(rows), "source_verified": c[True], "not_verified": c[False],
                    "labels": dict(Counter(ex["output"] for ex in rows))}
        logger.info(f"{g}: {stats[g]}")
        out.append({"dataset": g, "examples": rows})
    meta = dict(data["metadata"])
    meta["source_verification"] = stats
    meta["groups"] = GROUP_ORDER
    (ROOT / "full_data_out.json").write_text(json.dumps({"metadata": meta, "datasets": out}, ensure_ascii=False))
    logger.info(f"wrote full_data_out.json: {sum(len(d['examples']) for d in out)} examples in {len(out)} datasets")
''')
code(r'''
main()
''')

md(r'''
## Results
Reads back the `full_data_out.json` just written and summarises it: source-verification per group, a few example rows
(sentence, candidate, original gold, label and label source), and the label distribution by corpus, by system,
by L1 solver status and by complexity tercile.

Label semantics (`metadata_label_source`, precedence `panel3 > equiv_synthetic_gold > equiv_audited_gold > unknown`):
`panel3` = L3 blinded adjudication; `equiv_*` = L1 prover-checked equivalence to a (synthetic or audited) gold; `unknown` = no trustworthy label.
Key finding of the full dataset: 43.9% of solver-non-equivalent candidates are panel-faithful, so solver-only labels are biased.
''')
code(r'''
res = json.loads((ROOT / "full_data_out.json").read_text())
print("Source verification per group:")
print(pd.DataFrame(res["metadata"]["source_verification"]).T[["rows", "source_verified", "not_verified", "labels"]].to_string())

rows = [ex for d in res["datasets"] for ex in d["examples"]]
df = pd.DataFrame([{
    "sentence": json.loads(ex["input"])["sentence"],
    "candidate_fol": json.loads(ex["input"])["candidate_fol"],
    "gold_fol_original": ex["metadata_gold_fol_original"],
    "label": ex["output"],
    "label_source": ex["metadata_label_source"],
    "corpus": ex["metadata_corpus_subset"],
    "system": ex["metadata_system"],
    "parse_ok": ex["metadata_parse_ok"],
    "L1_status": ex["metadata_L1_orig_status"],
    "complexity": ex["metadata_complexity_tercile"],
    "verified": ex["metadata_source_verified"],
    "source_file": ex["metadata_source_file"],
} for ex in rows])

pd.set_option("display.max_colwidth", 90)
print(f"\n{len(df)} rows verified: {df['verified'].sum()} / {len(df)}\n")
for _, r in df.head(4).iterrows():
    print(f"[{r['corpus']} | {r['system']}] label={r['label']} ({r['label_source']}), L1={r['L1_status']}, verified={r['verified']}")
    print("  NL  :", r["sentence"])
    print("  cand:", r["candidate_fol"])
    print("  gold:", r["gold_fol_original"])
    print("  src :", r["source_file"], "\n")
print(pd.crosstab(df["L1_status"], df["label"], margins=True).to_string())
''')
code(r'''
fig, axes = plt.subplots(2, 2, figsize=(13, 9))
colors = {"faithful": "#2a9d8f", "unfaithful": "#e76f51", "unknown": "#adb5bd"}
for ax, col, title in zip(axes.flat, ["corpus", "system", "L1_status", "complexity"],
                          ["Label by corpus subset", "Label by generating system",
                           "Label by L1 solver status (vs original gold)", "Label by complexity tercile"]):
    ct = pd.crosstab(df[col], df["label"]).reindex(columns=[c for c in colors if c in df["label"].unique()])
    ct.plot(kind="barh", stacked=True, ax=ax, color=[colors[c] for c in ct.columns], legend=False)
    ax.set_title(title); ax.set_xlabel("rows"); ax.set_ylabel("")
handles, labels = axes.flat[0].get_legend_handles_labels()
fig.legend(handles, labels, loc="upper center", ncol=3, frameon=False)
fig.tight_layout(rect=(0, 0, 1, 0.96))
plt.show()
''')

nb = {"cells": cells, "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                                   "language_info": {"name": "python", "version": "3.12"}},
      "nbformat": 4, "nbformat_minor": 5}
for i, c in enumerate(nb["cells"]):
    c["id"] = f"cell-{i}"
Path(__file__).resolve().parent.parent.joinpath("code_demo.ipynb").write_text(json.dumps(nb, indent=1, ensure_ascii=False))
print("cells:", len(cells))
PYEOF
python3 scripts/build_notebook.py
```

### [22] TOOL RESULT — Bash · 2026-09-23 18:41:20 UTC

```
{"stdout": "cells: 23", "stderr": "", "interrupted": false, "isImage": false, "noOutputExpected": false}
```

### [23] TOOL CALL — Bash · 2026-09-23 18:41:26 UTC

```
/usr/local/bin/python3.12 -m venv .nb_env && .nb_env/bin/pip install -q pip jupyter ipykernel 2>&1 | tail -2; start=$(date +%s); .nb_env/bin/jupyter nbconvert --to notebook --execute --ExecutePreprocessor.timeout=600 code_demo.ipynb --output code_demo.ipynb 2>&1 | tail -5; echo "runtime $(( $(date +%s)-start ))s"
```

### [24] TOOL RESULT — Bash · 2026-09-23 18:52:22 UTC

```
{"stdout": "", "stderr": "", "interrupted": false, "isImage": false, "noOutputExpected": false, "backgroundTaskId": "bkxbksorp", "timedOutAfterMs": 600000}
```

### [25] ASSISTANT · 2026-09-23 18:53:30 UTC

```
While the clean-env test runs (pip install on this volume is slow), I'll write the README and manifest.
```

### [26] TOOL CALL — Bash · 2026-09-23 18:53:30 UTC

````
cat > README.md <<'EOF'
# Demo: Held-out NL→FOL Faithfulness Meta-Evaluation Set (`data.py`)

Colab-ready demo notebook for the dataset artifact `art_iyzYyaqlqpSX`
(source workspace: `/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_dataset_1`).

`data.py` is the final build step of the dataset: it takes the labelled candidate formalizations assembled by the
upstream pipeline, re-verifies every row against the original public source files (MALLS-v0.1-test, the
DSAVlab-UNIUD curated MALLS subset, FOLIO-v2-train, ProverQA-dev), stores `metadata_source_verified` /
`metadata_source_file` on each row and writes `full_data_out.json` with per-group statistics. The notebook is the
same code split into cells, with the file reads replaced by the bundled demo data.

## Layout
| Path | What |
|---|---|
| `code_demo.ipynb` | the demo notebook (loads `mini_demo_data.json` from GitHub, local fallback) |
| `mini_demo_data.json` | 98 diverse `heldout_confirm` rows (4 corpus subsets × 9 systems × 3 labels, incl. unparseable outputs and human-corrected MALLS gold) + only the source records needed to verify them (`sources`) |
| `scripts/build_mini_demo_data.py` | builds `mini_demo_data.json` from the source workspace |
| `scripts/build_notebook.py` | generates `code_demo.ipynb` from the original `data.py` code |
| `full_data_out.json`, `logs/` | written when the notebook runs (demo-scale output of `main()`) |

## Run
```bash
jupyter nbconvert --to notebook --execute code_demo.ipynb   # or open in Colab
```
`MAX_EXAMPLES` in the config cell sets how many rows per group are verified (demo: 100 ≥ all 98 bundled rows;
the original script processes all 15,606 rows of the full dataset).

## Restoring removed files
Nothing heavy is produced here; no `delete` entries. The testing venv `.nb_env/` is created and removed during testing
(`python3.12 -m venv .nb_env && .nb_env/bin/pip install jupyter ipykernel`).
EOF
cat > .aii/manifest.yaml <<'EOF'
entries:
  - path: mini_demo_data.json
    keep: curated demo subset (0.5 MB) read by code_demo.ipynb
EOF
ls .
````

### [27] TOOL RESULT — Bash · 2026-09-23 18:53:30 UTC

```
{"stdout": "README.md\ncode_demo.ipynb\nmini_demo_data.json\nscripts", "stderr": "", "interrupted": false, "isImage": false, "noOutputExpected": false}
```

### [28] TOOL CALL — Bash · 2026-09-23 18:53:30 UTC

```
cat /tmp/claude-0/-ai-inventor-aii-data-runs-run-qY2a2IS-WLIs-4-gen-paper-repo--4-gen-demo-art-notebook-workspaces-iter-1-art-iyzYyaqlqpSX/365987b7-3192-4dbd-8e08-b736991c3dd3/tasks/bkxbksorp.output; ls /ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/4_gen_paper_repo/_4_gen_demo_art/notebook_workspaces/iter_1/art_iyzYyaqlqpSX/.nb_env/lib/python3.12/site-packages | wc -l
```

### [29] TOOL RESULT — Bash · 2026-09-23 18:53:30 UTC

```
{"stdout": "[notice] A new release of pip is available: 25.0.1 -> 26.2.1\n[notice] To update, run: python3.12 -m pip install --upgrade pip\n219", "stderr": "", "interrupted": false, "isImage": false, "noOutputExpected": false}
```

### [30] TOOL CALL — ToolSearch · 2026-09-23 18:53:30 UTC

```
{'query': 'select:Monitor', 'max_results': 1}
```

### [31] TOOL RESULT — ToolSearch · 2026-09-23 18:53:30 UTC

```
{"matches": ["Monitor"], "query": "select:Monitor", "total_deferred_tools": 27}
```

### [32] TOOL CALL — Monitor · 2026-09-23 18:53:30 UTC

```
{'command': 'F=/tmp/claude-0/-ai-inventor-aii-data-runs-run-qY2a2IS-WLIs-4-gen-paper-repo--4-gen-demo-art-notebook-workspaces-iter-1-art-iyzYyaqlqpSX/365987b7-3192-4dbd-8e08-b736991c3dd3/tasks/bkxbksorp.output; until grep -q "runtime" $F; do sleep 5; done; tail -8 $F', 'description': 'nbconvert test-run of code_demo.ipynb finishing', 'timeout_ms': 1800000}
```

### [33] TOOL RESULT — Monitor · 2026-09-23 18:53:30 UTC

```
{"taskId": "bgu97h4b1", "timeoutMs": 1800000, "persistent": false}
```

### [34] TOOL CALL — Bash · 2026-09-23 18:53:30 UTC

```
F=/tmp/claude-0/-ai-inventor-aii-data-runs-run-qY2a2IS-WLIs-4-gen-paper-repo--4-gen-demo-art-notebook-workspaces-iter-1-art-iyzYyaqlqpSX/365987b7-3192-4dbd-8e08-b736991c3dd3/tasks/bkxbksorp.output; timeout 590 bash -c "until grep -q runtime $F; do sleep 5; done"; tail -8 $F
```

### [35] TOOL RESULT — Bash · 2026-09-23 18:55:38 UTC

```
{"stdout": "\u001b[1m[\u001b[0m\u001b[34;49mnotice\u001b[0m\u001b[1;39;49m]\u001b[0m\u001b[39;49m To update, run: \u001b[0m\u001b[32;49mpython3.12 -m pip install --upgrade pip\u001b[0m\n\n\u001b[1m[\u001b[0m\u001b[34;49mnotice\u001b[0m\u001b[1;39;49m]\u001b[0m\u001b[39;49m A new release of pip is available: \u001b[0m\u001b[31;49m25.0.1\u001b[0m\u001b[39;49m -> \u001b[0m\u001b[32;49m26.2.1\u001b[0m\n\u001b[1m[\u001b[0m\u001b[34;49mnotice\u001b[0m\u001b[1;39;49m]\u001b[0m\u001b[39;49m To update, run: \u001b[0m\u001b[32;49mpython3.12 -m pip install --upgrade pip\u001b[0m\n[NbConvertApp] Writing 87467 bytes to code_demo.ipynb\nruntime 268s\n\n[exited with code 0]", "stderr": "", "interrupted": false, "isImage": false, "noOutputExpected": false}
```

### [36] ASSISTANT · 2026-09-23 18:55:38 UTC

```
Passed at MAX_EXAMPLES=2 (268s, dominated by pip installs). Checking outputs, then scaling to all 98 rows.
```

### [37] TOOL CALL — Bash · 2026-09-23 18:55:38 UTC

```
python3 -c "
import json
nb=json.load(open('code_demo.ipynb'))
for c in nb['cells'][14:]:
  for o in c.get('outputs',[]):
    if o.get('text'): print(''.join(o['text'])[:2500])
    if o.get('output_type')=='error': print(o['ename'],o['evalue'])
    if 'data' in o: print(list(o['data']))
"
```

### [38] TOOL RESULT — Bash · 2026-09-23 18:55:38 UTC

```
{"stdout": "18:53:36|INFO   |sources loaded: malls=24 folio_train=25 proverqa_items=39\n\n18:53:36|INFO   |heldout_confirm: {'rows': 2, 'source_verified': 2, 'not_verified': 0, 'labels': {'faithful': 2}}\n\n18:53:36|INFO   |heldout_samples: {'rows': 0, 'source_verified': 0, 'not_verified': 0, 'labels': {}}\n\n18:53:36|INFO   |screen_gold_audit: {'rows': 0, 'source_verified': 0, 'not_verified': 0, 'labels': {}}\n\n18:53:36|INFO   |contamination: {'rows': 0, 'source_verified': 0, 'not_verified': 0, 'labels': {}}\n\n18:53:36|INFO   |transfer_unlabeled: {'rows': 0, 'source_verified': 0, 'not_verified': 0, 'labels': {}}\n\n18:53:36|INFO   |wrote full_data_out.json: 2 examples in 5 datasets\n\nSource verification per group:\n                   rows source_verified not_verified           labels\nheldout_confirm       2               2            0  {'faithful': 2}\nheldout_samples       0               0            0               {}\nscreen_gold_audit     0               0            0               {}\ncontamination         0               0            0               {}\ntransfer_unlabeled    0               0            0               {}\n\n2 rows verified: 2 / 2\n\n[malls_v0.1_test | phi-4] label=faithful (panel3), L1=equiv_proved, verified=True\n  NL  : When a bird migrates, it travels long distances, often across continents, and usually follows a seasonal pattern to find resources.\n  cand: ∀x ((Bird(x) ∧ Migrates(x)) → (TravelsLongDistances(x) ∧ OftenAcrossContinents(x) ∧ UsuallyFollowsSeasonalPattern(x)))\n  gold: ∀x (Bird(x) ∧ Migrates(x) → TravelsLongDistances(x) ∧ OftenCrossesContinents(x) ∧ UsuallyFollowsSeasonalPatternToFindResources(x))\n  src : yuan-yang__MALLS-v0/MALLS-v0.1-test.json[41] \n\n[malls_v0.1_test | qwen-2.5-7b] label=faithful (equiv_audited_gold), L1=equiv_proved, verified=True\n  NL  : No stars are planets.\n  cand: ∀x (Star(x) → ¬Planet(x))\n  gold: ∀x (Star(x) → ¬Planet(x))\n  src : yuan-yang__MALLS-v0/MALLS-v0.1-test.json[207] \n\n\nlabel         faithful  All\nL1_status                  \nequiv_proved         2    2\nAll                  2    2\n\n['image/png', 'text/plain']", "stderr": "", "interrupted": false, "isImage": false, "noOutputExpected": false}
```

### [39] TOOL CALL — Bash · 2026-09-23 18:55:38 UTC

```
sed -i 's/^MAX_EXAMPLES = 2   # rows per group to verify (original/MAX_EXAMPLES = 100   # rows per group to verify; demo file has 98 heldout_confirm rows (original/' scripts/build_notebook.py && grep -n "MAX_EXAMPLES = " scripts/build_notebook.py && python3 scripts/build_notebook.py && start=$(date +%s); .nb_env/bin/jupyter nbconvert --to notebook --execute --ExecutePreprocessor.timeout=600 code_demo.ipynb --output code_demo.ipynb 2>&1 | tail -1; echo "runtime $(( $(date +%s)-start ))s"; python3 -c "
import json
nb=json.load(open('code_demo.ipynb'))
for c in nb['cells'][16:]:
  for o in c.get('outputs',[]):
    if o.get('text'): print(''.join(o['text'])[:1500])
    if o.get('output_type')=='error': print(o['ename'],o['evalue'])
" | grep -v "^\s*$" | head -40
```

### [40] TOOL RESULT — Bash · 2026-09-23 18:55:38 UTC

```
{"stdout": "99:MAX_EXAMPLES = 100   # rows per group to verify; demo file has 98 heldout_confirm rows (original: all rows, i.e. None -> 15,606 in the full dataset)\ncells: 23\n[NbConvertApp] Writing 122380 bytes to code_demo.ipynb\nruntime 52s\n18:54:39|INFO   |sources loaded: malls=24 folio_train=25 proverqa_items=39\n18:54:40|INFO   |heldout_confirm: {'rows': 98, 'source_verified': 98, 'not_verified': 0, 'labels': {'faithful': 32, 'unfaithful': 38, 'unknown': 28}}\n18:54:40|INFO   |heldout_samples: {'rows': 0, 'source_verified': 0, 'not_verified': 0, 'labels': {}}\n18:54:40|INFO   |screen_gold_audit: {'rows': 0, 'source_verified': 0, 'not_verified': 0, 'labels': {}}\n18:54:40|INFO   |contamination: {'rows': 0, 'source_verified': 0, 'not_verified': 0, 'labels': {}}\n18:54:40|INFO   |transfer_unlabeled: {'rows': 0, 'source_verified': 0, 'not_verified': 0, 'labels': {}}\n18:54:40|INFO   |wrote full_data_out.json: 98 examples in 5 datasets\nSource verification per group:\n                   rows source_verified not_verified                                             labels\nheldout_confirm      98              98            0  {'faithful': 32, 'unfaithful': 38, 'unknown': 28}\nheldout_samples       0               0            0                                                 {}\nscreen_gold_audit     0               0            0                                                 {}\ncontamination         0               0            0                                                 {}\ntransfer_unlabeled    0               0            0                                                 {}\n98 rows verified: 98 / 98\n[malls_v0.1_test | phi-4] label=faithful (panel3), L1=equiv_proved, verified=True\n  NL  : When a bird migrates, it travels long distances, often across continents, and usually follows a seasonal pattern to find resources.\n  cand: ∀x ((Bird(x) ∧ Migrates(x)) → (TravelsLongDistances(x) ∧ OftenAcrossContinents(x) ∧ UsuallyFollowsSeasonalPattern(x)))\n  gold: ∀x (Bird(x) ∧ Migrates(x) → TravelsLongDistances(x) ∧ OftenCrossesContinents(x) ∧ UsuallyFollowsSeasonalPatternToFindResources(x))\n  src : yuan-yang__MALLS-v0/MALLS-v0.1-test.json[41] \n[malls_v0.1_test | qwen-2.5-7b] label=faithful (equiv_audited_gold), L1=equiv_proved, verified=True\n  NL  : No stars are planets.\n  cand: ∀x (Star(x) → ¬Planet(x))\n  gold: ∀x (Star(x) → ¬Planet(x))\n  src : yuan-yang__MALLS-v0/MALLS-v0.1-test.json[207] \n[malls_v0.1_test | d\nlabel                   faithful  unfaithful  unknown  All\nL1_status                                                 \nequiv_proved                  24           3        2   29\nnon_equiv                      3           7        1   11\nnon_equiv_no_bijection         5          28        6   39\nunparseable                    0           0       19   19\nAll                           32          38       28   98", "stderr": "", "interrupted": false, "isImage": false, "noOutputExpected": false}
```

### [41] ASSISTANT · 2026-09-23 18:55:38 UTC

```
All 98 rows verify. Quick look at the figure, then cleanup.
```

### [42] TOOL CALL — Bash · 2026-09-23 18:55:38 UTC

```
python3 -c "
import json,base64
nb=json.load(open('code_demo.ipynb'))
for c in nb['cells']:
  for o in c.get('outputs',[]):
    if 'data' in o and 'image/png' in o['data']: open('/tmp/claude-0/-ai-inventor-aii-data-runs-run-qY2a2IS-WLIs-4-gen-paper-repo--4-gen-demo-art-notebook-workspaces-iter-1-art-iyzYyaqlqpSX/365987b7-3192-4dbd-8e08-b736991c3dd3/scratchpad/fig.png','wb').write(base64.b64decode(o['data']['image/png']))
print(sum(1 for c in nb['cells'] for o in c.get('outputs',[]) if o.get('output_type')=='error'))
"; grep -c 'GITHUB_DATA_URL = \"https://raw.githubusercontent.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/main/round-1/dataset-1/demo/mini_demo_data.json\"' code_demo.ipynb; rm -rf .nb_env; du -sh .; ls -a
```

### [43] TOOL CALL — Read · 2026-09-23 18:55:38 UTC

```
/tmp/claude-0/-ai-inventor-aii-data-runs-run-qY2a2IS-WLIs-4-gen-paper-repo--4-gen-demo-art-notebook-workspaces-iter-1-art-iyzYyaqlqpSX/365987b7-3192-4dbd-8e08-b736991c3dd3/scratchpad/fig.png
```

### [44] TOOL RESULT — Bash · 2026-09-23 18:55:38 UTC

```
{"stdout": "0\n0\n5.4M\t.\n.\n..\n.aii\n.repl_agent.ptylog\nREADME.md\ncode_demo.ipynb\nfull_data_out.json\nlogs\nmini_demo_data.json\nscripts", "stderr": "", "interrupted": false, "isImage": false, "noOutputExpected": false}
```

### [45] TOOL RESULT — Read · 2026-09-23 18:55:38 UTC

```
[event truncated: exceeded SSE frame limit]
```

### [46] ASSISTANT · 2026-09-23 18:55:44 UTC

```
The URL grep returned 0, but that's probably just JSON quote escaping. Checking properly:
```

### [47] TOOL CALL — Bash · 2026-09-23 18:55:44 UTC

```
python3 -c "
import json
nb=json.load(open('code_demo.ipynb'))
src=''.join(''.join(c['source']) for c in nb['cells'])
print('GITHUB_DATA_URL = \"https://raw.githubusercontent.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/main/round-1/dataset-1/demo/mini_demo_data.json\"' in src, 'urlopen(GITHUB_DATA_URL)' in src)
"; sed -i 's/demo: 100 ≥ all 98 bundled rows/demo: 100, i.e. all 98 bundled rows/' README.md
cat >> README.md <<'EOF'

## Test result
Executed end-to-end in a clean Python 3.12 venv (Colab-mirroring install cell) with `MAX_EXAMPLES = 100`: 98/98 rows
source-verified, 0 errors, ~52 s runtime after installs (~4.5 min including a cold `pip install`).
EOF
echo '{"out_expected_files": {"notebook": "code_demo.ipynb", "mini_data_file": "mini_demo_data.json"}}' > .terminal_claude_agent_struct_out.json; cat .terminal_claude_agent_struct_out.json
```

### [48] TOOL RESULT — Bash · 2026-09-23 18:55:44 UTC

```
{"stdout": "True True\n{\"out_expected_files\": {\"notebook\": \"code_demo.ipynb\", \"mini_data_file\": \"mini_demo_data.json\"}}", "stderr": "", "interrupted": false, "isImage": false, "noOutputExpected": false}
```

### [49] ASSISTANT · 2026-09-23 18:55:55 UTC

```
I've converted `data.py` into a demo notebook, `code_demo.ipynb`, plus a 98-row sample file, `mini_demo_data.json`. The notebook runs cleanly start to finish in a fresh Python 3.12 environment set up like Colab: all 98 rows pass source verification, with no errors. It takes about 52s of processing, or about 4.5 minutes including a first-time package install, well inside the 10-minute limit.

**`mini_demo_data.json` (0.5 MB):** 98 rows from the `heldout_confirm` group only. They cover all four source corpora (MALLS-test, FOLIO-v2-train, ProverQA hard and medium), all 9 systems and all three labels (32 faithful, 38 unfaithful, 28 unknown). They also include 19 unparseable outputs, 5 MALLS rows with the human-corrected gold, and 10 rows labelled by the 3-model adjudication. The original script checks rows against the source datasets under `temp/datasets/`, which aren't available in Colab. So the file also carries just the source records those 98 rows need (under `sources`).

**`code_demo.ipynb`:** It loads the data from the GitHub URL, exactly as specified, and falls back to the local file. Your `data.py` code is copied unchanged, split into cells with an explanation before each one. I made three adaptations:
- **Source records:** `load_sources` reads them from the bundled data instead of files. The original file-reading lines are kept as comments.
- **Input:** `main()` reads the demo rows instead of `work/assembled_data_out.json.gz`, cut to `MAX_EXAMPLES` (the only setting, now 100, so all 98 rows run).
- **Unused sources:** the FOLIO v0.0 / Logic-LM sources are empty. Only the `screen_gold_audit` group uses them, and it isn't in the demo. The original code is kept as comments.

The results cells show the verification counts for each group, a few example rows (sentence, candidate formula, gold, label), and a table of the solver equivalence check (L1) against labels. They also draw a 2×2 chart of labels broken down by corpus, system, solver result and complexity. Among the 39 candidates the solver found not equivalent to the gold under any renaming of predicates, 5 are labelled faithful. That's the solver-label bias the dataset documents.

Only one scaling step was needed (2 rows, then all 98), since verification takes milliseconds per row. I also added `README.md`, `.aii/manifest.yaml` (keeps `mini_demo_data.json`; nothing to delete) and the two scripts that rebuild the data and the notebook. The required `.terminal_claude_agent_struct_out.json` is written.

Files are in `art_iyzYyaqlqpSX/`:
- `code_demo.ipynb`
- `mini_demo_data.json`
- `README.md`
- `scripts/build_mini_demo_data.py`
- `scripts/build_notebook.py`
```
