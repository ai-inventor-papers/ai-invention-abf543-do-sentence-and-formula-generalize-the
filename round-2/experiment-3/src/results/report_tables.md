## Dev grid (freeze; 609 dev panel items + 5,846 dev solver rows)

| config | AUROC_P | AUROC_S | mean | coverage | EQUIV-only-by-L2/L3 share of pairs | non-transitivity |
|---|---|---|---|---|---|---|
| L3on_UAin_DS_caps1 | 0.768 | 0.826 | 0.797 | 0.952 | 0.058 | 0.0036 |
| L3on_UAin_uniform_caps1 | 0.760 | 0.813 | 0.786 | 0.952 | 0.058 | 0.0036 |
| L3on_UAout_DS_caps1 | 0.782 | 0.814 | 0.798 | 0.930 | 0.058 | 0.0036 |
| L3on_UAout_uniform_caps1 | 0.774 | 0.797 | 0.785 | 0.930 | 0.058 | 0.0036 |
| L3off_UAin_DS_caps1 **(frozen)** | 0.777 | 0.855 | 0.816 | 0.952 | 0.001 | 0.0000 |
| L3off_UAin_uniform_caps1 | 0.771 | 0.841 | 0.806 | 0.952 | 0.001 | 0.0000 |
| L3off_UAout_DS_caps1 | 0.791 | 0.843 | 0.817 | 0.930 | 0.001 | 0.0000 |
| L3off_UAout_uniform_caps1 | 0.784 | 0.826 | 0.805 | 0.930 | 0.001 | 0.0000 |
| L3on_UAin_DS_caps0.5 | 0.768 | 0.826 | 0.797 | 0.952 | 0.058 | 0.0036 |
| L3on_UAin_uniform_caps0.5 | 0.760 | 0.813 | 0.786 | 0.952 | 0.058 | 0.0036 |
| L3on_UAout_DS_caps0.5 | 0.782 | 0.814 | 0.798 | 0.930 | 0.058 | 0.0036 |
| L3on_UAout_uniform_caps0.5 | 0.774 | 0.797 | 0.785 | 0.930 | 0.058 | 0.0036 |

## Fresh AUROC (panel: 256 adjudicated items, raked weights; solver: 3,720 audited-solver rows)

| metric | AUROC_P [95% CI] | n_P | AUROC_S [95% CI] | n_S | coverage |
|---|---|---|---|---|---|
| DC0 | 0.853 [0.798, 0.898] | 256 | 0.874 [0.849, 0.897] | 3720 | 1.000 |
| B8 | 0.843 [0.777, 0.904] | 143 | 0.784 [0.753, 0.813] | 823 | 0.993 |
| DC_self | 0.842 [0.775, 0.903] | 143 | 0.784 [0.754, 0.814] | 823 | 0.993 |
| LC_huiwalter | 0.836 [0.778, 0.887] | 256 | 0.852 [0.824, 0.877] | 3720 | 0.984 |
| LC_onecoin | 0.834 [0.776, 0.885] | 256 | 0.850 [0.823, 0.876] | 3720 | 0.984 |
| LC_ds_binary | 0.830 [0.773, 0.878] | 256 | 0.865 [0.840, 0.889] | 3720 | 0.984 |
| DC | 0.827 [0.770, 0.877] | 256 | 0.874 [0.849, 0.897] | 3720 | 1.000 |
| LC_maj | 0.797 [0.737, 0.850] | 256 | 0.859 [0.833, 0.883] | 3720 | 0.984 |
| B1 | 0.791 [0.726, 0.843] | 256 | 0.727 [0.698, 0.755] | 3720 | 1.000 |
| B3nliL | 0.784 [0.724, 0.835] | 256 | 0.619 [0.546, 0.687] | 260 | 1.000 |
| B3cosL | 0.752 [0.686, 0.817] | 256 | 0.657 [0.587, 0.730] | 260 | 1.000 |
| VC | 0.674 [0.598, 0.746] | 256 | 0.791 [0.764, 0.815] | 3720 | 1.000 |
| TJ_L | 0.659 [0.611, 0.710] | 256 | 0.593 [0.557, 0.631] | 260 | 1.000 |
| B7 | 0.554 [0.522, 0.590] | 256 | 0.503 [0.500, 0.505] | 3720 | 1.000 |
| B2 | 0.549 [0.518, 0.584] | 256 | 0.500 [0.500, 0.500] | 3720 | 1.000 |
| sp_net | 0.415 [0.358, 0.467] | 245 | 0.464 [0.449, 0.480] | 3720 | 1.000 |

## Pre-registered tests (fresh only; PASS requires both labels; T3 panel-only)

| test | panel | solver | verdict |
|---|---|---|---|
| T1 Δ AUROC(base+DC − base), base=[B1,B2,B3nliL,B3cosL,B7] | 0.033 [-0.001, 0.066] LB5 0.005 | 0.118 [0.051, 0.192] LB5 0.060 | **PASS** |
| T1 placebo (DC shuffled in strata) | -0.003 [-0.016, 0.008] | -0.001 [-0.010, 0.007] | – |
| T1 sensitivity base=[B1,B2,B7] | 0.126 [0.066, 0.189] | 0.159 [0.129, 0.190] (all 3,720 rows) | – |
| T2 DC − LC_maj (LB>0) | 0.030 [0.012, 0.049] LB5 0.014 | 0.015 [0.005, 0.026] LB5 0.007 | |
| T2 DC − LC_ds_binary (point>0) | -0.003 [-0.024, 0.017] LB5 -0.021 | 0.009 [-0.000, 0.019] LB5 0.001 | |
| T2 DC − VC (LB>0) | 0.152 [0.096, 0.209] LB5 0.104 | 0.083 [0.066, 0.102] LB5 0.069 | |
| T2 overall | False | True | **label-dependent** |
| T3a top-1 type (DC 0.122 vs majority added_condition 0.255 + 0.10; TJ_L 0.017) | False | panel-only | |
| T3b recall ≥ 0.5 (added / dropped / ∀∃) | added 0.039 (n=27), dropped 0.410 (n=14), quantifier 0.252 (n=21) | – | |
| T3c within-sentence DC vs B1 | dropped_condition: DC 1.000 B1 0.643 (pairs 7, underpowered), implication_direction_or_only: DC 1.000 B1 0.786 (pairs 7, underpowered) | – | **fail** |
| T4 gpt-4.1-mini | DC_self−B8 0.000 (LB5 0.000); stack Δ 0.015 (LB5 -0.062); n=76 | DC_self−B8 -0.002 (LB5 -0.007); stack Δ 0.089 (LB5 0.054); n=431 | **fail** |
| T4 llama-3.1-8b | DC_self−B8 -0.016 (LB5 -0.041); stack Δ -0.042 (LB5 -0.103); n=67 | DC_self−B8 0.005 (LB5 -0.002); stack Δ 0.125 (LB5 0.081); n=392 | **fail** |

## Circularity (panel items whose candidate is solver-NON-equivalent to the audited gold)

| metric | AUROC_P non-equiv (n=168) | AUROC_P no-bijection (n=143) |
|---|---|---|
| DC | 0.776 [0.679, 0.858] | 0.771 [0.678, 0.855] |
| LC_ds_binary | 0.805 [0.718, 0.878] | 0.796 [0.702, 0.871] |
| LC_maj | 0.752 [0.654, 0.836] | 0.744 [0.644, 0.829] |
| B1 | 0.738 [0.659, 0.816] | 0.744 [0.652, 0.822] |
| B3nliL | 0.799 [0.738, 0.862] | 0.809 [0.733, 0.876] |
| VC | 0.554 [0.437, 0.671] | 0.585 [0.462, 0.714] |
| TJ_L | 0.647 [0.575, 0.713] | 0.633 [0.563, 0.706] |

## Component ladder (fresh; derived from one relation cache)

| step | AUROC_P | AUROC_S |
|---|---|---|
| L1_uniform | 0.801 | 0.864 |
| L12_uniform | 0.801 | 0.863 |
| L123_uniform | 0.791 | 0.839 |
| LC_maj | 0.797 | 0.859 |
| LC_ds_binary | 0.830 | 0.865 |
| LC_onecoin | 0.834 | 0.850 |
| DC | 0.827 | 0.874 |
| DC:L3off_UAin_uniform_caps1 | 0.801 | 0.863 |
| DC:L3on_UAin_DS_caps1 | 0.820 | 0.859 |
| DC+SP(oof) | 0.791 | 0.867 |

## Complexity (fresh, AUROC)

| stratum | DC P | B1 P | DC S | B1 S | LC_ds_binary S |
|---|---|---|---|---|---|
| n_tokens=<=12 | 0.856 (n=80) | 0.764 (n=80) | 0.885 (n=1403) | 0.699 (n=1403) | 0.898 (n=1403) |
| n_tokens=13-20 | 0.824 (n=136) | 0.797 (n=136) | 0.849 (n=1808) | 0.746 (n=1808) | 0.824 (n=1808) |
| n_tokens=>20 | 0.727 (n=40) | 0.810 (n=40) | 0.881 (n=509) | 0.750 (n=509) | 0.868 (n=509) |
| n_quantifiers=0 | 0.923 (n=62) | 0.743 (n=62) | 0.958 (n=932) | 0.814 (n=932) | 0.943 (n=932) |
| n_quantifiers=1 | 0.829 (n=149) | 0.820 (n=149) | 0.841 (n=2104) | 0.662 (n=2104) | 0.849 (n=2104) |
| n_quantifiers=2+ | 0.659 (n=45) | 0.778 (n=45) | 0.847 (n=684) | 0.721 (n=684) | 0.847 (n=684) |
| nesting_depth=<=3 | 0.875 (n=164) | 0.796 (n=164) | 0.872 (n=2364) | 0.737 (n=2364) | 0.861 (n=2364) |
| nesting_depth=4-5 | 0.661 (n=68) | 0.732 (n=68) | 0.849 (n=924) | 0.600 (n=924) | 0.848 (n=924) |
| nesting_depth=6+ | 0.736 (n=24) | 0.780 (n=24) | 0.817 (n=432) | 0.734 (n=432) | 0.826 (n=432) |
| n_conditions=0-1 | 0.768 (n=74) | 0.793 (n=74) | 0.885 (n=1142) | 0.718 (n=1142) | 0.897 (n=1142) |
| n_conditions=2 | 0.795 (n=58) | 0.806 (n=58) | 0.884 (n=914) | 0.684 (n=914) | 0.873 (n=914) |
| n_conditions=3+ | 0.871 (n=124) | 0.787 (n=124) | 0.860 (n=1664) | 0.754 (n=1664) | 0.837 (n=1664) |

panel: tercile gap DC−B1 (bottom/middle/top) = 0.088, 0.107, -0.028; slope -0.058 [-0.135, 0.022]

solver: tercile gap DC−B1 (bottom/middle/top) = 0.167, 0.166, 0.118; slope -0.024 [-0.059, 0.009]

## Per panel error type (faithful vs unfaithful-of-type-X; all classes n<30 → descriptive)

| type | n | DC | DC0 | LC_ds_binary | B1 | B3nliL | VC | TJ_L |
|---|---|---|---|---|---|---|---|---|
| added_condition | 27 | 0.799 | 0.825 | 0.796 | 0.704 | 0.827 | 0.570 | 0.615 |
| quantifier_forall_exists | 21 | 0.896 | 0.914 | 0.914 | 0.857 | 0.809 | 0.763 | 0.781 |
| dropped_condition | 14 | 0.785 | 0.800 | 0.817 | 0.747 | 0.860 | 0.788 | 0.503 |
| implication_direction_or_only | 12 | 0.881 | 0.923 | 0.921 | 0.860 | 0.829 | 0.664 | 0.723 |
| quantifier_scope | 10 | 0.822 | 0.838 | 0.792 | 0.875 | 0.639 | 0.723 | 0.785 |
| syntax_unparseable | 7 | 0.732 | 0.770 | 0.736 | 0.963 | 0.731 | 0.521 | 0.890 |
| connective_and_or | 6 | 0.810 | 0.863 | 0.751 | 0.704 | 0.809 | 0.545 | 0.567 |
| conflation | 6 | 0.843 | 0.840 | 0.812 | 0.714 | 0.716 | 0.883 | 0.550 |
| wrong_constant | 3 | 0.868 | 0.865 | 0.872 | 0.770 | 0.599 | 0.805 | 0.471 |
| negation_polarity | 3 | 0.754 | 0.883 | 0.758 | 0.996 | 0.785 | 0.612 | 0.846 |
| other | 3 | 0.763 | 0.760 | 0.753 | 0.654 | 0.603 | 0.485 | 0.471 |
| argument_swap | 2 | 0.930 | 0.928 | 0.976 | 0.871 | 0.789 | 0.890 | 0.700 |
| wrong_split | 2 | 0.839 | 0.928 | 0.822 | 0.770 | 0.889 | 0.799 | 0.471 |

Within-sentence paired AUROC (panel, 70 faithful×unfaithful pairs in 70 sentences): DC 0.929 [0.864, 0.979]; DC0 0.929 [0.864, 0.979]; LC_ds_binary 0.914 [0.857, 0.971]; B1 0.786 [0.714, 0.850]; B3nliL 0.721 [0.614, 0.821]; VC 0.736 [0.643, 0.829]; TJ_L 0.693 [0.636, 0.750]

## Shared bias (mode-right vs mode-wrong sentences)

| stratum | DC | B1 | LC_maj |
|---|---|---|---|
| panel mode_right (n=195) | 0.883 [0.822, 0.934] | 0.782 | 0.867 |
| panel mode_wrong (n=61) | 0.419 [0.292, 0.557] | 0.786 | 0.433 |
| solver mode_right (n=2167) | 0.912 [0.876, 0.946] | 0.752 | 0.899 |
| solver mode_wrong (n=1553) | 0.517 [0.458, 0.566] | 0.554 | 0.576 |

## System level (9 systems; Kendall τ_b [sentence-bootstrap CI], pairwise accuracy)

| metric | τ_b panel | pairwise panel | τ_b solver | pairwise solver |
|---|---|---|---|---|
| DC | 0.556 [0.222, 0.722] | 0.778 | 0.889 [0.667, 0.944] | 0.944 |
| LC_ds_binary | 0.611 [0.222, 0.722] | 0.806 | 0.722 [0.556, 0.889] | 0.861 |
| LC_maj | 0.500 [0.111, 0.667] | 0.750 | 0.611 [0.389, 0.778] | 0.806 |
| B1 | 0.833 [0.389, 0.889] | 0.917 | 0.722 [0.611, 0.889] | 0.861 |
| VC | 0.500 [0.167, 0.722] | 0.750 | 0.611 [0.444, 0.778] | 0.806 |
| B2 | 0.479 [0.181, 0.761] | 0.722 | 0.704 [0.479, 0.761] | 0.833 |
| B7 | 0.500 [0.222, 0.770] | 0.750 | 0.611 [0.457, 0.761] | 0.806 |

## Invariance under solver-verified meaning-preserving rewrites (400 fresh candidates)

| rewrite | n verified | DC false-alarm rate (|ΔDC|>0.05 or mode flip or type change) |
|---|---|---|
| SYN_RENAME | 396 | 0.0025 |
| RAND_RENAME | 399 | 0.0050 |
| CONTRAPOS | 311 | 0.0000 |
| DEMORGAN | 276 | 0.0000 |
| REORDER | 313 | 0.0000 |

VC on the synonym-renamed subset: false-alarm rate 0.864 (mean |ΔVC| 0.199).

## Wrong-gold flag (gold as a 10th peer)

AUROC of 1 − DC_gold vs the L0 verdict = 0.859 (n=450, base rate 0.458); precision@50 = 0.800.

## Label quality

- Wrong shipped gold (L0): malls 0.553 [0.482, 0.629] (n=170); folio 0.620 [0.540, 0.700] (n=150); proverqa 0.146 [0.092, 0.208] (n=130)
- Correct-but-inequivalent (panel-faithful share among solver-non-equivalent panel items, weighted): 0.438 (n=168)
- Panel-unfaithful among solver-equivalent panel items: 0.081 (n=77)
- Solver–panel agreement (weighted): 0.689
- Fleiss κ: L3 full-panel subset 0.538 (n=24); L0 subset 0.466 (n=45)
- Panel weights: {"frame_n": 3933, "n_items": 256, "n_floor_capped": 148, "kish_n_eff": 201.69710288802236, "max_min_ratio": 6.0}

## Coverage and cost

- Relation shares over 14520 fresh greedy pairs: INCOMPARABLE 0.315, WEAKER 0.113, EQUIV 0.385, STRONGER 0.096, UNALIGNABLE 0.090, CONTRADICTORY 0.001; EQUIV non-transitivity 0.0000.
- Coverage: DC 0.945, LC_maj 0.930, LC_ds_binary 0.930, VC 0.945, B1 1.000, B7 1.000; unparseable greedy outputs 222 (kept, scored 0.5 by DC / 0 by DC0).
- DC: $0 when peers exist; 0.158 s solver time per item (p95 0.528 s); $0.00039 per item if the 8 peers must be generated. B1: $0.000030 per item.

## Contamination (dev, entity-renamed candidates)

mean DC(original) − DC(renamed) = 0.000 [0.000, 0.000] over 936 pairs (B1 in round 2: +0.096): DC is exactly name-blind.

## Frontier gap (dev anchor only)

stack [B1, B2, DC] OOF AUROC_P 0.796 vs gemini-2.5-pro B1plus 0.825 (B1 0.762), n=609.

## Controlled perturbations of 298 solver-verified faithful anchors (mechanism evidence only)

| operator | n | P(DC(anchor) > DC(mutant)) [95% CI] | DC typing accuracy | mutant still in mode | VC detection |
|---|---|---|---|---|---|
| NEG (negation_polarity) | 296 | 0.929 [0.909, 0.949] | 0.020 | 0.051 | 0.500 |
| IMPL_REV (implication_direction_or_only) | 254 | 0.888 [0.860, 0.915] | 0.228 | 0.130 | 0.500 |
| ADD (added_condition) | 254 | 0.913 [0.886, 0.939] | 0.720 | 0.079 | 0.960 |
| ANDOR (connective_and_or) | 204 | 0.919 [0.895, 0.944] | 0.000 | 0.064 | 0.500 |
| QUANT (quantifier_forall_exists) | 207 | 0.872 [0.838, 0.908] | 0.599 | 0.082 | 0.500 |
| DROP (dropped_condition) | 163 | 0.887 [0.850, 0.920] | 0.497 | 0.086 | 0.923 |
| ARG_SWAP (argument_swap) | 51 | 0.647 [0.559, 0.735] | 0.196 | 0.157 | 0.500 |
