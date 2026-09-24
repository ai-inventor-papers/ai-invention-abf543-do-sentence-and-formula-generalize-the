#!/usr/bin/env python3
"""STEP 11: E2 transfer split from the user's DPV / EU-AI-Act pilot (READ-ONLY zip, extracted to
raw/pilot/). One row per 04_fol.json (definition x condition x run) of pipeline pilot_results/.
input.sentence = the Art. 3 definition text from euaiact_enacting_terms.json; output = 'unlabeled'.
Pilot structural metrics (metric2 shape inconsistency, metric5 inter-run Jaccard per
definition x condition; per-run Prolog validation outcome) are attached where present.
Writes work/e2_rows.json.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from fol_parse import complexity_ast, parse  # noqa: E402

PIPE = ROOT / "raw" / "pilot" / "dpv_pilot_study" / "pipeline_Adapted_NL2FOL_prototype"


def main() -> None:
    terms = json.loads((PIPE / "euaiact_enacting_terms.json").read_text())["enacting_terms"]
    art3 = next(a for c in terms["chapters"] for a in c["articles"] if a["id"] == "Article 3")
    defs = {}
    for par in art3["paragraphs"][1:]:
        m = re.match(r"\((\d+)\)\s*[‘']([^’']+)[’']\s*(.*)", par)
        if m:
            defs[int(m.group(1))] = {"term": m.group(2), "text": par, "body": m.group(3)}
    mdir = PIPE / "pilot_results_metrics"
    m2 = json.loads((mdir / "metric2_shape_consistency.json").read_text()).get("by_sentence_condition", {})
    m5 = json.loads((mdir / "metric5_jaccard.json").read_text()).get("by_sentence_condition", {})
    rows = []
    for f in sorted((PIPE / "pilot_results").glob("*/*/run_*/04_fol.json")):
        run = f.parent.name
        cond = f.parent.parent.name
        ddir = f.parent.parent.parent.name
        num = int(ddir.split("_")[0])
        d = defs.get(num, {})
        try:
            fol = json.loads(f.read_text()).get("fol", "")
        except json.JSONDecodeError:
            fol = f.read_text()
        pr = parse(fol)
        pv = f.parent / "prolog_validation.json"
        pv_ok = None
        if pv.exists():
            try:
                pvd = json.loads(pv.read_text())
                pv_ok = any(a.get("ok") for a in pvd.get("attempts", []))
            except json.JSONDecodeError:
                pv_ok = None
        c = complexity_ast(pr.ast) if pr.ok else {}
        rows.append({
            "definition_id": ddir, "definition_number": num, "term": d.get("term"), "condition": cond, "run": run,
            "sentence": d.get("text", ""), "candidate_fol": fol, "parse_ok": pr.ok, "parse_error": pr.error,
            "parse_notes": pr.notes, "n_tokens": len(d.get("text", "").split()),
            "n_quantifiers": c.get("n_quantifiers"), "nesting_depth": c.get("nesting_depth"),
            "pilot_metric2_inconsistent_rate": (m2.get(ddir, {}).get(cond) or {}).get("inconsistent_rate"),
            "pilot_metric5_mean_jaccard": (m5.get(ddir, {}).get(cond) or {}).get("mean_jaccard"),
            "pilot_prolog_valid": pv_ok, "source_path": str(f.relative_to(ROOT)),
        })
    (ROOT / "work" / "e2_rows.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    n_ok = sum(r["parse_ok"] for r in rows)
    print(f"E2 rows {len(rows)}; parse_ok {n_ok}; definitions {len({r['definition_id'] for r in rows})}; "
          f"missing def text {sum(not r['sentence'] for r in rows)}")


if __name__ == "__main__":
    main()
