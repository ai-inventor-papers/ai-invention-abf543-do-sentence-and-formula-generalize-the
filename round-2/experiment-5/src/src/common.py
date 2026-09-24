"""Shared paths, logging and small helpers for the long-legal-text DC transfer experiment."""
from __future__ import annotations

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
RAW = ROOT / "raw"
VENDOR = ROOT / "vendor"
for _d in (WORK, RES, LOGS):
    _d.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
# torch 2.14 routes some eager ops (rotary outer product) to Triton kernels that need a host C compiler (absent here)
os.environ.setdefault("TORCH_DISABLE_NATIVE_JIT", "1")

# vendored dataset code (fol_parse / fol_equiv) is importable as top-level modules
for _p in (VENDOR / "ds", ROOT / "src", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

DS_DIR = Path("../../../../round-1/dataset-1/src")
PILOT_ZIP = Path("/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/user_uploads/dpv_pilot_study.zip")
PIPE = RAW / "pilot" / "dpv_pilot_study" / "pipeline_Adapted_NL2FOL_prototype"
SEED = 20260924
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


def file_sha1(p: Path) -> str:
    return hashlib.sha1(Path(p).read_bytes()).hexdigest()


def read_jsonl(p: Path) -> list[dict]:
    p = Path(p)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
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
            f.write(json.dumps(clean_nan(r), ensure_ascii=False) + "\n")


def append_jsonl(p: Path, rows: list[dict]) -> None:
    with open(p, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(clean_nan(r), ensure_ascii=False) + "\n")


def clean_nan(o):
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


def jdump(obj, p: Path) -> None:
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(json.dumps(clean_nan(obj), ensure_ascii=False, indent=1), encoding="utf-8")


def jload(p: Path):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def cpu_count() -> int:
    try:
        q = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us").read_text())
        p = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us").read_text())
        if q > 0:
            return max(1, math.ceil(q / p))
    except (FileNotFoundError, ValueError):
        pass
    try:
        return len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        return os.cpu_count() or 1


def set_ram_limit(gb: float) -> None:
    import resource
    b = int(gb * 1024 ** 3)
    resource.setrlimit(resource.RLIMIT_AS, (b, b))
