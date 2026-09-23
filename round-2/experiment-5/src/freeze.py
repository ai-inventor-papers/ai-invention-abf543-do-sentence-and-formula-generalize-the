#!/usr/bin/env python3
"""STEP 5: FREEZE. Writes results/frozen_config.json with every tuned choice, the models/prompts, the sha256 of every
file in sigfaith/ and legacy_armA/src/, the timestamp and the R1/R2/R3 dev/test tables. Before writing it checks that
the label firewall is closed (load_labels() raises); after writing it checks that it opens.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "sigfaith"))
import heldout_io  # noqa: E402

RES = ROOT / "results"


def main():
    try:
        heldout_io.load_labels()
        raise SystemExit("FIREWALL BROKEN: labels readable before the freeze")
    except heldout_io.FirewallError as e:
        pre = f"closed ({e})"
    r1 = json.loads((RES / "r1_grid.json").read_text())
    r2 = json.loads((RES / "r2_select.json").read_text())
    r2t = json.loads((RES / "r2_test.json").read_text()) if (RES / "r2_test.json").exists() else None
    r3 = json.loads((RES / "r3_decoder.json").read_text())
    reg = json.loads((RES / "regression_test.json").read_text())
    side = r2["chosen"]
    fz = {
        "frozen_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "aligner": r1["chosen_cfg"], "aligner_name": r1["chosen"],
        "text_side": side, "t2_model": r2.get("t2_model"),
        "text_side_rule": "T0 rules marker (iter-1 A3); T1a/T1b/T1c/T2 as in sigfaith/core.choose_labels",
        "decoder": {"weights": r3["weights"], "blind_prior": r3["blind_prior"], "lr_model": r3["lr_model"],
                    "carry_D_lr": r3["carry_D_lr_to_heldout"], "primary": "D_rule"},
        "score_weights": "unchanged from iter-1 score.py: label 1/|aligned P|, dropped 1, added 1, swap 1, rel 0.5",
        "coverage_rule": "covered = parse_ok ∧ ≤20% '?' coords ∧ coverage ≥ 0.5 ∧ ≥1 labelled concept; else score 0.5",
        "solver": {"N": 3, "timeout_ms": 5000, "rel_max_unary": 8,
                   "heavy_fallback": "N=2 if >12 predicates or >6 quantifiers; 120 s wall -> timeout (uncovered)"},
        "front_end": "dataset src/fol_parse.py (VARLIKE + LaTeX) -> iter-1 AST",
        "models": {"probe": "google/gemini-2.5-flash thinking 1024 (only if text_side != T0)",
                   "B1": "google/gemini-2.5-flash thinking off, iter-1 B1_PROMPT", "TJ": "google/gemini-2.5-flash "
                   "thinking off, typed prompt (phase2_llm.TJ_PROMPT)", "embeddings": r1["chosen_cfg"]["emb"]},
        "hashes": heldout_io.hash_tree(),
        "tables": {"regression": reg,
                   "R1": {k: r1[k] for k in ("chosen", "chosen_cfg", "legacy_dev", "test_chosen", "test_legacy",
                                             "R1_TARGET_MISSED", "R1_TARGET_MISSED_DET", "fallback_used")},
                   "R1_grid_dev": {k: v["res"] for k, v in r1["grid_dev"].items()},
                   "R2": {"objectives": r2["objectives"], "chosen": side, "t0_down": r2["t0_down"],
                          "test": (r2t or {}).get("tables")},
                   "R3": {k: r3[k] for k in ("weights", "dev_macro_f1_calib", "blind_prior", "dev_eval", "test_eval",
                                             "scope_supplement", "carry_D_lr_to_heldout")}},
        "firewall_pre_freeze": pre,
    }
    (RES / "frozen_config.json").write_text(json.dumps(fz, indent=1, ensure_ascii=False))
    labs = heldout_io.load_labels()
    fz["firewall_post_freeze"] = f"open ({len(labs)} label rows readable)"
    (RES / "frozen_config.json").write_text(json.dumps(fz, indent=1, ensure_ascii=False))
    print(f"FROZEN: aligner={fz['aligner_name']} text_side={side} decoder weights={r3['weights']}; firewall {pre} -> "
          f"{fz['firewall_post_freeze']}")


if __name__ == "__main__":
    main()
