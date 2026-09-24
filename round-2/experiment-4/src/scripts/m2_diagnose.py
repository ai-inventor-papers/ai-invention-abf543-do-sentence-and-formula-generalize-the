#!/usr/bin/env python3
"""Fallback 10: diagnose rename-induced relation changes in M2 (which peer relations changed, and why)."""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dc.common import RES, WORK, PairStore, load_frame, rj, jdump
from dc import front, probes as PR

rows = [r for r in rj(WORK / "m2_rows.jsonl") if r.get("ok") and r["kind"] in ("syn_rename", "tok_rename", "var_rename") and r["rels_changed"]]
st = PairStore()
G = {r["item_id"]: r for r in load_frame() if r["fold"] == "heldout_confirm"}
cm = {c["raw"]: (c["canon"] if c["ok"] else None) for c in rj(WORK / "canon.jsonl")}
by = {}
for r in G.values():
    by.setdefault(r["sentence_id"], []).append(r)
out = []
for x in rows:
    r = G[x["item_id"]]
    c = cm[r["candidate_fol"]]
    A = front.parse_canon(c)
    rw = {y["kind"]: y for y in PR.rewrites(A, x["item_id"]) if y.get("ok")}
    new = front.canon(rw[x["kind"]]["fol"])["canon"]
    for p in sorted(by[r["sentence_id"]], key=lambda q: q["system"]):
        if p["item_id"] == r["item_id"]:
            continue
        pc = cm.get(p["candidate_fol"] or "")
        if not pc:
            continue
        a, b = st.get(c, pc), st.get(new, pc)
        if a and b and a.get("rel") != b.get("rel"):
            out.append({"item_id": x["item_id"], "kind": x["kind"], "peer": p["system"], "orig": c, "renamed": new, "peer_fol": pc,
                        "rel_orig": a.get("rel"), "rel_renamed": b.get("rel"), "levels": [a.get("level"), b.get("level")],
                        "timeouts": [a.get("timeout"), b.get("timeout")], "targets": [a.get("target"), b.get("target")],
                        "lo_is_cand": [a.get("lo") == c, b.get("lo") == new], "n_maps_L2": [a.get("n_maps_L2"), b.get("n_maps_L2")],
                        "seconds": [a.get("seconds"), b.get("seconds")]})
jdump({"n_items_with_changed_relations": len(rows), "changed_pairs": out}, RES / "m2_rename_diagnosis.json")
for o in out:
    print(o["kind"], o["rel_orig"], "->", o["rel_renamed"], "levels", o["levels"], "timeouts", o["timeouts"], "targets", o["targets"], "lo_is_cand", o["lo_is_cand"], "nL2", o["n_maps_L2"], o["seconds"])
