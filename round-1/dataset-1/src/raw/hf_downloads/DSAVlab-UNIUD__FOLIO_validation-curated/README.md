---
license: cc-by-4.0
arxiv: arxiv.org/abs/2606.02837
---

Data from the paper "Fixing FOLIO and MALLS: Verified Annotations and an LLM-assisted Framework to Focus Human Relabeling" (https://arxiv.org/pdf/2606.02837)


# FOLIO — Curated Pairs and Signatures

Curated FOLIO instances (validation split) for evaluating LLM-based first-order-logic (FOL) formula curation. 
Each instance pairs a natural-language sentence with the original FOL formalization (`FOL_sentence_old`) and a curated reference (`FOL_sentence`), grouped by story; 
NLI labels (True, False or Unknown) are corrected and provided in this curated version for each conclusion.
per-story ontologies (signatures) are provided separately.

## Configurations

### `FOLIO_instances` — `FOLIO_instances.jsonl`

275 instances used for held-out evaluation.


| Field | Type | Description |
|---|---|---|
| `id` | string | Instance id (e.g. `story_380`, `concl_380_1`) |
| `NL_sentence` | string | Natural-language sentence |
| `FOL_sentence` | string | Curated reference FOL formalization |
| `FOL_sentence_old` | string | Original (pre-curation) FOL formalization |
| `corrected` | bool | Whether the original was corrected |
| `ambiguity` | bool | Whether the sentence is ambiguous |
| `ambiguity_explanation` | string | Rationale for the ambiguity flag (when applicable) |
| `correction_explanation` | string | Rationale for the correction (selection only) |
| `label` | string | Gold NLI label for the *curated* formula (`FOL_sentence`). |
| `label_z3` | string | Z3-derived NLI label for the curated formula. |
| `label_old` | string | Original NLI label from the *original* formula (`FOL_sentence_old`). |
| `label_old_z3` | string | Z3-derived NLI label for the original formula. |

### `labelled signature` — `FOLIO_ontology.jsonl`

Per-story ontology used to render vocabulary blocks in prompts and to type-check formulas. One JSON object per line, 73 stories.

| Field | Type | Description |
|---|---|---|
| `story_id` | int | Story id (matches the `*_{story_id}` suffix in `rawpairs_*.id`) |
| `Rel` | object | `{predicate_name → {arity, pos_meaning, neg_meaning}}` |
| `Const` | object | `{constant_name → description}` |


## FOL syntax

Unicode operators:
- Quantifiers: `∀`, `∃`
- Boolean: `¬`, `∧`, `∨`, `→`, `↔`, `⊕`
- Predicates: capitalized (e.g. `Human(x)`)
- Variables: lowercase; constants: capitalized

## Citation
If you want to cite the full work or use the dataset, please refer to https://arxiv.org/pdf/2606.02837

```
@misc{brunello2026fixingfoliomallsverified,
      title={Fixing FOLIO and MALLS: Verified Annotations and an LLM-assisted Framework to Focus Human Relabeling}, 
      author={Andrea Brunello and Cristian Curaba and Luca Geatti and Michele Mignani and Angelo Montanari and Nicola Saccomanno},
      year={2026},
      eprint={2606.02837},
      archivePrefix={arXiv},
      primaryClass={cs.CL},
      url={https://arxiv.org/abs/2606.02837}, 
}
```

