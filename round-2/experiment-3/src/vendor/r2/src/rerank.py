"""S6 screen re-rank: runs workers/rerank_worker.py in its own interpreter (loads each arm's iter-1 analysis code under
a unique module name) -> results/screen_rerank.json."""
from __future__ import annotations


def run() -> None:
    from pipeline import run_worker
    run_worker(["workers/rerank_worker.py"], "rerank")
