#!/usr/bin/env python3
"""Split full_data_out.json (exp_sel_data_out, written by data.py) into parts < MAX_MB under full_data_out/, and write
mini_data_out.json (first 3 examples per dataset group) and preview_data_out.json (mini with strings
truncated to 200 chars). Each part is itself a valid exp_sel_data_out object. Read parts with:
    for f in sorted(glob.glob('full_data_out/full_data_out_*.json'), key=lambda p: int(p.rsplit('_',1)[1][:-5])): ...
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 20 * 1024 * 1024


def trunc(x):
    if isinstance(x, str):
        return x[:200]
    if isinstance(x, list):
        return [trunc(v) for v in x]
    if isinstance(x, dict):
        return {k: trunc(v) for k, v in x.items()}
    return x


data = json.loads((ROOT / "full_data_out.json").read_text())
meta = data["metadata"]
outdir = ROOT / "full_data_out"
outdir.mkdir(exist_ok=True)
for old in list(outdir.glob("*full_data_out_*.json")):
    old.unlink()
parts, cur, cur_bytes = [], {}, 0
for ds in data["datasets"]:
    for ex in ds["examples"]:
        b = len(json.dumps(ex, ensure_ascii=False).encode()) + 2
        if cur_bytes + b > MAX_BYTES and cur:
            parts.append(cur)
            cur, cur_bytes = {}, 0
        cur.setdefault(ds["dataset"], []).append(ex)
        cur_bytes += b
if cur:
    parts.append(cur)
for i, p in enumerate(parts, 1):
    obj = {"metadata": {**meta, "part": i, "n_parts": len(parts)}, "datasets": [{"dataset": k, "examples": v} for k, v in p.items()]}
    (outdir / f"full_data_out_{i}.json").write_text(json.dumps(obj, ensure_ascii=False))
    print(f"part {i}: {sum(len(v) for v in p.values())} rows, groups={ {k: len(v) for k, v in p.items()} }, "
          f"{(outdir / f'full_data_out_{i}.json').stat().st_size / 1e6:.1f} MB")
for i in range(1, len(parts) + 1):  # per-part mini/preview (aii-file-size-limit)
    obj = json.loads((outdir / f"full_data_out_{i}.json").read_text())
    m = {"metadata": obj["metadata"], "datasets": [{"dataset": d["dataset"], "examples": d["examples"][:3]} for d in obj["datasets"]]}
    (outdir / f"mini_full_data_out_{i}.json").write_text(json.dumps(m, ensure_ascii=False, indent=1))
    (outdir / f"preview_full_data_out_{i}.json").write_text(json.dumps(trunc(m), ensure_ascii=False, indent=1))
# top-level mini/preview over ALL groups (the aii-json format script slices only the first 3 dataset groups)
mini = {"metadata": meta, "datasets": [{"dataset": d["dataset"], "examples": d["examples"][:3]} for d in data["datasets"]]}
(ROOT / "mini_full_data_out.json").write_text(json.dumps(mini, ensure_ascii=False, indent=1))
(ROOT / "preview_full_data_out.json").write_text(json.dumps(trunc(mini), ensure_ascii=False, indent=1))
(ROOT / "full_data_out.json").unlink()
print("per-part mini/preview written; full_data_out.json removed (parts are the full data)")
