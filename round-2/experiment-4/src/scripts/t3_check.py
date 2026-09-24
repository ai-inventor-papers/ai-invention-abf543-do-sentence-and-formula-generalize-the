#!/usr/bin/env python3
"""T3 probe sanity on the full M1 build: DC(F_tok) == DC(F_conf) == DC(F_syn) exactly; same for each mutant across
arms; canonical re-parse identity; appended to results/integrity.json."""
import json, sys
from collections import defaultdict
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dc.common import RES, WORK, rj, jdump

P = rj(WORK / "m1_probes.jsonl")
by = defaultdict(dict)
for p in P:
    by[(p["sid"], p["kind"], p["op"])][p["arm"]] = p
F = [v for k, v in by.items() if k[1] == "F"]
M = [v for k, v in by.items() if k[1] == "M" and len(v) == 3]
t3 = {"n_sentences": len(F),
      "F_DC_identical_all_arms": sum(1 for v in F if len({v[a]["DC"] for a in v}) == 1) / len(F),
      "F_rel_vectors_identical_all_arms": sum(1 for v in F if len({tuple(v[a].get("rels") or []) for a in v}) == 1) / len(F),
      "M_DC_identical_all_arms": sum(1 for v in M if len({v[a]["DC"] for a in v}) == 1) / max(1, len(M)),
      "canon_same_ast_rate": json.loads((WORK / "m1_build_info.json").read_text())["canon_same_ast_rate"],
      "F_conf_equiv_R_identity": "asserted at build time (pair_relation EQUIV required; 28 sentences without a renderable member dropped)"}
integ = json.loads((RES / "integrity.json").read_text())
integ["T3_probe_sanity"] = t3
integ["T0_pytest"] = (RES / "pytest_result.txt").read_text().strip()
integ["T5_audit_all_match"] = json.loads((RES / "audit_rederive.json").read_text())["ALL_MATCH"]
jdump(integ, RES / "integrity.json")
print(json.dumps(t3))
