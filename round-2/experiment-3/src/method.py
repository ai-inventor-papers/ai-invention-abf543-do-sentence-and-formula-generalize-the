#!/usr/bin/env python3
"""Frozen held-out confirmation of the iter-1 gold-free NL->FOL faithfulness metrics (run_qY2a2IS-WLIs, iter 2).

Single entry point:
    uv run method.py --stage {frame,adapter,preflight,mini,zero_llm,llm,analysis,rerank,transfer,export,all}
                     [--limit_sents N] [--llm_parts b1,a1,b3,b3c,b1plus,recall]

Metrics (all iter-1 code vendored read-only under vendor/, sha1-frozen in results/frozen_manifest.json):
  LC_onecoin / LC_onecoin_str / LC_huiwalter / LC_maj / LC_ds_binary  latent-class agreement over the 9 systems
      (Arm B latent_class.run_latent_class verbatim, candidate pairs via fol_core.find_bijections(wall_s=15))
  LC_within (6 rater slots of one system: greedy + 5 T=0.8 samples), LC_granular (POST-HOC; WordNet-granular merges)
  A3 zero-LLM monotonicity signature, A0 alignment-only control, Ccov coverage control, A1 gemini text probe (Arm A)
Baselines: B1 cheap judge (gemini-2.5-flash, frozen prompt), B1plus frontier judge (same prompt), B2 parse,
  B3cos / B3nli round trip, B3c Monty-style clause conformance (re-implementation), B7 structural (port; components),
  B8 sampling self-consistency.
LOCAL substitutes (stage 'local'; OpenRouter daily key limit hit during this run, see results/deviations.json):
  B1L / B1plusL / A1L / B3cosL / B3nliL / B3cL / RECALL_L answered by Qwen3-8B / Qwen3-14B-NF4 on the local GPU with
  the SAME frozen prompts.
Every stage is resumable: LLM calls, pair checks and signature scores are cached in work/ by content.
"""
from __future__ import annotations

import argparse
import os
import resource
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("NLTK_DATA", str(ROOT / ".nltk_data"))

from common import setup_logger  # noqa: E402

logger = setup_logger("method")


def _limits(stage: str):
    """Container: 56 GB RAM, 14 CPUs, RTX 4090. The orchestrator is light (workers are separate processes).
    RLIMIT_AS is not applied to stages that initialise CUDA (virtual reservations of the CUDA runtime exceed any
    sane address-space cap); those stages cap VRAM with torch.cuda.set_per_process_memory_fraction instead."""
    if stage not in ("llm", "local", "all", "mini"):
        resource.setrlimit(resource.RLIMIT_AS, (24 * 1024 ** 3, 24 * 1024 ** 3))


@logger.catch(reraise=True)
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", required=True,
                    choices=["frame", "adapter", "preflight", "mini", "zero_llm", "llm", "local", "analysis", "rerank",
                             "transfer", "export", "all"])
    ap.add_argument("--limit_sents", type=int, default=None)
    ap.add_argument("--llm_parts", default="b1,a1,b3,b3c,b1plus,recall")
    ap.add_argument("--local_parts", default="b1,a1,b3,b3c,recall,b1plus")
    ap.add_argument("--workers", type=int, default=12)
    a = ap.parse_args()
    import pipeline as P
    stages = [a.stage] if a.stage not in ("all", "mini") else \
        ["frame", "adapter", "preflight", "zero_llm", "llm", "local", "analysis", "rerank", "transfer", "export"]
    limit = a.limit_sents if a.stage != "mini" else (a.limit_sents or 50)
    for st in stages:
        logger.info(f"===== stage {st} (limit_sents={limit})")
        if st == "frame":
            P.stage_frame()
        elif st == "adapter":
            P.stage_adapter()
        elif st == "preflight":
            import preflight
            preflight.run()
        elif st == "zero_llm":
            P.stage_zero_llm(P.Frame(limit), workers=a.workers)
        elif st == "llm":
            P.stage_llm(P.Frame(limit), set(a.llm_parts.split(",")))
        elif st == "local":
            P.stage_local(P.Frame(limit), set(a.local_parts.split(",")))
        elif st == "analysis":
            import analysis
            analysis.run(limit)
        elif st == "rerank":
            import rerank
            rerank.run()
        elif st == "transfer":
            import transfer
            transfer.run()
        elif st == "export":
            import export
            export.run(limit)


if __name__ == "__main__":
    _st = sys.argv[sys.argv.index("--stage") + 1] if "--stage" in sys.argv else ""
    _limits(_st)
    main()
