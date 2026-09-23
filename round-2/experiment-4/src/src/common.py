"""Shared paths, environment and IO helpers (import first: sets NLTK_DATA and sys.path)."""
from __future__ import annotations

import glob
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("NLTK_DATA", str(ROOT / "nltk_data"))
for p in (ROOT / "src", ROOT / "third_party" / "armB" / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

I1 = Path("/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art")
DATASET_DIR = I1 / "gen_art_dataset_1"
ARMB = ROOT / "third_party" / "armB"
ARMA = ROOT / "third_party" / "armA"
RESULTS = ROOT / "results"
DATA = ROOT / "data"
CACHE = ROOT / "cache"
for d in (RESULTS, DATA, CACHE, ROOT / "logs"):
    d.mkdir(parents=True, exist_ok=True)

# fields the LABEL-BLIND scoring code may read from held-out rows (plan §4)
BLIND_FIELDS = ("input", "metadata_item_id", "metadata_sentence_id", "metadata_system", "metadata_corpus",
                "metadata_corpus_subset", "metadata_complexity_tercile", "metadata_complexity_composite",
                "metadata_n_conditions", "metadata_n_tokens", "metadata_n_quantifiers", "metadata_nesting_depth",
                "metadata_parse_ok", "metadata_fold", "metadata_original_item_id", "metadata_label_source",
                "metadata_sample_idx", "metadata_contamination_rename_incomplete", "metadata_original_sentence",
                "metadata_rename_map", "metadata_gold_fol_audited", "metadata_gold_fol_original")


def sha1(s: str) -> str:
    return hashlib.sha1(s.encode()).hexdigest()


def read_jsonl(p: Path) -> list[dict]:
    if not Path(p).exists():
        return []
    out = []
    with open(p) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


def append_jsonl(p: Path, rows: list[dict]) -> None:
    with open(p, "a") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def load_dataset_rows(blind: bool = True) -> list[dict]:
    """All rows of art_iyzYyaqlqpSX (parts sorted numerically). blind=True strips every label field
    (output, metadata_L3_*, L1/L2 labels, gold audit verdicts) so scoring code cannot see labels."""
    parts = sorted(glob.glob(str(DATASET_DIR / "full_data_out" / "full_data_out_*.json")),
                   key=lambda s: int(Path(s).stem.split("_")[-1]))
    rows = []
    for fp in parts:
        d = json.loads(Path(fp).read_text())
        for g in d["datasets"]:
            for e in g["examples"]:
                e = {k: e[k] for k in BLIND_FIELDS if k in e} if blind else dict(e)
                e["group"] = g["dataset"]
                rows.append(e)
    return rows
