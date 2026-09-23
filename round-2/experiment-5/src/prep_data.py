#!/usr/bin/env python3
"""Step 0b: split the dependency dataset (art_iyzYyaqlqpSX) into LABEL-FREE inputs and a firewalled label file.

Reads DS/full_data_out/full_data_out_{1,2,3}.json (all 5 groups) and writes
  data/heldout_inputs.jsonl    heldout_confirm rows: ids, sentence, candidate FOL, system, corpus, story, complexity,
                               the ORIGINAL shipped gold formula (an input for the gold flagger) — no label fields
  data/heldout_labels.jsonl    every label / audit / adjudication field of the same rows (read ONLY via
                               sigfaith.heldout_io.load_labels(), which checks the frozen hashes)
  data/samples_inputs.jsonl    heldout_samples rows (inputs only; unused by the primary analyses, counted)
  data/screen_l4.jsonl         screen_gold_audit rows (the SCREEN, not held-out: L4 gold audit used as dev)
  data/transfer_inputs.jsonl   transfer_unlabeled rows (EU-AI-Act pilot)
  data/contamination_count.json  (contamination group is not used by this experiment; counted only)
This script copies fields; it computes nothing from labels.
"""
from __future__ import annotations

import glob
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DS = Path("/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_dataset_1")
LABEL_PREFIX = ("metadata_L0", "metadata_L1", "metadata_L2", "metadata_L3", "metadata_gold_audit",
                "metadata_gold_faithful_final", "metadata_paper_corrected_flag", "metadata_gold_fol_paper",
                "metadata_gold_fol_audited", "metadata_gold_source", "metadata_sentence_ambiguous",
                "metadata_label_source", "metadata_gold_correction_status", "metadata_gold_fol_refined",
                "metadata_label_orig", "metadata_gold_fol_v2")
INPUT_KEEP = ["metadata_item_id", "metadata_sentence_id", "metadata_corpus", "metadata_corpus_subset",
              "metadata_source_id", "metadata_story_id", "metadata_system", "metadata_model", "metadata_parse_ok",
              "metadata_parse_error", "metadata_gold_fol_original", "metadata_gold_parse_ok", "metadata_n_tokens",
              "metadata_n_quantifiers", "metadata_nesting_depth", "metadata_n_conditions",
              "metadata_complexity_composite", "metadata_complexity_tercile", "metadata_sample_idx"]


def main():
    parts = sorted(glob.glob(str(DS / "full_data_out" / "full_data_out_*.json")),
                   key=lambda p: int(p.rsplit("_", 1)[1][:-5]))
    rows = []
    for f in parts:
        for d in json.load(open(f))["datasets"]:
            for ex in d["examples"]:
                ex["_group"] = d["dataset"]
                rows.append(ex)
    print("rows", len(rows), Counter(r["_group"] for r in rows))
    out = {k: [] for k in ("heldout_inputs", "heldout_labels", "samples_inputs", "screen_l4", "transfer_inputs")}
    for r in rows:
        g = r["_group"]
        inp = json.loads(r["input"])
        if g in ("heldout_confirm", "heldout_samples"):
            x = {"item_id": r["metadata_item_id"], "sentence": inp["sentence"], "candidate_fol": inp["candidate_fol"]}
            for k in INPUT_KEEP:
                if k in r:
                    x[k.replace("metadata_", "")] = r[k]
            assert not any(k.startswith(LABEL_PREFIX) for k in x)
            if g == "heldout_confirm":
                out["heldout_inputs"].append(x)
                lab = {"item_id": r["metadata_item_id"], "output": r["output"],
                       "sentence_id": r["metadata_sentence_id"]}
                for k, v in r.items():
                    if k.startswith(LABEL_PREFIX):
                        lab[k.replace("metadata_", "")] = v
                out["heldout_labels"].append(lab)
            else:
                out["samples_inputs"].append(x)
        elif g == "screen_gold_audit":
            x = {"item_id": r["metadata_item_id"], "sentence": inp["sentence"], "candidate_fol": inp["candidate_fol"],
                 "output": r["output"]}
            for k, v in r.items():
                if k.startswith("metadata_"):
                    x[k.replace("metadata_", "")] = v
            out["screen_l4"].append(x)
        elif g == "transfer_unlabeled":
            x = {"item_id": r["metadata_item_id"], "sentence": inp["sentence"], "candidate_fol": inp["candidate_fol"]}
            for k, v in r.items():
                if k.startswith("metadata_") and k != "metadata_source_path":
                    x[k.replace("metadata_", "")] = v
            out["transfer_inputs"].append(x)
    (ROOT / "data").mkdir(exist_ok=True)
    for k, v in out.items():
        with (ROOT / "data" / f"{k}.jsonl").open("w") as f:
            for x in v:
                f.write(json.dumps(x, ensure_ascii=False) + "\n")
        print(k, len(v))
    (ROOT / "data" / "contamination_count.json").write_text(json.dumps(
        {"contamination_rows": sum(r["_group"] == "contamination" for r in rows),
         "note": "not used by this experiment (sibling experiment 1 owns the contamination check)"}))


if __name__ == "__main__":
    sys.exit(main())
