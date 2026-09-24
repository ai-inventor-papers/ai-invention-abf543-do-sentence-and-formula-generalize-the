# Gold-free checks of whether a logic formula matches its sentence

<div align="center">

<a href="https://cdn.jsdelivr.net/gh/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the@main/workflow.svg">
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="workflow-dark.svg">
  <img alt="Artifact workflow — how every artifact in this repo was built" src="workflow.svg">
</picture>
</a>

<sub>🖱️ <b><a href="https://cdn.jsdelivr.net/gh/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the@main/workflow.svg">Open the interactive diagram</a></b> — every card links to its artifact folder.</sub>

</div>

> **TL;DR** — We tested whether agreement among nine LLMs' first-order-logic formalizations of the same sentence, checked by an SMT solver without reading predicate names, predicts whether a formalization is faithful to its sentence. On 450 fresh sentences it reached 0.827 AUROC under LLM-panel labels and 0.874 under audited-solver labels, against 0.791 and 0.727 for a gemini-2.5-flash judge, and it is exactly invariant to predicate renaming. The evidence is preliminary: added to a judge-plus-round-trip baseline it gains only about 0.03 AUROC (95% CI -0.001 to 0.066), it ties an existing Dawid-Skene agreement estimator, and it drops to 0.419 AUROC when most systems share an error, which leaves it far behind the judge on long legal definitions (0.705 vs 0.927). It is useful as a complement to a text-reading judge and as a wrong-gold flag (0.84 to 0.86 AUROC), not as a replacement.

<details>
<summary>Full hypothesis</summary>

CLAIM (deepening the cross-output agreement lead; final round; claim kept at full size, test made stronger).
Two cheap gold-free signals fail in opposite, predictable regimes, and a combination rule that knows which regime it is in is safe in both.

(1) NAME-FREE AGREEMENT (DA). DA is the reliability-weighted share of other systems' outputs for the same sentence that Z3 proves EQUIVALENT to the candidate under an arity-preserving bijection or a partial map. It equals the frozen DC configuration of the fresh confirmation: levels 1-2, no granularity definitions, Dawid-Skene weights, UNALIGNABLE peers kept in the denominator.
- DA reads no text and no names. Across 1,794 renamings it never moved at delta=0.10.
- It fails exactly when the modal meaning cluster is wrong (shared bias). Fresh set: 0.419 when the mode is wrong vs 0.883 when it is right. Legal set: 0.624. Development dose curve: equal to the arithmetic of peer mass.

(2) CHEAP JUDGE (J). J is gemini-2.5-flash with the fixed prompt. It reads the text.
- Its accuracy does NOT depend on whether the mode is right: fresh 0.786 (mode wrong) vs 0.782 (mode right); legal 0.946 vs 0.885.
- It rewards conventional vocabulary: -0.151 AUROC when the same formula is written in random tokens.
- It is noisy across runs (0.017 AUROC).
- On the round-2 partnered set, all-pairs within-sentence detection of dropped conditions and implication direction was only 0.577 and 0.576.

CLAIM. A MODE-GATED ARBITRATION score (MGA), fitted once on development data and then frozen, transfers without refitting across populations whose shared-bias rate differs: development 41% of sentences mode-wrong, legal 76%. A fixed linear stack of the same inputs cannot do this. The best weight on agreement is a function of whether the mode is right, and the share of mode-wrong sentences changes from domain to domain. MGA estimates that function per sentence from the judge's view of the peer CLUSTERS.

DEFINITION (every step is zero-API once each output has one judge score).
- Cluster the sentence's parseable outputs by name-free equivalence, as DA does.
- q_k = mean J over the members of cluster k. Members of one cluster are the same meaning written in different vocabularies, so averaging over them also cancels part of the judge's vocabulary bias and run-to-run noise.
- Mode reliability r = sigmoid(a*(q_mode - max_{k!=mode} q_k) + b*w_mode + c), where w_mode is the Dawid-Skene weight share of the mode.
- MGA(x) = r*DA(x) + (1-r)*q_{cluster(x)}. An unparseable x gets J(x) alone, and is counted.
- a, b and c are fitted on development only and then frozen with a SHA receipt.
- Variant MGA+arb (secondary). When r < 0.5, the pre-registered text-anchored arbiter replaces the q comparison. The arbiter builds one Z3 distinguishing world between the two heaviest clusters, verbalizes it and asks gemini-2.5-flash to judge it against the SENTENCE. Its 1,402 prompts are already saved; running them costs about $0.10.

EVIDENCE PARTITION.
- DEVELOPMENT (fit a, b, c; freeze): the held-out set of 700 sentences x 9 systems (609 panel items; 5,847 solver rows). J and DA already exist for all 6,300 rows.
- CONFIRMATION-0 (fully unseen; primary if budget of about $2 or more exists): about 300 new sentences from the remaining Section-1.6 eligible pool, top tercile oversampled. They exclude every development, screen, contamination, fresh and tuning sentence. Same 9 systems and frozen prompt. The panel labels about 270 items: half from the modal/minority sampler, half uniform random, so that the within-sentence and population AUROCs are both unbiased.
- CONFIRMATION-1 (fresh set; 450 sentences, 256 panel items, 3,720 solver rows). MGA has never been computed on it. DC and J have already been read against its labels, so it is declared PARTIALLY SEEN. It becomes primary only if Confirmation-0 cannot be bought.
- TRANSFER (the shared-bias test): the legal set of 158 sentences and 655 panel labels. It needs J on all of about 1,420 legal outputs, a top-up of about $0.05.

LABELS.
- Short text: panel and audited-solver labels are co-primary, and a test passes only under both. Solver labels are derived from L1_audited_status. The sampler-bias check is reported: DA scores 0.850 on the panel frame vs 0.874 on all rows.
- Legal: panel only. This is a sentence-only LLM panel with kappa 0.38 overall and 0.17 in the high-marker bin, which can agree with LLM judges for reasons other than faithfulness. The cheap judge scoring above gemini-2.5-pro (0.927 vs 0.852) is recorded as unexplained.
- Before any legal result is read, buy the panel's 30-mutant exception-sensitivity check (about $0.3). If the panel misses more than 30% of exception mutants, all legal results are reported as label-limited.
- Robustness is reported under each single member's labels and on unanimous items.

PRE-REGISTERED TESTS. Each is a sentence-clustered paired bootstrap with 2,000 draws. BOTH the one-sided 5% bound and the two-sided 2.5% bound are reported. A test PASSES only on the two-sided 2.5% bound, round 2's rule, applied the same way to every metric.
- G1, AGREEMENT INCREMENT, POOLED. This is the honest re-test of the lead. The reviewer showed that the increment is +0.019 to +0.028 on held-out and +0.033 on fresh, and that it is significant only under the one-sided rule.
  - Setup: DA over the frozen base [J, parse, round-trip NLI, round-trip cosine, structural], pooled over held-out and fresh (and Confirmation-0 if built), cross-fitted within population and bootstrapped jointly.
  - Pass: two-sided lower bound > 0 under both labels. The binary Dawid-Skene form is reported beside it.
- G2, GATING BEATS LINEAR STACKING UNDER TRANSFER.
  - Setup: MGA vs a logistic stack [J, parse, DA] with the same inputs. Both are fitted on development only and frozen.
  - Pass: MGA minus the stack, lower bound > 0 on the legal panel labels; and non-inferiority on the confirmation set, lower bound > -0.01, under both labels.
- G3, SAFETY.
  - Legal: MGA >= J - 0.02 (lower bound).
  - Short-text confirmation: MGA > J with lower bound > 0 under both labels, and MGA >= DA (point estimate).
- G4, REPAIR, descriptive, since mode correctness is read from the labels.
  - Mode-wrong sentences: MGA >= J - 0.03 while DA collapses.
  - Mode-right sentences: MGA >= DA - 0.02.
  - Also reported: r against true mode correctness (AUROC), because it is the mechanism.

SECONDARY, reported and not deciding.
- MGA+arb vs MGA on sentences with r < 0.5.
- WRONG-GOLD FLAG, with the gold as a tenth peer (DA(gold), MGA(gold)).
  - Human-anchored check on the 99 MALLS golds with human corrections: compare with the signature's 0.635 and the judge's 0.759.
  - Also on the 700 + 450 panel-audited golds.
  - Reviewing-effort curve (share of items reviewed to reach 90% dataset accuracy) against the figure reported by Brunello et al. [4].
- The one open strand of the starting hypothesis, at zero API cost: within-sentence detection of dropped-condition and implication-direction errors by the alignment-only control and the rule-marker signature.
  - Run on the fresh partnered pairs and on the legal set's 20 dropped-condition and 83 implication-direction pairs, where J scores 0.875 and 0.837.
  - It is also a pre-declared secondary stack feature. It closes if it fails on both sets.
- The frontier judge (gemini-2.5-pro) on the fresh 256 items (about $0.3), under both labels.
- Invariance of MGA under renaming and rewrites at delta=0.10, split by component.
- Complexity: length, number of quantifiers, nesting depth, number of conditions, and legal marker bins.
- System-level Kendall tau, labelled descriptive.
- COST under two accountings.
  - Peers exist: MGA costs one judge call per output, about $0.00003 on short text and $0.00006 on legal, plus 0.16 to 1.3 CPU-s.
  - Peers generated: about $0.0007 per short item and $0.0025 per legal item. DA alone costs 13 to 31 times the judge.
  - Both are reported as cost per AUROC point over J, because the user allows extra cost only where it earns it.

DECISION.
- G1, G2 and G3 pass: supported. Name-free agreement complements a cheap judge, and gating it by the judged reliability of the clusters makes it safe where shared bias dominates. The deliverable is MGA.
- G1 passes and G2 fails: agreement complements a judge on short text only. Gating adds nothing a linear stack does not, and shared bias stays unsolved without reading the text.
- G1 fails on the two-sided bound: the agreement increment is +0.02 to +0.03, at the edge of significance, in every population. It is reported as such, with no complement claim.
- G3 fails on legal: no agreement-based score is safe on long exception-heavy text under these labels, and J alone is recommended there.

CLOSED STRANDS, one sentence each in the paper, no budget:
- the directional strength profile (AUROC 0.415, below chance);
- solver-derived error typing (top-1 0.122, 0.213 and 0.044 against majority classes of 0.22 to 0.26). Error-type NAMING is reported as an unmet requirement;
- granularity definitions (they absorb negations and dropped restrictors, and add 11.9% spurious equivalence);
- DC on a system's own samples (identical to sampling self-consistency);
- the monotonicity signature as a ranking metric;
- truth-value-judgment worlds;
- DeBERTa instance NLI;
- document-level conflation flags.

REPORTING OBLIGATIONS carried from the review:
- Replace the claim that DC was the 'first to pass an increment test' with the both-rules table.
- Qualify every legal conclusion with the LLM-panel caveat.
- Split the cost row into peers-exist and peers-generated.
- Give the coverage verdict as 'partial', naming what is missing.
- Cite FormalAlign (arXiv:2410.10135) and arXiv:2606.16118.
- Explain the 6% of legal rows where DC and DC_unw differ.
- Move the contamination comparison under invariance.
- Base the between-sentence statement on the solver-arm shuffle only.
- Add the M1b vocabulary-quintile table, the legal system-only frame (DC 0.729, J 0.931), the exact solver-label reproduction and a power line for the per-class tests.

DELIVERABLES. Each function comes with a one-line statement of what it measures:
- mga_score(text, fol, peers, judge_scores) -> {score, mode_reliability, agreement, cluster_judge, coverage, cost}
- agreement(fol, peers): frozen DC
- mode_reliability(clusters, judge_scores)
- gold_flag(gold, peers)
The meta-evaluation data are extended with Confirmation-0 if it is built.

</details>

[![Read the interactive presentation](https://img.shields.io/badge/Read-Interactive_Presentation-8A2BE2?style=for-the-badge)](https://ai-inventor-papers.github.io/ai-invention-abf543-do-sentence-and-formula-generalize-the/)

[![Download PDF](https://img.shields.io/badge/Download-PDF-red)](https://cdn.jsdelivr.net/gh/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the@main/paper.pdf) [![Read the full report](https://img.shields.io/badge/Read-Full_Report-blue)](https://cdn.jsdelivr.net/gh/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the@main/report.pdf) [![Read the internal report](https://img.shields.io/badge/Read-Internal_Report-green)](https://cdn.jsdelivr.net/gh/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the@main/round-2/report.pdf) [![LaTeX Source](https://img.shields.io/badge/LaTeX-Source-orange)](https://github.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/tree/main/paper_latex)

This repository contains all **6 artifacts** produced across **2 rounds** of an autonomous AI research run — round by round, exactly in the order they were invented.

## Round 1

| Artifact | Type | Demo | Source | Builds on |
|----------|------|------|--------|-----------|
| **[Screening solver-based faithfulness scores for logic transla…](https://github.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/tree/main/round-1/experiment-1)** | [![experiment](https://img.shields.io/badge/experiment-8b5cf6)](https://github.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/tree/main/round-1/experiment-1) | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/blob/main/round-1/experiment-1/demo/art_WABUmpThXw7N) | [![Source Code](https://img.shields.io/badge/Source_Code-2962FF)](https://github.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/tree/main/round-1/experiment-1/src) | — |
| **[Testing solver worlds and agreement as FOL checks](https://github.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/tree/main/round-1/experiment-2)** | [![experiment](https://img.shields.io/badge/experiment-8b5cf6)](https://github.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/tree/main/round-1/experiment-2) | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/blob/main/round-1/experiment-2/demo/art_n0DrABr4tqyb) | [![Source Code](https://img.shields.io/badge/Source_Code-2962FF)](https://github.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/tree/main/round-1/experiment-2/src) | — |
| **[Held-out NL-to-FOL Faithfulness Meta-Evaluation Set](https://github.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/tree/main/round-1/dataset-1)** | [![dataset](https://img.shields.io/badge/dataset-f59e0b)](https://github.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/tree/main/round-1/dataset-1) | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/blob/main/round-1/dataset-1/demo/art_iyzYyaqlqpSX) | [![Source Code](https://img.shields.io/badge/Source_Code-2962FF)](https://github.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/tree/main/round-1/dataset-1/src) | — |

## Round 2

| Artifact | Type | Demo | Source | Builds on |
|----------|------|------|--------|-----------|
| **[Checking a formula against its peers on fresh data](https://github.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/tree/main/round-2/experiment-3)** | [![experiment](https://img.shields.io/badge/experiment-8b5cf6)](https://github.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/tree/main/round-2/experiment-3) | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/blob/main/round-2/experiment-3/demo/art_D-NE4j8Hew3l) | [![Source Code](https://img.shields.io/badge/Source_Code-2962FF)](https://github.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/tree/main/round-2/experiment-3/src) | <sub><i>uses:</i><br/>[dataset‑1&nbsp;(R1)](https://github.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/tree/main/round-1/dataset-1)</sub> |
| **[Stress-testing peer-agreement scores for logic translations](https://github.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/tree/main/round-2/experiment-4)** | [![experiment](https://img.shields.io/badge/experiment-8b5cf6)](https://github.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/tree/main/round-2/experiment-4) | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/blob/main/round-2/experiment-4/demo/art_0IXpxygQOyeu) | [![Source Code](https://img.shields.io/badge/Source_Code-2962FF)](https://github.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/tree/main/round-2/experiment-4/src) | <sub><i>uses:</i><br/>[dataset‑1&nbsp;(R1)](https://github.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/tree/main/round-1/dataset-1)</sub> |
| **[Peer-agreement metric on long legal definitions](https://github.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/tree/main/round-2/experiment-5)** | [![experiment](https://img.shields.io/badge/experiment-8b5cf6)](https://github.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/tree/main/round-2/experiment-5) | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/blob/main/round-2/experiment-5/demo/art_opzsjP9sSoPn) | [![Source Code](https://img.shields.io/badge/Source_Code-2962FF)](https://github.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/tree/main/round-2/experiment-5/src) | <sub><i>uses:</i><br/>[dataset‑1&nbsp;(R1)](https://github.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/tree/main/round-1/dataset-1)</sub> |

## Repository Structure

Artifacts are grouped by the round of invention that produced them. Each
artifact has its own folder with source code and a self-contained demo:

```
.
├── round-1/                         # One folder per round of invention
│   ├── experiment-1/
│   │   ├── README.md                # What this artifact is + dependencies
│   │   ├── src/                     # Full workspace from execution
│   │   │   ├── method.py            # Main implementation
│   │   │   ├── method_out.json      # Full output data
│   │   │   └── ...                  # All execution artifacts
│   │   └── demo/                    # Self-contained demo
│   │       └── method_code_demo.ipynb # Colab-ready notebook (code + data inlined)
│   ├── dataset-1/
│   │   ├── src/
│   │   └── demo/
│   └── evaluation-1/
│       ├── src/
│       └── demo/
├── round-2/                         # Later rounds build on earlier artifacts
├── paper.pdf                        # Research paper
├── paper_latex/                     # LaTeX source files
├── report.pdf                       # Full internal report — every experiment, table and dead end
├── report_latex/                    # LaTeX source of the report
├── chat/                            # Every prompt, response and tool call, per module
├── workflow.svg                     # Artifact dependency diagram (this page's header)
└── README.md
```

## Running Notebooks

### Option 1: Google Colab (Recommended)

Click the "Open in Colab" badges above to run notebooks directly in your browser.
No installation required!

### Option 2: Local Jupyter

```bash
# Clone the repo
git clone https://github.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the
cd ai-invention-abf543-do-sentence-and-formula-generalize-the

# Install dependencies
pip install jupyter

# Run any artifact's demo notebook
jupyter notebook <artifact_folder>/demo/
```

## Source Code

The original source files are in each artifact's `src/` folder.
These files may have external dependencies - use the demo notebooks for a self-contained experience.

---
*Generated by AI Inventor Pipeline - Automated Research Generation*
