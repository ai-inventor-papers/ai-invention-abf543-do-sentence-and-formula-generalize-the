"""Held-out LABEL loader — runs only after the freeze receipt exists and its hashes match (plan §6)."""
from __future__ import annotations

import hashlib
import json

import common
from common import RESULTS


class FreezeViolation(RuntimeError):
    pass


def check_receipt() -> dict:
    rp = RESULTS / "freeze_receipt.json"
    if not rp.exists():
        raise FreezeViolation("freeze_receipt.json missing: labels may not be read before the freeze")
    rc = json.loads(rp.read_text())
    for f, k in (("frozen_config.json", "frozen_config_sha1"), ("prereg.json", "prereg_sha1")):
        h = hashlib.sha1((RESULTS / f).read_bytes()).hexdigest()
        if h != rc[k]:
            raise FreezeViolation(f"{f} changed after the freeze ({h} != {rc[k]})")
    return rc


def load_labels() -> dict[str, dict]:
    """item_id → {y_panel, w, y_hard, y_soft, primary_error, L1_equiv, group, rename_incomplete}."""
    check_receipt()
    lr = json.loads((common.DATASET_DIR / "label_report.json").read_text())
    rows = common.load_dataset_rows(blind=False)
    out = {}
    for r in rows:
        if r["group"] not in ("heldout_confirm", "contamination"):
            continue
        o = r.get("output")
        y_hard = 1 if o == "faithful" else 0 if o == "unfaithful" else None
        panel = r.get("metadata_label_source") == "panel3"
        l1 = r.get("metadata_L1_audited_status") or r.get("metadata_L1_orig_status")
        l1_eq = None if l1 is None else str(l1).startswith("equiv")
        if panel:
            y_soft = 1.0 if r.get("metadata_L3_majority") else 0.0
        elif r.get("metadata_L3_stratum_p_faithful") is not None:
            y_soft = float(r["metadata_L3_stratum_p_faithful"])
        elif l1_eq is not None:
            y_soft = 0.90 if l1_eq else 0.44
        else:
            y_soft = None
        out[r["metadata_item_id"]] = {
            "group": r["group"], "panel": panel,
            "y_panel": (1 if r.get("metadata_L3_majority") else 0) if panel else None,
            "w": float(r.get("metadata_L3_sampling_weight") or 1.0) if panel else None,
            "y_hard": y_hard, "y_soft": y_soft, "primary_error": r.get("metadata_L3_primary_error"),
            "L1_equiv": l1_eq, "rename_incomplete": r.get("metadata_contamination_rename_incomplete"),
            "label_source": r.get("metadata_label_source")}
    out["__label_report_rates__"] = {"note": "soft priors 0.90 / 0.44 from label_report.json",
                                     "keys": list(lr.keys())[:20]}
    return out
