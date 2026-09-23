"""Label firewall for the held-out population (dataset art_iyzYyaqlqpSX, group heldout_confirm).

load_inputs()  -> list of label-free rows (sentence, candidate FOL, system, corpus, story, complexity, ORIGINAL gold
                  formula) plus ONE design variable, `in_panel_sample` (= L3_selected: membership in the stratified
                  adjudication sample, fixed by the sampling design before any label existed; it is needed to know
                  WHICH items the LLM baselines must score). No verdict, error type, weight or audit field is exposed.
load_labels()  -> {item_id: label row}; raises unless results/frozen_config.json exists AND the sha256 of every file
                  in sigfaith/ (and the vendored legacy_armA/src/) equals the frozen hashes.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INPUTS = ROOT / "data" / "heldout_inputs.jsonl"
LABELS = ROOT / "data" / "heldout_labels.jsonl"
FROZEN = ROOT / "results" / "frozen_config.json"
STRIP_PREFIX = ("L0", "L1", "L2", "L3", "gold_audit", "gold_faithful_final", "paper_corrected_flag", "gold_fol_paper",
                "gold_fol_audited", "gold_source", "sentence_ambiguous", "label_source", "output")


class FirewallError(RuntimeError):
    pass


def hash_tree() -> dict:
    out = {}
    for d in (ROOT / "sigfaith", ROOT / "legacy_armA" / "src"):
        for p in sorted(d.glob("*.py")):
            out[str(p.relative_to(ROOT))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def load_inputs(with_design: bool = True) -> list[dict]:
    rows = [json.loads(l) for l in INPUTS.read_text().splitlines()]
    for r in rows:
        for k in list(r):
            if k.startswith(STRIP_PREFIX):
                del r[k]
    if with_design:
        sel = {}
        for l in LABELS.read_text().splitlines():
            x = json.loads(l)
            sel[x["item_id"]] = bool(x.get("L3_selected"))
        for r in rows:
            r["in_panel_sample"] = sel.get(r["item_id"], False)
    return rows


def check_frozen() -> dict:
    if not FROZEN.exists():
        raise FirewallError("frozen_config.json does not exist: labels are locked until the freeze")
    fz = json.loads(FROZEN.read_text())
    now = hash_tree()
    if now != fz.get("hashes"):
        diff = sorted(set(now.items()) ^ set(fz.get("hashes", {}).items()))
        raise FirewallError(f"sigfaith/ or legacy code changed after the freeze: {diff[:4]}")
    return fz


def load_labels() -> dict:
    check_frozen()
    return {json.loads(l)["item_id"]: json.loads(l) for l in LABELS.read_text().splitlines()}
