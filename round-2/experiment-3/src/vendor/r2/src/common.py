"""Shared paths, logging, dataset loading and small helpers for the held-out confirmation run.

Every module of this workspace imports ONLY this file plus third-party libraries; the vendored iter-1 code
(vendor/armA, vendor/armB, vendor/ds) is imported exclusively inside the per-arm worker subprocesses
(workers/*.py) because Arm A and Arm B both ship a module called `llm`, and Arm A and the dataset both ship
`fol_parse` (module-name collisions -> never import two arms into one interpreter).
"""
from __future__ import annotations

import glob
import hashlib
import json
import math
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "work"
RES = ROOT / "results"
LOGS = ROOT / "logs"
VENDOR = ROOT / "vendor"
for _d in (WORK, RES, LOGS):
    _d.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("NLTK_DATA", str(ROOT / ".nltk_data"))
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
# torch 2.14 routes some eager ops (e.g. the rotary-embedding outer product) to Triton kernels that must be compiled
# with a host C compiler, which this container lacks -> keep the eager ATen kernels.
os.environ.setdefault("TORCH_DISABLE_NATIVE_JIT", "1")

I1 = Path("/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art")
DS_DIR = I1 / "gen_art_dataset_1"
ARMA_DIR = I1 / "gen_art_experiment_1"
ARMB_DIR = I1 / "gen_art_experiment_2"
SYSTEMS = ["deepseek-v3.1", "gemini-2.5-flash", "gemma-3-27b", "gpt-4.1-mini", "gpt-oss-120b", "llama-3.1-8b",
           "mistral-small-3.2-24b", "phi-4", "qwen-2.5-7b"]
SAMPLE_SYSTEMS = ["gpt-4.1-mini", "llama-3.1-8b"]


def setup_logger(name: str):
    from loguru import logger
    logger.remove()
    logger.add(sys.stdout, level="INFO", format="{time:HH:mm:ss}|{level:<7}|{message}")
    logger.add(LOGS / f"{name}.log", rotation="30 MB", level="DEBUG")
    return logger


def sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def read_jsonl(p: Path) -> list[dict]:
    if not Path(p).exists():
        return []
    out = []
    for line in Path(p).read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def write_jsonl(p: Path, rows: list[dict]) -> None:
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def append_jsonl(p: Path, rows: list[dict]) -> None:
    with open(p, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def jdump(obj, p: Path) -> None:
    Path(p).write_text(json.dumps(clean_nan(obj), ensure_ascii=False, indent=1), encoding="utf-8")


def clean_nan(o):
    """Recursively replace NaN/inf floats with None and numpy scalars with python scalars (strict JSON)."""
    try:
        import numpy as np
        if isinstance(o, np.generic):
            o = o.item()
        if isinstance(o, np.ndarray):
            o = o.tolist()
    except ImportError:
        pass
    if isinstance(o, float):
        return None if (math.isnan(o) or math.isinf(o)) else o
    if isinstance(o, dict):
        return {str(k): clean_nan(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean_nan(v) for v in o]
    return o


# ------------------------------------------------------------------------------------------ dataset
KEEP = ["metadata_fold", "metadata_item_id", "metadata_sentence_id", "metadata_system", "metadata_sample_idx",
        "metadata_corpus", "metadata_corpus_subset", "metadata_story_id", "metadata_source_id", "metadata_parse_ok",
        "metadata_complexity_tercile", "metadata_n_conditions", "metadata_n_tokens", "metadata_n_quantifiers",
        "metadata_nesting_depth", "metadata_complexity_composite", "metadata_L1_audited_status",
        "metadata_L1_orig_status", "metadata_L2_status", "metadata_label_source", "metadata_gold_source",
        "metadata_gold_fol_original", "metadata_gold_fol_audited", "metadata_L3_majority", "metadata_L3_primary_error",
        "metadata_L3_dissent", "metadata_L3_votes", "metadata_L3_sampling_weight", "metadata_L3_design_weight",
        "metadata_L3_design_stratum", "metadata_L3_poststratum", "metadata_L3_stratum_p_faithful", "metadata_L3_selected",
        "metadata_original_item_id", "metadata_original_sentence", "metadata_rename_map",
        "metadata_contamination_rename_incomplete", "metadata_candidate_fol_original", "metadata_gold_fol_renamed",
        "metadata_in_screen_first300", "metadata_screen_rank", "metadata_logiclm_id", "metadata_condition",
        "metadata_run", "metadata_definition_id", "metadata_term", "metadata_raw_output", "metadata_provider",
        "metadata_model", "metadata_verify_same_meaning", "metadata_label_orig", "metadata_paper_corrected_flag"]


def load_rows() -> list[dict]:
    """All 15,606 dataset rows (5 folds) with the fields this experiment needs, input JSON decoded."""
    parts = sorted(glob.glob(str(DS_DIR / "full_data_out" / "full_data_out_*.json")),
                   key=lambda p: int(p.rsplit("_", 1)[1][:-5]))
    rows = []
    for f in parts:
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        for g in d["datasets"]:
            for ex in g["examples"]:
                inp = json.loads(ex["input"])
                r = {k.replace("metadata_", ""): ex.get(k) for k in KEEP}
                r["sentence"] = inp.get("sentence")
                r["candidate_fol"] = inp.get("candidate_fol")
                r["output"] = ex["output"]
                rows.append(r)
        del d
    return rows


def frame_path() -> Path:
    return WORK / "frame.jsonl"


def load_frame() -> list[dict]:
    """Cached compact frame (built once by method.py stage 'frame')."""
    p = frame_path()
    if not p.exists():
        rows = load_rows()
        write_jsonl(p, rows)
        return rows
    return read_jsonl(p)


def cand_key(fold: str, item_id: str) -> str:
    return f"{fold}|{item_id}"
