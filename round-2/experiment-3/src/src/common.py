"""Shared paths, loaders and helpers for the DC freeze-then-confirm pipeline."""
from __future__ import annotations

import builtins
import glob
import hashlib
import json
import re
import sys
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "work"
RES = ROOT / "results"
LOGS = ROOT / "logs"
for _d in (WORK, RES, LOGS):
    _d.mkdir(exist_ok=True)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor" / "ds" / "src"))

DEP = Path("/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_dataset_1")
R2 = Path("/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_2/gen_art/gen_art_experiment_3")
SYSTEMS = ["deepseek-v3.1", "gemini-2.5-flash", "gemma-3-27b", "gpt-4.1-mini", "gpt-oss-120b", "llama-3.1-8b",
           "mistral-small-3.2-24b", "phi-4", "qwen-2.5-7b"]
SAMPLE_SYSTEMS = ["gpt-4.1-mini", "llama-3.1-8b"]
TERC = {"bottom": 0, "middle": 1, "top": 2}
FROZEN = RES / "frozen_config.json"


def setup_logging(name: str) -> None:
    logger.remove()
    logger.add(sys.stdout, level="INFO", format="{time:HH:mm:ss}|{level:<7}|{message}")
    logger.add(LOGS / f"{name}.log", rotation="30 MB", level="DEBUG")


def norm(s: str) -> str:
    """lowercase, strip punctuation and whitespace (the exclusion key)."""
    return re.sub(r"[\W_]+", "", (s or "").lower())


def sha1(s: str) -> str:
    return hashlib.sha1((s or "").encode("utf-8")).hexdigest()


def read_jsonl(p) -> list[dict]:
    p = Path(p)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                logger.warning(f"bad jsonl line in {p.name}")
    return out


def write_jsonl(p, rows) -> None:
    with open(p, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")


def load_dev_rows(folds: tuple = ("heldout_confirm", "heldout_samples", "contamination", "transfer_unlabeled")):
    """Dataset rows (art_iyzYyaqlqpSX) of the requested folds, loaded one part at a time."""
    parts = sorted(glob.glob(str(DEP / "full_data_out" / "full_data_out_*.json")),
                   key=lambda p: int(p.rsplit("_", 1)[1][:-5]))
    rows = []
    for f in parts:
        d = json.loads(Path(f).read_text())
        for g in d["datasets"]:
            for ex in g["examples"]:
                if ex["metadata_fold"] in folds:
                    rows.append(ex)
        del d
    return rows


def assert_frozen() -> dict:
    """Refuse to run a label stage before the freeze receipt exists and verifies."""
    if not FROZEN.exists() or not (RES / "frozen_config.sha256").exists():
        raise RuntimeError("frozen_config.json receipt missing: labels may not be created before the freeze")
    txt = FROZEN.read_bytes()
    h = hashlib.sha256(txt).hexdigest()
    rec = (RES / "frozen_config.sha256").read_text().split()[0]
    if h != rec:
        raise RuntimeError(f"frozen_config.json hash mismatch {h} != {rec}")
    return json.loads(txt)


_READ_LOG = RES / "post_freeze_reads.log"


def log_reads(stage: str) -> None:
    """After the freeze: log every file opened for reading by this process (wrapper around open)."""
    orig = builtins.open

    def wrapped(file, mode="r", *a, **k):
        try:
            if "r" in mode and "+" not in mode:
                with orig(_READ_LOG, "a", encoding="utf-8") as f:
                    f.write(f"{stage}\t{file}\n")
        except OSError:
            pass
        return orig(file, mode, *a, **k)
    builtins.open = wrapped
    import io
    io.open = wrapped  # pathlib reads go through io.open
