#!/usr/bin/env python3
"""Re-apply the (frozen, v2) formula extractor + parser to every stored raw generation.

v2 adds LaTeX unwrapping (\\( \\) \\text{..} \\, \\left( ...) and skips bullet/definition lines; the raw
outputs are unchanged, so this is a pure function of raw_output.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from fol_parse import extract_formula, parse  # noqa: E402

for f in sorted((ROOT / "raw" / "generations").glob("*.jsonl")):
    rows = [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
    changed = 0
    for r in rows:
        raw = r.get("raw_output")
        ext = extract_formula(raw) if raw else ""
        pr = parse(ext) if ext else None
        new_ok = bool(pr and pr.ok)
        if ext != r.get("candidate_fol") or new_ok != r.get("parse_ok"):
            changed += 1
        r["candidate_fol"] = ext
        r["parse_ok"] = new_ok
        r["parse_error"] = (pr.error if pr else ("empty_output" if raw is not None else r.get("api_error", "")))
        r["parse_notes"] = pr.notes if pr else []
        r["extractor_version"] = 2
    f.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    g = [r for r in rows if r["sample_idx"] == 0]
    print(f.stem.ljust(24), "changed", changed, "greedy parse rate %.3f" % (sum(r["parse_ok"] for r in g) / len(g)))
