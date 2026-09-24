#!/usr/bin/env python3
"""Directional Consensus (DC): freeze on dev, confirm on fresh NL->FOL data. Single entry point.

Stages (run in order; every API stage is cached per request, so a re-run costs $0):
  sample    src/s01_sample_fresh.py            fresh 450-sentence set, overlap-asserted            ($0)
  generate  src/s02_generate.py                9 systems greedy + 2 x 5 samples                    (~$0.45)
  devframe  src/s03_dev_frame.py               dev rows + round-2 frozen dev scores                ($0)
  devpairs  src/pairs.py (dev jobs)            DC relation cache on dev                            ($0, ~2 min)
  freeze    src/s04_freeze.py                  12-config grid on dev -> frozen_config.json + sha256 ($0)
  fresh     src/s05_fresh.py frame|dcpairs|lcpairs|lc|b7|vc   fresh frame, caches, frozen neighbours ($0)
  gate      src/s06_labels.py gate             calibration gate (40 items x 3 members)             (~$0.15)
  labels    src/s06_labels.py l0|l1|l3         gold audit, solver labels, panel adjudication      (~$1.7)
  llm       src/s09_llm_baselines.py b1        B1 on every fresh greedy row                         (~$0.10)
  local     src/s09b_local.py                  Qwen3-8B substitutes B3L / TJ_L (GPU)                ($0)
  scores    src/s10_scores.py                  results/scores.jsonl                                ($0)
  tests     src/s11_tests.py                   pre-registered T1-T4 -> results/tests.json          ($0)
  secondary src/s12_secondary.py, s12b_extra.py, s12c_perturb.py, report_tables.py
                                               results/analysis*.json, perturbation_sensitivity.json ($0)
  export    src/s13_export.py                  results/fresh_set.jsonl + method_out.json           ($0)
Usage: uv run method.py --stage STAGE   (or --stage all_offline: devframe..export without API stages)
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable
STAGES = {
    "sample": [["s01_sample_fresh.py"]],
    "generate": [["s02_generate.py", "--cap", "0.9"]],
    "devframe": [["s03_dev_frame.py"]],
    "devpairs": [["pairs.py", "../work/dev_pair_jobs.jsonl"], ["pairs.py", "../work/dev_within_jobs.jsonl"]],
    "freeze": [["s04_freeze.py"]],
    "fresh": [["s05_fresh.py", c] for c in ("frame", "dcpairs", "lcpairs", "lc", "b7", "vc")],
    "gate": [["s06_labels.py", "gate", "--cap", "0.35"]],
    "labels": [["s06_labels.py", "l0", "--cap", "0.9"], ["s06_labels.py", "l1"],
               ["s06_labels.py", "l3", "--n", "272", "--n_unparse", "12", "--cap", "1.05"]],
    "llm": [["s09_llm_baselines.py", "b1", "--cap", "0.25"]],
    "local": [["s09b_local.py"]],
    "scores": [["s10_scores.py"]],
    "tests": [["s11_tests.py"]],
    "secondary": [["s12_secondary.py"], ["s12b_extra.py"], ["s12c_perturb.py"], ["report_tables.py"]],
    "export": [["s13_export.py"]],
}
OFFLINE = ["devframe", "devpairs", "freeze", "fresh", "local", "scores", "tests", "secondary", "export"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True, choices=list(STAGES) + ["all_offline"])
    a = ap.parse_args()
    todo = OFFLINE if a.stage == "all_offline" else [a.stage]
    for st in todo:
        if st == "freeze" and (ROOT / "results" / "frozen_config.json").exists():
            print("== freeze: receipt exists (results/frozen_config.json) -> not re-frozen", flush=True)
            continue
        for cmd in STAGES[st]:
            print(f"== {st}: {' '.join(cmd)}", flush=True)
            r = subprocess.run([PY, *cmd], cwd=ROOT / "src")
            if r.returncode != 0:
                sys.exit(f"stage {st} failed ({' '.join(cmd)}), exit {r.returncode}")


if __name__ == "__main__":
    main()
