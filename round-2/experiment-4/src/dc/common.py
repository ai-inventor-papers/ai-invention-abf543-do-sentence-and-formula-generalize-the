"""Paths, dataset frame, jsonl helpers, hardware detection and the parallel pair runner (spawn pool, RLIMIT_AS)."""
from __future__ import annotations

import glob
import hashlib
import json
import math
import multiprocessing as mp
import os
import resource
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK, RES, LOGS = ROOT / "work", ROOT / "results", ROOT / "logs"
for _d in (WORK, RES, LOGS):
    _d.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("NLTK_DATA", str(ROOT / "nltk_data"))
for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

R1 = Path("/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art")
DS_DIR = R1 / "gen_art_dataset_1"
R2 = Path("/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_2/gen_art")
EXP3, EXP4, EXP5 = R2 / "gen_art_experiment_3", R2 / "gen_art_experiment_4", R2 / "gen_art_experiment_5"
SYSTEMS = ["deepseek-v3.1", "gemini-2.5-flash", "gemma-3-27b", "gpt-4.1-mini", "gpt-oss-120b", "llama-3.1-8b",
           "mistral-small-3.2-24b", "phi-4", "qwen-2.5-7b"]
PAIRS_CACHE = WORK / "pairs_dc.jsonl"


def detect_cpus() -> int:
    try:
        parts = Path("/sys/fs/cgroup/cpu.max").read_text().split()
        if parts[0] != "max":
            return math.ceil(int(parts[0]) / int(parts[1]))
    except (FileNotFoundError, ValueError):
        pass
    try:
        return len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        return os.cpu_count() or 1


def sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def rj(p) -> list[dict]:
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


def wj(p, rows) -> None:
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(clean(r), ensure_ascii=False) + "\n")


def clean(o):
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
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)):
        return [clean(v) for v in o]
    return o


def jdump(obj, p) -> None:
    Path(p).write_text(json.dumps(clean(obj), ensure_ascii=False, indent=1), encoding="utf-8")


# ------------------------------------------------------------------------------------------ dataset frame
KEEP = ["fold", "item_id", "sentence_id", "system", "sample_idx", "corpus", "corpus_subset", "story_id", "parse_ok",
        "complexity_tercile", "n_conditions", "n_tokens", "n_quantifiers", "nesting_depth", "complexity_composite",
        "L1_audited_status", "L1_orig_status", "L2_status", "label_source", "gold_source", "gold_fol_original",
        "gold_fol_audited", "gold_faithful_final", "gold_audit_primary_error", "sentence_ambiguous", "gold_parse_ok",
        "L3_majority", "L3_primary_error", "L3_votes", "L3_sampling_weight", "L3_stratum_p_faithful", "L3_selected",
        "original_item_id", "original_sentence", "rename_map", "contamination_rename_incomplete",
        "candidate_fol_original", "gold_fol_renamed", "paper_corrected_flag"]


def build_frame() -> list[dict]:
    parts = sorted(glob.glob(str(DS_DIR / "full_data_out" / "full_data_out_*.json")),
                   key=lambda p: int(p.rsplit("_", 1)[1][:-5]))
    rows = []
    for f in parts:
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        for g in d["datasets"]:
            if g["dataset"] not in ("heldout_confirm", "contamination"):
                continue
            for ex in g["examples"]:
                inp = json.loads(ex["input"])
                r = {k: ex.get("metadata_" + k) for k in KEEP}
                r["sentence"] = inp.get("sentence")
                r["candidate_fol"] = inp.get("candidate_fol")
                r["output"] = ex["output"]
                rows.append(r)
        del d
    return rows


def load_frame() -> list[dict]:
    p = WORK / "frame.jsonl"
    if not p.exists():
        rows = build_frame()
        wj(p, rows)
        return rows
    return rj(p)


# ------------------------------------------------------------------------------------------ pair runner
def _init_worker(mem_gb: float) -> None:
    for v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[v] = "1"
    try:
        b = int(mem_gb * 1024 ** 3)
        resource.setrlimit(resource.RLIMIT_AS, (b, b))
    except (ValueError, OSError):
        pass
    sys.path.insert(0, str(ROOT))


def _pair_batch(batch: list[tuple[str, str, bool]]) -> list[dict]:
    from dc.pairs import compute_record
    out = []
    for a, b, lex in batch:
        try:
            out.append(compute_record(a, b, want_lex=lex))
        except MemoryError:
            from dc.pairs import pkey
            lo, hi = (a, b) if a <= b else (b, a)
            out.append({"k": pkey(a, b), "lo": lo, "hi": hi, "rel": "UNKNOWN", "rel_L1": "UNKNOWN",
                        "rel_L2": "UNKNOWN", "rel_L3": "UNKNOWN", "rel_lex": "UNKNOWN", "error": "MemoryError"})
    return out


class PairStore:
    """Resumable append-only cache of best_relation records keyed by pkey (orientation-free)."""

    def __init__(self, path: Path = PAIRS_CACHE):
        self.path = path
        self.d: dict[str, dict] = {}
        for r in rj(path):
            self.d[r["k"]] = r

    def get(self, a: str, b: str) -> dict | None:
        from dc.pairs import oriented, pkey
        r = self.d.get(pkey(a, b))
        if r is None:
            return None
        return oriented(r, a == r["lo"])

    def compute(self, pairs: list[tuple[str, str]], workers: int, want_lex: bool = True, batch: int = 16,
                log=print, limit_s: float = 0) -> dict:
        from dc.pairs import pkey
        todo, seen = [], set()
        for a, b in pairs:
            k = pkey(a, b)
            if k in self.d or k in seen:
                continue
            seen.add(k)
            todo.append((a, b, want_lex))
        log(f"pairs: {len(pairs)} requested, {len(todo)} to compute ({len(self.d)} cached)")
        if not todo:
            return {"n_new": 0}
        # heavy pairs spread across workers: interleave by a hash so batches are mixed
        todo.sort(key=lambda t: sha1(t[0] + t[1]))
        batches = [todo[i:i + batch] for i in range(0, len(todo), batch)]
        t0, n = time.time(), 0
        with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn"), initializer=_init_worker,
                                 initargs=(3.0,)) as ex, open(self.path, "a", encoding="utf-8") as f:
            futs = [ex.submit(_pair_batch, b) for b in batches]
            for fu in as_completed(futs):
                try:
                    rs = fu.result()
                except Exception as e:  # noqa: BLE001 - a crashed batch is logged, its pairs stay uncached
                    log(f"batch failed: {e!r}")
                    continue
                for r in rs:
                    self.d[r["k"]] = r
                    f.write(json.dumps(clean(r), ensure_ascii=False) + "\n")
                f.flush()
                n += len(rs)
                if n % (batch * 50) < batch:
                    el = time.time() - t0
                    log(f"  pairs {n}/{len(todo)} {el:.0f}s ({n / max(el, 1e-9):.1f}/s)")
                if limit_s and time.time() - t0 > limit_s:
                    log("time limit reached; cancelling (resumable)")
                    for x in futs:
                        x.cancel()
                    break
        el = time.time() - t0
        log(f"pairs done {n} in {el:.0f}s")
        return {"n_new": n, "seconds": el}
