#!/usr/bin/env python3
"""T1 alignment audit: 10 random L2/L3 EQUIV verdicts + 5 random other aligned pairs with their maps/definitions
-> logs/alignment_audit.txt (to check that alignment is not MANUFACTURING agreement)."""
import json
import random
from pathlib import Path

from common import LOGS, WORK, read_jsonl

tasks = {}
for f in (WORK / "dc_tasks" / "legal").glob("*.json"):
    for p in json.loads(f.read_text())["pairs"]:
        tasks[p["key"]] = p
recs = []
for f in sorted((WORK / "dc_pairs" / "legal").glob("*.jsonl")):
    recs += [r for r in read_jsonl(f) if r["key"] in tasks]
rng = random.Random(7)
eq = [r for r in recs if r["relation"] == "EQUIV" and r.get("level") in (2, 3)]
oth = [r for r in recs if r["relation"] in ("STRONGER", "WEAKER") and r.get("level") in (1, 2)]
lines = [f"L2/L3 EQUIV verdicts: {len(eq)} of {len(recs)} pairs; sample of 10\n"]
for r in rng.sample(eq, min(10, len(eq))) + rng.sample(oth, min(5, len(oth))):
    p = tasks[r["key"]]
    lines.append(f"== {r['relation']} level {r.get('level')} direction {r.get('direction')} ({r.get('seconds')}s)\n"
                 f"A: {p['a']}\nB: {p['b']}\nmap(B->A): {r.get('map')}\ndefs: {r.get('defs')}\n")
(LOGS / "alignment_audit.txt").write_text("\n".join(lines), encoding="utf-8")
print(len(eq), "L2/L3 EQUIV; audit written")
