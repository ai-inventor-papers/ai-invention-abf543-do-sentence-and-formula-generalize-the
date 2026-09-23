# Do sentence and formula generalize the same way?

<div align="center">

<a href="https://cdn.jsdelivr.net/gh/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the@main/workflow.svg">
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="workflow-dark.svg">
  <img alt="Artifact workflow — how every artifact in this repo was built" src="workflow.svg">
</picture>
</a>

<sub>🖱️ <b><a href="https://cdn.jsdelivr.net/gh/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the@main/workflow.svg">Open the interactive diagram</a></b> — every card links to its artifact folder.</sub>

</div>

> **Hypothesis** — A candidate FOL formalization is faithful to its sentence only if the two share the same MONOTONICITY SIGNATURE. This signature records, for every concept the sentence mentions, whether the sentence stays true when that concept is made more general (upward), stays true when it is made more specific (downward), both (the concept is irrelevant, i.e. vacuous), or neither.

<details>
<summary>Full hypothesis</summary>

A candidate FOL formalization is faithful to its sentence only if the two share the same MONOTONICITY SIGNATURE. This signature records, for every concept the sentence mentions, whether the sentence stays true when that concept is made more general (upward), stays true when it is made more specific (downward), both (the concept is irrelevant, i.e. vacuous), or neither. It also records which concept fills each argument slot of each relation (ROLE ANCHORING). Both sides can be measured with the SAME substitution experiment. (i) On the formula, a solver checks exactly, for each predicate P, whether P ⊆ P' ∧ F(P) ∧ ¬F(P') and P ⊆ P' ∧ F(P') ∧ ¬F(P) are unsatisfiable on finite structures, and whether restricting relation slot i to a unary predicate A ever changes F. (ii) On the sentence, a behavioural probe asks a mid-size LLM English-to-English entailment questions between the sentence and copies of it in which one concept is specialized ('dogs' → 'brown dogs', 'provider' → 'European provider'). The LLM never sees any formula. Because the formula-side signature is a semantic property, it is by construction invariant to logical equivalence, variable and predicate renaming, reordering, and most granularity choices (for example 'UntrainedDog(x)' vs 'Dog(x) ∧ ¬Trained(x)'). So it scores correct-but-gold-inequivalent formalizations as faithful. The mismatch vector is a gold-free faithfulness score and also names the error type:
- one concept's sign flipped → negation/polarity error;
- restrictor turned from downward to upward → ∀/∃ error;
- restrictor and scope signs swapped → reversed implication / 'only' error;
- a sentence concept with no non-vacuous predicate → dropped condition;
- a predicate with no sentence concept, or a vacuous one → added condition;
- swapped slot anchors → swapped arguments;
- two concepts with different signatures merged into one predicate → conflation;
- one concept split into predicates with opposite signs → wrong split.
Mechanistic prediction: the signature has one coordinate per concept, so its detecting power GROWS with the number of conditions and exceptions, while whole-formula judges (LLM-as-judge, round-trip) degrade with length. This predicts a crossover in which the signature beats the judge on long, heavily conditioned sentences. The theory also predicts its blind spots in advance: pure quantifier-scope permutations and cardinality errors leave the signature unchanged, so detection of those should sit at chance. That is a falsifiable part of the claim.

</details>

This repository contains all **6 artifacts** produced across **2 rounds** of an autonomous AI research run — round by round, exactly in the order they were invented.

## Round 1

| Artifact | Type | Demo | Source | Builds on |
|----------|------|------|--------|-----------|
| **[Screening solver-based faithfulness scores for logic transla…](https://github.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/tree/main/round-1/experiment-1)** | [![experiment](https://img.shields.io/badge/experiment-8b5cf6)](https://github.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/tree/main/round-1/experiment-1) | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/blob/main/round-1/experiment-1/demo/method_code_demo.ipynb) | [![Source Code](https://img.shields.io/badge/Source_Code-2962FF)](https://github.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/tree/main/round-1/experiment-1/src) | — |
| **[Testing solver worlds and agreement as FOL checks](https://github.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/tree/main/round-1/experiment-2)** | [![experiment](https://img.shields.io/badge/experiment-8b5cf6)](https://github.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/tree/main/round-1/experiment-2) | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/blob/main/round-1/experiment-2/demo/method_code_demo.ipynb) | [![Source Code](https://img.shields.io/badge/Source_Code-2962FF)](https://github.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/tree/main/round-1/experiment-2/src) | — |
| **[Held-out NL-to-FOL Faithfulness Meta-Evaluation Set](https://github.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/tree/main/round-1/dataset-1)** | [![dataset](https://img.shields.io/badge/dataset-f59e0b)](https://github.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/tree/main/round-1/dataset-1) | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/blob/main/round-1/dataset-1/demo/data_code_demo.ipynb) | [![Source Code](https://img.shields.io/badge/Source_Code-2962FF)](https://github.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/tree/main/round-1/dataset-1/src) | — |

## Round 2

| Artifact | Type | Demo | Source | Builds on |
|----------|------|------|--------|-----------|
| **[Held-out check of gold-free logic-translation metrics](https://github.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/tree/main/round-2/experiment-3)** | [![experiment](https://img.shields.io/badge/experiment-8b5cf6)](https://github.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/tree/main/round-2/experiment-3) | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/blob/main/round-2/experiment-3/demo/method_code_demo.ipynb) | [![Source Code](https://img.shields.io/badge/Source_Code-2962FF)](https://github.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/tree/main/round-2/experiment-3/src) | <sub><i>uses:</i><br/>[dataset‑1&nbsp;(R1)](https://github.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/tree/main/round-1/dataset-1)</sub> |
| **[Repaired world-truth checks lose to the plain judge](https://github.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/tree/main/round-2/experiment-4)** | [![experiment](https://img.shields.io/badge/experiment-8b5cf6)](https://github.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/tree/main/round-2/experiment-4) | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/blob/main/round-2/experiment-4/demo/method_code_demo.ipynb) | [![Source Code](https://img.shields.io/badge/Source_Code-2962FF)](https://github.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/tree/main/round-2/experiment-4/src) | <sub><i>uses:</i><br/>[dataset‑1&nbsp;(R1)](https://github.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/tree/main/round-1/dataset-1)</sub> |
| **[Repaired FOL signature: error naming and bad-gold flags](https://github.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/tree/main/round-2/experiment-5)** | [![experiment](https://img.shields.io/badge/experiment-8b5cf6)](https://github.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/tree/main/round-2/experiment-5) | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/blob/main/round-2/experiment-5/demo/method_code_demo.ipynb) | [![Source Code](https://img.shields.io/badge/Source_Code-2962FF)](https://github.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/tree/main/round-2/experiment-5/src) | <sub><i>uses:</i><br/>[dataset‑1&nbsp;(R1)](https://github.com/ai-inventor-papers/ai-invention-abf543-do-sentence-and-formula-generalize-the/tree/main/round-1/dataset-1)</sub> |

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
