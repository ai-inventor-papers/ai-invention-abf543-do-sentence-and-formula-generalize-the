"""A3 (Arm A zero-LLM monotonicity signature) on held-out targets, isolated from this workspace's modules
(Arm A has its own fol_parse/llm). Resumable: results/a3_scores.jsonl. Priority P → Ccon → T."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

W = Path(__file__).resolve().parents[1]
os.environ.setdefault("NLTK_DATA", str(W / "nltk_data"))
ARMA = W / "third_party" / "armA"
sys.path[:0] = [str(ARMA), str(ARMA / "src")]
os.chdir(ARMA)
import method as armA  # noqa: E402

OUT = W / "results" / "a3_scores.jsonl"
tg = [json.loads(l) for l in (W / "data" / "heldout_targets.jsonl").read_text().splitlines()]
ids = {t["original_item_id"] for t in tg if t["group"] == "contamination"}
keep = [t for t in tg if t["panel"] or t["group"] == "contamination" or t["item_id"] in ids or t["tercile"] == "top"]
keep.sort(key=lambda t: (0 if t["panel"] else 1 if (t["group"] == "contamination" or t["item_id"] in ids) else 2))
if len(sys.argv) > 1:
    keep = keep[: int(sys.argv[1])]
done = set()
if OUT.exists():
    done = {json.loads(l)["item_id"] for l in OUT.read_text().splitlines() if l.strip()}
t0 = time.time()
with OUT.open("a") as f:
    for i, t in enumerate(keep):
        if t["item_id"] in done:
            continue
        s0 = time.time()
        if not t["fol_folio"]:
            r = {"score": 0.5, "covered": False, "error": "unparseable", "error_type_pred": None}
        else:
            try:
                r = armA.signature_faithfulness(t["nl"], t["fol_folio"], variant="A3")
            except Exception as e:  # noqa: BLE001 - scorer failure → uncovered, counted
                r = {"score": 0.5, "covered": False, "error": f"{type(e).__name__}:{e}"[:160], "error_type_pred": None}
        f.write(json.dumps({"item_id": t["item_id"], "metric": "A3", "score": float(r.get("score", 0.5)),
                            "covered": bool(r.get("covered", True)) and "error" not in r,
                            "error_type_pred": r.get("error_type_pred"), "err": r.get("error"),
                            "seconds": round(time.time() - s0, 3)}) + "\n")
        f.flush()
        if (i + 1) % 100 == 0:
            print(f"A3 {i + 1}/{len(keep)} {time.time() - t0:.0f}s", flush=True)
print("A3_DONE", flush=True)
