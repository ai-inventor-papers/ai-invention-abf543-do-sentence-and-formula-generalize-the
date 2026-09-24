# gen_html_demo — report_results

> Phase: `gen_paper_repo` · `gen_html_demo`
> Run: `gen_paper_repo_231b3d976c60` — Gold-free checks of whether a logic formula matches its sentence
>
> Full, verbatim record of every prompt the AI Inventor pipeline gave this agent — system-user, human-user and skill-input — in the order they landed. Nothing truncated.

## Task: `gen_html_demo` (terminal_claude_agent)

### [1] SYSTEM-USER prompt · 2026-09-24 17:03:52 UTC

````
<design_philosophy>
You are building ONE explorable web page for a research result. The reader should come away
having SEEN the result in the run's own data, because they operated it: they switched between
the conditions the run compared, dragged a threshold and watched the numbers move, pointed at a
mark to see which model or item it was, filtered down to the cases where the method failed, and
put an input beside its output. The page explains through interaction. It is not the paper with
nicer CSS, not a list of headline numbers, and not a gallery of the paper's figures.

WHAT EARNS AN INTERACTION
Every control answers a question a reader actually has at that point, and it changes a view drawn
from the run's real data:
- "Does it hold everywhere?" A chart of the per-condition, per-model or per-dataset results with a
  control over which ones are shown; the baseline always visible; pointing at a mark shows that
  record in full.
- "What does it do to one case?" An item browser over the real per-item records: filter, search
  or sort, and the selected item shows its input, the method's output, the baseline's output and
  the verdict side by side, as a before and after.
- "Where does it break?" A toggle that isolates the failures, the disagreements or the hardest
  slice, with the counts updating as it changes.
- "What if?" A slider over a parameter the recorded data lets the page recompute honestly, such as
  a decision threshold applied to the recorded per-item scores, with the metrics recomputed live.
- "Can I try it?" A live mini-demo of the method, only when the method runs exactly in a few
  dozen lines of JavaScript; it runs on the embedded examples and shows that its output matches
  the recorded one.
- "How does it work?" A stepper that walks ONE real example through the method's stages with the
  values recorded at each stage, over a pipeline diagram that highlights the current stage.
- "What does this word mean?" Term tooltips on hover, focus and tap, with a glossary.
Do not add an interaction that answers no question: no animated counters, no parallax, no
autoplaying carousel, no toggle that swaps one paragraph for a synonym of itself.

THE DATA IS REAL, OR IT IS NOT ON THE PAGE
Every data point comes from the run's output files, embedded as the file has it or trimmed to
the fields a view uses, and every number the prose states matches the paper. A view may compute
from real data (a mean, a filter, a threshold swept over recorded scores), but nothing is ever
invented, interpolated, simulated or smoothed to make a control feel richer. A page that looks
excellent and misreports one result is worse than no page.

ONE STORY
Top to bottom the page tells one story: the question, the answer shown in a view the reader can
operate at once, how the method works, the evidence to explore, where it fails, and what it does
not show. Each view opens with the question it answers and closes with one takeaway sentence
that rewrites itself to describe what the current selection shows.

CRAFT
- Type carries the design: one system font stack, a real scale with visible jumps between levels,
  body text around 17-19px with a measure of 65-75 characters and generous line height.
- Colour is restrained: a light, near-white ground, one dark ink for text, one accent for links,
  the active state and the highlighted series, a muted second colour for baselines, and a
  colour-blind-safe palette when series need more. No gradients as decoration, no purple-to-blue
  banner, no emoji, no icon fonts.
- Charts are read, not decorated: labelled axes with units, a legend when there is more than one
  series, gridlines light enough to recede, and the exact value one hover, focus or tap away.
- Controls look like controls: a visible affordance, a visible selected state, a visible focus
  ring, and a hit area of at least 40 by 40 pixels on a phone.
- Motion is a courtesy: short transitions on state changes only, and none at all under
  prefers-reduced-motion.
- Every interactive element works with a keyboard and tells a screen reader what it is and what
  state it is in. That is part of the craft, not a checklist bolted on at the end.

FINISH IT
The page is done when you have opened it in a headless browser, operated every control, seen no
script error, read it at a phone width and a desktop width, and found nothing to fix. Not before.
</design_philosophy>

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
Your workspace: `/ai-inventor/aii_data/runs/run_TGmg0LeEY5Gp/4_gen_paper_repo/_4_assemble_paper/paper`

CRITICAL: Every file you create, write, or save MUST be inside this workspace directory (subdirectories OK). You MUST NOT write files anywhere outside this path — external paths are READ-ONLY. Use absolute paths for all file operations.

EVERY file write MUST start with `/ai-inventor/aii_data/runs/run_TGmg0LeEY5Gp/4_gen_paper_repo/_4_assemble_paper/paper/`:
GOOD: `/ai-inventor/aii_data/runs/run_TGmg0LeEY5Gp/4_gen_paper_repo/_4_assemble_paper/paper/file.py`, `/ai-inventor/aii_data/runs/run_TGmg0LeEY5Gp/4_gen_paper_repo/_4_assemble_paper/paper/results/out.json`
BAD: `/tmp/file.py`, `~/output.json`, `./file.py`, any path outside the workspace
</workspace>
<disposable_outputs>
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
Name each kept artifact in your results and your `README.md` by its path
RELATIVE to your cwd, and say it stays on the run's volume rather than in the
published repository. Never write an absolute server path into a file that is
published: a reader's machine has none of them.
</disposable_outputs>

<task>
Build ONE self-contained, explorable `interactive.html` for this run's result. The
reader operates views drawn from the run's REAL output data (switching conditions, dragging a
threshold, pointing at marks, filtering items, comparing an input with its output) and comes
away understanding the finding and the method. It is published next to the paper, and its most
prominent link is the paper PDF.
</task>

<tool_use>
Maximize parallel tool calls. Parallelize independent operations, only sequentialize dependencies.
- Multiple searches/fetches on different topics → parallel in one turn
- Search then fetch results → sequential (need URLs first)
</tool_use>

<what_is_already_here>
Your workspace is the finished paper folder. You are adding one file and, where needed, PNG
renders of figures, and linking that file from the presentation page. Change nothing else, and
keep your scratch work (extraction scripts, screenshots) in a temporary directory outside this
folder, because the folder is published.

- `paper.tex`: the paper as written. It is the source for every claim, name, term
  definition and number the prose states.
- `paper.pdf`: the compiled paper. Do not link to it by this local name; link to the
  full URL in the links section.
- `references.bib`: the bibliography, when the paper has one.
- `figures/`: every figure the paper uses, flattened into one folder.
- `index.html`, when present: the paper's static presentation page and the site's
  landing page. Change it in one way only: add the link to your page described under
  presentation_link.
- `workspace/`: the scratch folder the LaTeX task worked in. Ignore it.
</what_is_already_here>

<artifact_data>
Every artifact this run produced, with the directory it ran in and the output files it declared.
These directories are on disk and you can read them. Their JSON and CSV outputs hold the REAL
per-item and per-condition results: the recorded inputs and outputs, the scores, the verdicts,
the per-model and per-setting metrics. They are what the page's views are built from. Where a
file has `mini_` and `preview_` variants beside it, read those first to learn its shape.

- iteration: 1
  name: gen_art_experiment_1
  type: experiment
  title: Screening solver-based faithfulness scores for logic translations
  summary: >-
    Arm A of the iter-1 NL->FOL faithfulness screen (run_qY2a2IS-WLIs). PROVIDES: (1) data/screen_set.json, the frozen meta-evaluation
    set built with the recipe shared with Arm B: 300 sha1-first FOLIO-dev sentences and 835 Logic-LM real candidates (gpt-3.5-turbo
    265, gpt-4 298, davinci-003 272). Each has blind bijection-equivalence labels (389 equiv, 0 unlabeled; bounded and unbounded
    z3 agree 389/389), plus labels against FOLIO v0.0 gold and lexical-bijection labels. The curated 2606.02837 gold is HF
    DSAVlab-UNIUD/FOLIO_validation-curated, matched on 97 sentences, 52% of which were corrected. There are 1375 solver-verified
    mutants (9 operators; SCOPE has 0) and 412 equivalent rewrites; data/screen_set_ids.txt is for Arm B. (2) method.py, the
    reusable API signature_faithfulness(text, fol, variant A1/A2/A3/A0/Ccov) and the pipeline. (3) Results in method_out.json
    (validated, exp_gen_sol_out) and results/summary.json. AUROC [clustered 95% CI]: A1 0.711 [0.663,0.756], A2 0.711, A3
    (zero-LLM rules) 0.718 [0.673,0.763], B1 gemini judge 0.644, B3nli round-trip 0.660, B4 decomposed LLM judge 0.715, B5
    oracle 0.741, B7 structural 0.537, B8 self-consistency 0.608, and the controls A0 (alignment-only) 0.674 and Ccov 0.661.
    G3 increment over judge+parse is A1 +0.084 [0.037,0.138] and A3 +0.093 [0.048,0.143]. VERDICT (pre-registered rule): NO
    survivor. Every candidate fails G2, with 13-14% false alarms, all from synonym-renamed rewrites (38-42%); logical rewrites
    give 0/270. A3 advances by the no-survivor clause. DIAGNOSIS: the text side is the bottleneck (LLM probe MED downward
    accuracy 0.60; rule marker 0.86). Exact semantics roughly equals LLM decomposition (A1-B4 -0.005 [-0.024,0.014]). Much
    of the signal is lexical alignment: the polarity increment over [B1, parse, A0] is not significant (A1 +0.013, A3 +0.024,
    CIs include 0). Every metric is near chance in the TOP complexity tercile (A1 0.507, B1 0.533), so there is no crossover.
    Blind spots CARD and ANDOR are confirmed (0.50), and A2 does not fix ANDOR. Spend was $5.67; B1+ was skipped for budget.
    The headline numbers were independently re-derived (audit_rederive.py) and the placebos fail as expected.
  workspace: >-
    /ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_experiment_1
  output_files:
  - method.py
  - full_method_out.json
  - mini_method_out.json
  - preview_method_out.json
- iteration: 1
  name: gen_art_experiment_2
  type: experiment
  title: Testing solver worlds and agreement as FOL checks
  summary: >-
    Screen Arm B (iter 1): three gold-free NL->FOL faithfulness metrics vs baselines on 833 REAL Logic-LM FOLIO-dev candidates
    (gpt-3.5/gpt-4/davinci-003; 300 sha1-first sentences; fingerprint a74f4cdd...), labelled by blind z3 bijection-equivalence
    to FOLIO v1 gold (463 correct/370 incorrect; curated DSAVlab gold is a FOLIO-v2 re-annotation with different vocabulary,
    so it is kept as the secondary label L_bij_cur). Results (AUROC, 1000x sentence-clustered CIs): LC_onecoin latent-class
    over cross-system solver-equivalence 0.853 [0.813,0.888], G3 dAUROC over [B1 judge+parse_ok] +0.111, within-sentence 0.765;
    it is the only survivor and the pre-registered rule WINNER. TVJT (z3 distinguishing worlds + gemini-2.5-flash judging
    only the sentence) 0.701, G3 +0.039, passes G1/G3/G4 but FAILS G2 (rewrite false alarms 0.479 at tau*=1.0; 0.184 at 0.5).
    TVJT grows with complexity (top tercile 0.751) while the B1 judge falls (0.552): dAUROC +0.199 [0.085,0.308]. DeBERTa
    instance-consequence NLI 0.603 (null beyond the simplest tercile; the same pairs judged by gemini +0.079). B1 0.665, B2
    0.578, B3sc self-consistency 0.597. Non-vacuous worlds hurt TVJT (-0.035). Label-noise estimates: 67.6% of incorrect labels
    are vocabulary/granularity mismatches; v1 vs curated gold differ on 43/108 (6 semantic). FOLIO-dev has 0 mixed-quantifier
    golds, so SCOPE_SWAP is covered only by a FOLIO-train/MALLS supplement (TVJT 0.65, n=37; NLI 0.47). Also found: Arm A
    zips misaligned premise lists (stories 87/105/106/173). Spend $1.55. Headline numbers were independently re-derived (audit/rederive.py)
    and the placebo G3 test fails. Kept for iter 2: data/screen_set.json, alt_candidates.jsonl, worlds_cache.jsonl, consequences_cache.jsonl,
    blindspot_supplement.jsonl, results/screen_scores.jsonl, analysis.json, verdict.json; reusable (text,fol) API in src/metrics_api.py.
  workspace: >-
    /ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_experiment_2
  output_files:
  - method.py
  - full_method_out.json
  - mini_method_out.json
  - preview_method_out.json
- iteration: 1
  name: gen_art_dataset_1
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
  workspace: >-
    /ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_dataset_1
  output_files:
  - data.py
  - full_data_out.json
  - preview_data_out.json
  - mini_data_out.json
- iteration: 2
  name: gen_art_experiment_3
  type: experiment
  title: Checking a formula against its peers on fresh data
  summary: >-
    Freeze-then-confirm test of Directional Consensus (DC), a gold-free, text-blind NL->FOL faithfulness score: lexical-free
    vocabulary alignment of each peer output (L1 bijection / L2 partial map / L3 granularity), z3 entailment relation, DS-weighted
    EQUIV share. Library dc/ (directional_consensus, align_pair, pair_relation, fit_weights, type_error; 16 unit tests). Config
    frozen on 700 dev sentences (L3 off, UNALIGNABLE in denominator, DS weights; sha256 receipt 04:14 UTC; dev AUROC 0.777
    panel/0.855 solver) BEFORE fresh labels. Fresh set: 450 overlap-free sentences (MALLS 170, FOLIO-v2-train 150, ProverQA
    130) x 9 systems (4,050 greedy + 4,500 samples), labels: L0 gold audit (wrong gold MALLS 55%, FOLIO 62%, ProverQA 15%),
    L1 audited-solver (3,720 rows), L3 blinded panel (256 items, raked weights, Kish 202; planned ~1,000 but the $7 OpenRouter
    key shared by 3 experiments ran out; spend $2.38). Results: DC AUROC 0.827 panel / 0.874 solver; LC_ds_binary 0.830/0.865;
    B1 flash judge 0.791/0.727; VC 0.674/0.791; B2/B7 ~0.5. T1 (increment over frozen base [B1,B2,B3nliL,B3cosL,B7]) PASS:
    +0.033 (LB5 +0.005) panel, +0.118 solver; vs API-only base +0.126/+0.159. T2 label-dependent (DC not > LC_ds_binary on
    panel, -0.003). T3 typing fail (top-1 0.12). T4 DC_self == B8, fail. Secondaries: circularity AUROC 0.776 on solver-non-equivalent
    panel items; DC collapses when the modal cluster is wrong (0.42 vs B1 0.79); DC weaker than B1 on 2+ quantifiers / long
    sentences, stronger with 3+ conditions; invariance false alarms <=0.5% (VC 86%); gold-as-peer wrong-gold flag AUROC 0.86;
    controlled mutants detected 0.87-0.93 (arg swap 0.65); 43.8% correct-but-inequivalent. B3/TJ use local Qwen3-8B substitutes
    (key exhausted); B1plus, arbiter, EU-AI-Act not run. Headline AUROCs, T1, T2, placebos, wrong-gold and correct-but-inequivalent
    rates independently re-derived (results/rederive_headline.json). Outputs: method_out.json (exp_gen_sol_out, 4,050 examples,
    predict_DC etc.), results/fresh_set.jsonl (labelled meta-eval set, 8,550 rows), tests.json, analysis*.json, report_tables.md,
    deviations.json.
  workspace: >-
    /ai-inventor/aii_data/runs/run_ujABDGgoK_5Q/3_invention_loop/iter_2/gen_art/gen_art_experiment_3
  output_files:
  - method.py
  - full_method_out.json
  - mini_method_out.json
  - preview_method_out.json
  - reproducibility.md
- iteration: 2
  name: gen_art_experiment_4
  type: experiment
  title: Stress-testing peer-agreement scores for logic translations
  summary: >-
    DEV-set stress test of Directional Consensus (DC), a gold-free NL->FOL faithfulness metric: the reliability-weighted share
    of 9 peer system formalisations that are logically EQUIVALENT to a candidate under a name-free (L1 bijection / L2 partial
    / L3 granularity) alignment, z3-checked. Package dc/ (align_pair, pair_relation, best_relation, directional_consensus;
    12 unit tests), frozen config sha256 7ebda7e2, prereg before scoring. Results (700 sent x 9 systems, 609 weighted panel
    labels + solver labels, 2000-draw sentence bootstraps): M0 DC panel AUROC 0.769 [0.717,0.819] (solver 0.815) ~ LC_maj
    0.765, LC_ds 0.787, B1 judge 0.762; no-L3 variant DC_L2w 0.774/0.833; L1 cross-check vs round-2 cache 100%. M1 constructed
    vocab x meaning (223 sent): DC exactly vocab-invariant (gap 0.0015) while B1 judge drops 0.945->0.794 with random tokens
    and VC falls to 0.176 crossed; BUT L3 name-free definitions absorb negation (NEG AUROC 0.51 vs 1.00 without L3) and dropped
    restrictors (0.66 vs 0.99); automorphic mutants at chance. DC adds nothing over LC_maj in stacking (panel +0.015 [-0.009,0.040]).
    M2: rename FA(0.10)=0/999, contamination delta +0.002 vs B1 +0.096; 1/999 exact changes traced to a name-dependent role
    tie-break. M3 shared-bias dose curve equals the analytic peer-mass curve (0.93/0.77/0.43/0.14/0.06 for k=0..8); real within-sentence
    concordance falls to 0.45 when wrong clusters dominate (slope -2.08); text-anchored arbiter NOT RUN (OpenRouter run budget
    403). M4: within-sentence shuffle keeps AUROC 0.73 (most signal is between-sentence); L3 adds 11.9% spurious cross-sentence
    EQUIV. M5 ladder: L2 is the whole mechanism (+0.128), L3/DS neutral; typing below majority. M6 reproduces exp5 partnered
    counts (36/24); arXiv:2606.02837 v1 39%/36% vs v2 42.5%/42%. M7: DC(gold) flags wrong gold AUROC 0.837 [0.809,0.864],
    adds +0.070 over B1 and +0.048 over TJ. Verdicts 9 PASS/10 FAIL/1 NOT_RUN; amendments (use DC_L2w, name-free tie-break)
    in results/proposed_amendments.json. Files: method_out.json (6300 dev rows + 3175 probes + 700 golds), results/*.json,
    README.md; kept cache work/pairs_dc.jsonl (74k relations). Spend $0.088.
  workspace: >-
    /ai-inventor/aii_data/runs/run_ujABDGgoK_5Q/3_invention_loop/iter_2/gen_art/gen_art_experiment_4
  output_files:
  - method.py
  - full_method_out.json
  - mini_method_out.json
  - preview_method_out.json
  - reproducibility.md
- iteration: 2
  name: gen_art_experiment_5
  type: experiment
  title: Peer-agreement metric on long legal definitions
  summary: >-
    Secondary, panel-only transfer test of directional consensus (DC, contract v1, frozen before labels) on 158 long legal
    sentences (68 AI-Act Art.3 definitions, GDPR/DSA/DMA/Data Act, SARA-IRC, AI-Act top-up; marker bins B0 91/B1 51/B2 16).
    9 OpenRouter systems + 2x5 samples + 367 user pilot formulas; 655/680 sampled candidates labelled by the calibrated no-gold
    panel (haiku-4.5/grok-4.3/glm-4.6, Fleiss kappa 0.38; weighted faithful 9.4%). X1 PASS: AUROC(DC)=0.705 [0.608,0.792].
    X2 marginal PASS: +0.021 [-0.001,0.046] over [B1,parse]; no increment over the full base (+0.008). B1 cheap judge dominates
    (0.927); gemini-2.5-pro 0.852; LC_maj 0.754; B3 (local Qwen3-8B back-translation) 0.694; VC 0.685; B7 0.597; parse 0.569;
    shuffled-peer placebo 0.506. DC trails B1 in every marker bin; slope inconclusive; DC error naming fails (top-1 0.044).
    DC collapses when the modal cluster is wrong (0.624 vs 0.889). DS weights degenerate to the floor (EQUIV agreement 6%
    of legal pairs vs 19% on short text). Dev anchor DC 0.774 (round-2 0.756-0.787). Invariance false alarms 0-2%. Run-level
    API budget exhausted mid-run: B3/DC+arb use a local Qwen3-8B substitute; exception-sensitivity check not run. Spend $4.65.
    Key files: results/tests.json, results/analysis.json, results/exception_set.jsonl, results/scores.jsonl, dc/, README.md.
  workspace: >-
    /ai-inventor/aii_data/runs/run_ujABDGgoK_5Q/3_invention_loop/iter_2/gen_art/gen_art_experiment_5
  output_files:
  - method.py
  - full_method_out.json
  - mini_method_out.json
  - preview_method_out.json
  - reproducibility.md
</artifact_data>

<available_figures>
Each line gives the path the page must use, then the figure's title and caption.

- figures/fig1_v0.png [render from fig1_v0.pdf first] — "Peer agreement predicts faithfulness until peers share an error" (caption: "Peer agreement on 450 fresh sentences formalized by nine LLMs. (a) AUROC with sentence-clustered 95% intervals under blinded LLM-panel labels (256 items) and audited-solver labels (3,720 rows; round-trip NLI on 260 rows). Peer agreement is above the gemini-2.5-flash judge under both label families and ties binary Dawid-Skene agreement; parse rate and the structural consistency metrics are near chance. (b) Panel-label AUROC split by whether the sentence's modal equivalence cluster is faithful. When most systems share an error, agreement falls below chance while the judge is unaffected.")
- figures/fig2_v0.jpg — "How the peer agreement score is computed" (caption: "The peer agreement score. A candidate formula is compared with each peer formula (other systems' outputs for the same sentence) after a name-free vocabulary alignment (a bijection, then a partial map). An SMT solver decides the logical relation of each aligned pair. EQUIV relations define equivalence clusters, from which a label-free one-coin Dawid-Skene model estimates one reliability weight per system. The score is the weighted share of peers that are equivalent to the candidate. The sentence text and predicate names are never read.")
- figures/fig3_v0.png [render from fig3_v0.pdf first] — "Agreement ignores vocabulary; the judge does not" (caption: "Constructed vocabulary test on 223 development sentences with faithful gold: AUROC of faithful formulas against 739 operator mutants, with the same formulas rendered in the modal peer's vocabulary, in random tokens, in WordNet synonyms, and crossed (faithful formula in random tokens, mutants in conventional names). Peer agreement (without granularity definitions) and majority clustering are unchanged across renderings; the LLM judge loses up to 0.182 AUROC and the vocabulary-conformity control collapses in the crossed condition.")
- figures/fig4_v0.png [render from fig4_v0.pdf first] — "Shared errors defeat agreement by peer arithmetic" (caption: "The shared-error boundary. (a) Controlled dose test on 200 development sentences (560 items, four operators): probability that the faithful formula scores above a mutant when k of its eight peers are replaced by renamed copies of the mutant, for the configuration without granularity definitions, replacing peers in random order or faithful peers first. (b) Real development data (6,772 faithful × unfaithful pairs in 508 sentences, development configuration): within-sentence concordance of the agreement score by the peer-weight share held by wrong-meaning clusters, with 95% intervals; logistic slope −2.08 [−2.55, −1.61].")
- figures/fig5_v0.png [render from fig5_v0.pdf first] — "Agreement versus the judge as text gets complex" (caption: "Reliability by complexity under panel labels. (a) Fresh set: AUROC of peer agreement and the LLM judge per stratum of the four complexity features (items per stratum in parentheses); agreement leads on short, quantifier-free and low-nesting sentences and on sentences with three or more conditions, and trails on two or more quantifiers, deeper nesting and long sentences. (b) Legal definitions (655 items, sentence-only panel labels) by number of exception and condition markers: every gold-free score trails both judges in every bin; the upper two bins hold only 6 and 5 faithful items.")
</available_figures>

<data_requirements>
- Embed each dataset the views use as its own
  `<script type="application/json" id="data-..." data-source="...">` element, where
  `data-source` names the artifact and the output file it came from (for example
  `experiment_1/method_out.json`), never an absolute path. The inline script reads each one with
  `JSON.parse(document.getElementById(id).textContent)` and builds every chart, table, count and
  control from it; no number a view shows is typed into the markup by hand.
- Produce the embedded JSON with a script that reads the output files, not by copying values, so
  it is exactly what the files hold. Keep only the fields the views use.
- When a file is too large to embed whole, embed a subset chosen by a rule the page states (for
  example every failure plus a seeded random sample of the rest) and the aggregates computed from
  the full file.
- The numbers the prose states match the paper. A view may compute from the embedded data (a
  mean, a filter, a threshold swept over recorded scores), and says so; it never invents,
  interpolates, simulates or smooths a data point.
</data_requirements>

<figure_requirements>
- The page draws its own charts from the embedded data; the paper's figures are not its visuals.
  Show at most 3 of them, and only where a figure shows what the data cannot
  (the method diagram, an example rendering), never a data plot the page can draw live.
- Reference a figure as `figures/` plus its filename, exactly as listed above. The
  page and the figures folder are published together, so that relative path resolves on the live
  site and anything else breaks.
- A browser cannot draw a PDF in an image element. For a figure listed as "render from ...
  first", use the PNG of that name in `figures/` when it is already there, and
  otherwise render one there at about 200 DPI with pdftoppm or pymupdf. Renderable formats:
  .avif, .gif, .jpeg, .jpg, .png, .svg, .webp.
- Use the figure's own caption, and look at the figure before placing it.
</figure_requirements>

<page_structure>
Top to bottom:

1. HEADER: the title, the author line as the paper gives it, and the paper link as the primary
   button, labelled "Read the paper (PDF)". The other links from the links section sit beside it.
2. THE FINDING: the question and the answer in plain language, with the single number that
   carries it, and beside them the headline view, operable at once: the result drawn from the
   embedded data, the baseline shown with it, and a control over the conditions it was measured
   under.
3. HOW IT WORKS: a stepper that walks ONE real example from the data through the method's
   stages, showing at each stage what goes in, what is done to it, what comes out (the recorded
   values where the run kept them) and why. A pipeline diagram in inline SVG highlights the
   current stage; previous and next buttons, clickable stage markers and the left and right arrow
   keys move between stages.
4. EXPLORE THE EVIDENCE: two or more views over the real data, chosen from the kinds in the
   design philosophy to fit this result. At least one is an item browser: filter, search or sort
   over the real per-item records, and a detail panel that puts the selected item's input, the
   method's output and the baseline's output (or its before and after) side by side.
5. TRY IT: the live mini-demo when the method runs exactly in the page; otherwise a what-if view
   that sweeps a threshold or parameter over the recorded scores and recomputes the metrics live.
   Leave it out only when neither would be honest for this result, and say why in your summary.
6. WHERE IT FAILS: the failure cases from the data one control away, then what the paper says it
   does not show.
7. FOOTER: every link from the links section again, a data provenance list naming the artifact
   file behind each view, the glossary of every term with a tooltip, and the citation if the
   paper carries one.

A compact section navigation marks where the reader currently is. Each view opens with the
question it answers and ends with a takeaway sentence that updates with the selection.
</page_structure>

<interaction_requirements>
- Controls are real form controls or ARIA widgets: a range input with its current value printed
  beside it, a select, checkboxes, a radio group or tab list, buttons with aria-pressed. Each one
  changes a view without a page jump, and the view's counts and takeaway sentence change with it.
- Charts are inline SVG you generate, or canvas when there are thousands of marks: labelled axes
  with units, bars that start at zero, the baseline always shown, a legend when there is more than
  one series, and values printed at the precision the source has. Every mark shows its record on
  hover, on keyboard focus and on tap.
- Tooltips: each term trigger is a button with the term as its text, showing its definition on
  hover, on keyboard focus and on tap, dismissed by Escape and by tapping elsewhere, and exposed to
  assistive technology through aria-describedby. Define each term from the paper's own wording.
  A mouse click fires hover, focus and click in turn, and a tap fires focus and click, so a click
  handler that toggles closes the definition the moment it opened: every one of those events
  OPENS the tooltip, and only Escape, a click or tap elsewhere, or leaving the trigger closes it.
- Stepper: the current stage is announced through an aria-live region, the buttons disable at
  the ends, and the current stage marker carries aria-current.
- The page works with no network at all and logs no error or warning to the browser console.
</interaction_requirements>

<technical_requirements>
- ONE file: all CSS in a style element and all JavaScript in a script element, both inline in
  `interactive.html`, beside the data elements. No framework, no external script,
  stylesheet, web font or analytics. The only files the page may point at are the figures listed
  above.
- Plain modern JavaScript, no build step.
- Formulas use HTML sub and sup elements or inline MathML. TeX notation such as `^`, `_` or
  `\frac` must not reach the page.
- System font stack only. Light theme.
- Responsive from a 360px phone to a wide desktop with no horizontal page scroll; wide tables and
  charts scroll inside their own container or reflow, and charts redraw to their container width.
- Honour prefers-reduced-motion.
- Keyboard-navigable in a sensible Tab order with a visible focus ring and a skip link to the
  main content.
- Semantic HTML: one top-level heading, headings that descend without skipping, landmark
  elements, and alt text on every image that says what it shows.
- Keep the whole file under 3 MB.
</technical_requirements>

<page_gate>
When you finish, the page is loaded in a headless browser and sent back to you if its script
throws an error; if it has no `application/json` data element that its inline script reads by
id; if it shows more than 3 static images; or if, once its script has run, it
draws fewer than 2 charts (svg or canvas) or offers fewer than 3
controls. It is also sent back if `index.html` is present and does not link to
`interactive.html`.
</page_gate>

<writing_register>
Write in the register of the field's best papers (the paper this page teaches, which was written to them), not in the register of a language
model. Four things are measured on the finished draft, and a draft outside them is sent back with
the numbers:
- Never use: delve, underscore, showcase, intricate, pivotal, realm, commendable, meticulous, tapestry, garner, multifaceted, it is worth noting, plays a crucial role, not only ... but also. These are 10 to 30 times more frequent in machine-written abstracts than in
  human ones, and reviewers read them as such.
- Em dashes: at most 3 per 1,000 words. Use a comma, a colon or a full stop.
- Sentence rhythm: mix short and long sentences. An interquartile range of sentence length under
  8 words reads as machine-written.
- Hedging: at most 15 hedges (may, likely, suggests, appears) per 1,000
  words. State what the evidence supports plainly; hedge where it is thin, not everywhere.
Style never changes substance: numbers, claims, citations and figure markers stay exactly as the
evidence gives them. The user's original request (delivered as a separate message) overrides all
of this wherever the two conflict.
</writing_register>

<links>
Use these URLs VERBATIM. Do not shorten them, do not make any of them relative, and do not
compose one of your own.

- The paper PDF: https://cdn.jsdelivr.net/gh/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the@fork/run_TGmg0LeEY5Gp/paper.pdf
  Label it "Read the paper (PDF)"; it is the page's primary call to action.
- The code repository: https://github.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/tree/fork/run_TGmg0LeEY5Gp
- The full research report, every experiment and every table: https://cdn.jsdelivr.net/gh/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the@fork/run_TGmg0LeEY5Gp/report.pdf
  Label it "Read the full research report" and place it beside the paper link.

Each carries the branch this run publishes to, and they begin resolving only after this run
finishes publishing, so do NOT try to open or verify them.
</links>

<presentation_link>
When `index.html` is present, it is what a reader lands on, so your page is found only
if it links there. In `index.html`, add a link whose href is exactly
`interactive.html`, labelled "Explore the interactive paper", beside the paper link in the
hero and again beside it in the footer, styled like the links next to it. This one link is
relative, unlike the URLs above, because both pages are published into the same folder. Change
nothing else in `index.html`.
</presentation_link>

FIRST, add ALL of these to your todo list using your task/todo-tracking tool:

CRITICAL: Todo content must be copied exactly as is written here, with NO CHANGES. These todos are intentionally detailed so that another LLM could read each one without any external context and understand exactly what it has to do.

<todos>
TODO 1. Read `paper.tex` end to end and list `figures/`. Write down
the title, the author line, the question and the finding, the method's stages in order, every
technical term with the sentence that defines it, every headline number with the sentence it
appears in, and the limitations.
TODO 2. Open the output files in <artifact_data>, the `mini_` or `preview_` variant first. Write
down which files hold per-item records (inputs, outputs, scores, verdicts), which hold
per-condition, per-model or per-setting results, which hold the values a method stage recorded,
their fields, and how many rows each has. Note the ones that carry the paper's headline
numbers.
TODO 3. Design the page before writing it. For each view in the page_structure, write down the
reader's question, the file and fields it draws, the control, the chart, and the takeaway
sentence. Pick the views that make the finding VISIBLE (the gap between method and baseline, the
cases where it fails, the one example that shows the mechanism), not ones that restate a number
the prose already gives.
TODO 4. Write a script that reads those output files and writes the JSON each view embeds, then
check that every headline number it produces matches the paper.
TODO 5. Render the PNGs of the figures you will show (at most 3) into
`figures/`, then LOOK at each one.
TODO 6. Write `interactive.html` following the data_requirements, page_structure,
interaction_requirements and technical_requirements sections above.
TODO 7. VERIFY THE NUMBERS: every number in the prose appears in `paper.tex` with the
same meaning, and every embedded value traces to the output file its data-source names. Delete or
fix anything you cannot trace.
TODO 8. VERIFY THE PAGE: confirm it has no external script, stylesheet or font reference; that
every image path starts with `figures/` and names a file in `figures/`;
and that the paper, repository and report links are character-for-character the URLs in the
links section.
TODO 9. LINK YOUR PAGE from `index.html` when it is present, as the presentation_link
section says, then open `index.html` and confirm the link is in its hero and its footer
and that nothing else on that page changed.
TODO 10. OPERATE THE PAGE in a headless browser. `chromium-headless-shell` is already installed,
the same browser the finished page is checked in: drive it with Playwright (`uv pip install
playwright` in a scratch virtual environment, then launch Chromium with `executable_path` set
to the output of `which chromium-headless-shell`, with no `playwright install`). Only if that
command finds nothing, run `playwright install --with-deps chromium` instead. Open the page at
390px and 1440px wide, operate every control, hover and tap chart marks, step the stepper, select
items in the browser, click a term and confirm its definition is STILL showing after the click,
and confirm each view and its takeaway sentence change as they should. Use real clicks (the
browser's click, not a dispatched event), since that is what a reader's mouse and finger
produce. Screenshot each state, read the screenshots, and confirm the console shows no errors
and the page never scrolls sideways. Fix anything broken, cramped, overlapping, empty or cut
off, then operate it again.
</todos>

---

Output the result as JSON to: `./.terminal_claude_agent_struct_out.json`

JSON Schema:
```json
{
  "$defs": {
    "InteractivePaperExpectedFiles": {
      "description": "All expected output files from interactive-page generation.",
      "properties": {
        "page_html_path": {
          "description": "Path to the single self-contained HTML page. Example: 'interactive.html'",
          "title": "Page Html Path",
          "type": "string"
        }
      },
      "required": [
        "page_html_path"
      ],
      "title": "InteractivePaperExpectedFiles",
      "type": "object"
    }
  },
  "description": "Interactive paper page: structured output from gen_html_demo.",
  "properties": {
    "summary": {
      "description": "Brief summary of the page you built: each view and control, the question it answers, and the artifact output file its data came from.",
      "maxLength": 5000,
      "minLength": 300,
      "title": "Summary",
      "type": "string"
    },
    "out_expected_files": {
      "$ref": "#/$defs/InteractivePaperExpectedFiles",
      "description": "All output files you created. Must include interactive.html."
    }
  },
  "required": [
    "summary",
    "out_expected_files"
  ],
  "title": "InteractivePaper",
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

### [2] SYSTEM-USER prompt · 2026-09-24 17:08:17 UTC

```
[Image: original 3168x1344, displayed at 2000x848. Multiply coordinates by 1.58 to map to original image.]
```

### [3] SYSTEM-USER prompt · 2026-09-24 17:18:20 UTC

```
[Image: original 358x3557, displayed at 201x2000. Multiply coordinates by 1.78 to map to original image.]
```

### [4] SYSTEM-USER prompt · 2026-09-24 17:19:06 UTC

```
[Image: original 358x3111, displayed at 230x2000. Multiply coordinates by 1.56 to map to original image.]
```
