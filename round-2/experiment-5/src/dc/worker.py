"""Per-sentence DC pair worker (run as a subprocess with RLIMIT_CPU / RLIMIT_AS set by the parent).

python -m dc.worker <task.json> <out.jsonl>
task = {"sid": ..., "budget_s": 300, "limits": {...}, "pairs": [{"key", "a", "b", "kind"}...]}
Each finished pair is appended to out.jsonl immediately, so a killed worker loses only unfinished pairs
(the parent marks those UNKNOWN / timeout).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dc.core import Formula, pair_relation  # noqa: E402


def main() -> None:
    task = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = Path(sys.argv[2])
    done = set()
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    done.add(json.loads(line)["key"])
                except (json.JSONDecodeError, KeyError):
                    pass
    t0 = time.time()
    budget = float(task.get("budget_s", 300))
    limits = task.get("limits") or {}
    cache: dict[str, Formula] = {}

    def F(s):
        if s not in cache:
            cache[s] = Formula(s)
        return cache[s]
    with open(out, "a", encoding="utf-8") as f:
        for p in task["pairs"]:
            if p["key"] in done:
                continue
            left = budget - (time.time() - t0)
            if left <= 0.5:
                rec = {"key": p["key"], "relation": "UNKNOWN", "reason": "sentence_budget", "seconds": 0.0}
            else:
                lim = dict(limits)
                lim["pair_seconds"] = min(float(lim.get("pair_seconds", 20.0)), left)
                A, B = F(p["a"]), F(p["b"])
                big = A.ok and B.ok and len(A.preds) > 12 and len(B.preds) > 12
                if big and task.get("big_rule"):
                    lim.update(task["big_rule"])
                try:
                    r = pair_relation(A, B, lim, seed=0)
                except (RecursionError, MemoryError, ValueError, KeyError, IndexError) as e:
                    r = {"relation": "UNKNOWN", "reason": f"error:{type(e).__name__}:{str(e)[:80]}", "seconds": 0.0}
                rec = {"key": p["key"], **{k: v for k, v in r.items() if k in (
                    "relation", "level", "map", "cmap", "defs", "n_maps", "n_z3", "timed_out", "seconds", "direction",
                    "relation_l12", "level_l12", "map_l12", "reason")}}
                rec["n_preds_a"] = len(A.preds) if A.ok else None
                rec["n_preds_b"] = len(B.preds) if B.ok else None
                rec["big_rule_applied"] = bool(big and task.get("big_rule"))
            rec["kind"] = p.get("kind")
            f.write(json.dumps(rec, ensure_ascii=False, default=list) + "\n")
            f.flush()


if __name__ == "__main__":
    main()
