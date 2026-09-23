"""Stage: label-blind held-out target table (data/heldout_targets.jsonl) + syntax-bridge coverage."""
from __future__ import annotations

import collections as C
import json

from loguru import logger

import common
from bridge import to_folio_str


def build() -> dict:
    rows = common.load_dataset_rows(blind=True)
    assert all("output" not in r for r in rows), "label leak into scoring"
    out, cov = [], C.defaultdict(C.Counter)
    for r in rows:
        if r["group"] not in ("heldout_confirm", "contamination", "heldout_samples"):
            continue
        inp = json.loads(r["input"])
        fol_raw = inp.get("candidate_fol") or ""
        fol, how = to_folio_str(fol_raw) if fol_raw else (None, "unparseable:empty")
        t = {"item_id": r["metadata_item_id"], "group": r["group"], "sid": r["metadata_sentence_id"],
             "system": r.get("metadata_system"), "corpus": r.get("metadata_corpus"),
             "nl": inp.get("sentence"), "fol_raw": fol_raw, "fol_folio": fol, "bridge": how,
             "parse_ok_meta": bool(r.get("metadata_parse_ok")),
             "tercile": r.get("metadata_complexity_tercile"), "composite": r.get("metadata_complexity_composite"),
             "n_conditions": r.get("metadata_n_conditions"),
             "panel": r.get("metadata_label_source") == "panel3",
             "original_item_id": r.get("metadata_original_item_id"),
             "rename_incomplete": r.get("metadata_contamination_rename_incomplete"),
             "sample_idx": r.get("metadata_sample_idx")}
        out.append(t)
        if r["group"] != "heldout_samples":
            cov[r["group"] + "|" + str(t["system"])][how.split(":")[0]] += 1
    # contamination rows inherit tercile/composite/n_conditions from their original
    by_id = {t["item_id"]: t for t in out if t["group"] == "heldout_confirm"}
    for t in out:
        if t["group"] == "contamination" and t["original_item_id"] in by_id:
            o = by_id[t["original_item_id"]]
            for k in ("tercile", "composite", "n_conditions", "panel"):
                t["orig_" + k] = o[k]
            t["tercile"] = t["tercile"] or o["tercile"]
            t["composite"], t["n_conditions"] = o["composite"], o["n_conditions"]
    with open(common.DATA / "heldout_targets.jsonl", "w") as f:
        for t in out:
            if t["group"] != "heldout_samples":
                f.write(json.dumps(t, ensure_ascii=False) + "\n")
    with open(common.DATA / "heldout_samples.jsonl", "w") as f:
        for t in out:
            if t["group"] == "heldout_samples":
                f.write(json.dumps(t, ensure_ascii=False) + "\n")
    cov = {k: dict(v) for k, v in sorted(cov.items())}
    hc = [t for t in out if t["group"] == "heldout_confirm"]
    summ = {"n_heldout_confirm": len(hc), "n_panel": sum(t["panel"] for t in hc),
            "n_top": sum(t["tercile"] == "top" for t in hc),
            "n_panel_top_label_free": sum(t["panel"] and t["tercile"] == "top" for t in hc),
            "n_contamination": sum(t["group"] == "contamination" for t in out),
            "bridge_coverage": cov}
    (common.RESULTS / "bridge_coverage.json").write_text(json.dumps(summ, indent=1))
    return summ


if __name__ == "__main__":
    s = build()
    logger.info(json.dumps({k: v for k, v in s.items() if k != "bridge_coverage"}))
    for k, v in s["bridge_coverage"].items():
        logger.info(f"{k}: {v}")
