# Held-out confirmation of gold-free NL→FOL faithfulness metrics (run_qY2a2IS-WLIs, iteration 2)

This repository re-runs the iteration-1 screen metrics **with their frozen iteration-1 code, prompts and thresholds** on a fresh population:
- **700 sentences × 9 LLM systems = 6,300 real candidate formalisations** (dataset `art_iyzYyaqlqpSX`).
- **Primary labels:** the **609 blinded, family-disjoint 3-model panel adjudications** (307 faithful / 302 unfaithful), post-stratified weights, Kish n_eff 350.
- **Secondary labels:** audited-solver labels (5,847 rows).
- **Tertiary labels:** soft stratum labels.
- **CIs:** 1,000× sentence bootstrap within corpus × tercile strata, seed 0.

Workspace (absolute path, where every kept artefact lives):
`/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_2/gen_art/gen_art_experiment_3`

> **Deviation D-LLM (budget/outage).**
> - The shared OpenRouter key was exhausted (daily limit) when the LLM stage began.
> - While it was down, the frozen prompts were answered by a local **Qwen3-8B** on the RTX 4090. These are the substitutes, suffix **L**: B1L, B1plusL (thinking mode), A1L, B3cosL, B3nliL, B3cL, RECALL_L.
> - After the platform restored the key (about $7 left for all runs today), the **frozen gemini metrics were run**, for **$2.70 in total**:
>   - **B1** on all 6,300 held-out + 936 contamination rows, plus a 300-call sequential retest;
>   - **B3** back-translation on the panel items + the 3-system contamination slice;
>   - **B1plus = google/gemini-2.5-pro** on the 609 panel items only;
>   - **A1** on the 530 panel + contamination sentences only.
> - The last two restrictions follow plan fallback 5.
> - The gemini B3c and gold-recall probe were not re-run. Only their local substitutes are reported.
> - The **frozen metrics are primary**. The L substitutes are kept as secondary rows.
> - All deviations are in `results/deviations.json`.

## 1. Headline results

All numbers come from `results/analysis.json` and `results/confirmation_table.json`. The **frozen stacking base** is [B1, B2, B3nli, B3cos, B7], with OOF AUROC_base = 0.788.

### 1.1 Confirmation table (pre-registered C1–C3; P = panel, weighted)

The pre-registered criteria:
- C1: AUROC_P ≥ 0.70.
- C2: the ΔAUROC of the cross-fitted sentence-grouped logistic stack over the base has a 95% lower bound > 0.
- C3: coverage ≥ 0.70, with unscored items = 0.5.

Coverage is computed over all 6,300 rows, except for A1, B1plus and B3* (and the L versions), where it is computed over the rows each metric ran on. "–" in C2 means the metric is itself in the base.

| metric | AUROC_P [95% CI] | AUROC_S | AUROC_T | AUROC_U | coverage | C1 | C2 ΔAUROC [CI] | C3 | CONFIRMED | top-tercile AUROC_P |
|---|---|---|---|---|---|---|---|---|---|---|
| LC_onecoin | 0.756 [0.701, 0.808] | 0.810 | 0.680 | 0.836 | 0.937 | Y | 0.019 [-0.003, 0.043] | Y | no | 0.719 |
| LC_huiwalter | 0.755 [0.700, 0.809] | 0.810 | 0.680 | 0.837 | 0.937 | Y | 0.019 [-0.003, 0.043] | Y | no | 0.718 |
| LC_maj | 0.765 [0.710, 0.816] | 0.824 | 0.664 | 0.847 | 0.937 | Y | 0.028 [-0.002, 0.056] | Y | no | 0.744 |
| LC_ds_binary | 0.787 [0.733, 0.836] | 0.831 | 0.677 | 0.870 | 0.937 | Y | 0.022 [-0.005, 0.049] | Y | no | 0.777 |
| LC_onecoin_str | 0.757 [0.702, 0.810] | 0.811 | 0.680 | 0.839 | 0.937 | Y | 0.021 [-0.002, 0.045] | Y | no | 0.720 |
| LC_granular | 0.753 [0.697, 0.805] | 0.813 | 0.685 | 0.832 | 0.937 | Y | 0.020 [-0.000, 0.042] | Y | no | 0.725 |
| A3 | 0.642 [0.589, 0.695] | 0.609 | 0.599 | 0.663 | 0.904 | n | 0.016 [-0.000, 0.035] | Y | no | 0.570 |
| A0 | 0.656 [0.604, 0.705] | 0.654 | 0.617 | 0.697 | 0.904 | n | 0.015 [-0.002, 0.034] | Y | no | 0.594 |
| Ccov | 0.655 [0.607, 0.705] | 0.642 | 0.614 | 0.695 | 0.937 | n | 0.010 [-0.004, 0.025] | Y | no | 0.605 |
| A1 | 0.657 [0.603, 0.708] | 0.579 | 0.589 | 0.699 | 0.875 | n | 0.012 [-0.002, 0.028] | Y | no | 0.596 |
| B1 | 0.762 [0.718, 0.804] | 0.713 | 0.637 | 0.833 | 1.000 | Y | – – | Y | no | 0.779 |
| B1plus | 0.825 [0.788, 0.860] | 0.802 | 0.802 | 0.902 | 1.000 | Y | 0.034 [0.017, 0.052] | Y | **YES** | 0.834 |
| B3cos | 0.723 [0.673, 0.770] | 0.647 | 0.642 | 0.764 | 1.000 | Y | – – | Y | no | 0.669 |
| B3nli | 0.734 [0.682, 0.782] | 0.631 | 0.659 | 0.812 | 1.000 | Y | – – | Y | no | 0.668 |
| A1L | 0.557 [0.500, 0.610] | 0.561 | 0.558 | 0.569 | 0.896 | n | -0.001 [-0.005, 0.003] | Y | no | 0.497 |
| B1L | 0.704 [0.664, 0.746] | 0.662 | 0.605 | 0.751 | 1.000 | Y | 0.017 [-0.001, 0.035] | Y | no | 0.643 |
| B1plusL | 0.791 [0.753, 0.826] | 0.781 | 0.781 | 0.873 | 0.749 | Y | 0.046 [0.021, 0.073] | Y | **YES** | 0.759 |
| B3cosL | 0.723 [0.672, 0.770] | 0.617 | 0.629 | 0.761 | 1.000 | Y | 0.014 [-0.001, 0.030] | Y | no | 0.697 |
| B3nliL | 0.748 [0.697, 0.796] | 0.641 | 0.675 | 0.814 | 1.000 | Y | 0.011 [-0.004, 0.028] | Y | no | 0.717 |
| B3cL | 0.601 [0.567, 0.637] | 0.580 | 0.580 | 0.631 | 1.000 | n | 0.002 [-0.008, 0.013] | Y | no | 0.606 |
| B2 | 0.500 [0.500, 0.500] | 0.500 | 0.556 | 0.500 | 1.000 | n | – – | Y | no | 0.500 |
| B2_armB | 0.511 [0.495, 0.526] | 0.509 | 0.560 | 0.519 | 1.000 | n | -0.001 [-0.005, 0.003] | Y | no | 0.499 |
| B7 | 0.511 [0.500, 0.526] | 0.509 | 0.556 | 0.517 | 1.000 | n | – – | Y | no | 0.497 |
| B7_arity_self | 0.501 [0.500, 0.503] | 0.501 | 0.557 | 0.501 | 1.000 | n | -0.000 [-0.000, 0.000] | Y | no | 0.502 |
| B7_arity_story | 0.511 [0.502, 0.525] | 0.509 | 0.557 | 0.515 | 1.000 | n | -0.002 [-0.015, 0.007] | Y | no | 0.505 |
| B7_joint | 0.500 [0.495, 0.507] | 0.500 | 0.556 | 0.503 | 1.000 | n | -0.001 [-0.015, 0.007] | Y | no | 0.492 |
| LC_within | 0.728 [0.581, 0.854] | 0.753 | 0.664 | 0.834 | 0.944 | Y | -0.004 [-0.030, 0.017] | Y | no | 0.670 |
| B8 | 0.771 [0.660, 0.860] | 0.748 | 0.650 | 0.852 | 0.944 | Y | 0.026 [-0.008, 0.067] | Y | no | 0.706 |
| B7_jacc | 0.787 [0.670, 0.879] | 0.659 | 0.606 | 0.836 | 0.949 | Y | 0.003 [-0.023, 0.028] | Y | no | 0.797 |

**Readings**

- **No candidate metric CONFIRMS.** The only metric passing C1–C3 is the frontier judge **B1plus**: gemini-2.5-pro with the frozen B1 prompt, a cost-comparison baseline.
  - AUROC_P 0.825 [0.788, 0.860].
  - Stacking increment +0.034 [0.017, 0.052].

- **Latent-class agreement (LC_onecoin, the iter-1 screen winner) replicates as a standalone predictor but does not add to the frozen baseline stack.**
  - C1 passes: AUROC_P 0.756 [0.701, 0.808]. Solver labels give 0.810 and the unanimous subset 0.836.
  - C3 passes: coverage 0.937.
  - **C2 fails**: +0.019 [−0.003, 0.043]. LC_maj (+0.028 [−0.002, 0.056]), LC_ds_binary and LC_huiwalter behave the same.
  - Sensitivity:
    - base without round-trip [B1, B2, B7], AUROC 0.730: LC adds +0.049 [0.017, 0.085];
    - with B1plus in the base (AUROC 0.822): LC adds +0.010 [−0.010, 0.030].
  - LC and A3 together add +0.030 [0.005, 0.057]. All candidates together add +0.073 [0.038, 0.111].
  - Independent re-derivation (numpy IRLS, other folds): LC +0.020, against the analysis value of +0.019. The shuffled-LC placebo gives +0.004.

- **Monotonicity signature A3 does NOT replicate.**
  - A3: AUROC_P 0.642 [0.589, 0.695], versus 0.718 on the screen. C1 fails.
  - The alignment-only control A0 (0.656) and the coverage control Ccov (0.655) do as well as A3.
  - The polarity increment of A3 over A0 is +0.002 [−0.008, 0.013]: the iter-1 null again.
  - The gemini text-side variant **A1** (panel + contamination sentences) gets 0.657 [0.603, 0.708]; C1 fails.

- **Cheap judge B1** (gemini-2.5-flash, frozen prompt):
  - AUROC_P 0.762 [0.718, 0.804], solver labels 0.713.
  - Test-retest over 300 sequential re-calls: Spearman 0.965; 2.3% of scores move by more than 0.2.

- **Round trip.** B3nli 0.734 and B3cos 0.723 on the panel. The local B3cL substitute gives 0.601.

- **Structural metrics (the user's pilot family) are at chance on the panel.** B2 parse is 0.500, and B7 and its components are 0.50–0.51.
  - On the two systems with samples, B8 self-consistency (0.771) and B7_jacc (0.787) are informative.
  - They do not add over the base (n = 138).

- **Local substitutes (secondary).**
  - B1L 0.704, weaker than B1.
  - B1plusL (Qwen3-8B thinking) 0.791 at coverage 0.749.
  - A1L 0.557.
  - B3nliL 0.748.

### 1.2 Is LC's win a shared-checker artefact? (circularity; panel items)

Test (b) is restricted to the 545 panel items whose candidate is solver-NON-equivalent to the audited gold; 43.9% of them are faithful.

| metric | (b) AUROC [CI] | reading | (d) no-bijection AUROC [CI] | (a) panel − solver-pure [CI] |
|---|---|---|---|---|
| LC_onecoin | 0.722 [0.669, 0.770] | not a checker artefact | 0.711 [0.653, 0.767] | -0.042 [-0.110, 0.018] |
| LC_maj | 0.741 [0.693, 0.786] | not a checker artefact | 0.749 [0.701, 0.796] | -0.036 [-0.109, 0.027] |
| LC_ds_binary | 0.773 [0.729, 0.815] | not a checker artefact | 0.779 [0.734, 0.822] | -0.025 [-0.096, 0.040] |
| LC_huiwalter | 0.721 [0.669, 0.770] | not a checker artefact | 0.711 [0.652, 0.767] | -0.042 [-0.110, 0.018] |
| LC_granular | 0.726 [0.674, 0.773] | not a checker artefact | 0.715 [0.659, 0.769] | -0.029 [-0.091, 0.032] |
| A3 | 0.609 [0.554, 0.667] |  | 0.616 [0.558, 0.675] | 0.040 [-0.028, 0.103] |
| A0 | 0.593 [0.536, 0.646] |  | 0.606 [0.544, 0.667] | -0.029 [-0.089, 0.025] |
| Ccov | 0.602 [0.547, 0.652] |  | 0.618 [0.560, 0.675] | -0.017 [-0.073, 0.038] |
| A1 | 0.622 [0.569, 0.676] |  | 0.617 [0.560, 0.677] | 0.024 [-0.035, 0.079] |
| B1 | 0.709 [0.661, 0.753] |  | 0.702 [0.645, 0.755] | 0.005 [-0.046, 0.058] |
| B1plus | 0.785 [0.742, 0.823] |  | 0.783 [0.735, 0.826] | 0.089 [0.035, 0.142] |
| B3nli | 0.709 [0.655, 0.757] |  | 0.717 [0.657, 0.769] | 0.063 [-0.008, 0.139] |
| B3cos | 0.679 [0.627, 0.730] |  | 0.678 [0.613, 0.735] | 0.081 [0.013, 0.144] |
| A1L | 0.538 [0.482, 0.595] |  | 0.538 [0.482, 0.598] | -0.018 [-0.074, 0.040] |
| B1L | 0.663 [0.619, 0.706] |  | 0.659 [0.611, 0.706] | 0.068 [0.019, 0.123] |
| B1plusL | 0.789 [0.756, 0.824] |  | 0.788 [0.750, 0.823] | 0.108 [0.066, 0.153] |
| B3nliL | 0.731 [0.678, 0.778] |  | 0.738 [0.688, 0.789] | 0.086 [0.009, 0.166] |
| B3cosL | 0.670 [0.616, 0.718] |  | 0.688 [0.631, 0.738] | 0.046 [-0.018, 0.109] |
| B3cL | 0.603 [0.565, 0.641] |  | 0.611 [0.573, 0.651] | 0.038 [0.003, 0.081] |
| B7 | 0.507 [0.494, 0.524] |  | 0.507 [0.491, 0.527] | -0.004 [-0.013, 0.005] |

- **Pre-registered reading for LC_onecoin: "not a checker artefact".** The (b) AUROC is 0.722 [0.669, 0.770]; the no-bijection subset (d) gives 0.711.
- (a) On the same items, LC's AUROC against the panel does not differ significantly from its AUROC against solver-pure labels: the difference is −0.042 [−0.110, 0.018].
  - The judges gain under panel labels: B1plus +0.089 [0.035, 0.142].
- (c) Class position:
  - panel-faithful but solver-non-equivalent candidates fall in a minority or singleton LC class 35% of the time (mean LC 0.58);
  - panel-unfaithful non-equivalent candidates do so 69% of the time (mean LC 0.26).

### 1.3 Complexity: the pre-registered crossover vs B1

**No crossover is confirmed** for any metric under any labelling. On the panel's top tercile (n = 389), B1 reaches 0.779, above LC (0.719). Unlike on the screen, the cheap judge does not collapse on complex held-out items. The gap LC − B1 in the top tercile is −0.059 [−0.137, 0.015].

| pop|metric | gap bottom/middle/top | slope [CI] | top gap CI | CONFIRMED | interaction>0 |
|---|---|---|---|---|---|
| P|LC_onecoin | -0.051/0.136/-0.059 | -0.004 [-0.074, 0.064] | [-0.137, 0.015] | False | False |
| P|A3 | -0.144/0.038/-0.209 | -0.032 [-0.117, 0.055] | [-0.307, -0.108] | False | False |
| P|A1 | -0.114/0.011/-0.183 | -0.034 [-0.114, 0.040] | [-0.279, -0.089] | False | False |
| P|B1plus | -0.004/0.143/0.056 | 0.030 [-0.031, 0.088] | [0.008, 0.109] | False | False |
| P|B3nli | -0.074/0.128/-0.110 | -0.018 [-0.090, 0.055] | [-0.192, -0.029] | False | False |
| S|LC_onecoin | 0.129/0.103/0.071 | -0.029 [-0.059, 0.005] | [0.032, 0.106] | False | False |
| S|A3 | -0.108/-0.107/-0.130 | -0.011 [-0.052, 0.030] | [-0.184, -0.079] | False | False |
| S|A1 | -0.068/-0.079/-0.167 | -0.050 [-0.096, 0.003] | [-0.215, -0.114] | False | False |
| S|B1plus | 0.020/0.136/0.050 | 0.015 [-0.040, 0.068] | [0.005, 0.091] | False | False |
| S|B3nli | -0.029/0.014/-0.068 | -0.020 [-0.071, 0.035] | [-0.140, 0.005] | False | False |
| T|LC_onecoin | 0.077/0.040/0.023 | -0.027 [-0.046, -0.009] | [0.003, 0.043] | False | None |
| T|A3 | -0.080/-0.036/-0.028 | 0.026 [-0.000, 0.050] | [-0.053, -0.001] | False | None |
| T|A1 | -0.079/0.010/-0.046 | 0.017 [-0.018, 0.047] | [-0.071, -0.017] | False | None |
| T|B1plus | 0.020/0.136/0.050 | 0.015 [-0.036, 0.062] | [0.005, 0.093] | False | None |
| T|B3nli | -0.026/0.066/-0.059 | -0.016 [-0.059, 0.031] | [-0.112, -0.004] | False | None |

| cell | n (pos/neg) | LC_onecoin | LC_ds_binary | A3 | B1 | B1plus | B3nli |
|---|---|---|---|---|---|---|---|
| P|tn=1 | 105 (64/41) | 0.747 | 0.754 | 0.654 | 0.798 | 0.794 | 0.724 |
| P|tn=2 | 115 (67/48) | 0.808 | 0.825 | 0.709 | 0.671 | 0.814 | 0.799 |
| P|tn=3 | 389 (176/213) | 0.719 | 0.777 | 0.570 | 0.779 | 0.834 | 0.668 |
| P|nbin=0-1 | 209 (116/93) | 0.793 | 0.810 | 0.659 | 0.741 | 0.796 | 0.765 |
| P|nbin=2-3 | 241 (119/122) | 0.653 | 0.708 | 0.626 | 0.753 | 0.804 | 0.674 |
| P|nbin=4+ | 159 (72/87) | 0.857 | 0.874 | 0.657 | 0.800 | 0.909 | 0.768 |
| S|tn=1 | 1528 (729/799) | 0.841 | 0.876 | 0.605 | 0.713 | 0.800 | 0.656 |
| S|tn=2 | 1773 (666/1107) | 0.794 | 0.808 | 0.583 | 0.691 | 0.794 | 0.623 |
| S|tn=3 | 2546 (822/1724) | 0.790 | 0.808 | 0.589 | 0.719 | 0.787 | 0.619 |
| S|nbin=0-1 | 2363 (877/1486) | 0.813 | 0.847 | 0.602 | 0.707 | 0.773 | 0.619 |
| S|nbin=2-3 | 2093 (738/1355) | 0.770 | 0.796 | 0.583 | 0.668 | 0.775 | 0.599 |
| S|nbin=4+ | 1391 (602/789) | 0.865 | 0.866 | 0.677 | 0.774 | 0.877 | 0.689 |

### 1.4 System level (9 systems; underpowered by design, not a gate)

| metric | tau_b all items [CI] | pairwise acc | tau_b panel [CI] |
|---|---|---|---|
| LC_onecoin | 0.778 [0.667, 0.944] | 0.889 | 0.556 [0.111, 0.778] |
| LC_maj | 0.722 [0.556, 0.833] | 0.861 | 0.278 [-0.111, 0.667] |
| LC_ds_binary | 0.722 [0.611, 0.889] | 0.861 | 0.278 [-0.167, 0.667] |
| A3 | 0.833 [0.667, 0.889] | 0.917 | 0.222 [-0.056, 0.667] |
| A0 | 0.556 [0.389, 0.722] | 0.778 | 0.333 [0.056, 0.722] |
| A1 | – – | – | 0.333 [-0.056, 0.667] |
| B1 | 0.889 [0.722, 0.944] | 0.944 | 0.722 [0.389, 0.889] |
| B1plus | – – | – | 0.778 [0.444, 0.944] |
| B3nli | – – | – | 0.722 [0.333, 0.833] |
| B1L | 0.889 [0.778, 1.000] | 0.944 | 0.333 [0.165, 0.722] |
| B1plusL | – – | – | 0.778 [0.444, 0.889] |
| B2 | 0.817 [0.592, 0.889] | 0.889 | – – |
| B7 | 0.761 [0.500, 0.833] | 0.861 | 0.377 [-0.131, 0.609] |
| RANDOM | -0.278 [-0.611, 0.111] | 0.361 | -0.056 [-0.389, 0.333] |

### 1.5 Contamination (104 entity-renamed paraphrase pairs, 936 rows)

Every metric scores the original higher than the renamed paraphrase (B1 +0.096 [0.068, 0.126]). No metric's AUROC differs significantly between originals and paraphrases.

For the zero-LLM signature metrics, the Δ comes from the lexical aligner breaking under renamed entities (the iter-1 SYN_RENAME weakness).

Gold-recall probe (local Qwen3-8B only; the gemini probe was skipped for budget):
- predicate-name recall of the benchmark gold is 0.335 on originals vs 0.243 on paraphrases, a difference of +0.092 [0.014, 0.169];
- exact match is ~1% on both.
- So there is mild vocabulary familiarity and no verbatim recall.

Self-preference check: gemini-2.5-pro's AUROC is 0.853 on the two Google-family generators and 0.817 on the others (n_own = 130).

| metric | mean Δ(orig−para) [CI] | AUROC orig | AUROC para | diff [CI] |
|---|---|---|---|---|
| B1 | 0.096 [0.068, 0.126] | 0.625 | 0.647 | -0.022 [-0.067, 0.030] |
| B3cos | 0.070 [0.029, 0.107] | 0.626 | 0.601 | 0.025 [-0.031, 0.088] |
| B3nli | 0.074 [0.018, 0.131] | 0.611 | 0.565 | 0.046 [-0.034, 0.129] |
| A1 | 0.142 [0.112, 0.176] | 0.564 | 0.532 | 0.032 [-0.055, 0.121] |
| B1L | 0.026 [0.013, 0.039] | 0.577 | 0.608 | -0.032 [-0.068, 0.010] |
| B3cosL | 0.101 [0.071, 0.130] | 0.516 | 0.554 | -0.038 [-0.125, 0.052] |
| B3nliL | 0.092 [0.035, 0.150] | 0.584 | 0.543 | 0.042 [-0.029, 0.117] |
| B3cL | 0.119 [0.064, 0.179] | 0.532 | 0.551 | -0.018 [-0.073, 0.039] |
| A1L | 0.106 [0.078, 0.137] | 0.581 | 0.510 | 0.072 [-0.016, 0.164] |
| A3 | 0.141 [0.108, 0.175] | 0.579 | 0.525 | 0.054 [-0.052, 0.158] |
| A0 | 0.186 [0.158, 0.214] | 0.559 | 0.529 | 0.030 [-0.062, 0.126] |
| Ccov | 0.236 [0.201, 0.275] | 0.567 | 0.598 | -0.031 [-0.094, 0.035] |

### 1.6 Screen re-rank under the dataset's audited screen labels (`results/screen_rerank.json`)

- Join rates: 832/835 (Arm A) and 830/833 (Arm B). The shared set has 754 items.
- The **governing outcome is unchanged: LC_onecoin is the sole survivor and winner** (top-tercile AUROC 0.822 → 0.814; `changed = false`).
- Under audited labels, A3's screen AUROC rises from 0.713 to 0.772, and its top tercile from 0.50 to 0.72. It still fails G2 (copied iter-1 value).
- y_aud is still solver equivalence, so the re-rank cannot test circularity.

### 1.7 Transfer (EU-AI-Act pilot, 367 formulas; `results/transfer_A3.json`)

- A3 coverage is 71%. The uncovered formulas are ⊆ / ⇒ / quotes that do not parse (counted), plus low alignment coverage.
- Its predicted type is **"conflation" for 98%** of formulas. The type decoder is degenerate on definitional text; held-out panel-unfaithful items give 54% conflation, against a panel mix led by added (25%) and ∀/∃ (22%).
- LC is not applicable (a single system per definition).

### 1.8 Reproduction and integrity

- `results/preflight.json`:
  - LC_onecoin on the iter-1 screen is reproduced exactly (max |diff| 0, n = 833);
  - A3 is reproduced exactly on 50 of 50 screen items;
  - A0 matches on 76%, because the screen's A0 used the LLM text side (deviation D-A0-textside).
- The frozen sha1 manifest of 36 vendored files is re-verified unchanged at the end (`results/integrity.json`). The ledger sum ($2.7017) equals the reported spend.
- `results/audit_rederive.json` (independent numpy re-derivation) matches `analysis.json` to < 1e-6 for:
  - panel AUROC of LC_onecoin (0.7555), A3 (0.6418) and B1 (0.7621);
  - circularity-(b) AUROC of LC (0.7224), A3 (0.6094) and B1 (0.7088).
- Placebos:
  - permuted labels give mean AUROC 0.50 (p = 0.005 for every real value), and a shuffled-label bootstrap CI covers 0.5;
  - the RANDOM metric scores 0.512 [0.456, 0.566];
  - a random stacking feature gives Δ −0.003 [−0.008, 0.000].
- `results/unit_tests.json`: all T0 tests pass.

## 2. What was run

| Stage | What | Where |
|---|---|---|
| frame / adapter | 15,606 dataset rows. Every candidate string is normalised by the dataset parser (`to_str(parse(x))`) before the frozen iter-1 parsers see it. Arm B coverage: 5,902 with the adapter vs 5,702 raw, of 6,300 | `workers/adapter.py`, `results/coverage_adapter.json` |
| LC pairs | 23,164 unique candidate pairs through Arm B `find_bijections(wall_s=15)` (cap 5040, max_preds 8) plus `label_trigram`: 29% equiv, 0.2% unlabeled | `workers/armB.py pairs`, `work/pairs_cache.jsonl` |
| LC fit | `latent_class.run_latent_class` VERBATIM (LC_onecoin/_str/huiwalter/maj/ds_binary) + LC_within (6 rater slots × 2 systems) + B8 + LC_granular (post-hoc, 244 WordNet-granular merges) | `workers/armB.py lc`, `work/lc_scores.jsonl` |
| Signature | Arm A `method.signature_faithfulness` for A3/A0/Ccov on 7,603 rows; A1L from cached Qwen3 probe answers | `workers/armA.py score` |
| B7 | ported structural metric + components | `src/pipeline.py build_b7` |
| LLM (frozen) | B1 / B1plus / A1 / B3 / B3c / recall with the exact requests, $9.50 hard cap, pilot-then-sweep. **Blocked by HTTP 403 (daily key limit)** | `src/llm_stages.py`, `src/or_client.py` |
| LLM (local substitutes) | Qwen3-8B on the RTX 4090, same prompts | `src/local_llm.py`, `work/local_llm/` |
| B3 GPU | MiniLM cosine + DeBERTa-v3-large NLI (min of both directions) | `src/gpu_b3.py` |
| Analysis | C1–C3, stacking, circularity, system level, complexity, contamination, judge reliability | `src/analysis.py`, `src/stats.py` |
| Re-rank | iter-1 G1–G4 rule with each arm's own analysis code (importlib, unique names) | `workers/rerank_worker.py` |

## 3. Layout

- `method.py` is the single entry point:
  `uv run method.py --stage {frame,adapter,preflight,mini,zero_llm,llm,local,analysis,rerank,transfer,export,all} [--limit_sents N]`
- `src/`:
  - `common.py`: paths and dataset loader;
  - `pipeline.py`: stages S1–S4 and the local substitutes;
  - `llm_stages.py`, `or_client.py`: frozen OpenRouter metrics, capped;
  - `local_llm.py`: Qwen3 substitutes;
  - `gpu_b3.py`;
  - `scores.py`: long score table;
  - `analysis.py`, `stats.py`;
  - `transfer.py`, `export.py`, `preflight.py`;
  - `report_tables.py`: markdown tables used in this README.
- `workers/`: one interpreter per code base, to avoid the `llm` / `fol_parse` module-name collisions:
  - `adapter.py` (dataset parser);
  - `armA.py` (signature);
  - `armB.py` (pairs / LC / B7 joint SAT / LC pre-flight);
  - `granular.py` (dataset L2);
  - `rerank_worker.py`.
- `vendor/`: read-only copies of the iter-1 code (armA, armB, ds). The sha1s are in `results/frozen_manifest.json`, and all are identical to iter 1.
- `results/`:
  - `heldout_scores.jsonl`: one row per (item_id, metric), including contamination and transfer rows;
  - `analysis.json`;
  - `confirmation_table.json`;
  - `circularity.json`;
  - `system_level.json`;
  - `screen_rerank.json`;
  - `transfer_A3.json`;
  - `deviations.json`;
  - `frozen_manifest.json`;
  - `preflight.json`;
  - `unit_tests.json`;
  - `audit_rederive.json`;
  - `integrity.json`;
  - `coverage_adapter.json`;
  - `local_stage_info.json`;
  - `report_tables.md`;
  - `analysis_mini50.json`: the T2 mini run.
- `method_out.json`: the exp_gen_sol_out schema, with `predict_<metric>` per item for the 6,300 held-out, 936 contamination and 367 transfer rows. `full_`, `mini_` and `preview_` variants exist alongside it.
- `work/`: content-keyed caches plus `cost_ledger.jsonl` (the per-call OpenRouter ledger). The caches are:
  - `llm_cache/`: every gemini response;
  - `pairs_cache.jsonl`;
  - `granular_cache.jsonl`;
  - `lc_*`;
  - `armA_scores*.jsonl`;
  - `b1L_scores.jsonl`;
  - `b1plusL_scores.jsonl`;
  - `b3L_*`, `b3cL_scores.jsonl`;
  - `a1L_raw.jsonl`;
  - `recallL.jsonl`;
  - `local_llm/` (every Qwen3 generation);
  - `frame.jsonl`, `canon.jsonl`.
- `audit_rederive.py`: independent re-derivation plus the placebos. `tests/run_tests.py`: the T0 unit tests.

## 4. How to run

```bash
bash restore.sh                                  # .venv + WordNet
uv run method.py --stage frame && uv run method.py --stage adapter && uv run method.py --stage preflight
uv run method.py --stage zero_llm                # ~50 min CPU (pairs 1 min; signatures ~50 min on this network FS)
uv run method.py --stage local                   # ~1.5 h GPU (Qwen3-8B substitutes)
uv run method.py --stage llm --llm_parts b1,b3,b1plus,a1   # frozen gemini metrics (cached; $2.70 when run)
uv run method.py --stage analysis && uv run method.py --stage rerank && uv run method.py --stage transfer && uv run method.py --stage export
uv run audit_rederive.py && uv run tests/run_tests.py
```

`--stage rerank` runs `workers/rerank_worker.py` (already run; its output is `results/screen_rerank.json`).

## 5. Restoring removed files

| Removed path (`.aii/manifest.yaml`) | Restore with |
|---|---|
| `.venv/` | `uv venv .venv --python 3.12 && uv pip install --python .venv/bin/python -r pyproject.toml` (all versions pinned) |
| `.nltk_data/` | `bash restore.sh`, which curls `https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/packages/corpora/{wordnet,omw-1.4}.zip` into `.nltk_data/corpora` and unzips them |
| `**/__pycache__/` | Regenerated automatically by Python |
| HF model weights (outside the workspace, in `$HF_HOME`) | Downloaded on first use: `sentence-transformers/all-MiniLM-L6-v2`, `MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli`, `Qwen/Qwen3-8B` |

## 6. Deviations (full list in `results/deviations.json`)

| ID | Deviation |
|---|---|
| D-LLM | Key outage then budget: Qwen3-8B substitutes (L), then frozen gemini B1/B3/B1plus/A1 run ($2.70). B1plus and A1 are panel-restricted; B3c and recall are local only |
| D-B1plusL | Thinking judge on panel items only; 1024-token cap, then a 2048-token retry; coverage 0.749 |
| D-14B | Qwen3-14B could not be loaded |
| D-B1-maxtokens | B1 uses max_tokens 16 + a 48 retry (Arm A), where Arm B used 8 |
| D-LC-uncovered | Uncovered LC is scored 0.5, as the iter-1 `stages.row` did |
| D-A0-textside | Held-out A0 uses the zero-LLM text side |
| D-A1-rewire | Cached probe answers; memoised signature |
| D-adapter | Canonical-print input adapter |
| D-B7-port | Ported structural metric |
| D-B3c / D-B3c-parse | Re-implementation; tolerant JSON reader |
| D-strata | Bootstrap strata = sentence-level corpus × tercile |
| D-rerank-story | Story-id matching per arm |
| D-panel-slice | Local B3/B3c/recall on panel + 3-system contamination slice |

A further note on the stacking placebo: adding a random feature gives Δ −0.005 [−0.009, −0.002]. This is never a positive increment; the small negative value is the out-of-fold cost of a noise feature.

