#!/usr/bin/env python3
"""TODO 3: preview 20 candidate HF datasets via the datasets-server API (first rows + card metadata)."""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parents[1]
CANDS = ["tasksource/folio", "yale-nlp/FOLIO", "yuan-yang/MALLS-v0", "DSAVlab-UNIUD/MALLS_test_subset-CURATED",
         "DSAVlab-UNIUD/FOLIO_validation-curated", "opendatalab/ProverQA", "yfxiao/folio-refined",
         "kenken6696/folio_by_ccg2lambda", "kenken6696/MALLS_by_ccg2lambda", "benlipkin/folio", "minimario/FOLIO",
         "tasksource/FOL-nli", "tasksource/LogicNLI", "tasksource/proofwriter", "kkkarry/LogicGraph",
         "logicreasoning/logi_glue", "Isotonic/symbolic_data_first_order_logic", "verify-ppt/ppt-logic_first_order",
         "tasksource/monotonicity-entailment", "jhkim64/NL2FOL_sentence"]
DS = "https://datasets-server.huggingface.co"
api = HfApi()


def one(rid):
    out = {"id": rid}
    try:
        info = api.dataset_info(rid, files_metadata=True)
        out.update({"downloads": info.downloads, "likes": info.likes, "gated": info.gated,
                    "license": (info.card_data or {}).get("license") if info.card_data else None,
                    "total_bytes": sum((s.size or 0) for s in info.siblings),
                    "files": [s.rfilename for s in info.siblings][:12]})
    except Exception as e:  # noqa: BLE001
        out["info_error"] = str(e)[:200]
    try:
        sp = requests.get(f"{DS}/splits", params={"dataset": rid}, timeout=30).json()
        s0 = (sp.get("splits") or [{}])[0]
        out["splits"] = [(s["config"], s["split"]) for s in sp.get("splits", [])][:8]
        if s0:
            fr = requests.get(f"{DS}/first-rows", params={"dataset": rid, "config": s0["config"], "split": s0["split"]}, timeout=30).json()
            out["columns"] = [f["name"] for f in fr.get("features", [])]
            out["rows"] = [{k: str(v)[:220] for k, v in r["row"].items()} for r in fr.get("rows", [])[:3]]
            if "error" in fr:
                out["rows_error"] = str(fr["error"])[:200]
        elif "error" in sp:
            out["rows_error"] = str(sp["error"])[:200]
    except Exception as e:  # noqa: BLE001
        out["rows_error"] = str(e)[:200]
    return out


with ThreadPoolExecutor(10) as ex:
    res = list(ex.map(one, CANDS))
(ROOT / "temp" / "previews" / "candidate_previews.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
for r in res:
    print(r["id"], "| dl", r.get("downloads"), "| lic", r.get("license"), "| bytes", r.get("total_bytes"), "| gated", r.get("gated"),
          "| cols", r.get("columns"), "|", (r.get("rows") or [{}])[0] if r.get("rows") else r.get("rows_error", "")[:100])
