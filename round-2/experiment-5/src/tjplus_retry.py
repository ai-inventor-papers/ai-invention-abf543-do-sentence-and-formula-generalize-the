#!/usr/bin/env python3
"""TJ+ retry: panel-unfaithful items whose TJ+ answer did not parse (thinking truncated at max_tokens=1600) are re-asked
ONCE with max_tokens=3000 (same prompt, thinking budget 1024). Rows are appended with method TJplus; the analysis keeps
the parse-ok row."""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "sigfaith"))
import phase2_llm as P
import llm
rows = [json.loads(l) for l in P.OUT.read_text().splitlines()]
ok = {r["unit_id"] for r in rows if r["method"] == "TJplus" and r.get("parse_ok")}
bad = {r["unit_id"] for r in rows if r["method"] == "TJplus" and not r.get("parse_ok")} - ok
us = [u for u in P.units() if u["unit_id"] in bad]
tax = P.taxonomy_block()
jobs = [dict(model=P.MODEL, messages=[{"role": "user", "content": P.TJ_PROMPT.format(s=u["s"], f=u["f"], tax=tax)}],
             purpose="TJplus_retry", reasoning={"max_tokens": 1024}, max_tokens=3000) for u in us]
print("retry", len(jobs))
res = llm.run(jobs, concurrency=16, est_cost_each=0.004)
out = []
for u, r in zip(us, res):
    d = P.parse_tj(r[0]) if not isinstance(r, Exception) else {"parse_ok": False}
    out.append({"unit_id": u["unit_id"], "kind": u["kind"], "method": "TJplus", **d, "retry": True,
                "usd": 0.0 if isinstance(r, Exception) else (r[1].get("cost") or 0.0), "cached": False,
                "error": repr(r)[:200] if isinstance(r, Exception) else None})
P.write(out)
print("parsed", sum(o["parse_ok"] for o in out), "of", len(out), "spent", llm.spent())
