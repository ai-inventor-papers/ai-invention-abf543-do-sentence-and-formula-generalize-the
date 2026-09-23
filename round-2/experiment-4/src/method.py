#!/usr/bin/env python3
"""TVJT crossover deep test (iter 2) — orchestrator.

    python method.py --stage setup|canon_diag|targets|worlds|zero_llm|freeze|score_heldout|labels|analysis|export|all
                     [--backend gemini] [--sets P,Ccon,T] [--limit N]

Stages (all resumable; every paid LLM call is cached and ledgered, hard cap $9.50):
  canon_diag     R1 canonical worlds for the screen + zero-cost diagnostics (T1 world-set identity, iter-1 judge
                 inconsistency, iter-1 FA decomposition, replay of iter-1 verdicts on canonical worlds)
  targets        label-blind held-out target table + syntax bridge coverage
  worlds         canonical worlds for held-out P ∪ Ccon ∪ top-tercile T
  zero_llm       LC_onecoin (9-system one-coin latent class) + B3sc + LC on contamination + A3 signature
  freeze         frozen_config.json + prereg.json → freeze_receipt.json (before any held-out label is read)
  score_heldout  TVJT* / B1 / B1x3 with gemini-2.5-flash (needs the OpenRouter key budget)
  analysis       results/analysis.json + verdict.json (+ audit/rederive.py) — labels via the guarded loader
  export         method_out.json (exp_gen_sol_out) + full/mini/preview
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
PY = str(ROOT / ".venv" / "bin" / "python")


def run(args: list[str], cwd: Path = SRC) -> None:
    logger.info("$ " + " ".join(args))
    subprocess.run([PY] + args, cwd=cwd, check=True)


@logger.catch(reraise=True)
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True)
    ap.add_argument("--backend", default="gemini")
    ap.add_argument("--sets", default="P")
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    stages = (["canon_diag", "targets", "worlds", "zero_llm", "freeze", "analysis", "export"]
              if a.stage == "all" else [a.stage])
    for st in stages:
        if st == "setup":
            subprocess.run("uv venv .venv --python 3.12 && uv pip install --python .venv/bin/python -r pyproject.toml "
                           "&& uv pip install --python .venv/bin/python torch --index-url "
                           "https://download.pytorch.org/whl/cpu && uv pip install --python .venv/bin/python "
                           "sentence-transformers", shell=True, cwd=ROOT, check=True)
            run(["-c", "import nltk; [nltk.download(p, download_dir='../nltk_data') for p in ('wordnet','omw-1.4')]"])
        elif st == "canon_diag":
            run(["stage_worlds.py", "screen", "4"])
            run(["diagnostics.py"])
            run(["diagnostics.py", "replay"])
        elif st == "targets":
            run(["stage_targets.py"])
        elif st == "worlds":
            run(["stage_worlds.py", "heldout", "4"])
            run(["heldout_g2.py"])
        elif st == "zero_llm":
            run(["stage_lc.py", "2"])
            run(["stage_lc.py", "2", "contamination"])
            run([str(SRC / "run_a3.py")], cwd=ROOT)
        elif st == "freeze":
            run(["freeze.py"])
        elif st == "score_heldout":
            cmd = ["stage_judge.py", a.backend, "--sets", a.sets, "--votes", "3" if a.backend == "gemini" else "1"]
            if a.backend == "gemini":
                cmd.append("--b1x3")
            if a.limit:
                cmd += ["--limit", str(a.limit)]
            run(cmd)
        elif st == "analysis":
            run(["analysis2.py"])
            run([str(ROOT / "audit" / "rederive.py")], cwd=ROOT)
            run(["figures.py"])
        elif st == "export":
            run(["export.py"])
        else:
            raise ValueError(f"unknown stage {st}")


if __name__ == "__main__":
    logger.remove()
    logger.add(sys.stdout, level="INFO")
    logger.add(ROOT / "logs" / "method.log", rotation="20 MB", level="DEBUG")
    main()
