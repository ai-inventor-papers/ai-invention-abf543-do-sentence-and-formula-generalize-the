#!/usr/bin/env python3
"""Integrity and independent re-derivation checks -> results/audit_rederive.json, results/integrity.json.

1. Independent O(n^2) weighted AUROC (vendor stats.wauc_pairwise) for DC / LC_ds_binary / B1 on panel and solver
   labels must match the fast implementation used in tests.json to < 1e-6.
2. Bounded vs unbounded agreement: 200 random dev pairs with an aligned map are re-solved; for every entailment the
   bounded stage (domains 1..4) left standing, the unbounded z3 verdict is recorded (proved / refuted / unknown).
3. Freeze integrity: the dc/ tree hash equals the receipt; the receipt's own sha256 verifies; dc/*.py were not modified
   after the freeze timestamp; the vendor sha1 manifest (results/vendor_manifest.json) is unchanged.
4. Ledger: the sum of cost_ledger.jsonl.
"""
from __future__ import annotations

import datetime
import hashlib
import importlib.util
import json
import random
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))


def sha1f(p: Path) -> str:
    return hashlib.sha1(p.read_bytes()).hexdigest()


def main() -> None:
    from aframe import load_frame, sc
    spec = importlib.util.spec_from_file_location("r2stats", ROOT / "vendor" / "r2" / "src" / "stats.py")
    st = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(st)
    tests = json.loads((ROOT / "results" / "tests.json").read_text())
    rows, _ = load_frame()
    out = {"auroc_rederive": {}}
    for lab in ("panel", "solver"):
        R = [r for r in rows if (r["y_panel"] if lab == "panel" else r["y_solver"]) is not None]
        for m in ("DC", "LC_ds_binary", "B1"):
            y = [r["y_panel"] if lab == "panel" else r["y_solver"] for r in R]
            s = [sc(r, m) for r in R]
            w = [r["w_panel"] for r in R] if lab == "panel" else None
            a = st.wauc_pairwise(y, s, w)
            ref = tests["auroc"][f"{m}|{lab}"]["auc"]
            out["auroc_rederive"][f"{m}|{lab}"] = {"pairwise": a, "tests_json": ref, "abs_diff": abs(a - ref),
                                                   "match_1e-6": abs(a - ref) < 1e-6}
    # bounded vs unbounded
    from dc.align import FRESH, apply_map, derive
    from dc.parse import fingerprint, parse_fol
    from dc.relation import pair_relation
    from pairs import load_cache
    cache = load_cache()
    dev = [json.loads(x) for x in (ROOT / "work" / "dev_pair_jobs.jsonl").read_text().splitlines() if x.strip()]
    rng = random.Random(0)
    rng.shuffle(dev)
    from pairs import pkey
    agree = {"checked_entailments": 0, "unbounded_proved": 0, "unbounded_refuted": 0, "unbounded_unknown": 0,
             "pairs": 0}
    for j in dev:
        if agree["pairs"] >= 200:
            break
        k, x, y = pkey(j["a"], j["b"])
        rec = cache.get(k)
        if not rec or rec.get("error"):
            continue
        d = derive(rec, use_L3=False)
        if d["map"] is None or d["rel"] in ("UNKNOWN", "UNALIGNABLE"):
            continue
        A, B = parse_fol(x), parse_fol(y)
        Bm = apply_map(B, d["map"], fingerprint(B))
        r = pair_relation(A, Bm)
        agree["pairs"] += 1
        for m, v in r["method"].items():
            if m == "sat":
                continue
            agree["checked_entailments"] += 1
            agree["unbounded_" + {"unbounded": "proved", "unbounded_refuted": "refuted", "bounded": "unknown"}[v]] += 1
    agree["agreement_where_unbounded_finished"] = (agree["unbounded_proved"] /
                                                   max(1, agree["unbounded_proved"] + agree["unbounded_refuted"]))
    out["bounded_vs_unbounded"] = agree
    (ROOT / "results" / "audit_rederive.json").write_text(json.dumps(out, indent=1))
    # integrity
    fz_txt = (ROOT / "results" / "frozen_config.json").read_bytes()
    fz = json.loads(fz_txt)
    h = hashlib.sha256()
    for p in sorted((ROOT / "dc").glob("*.py")):
        h.update(p.name.encode())
        h.update(p.read_bytes())
    ts = datetime.datetime.fromisoformat(fz["timestamp_utc"]).timestamp()
    man_p = ROOT / "results" / "vendor_manifest.json"
    man = json.loads(man_p.read_text())
    changed = [p for p, s in man["sha1"].items() if not (ROOT / p).exists() or sha1f(ROOT / p) != s]
    ledger = sum(json.loads(x)["cost_usd"] for x in (ROOT / "cost_ledger.jsonl").read_text().splitlines() if x.strip())
    integ = {"dc_tree_sha256_now": h.hexdigest(), "dc_tree_sha256_receipt": fz["dc_code_sha256"],
             "dc_tree_unchanged": h.hexdigest() == fz["dc_code_sha256"],
             "receipt_sha256_verifies": hashlib.sha256(fz_txt).hexdigest() ==
             (ROOT / "results" / "frozen_config.sha256").read_text().split()[0],
             "dc_files_modified_after_freeze": [p.name for p in (ROOT / "dc").glob("*.py") if p.stat().st_mtime > ts],
             "vendor_files": len(man["sha1"]), "vendor_changed": changed,
             "ledger_total_usd": round(ledger, 4), "freeze_timestamp_utc": fz["timestamp_utc"]}
    (ROOT / "results" / "integrity.json").write_text(json.dumps(integ, indent=1))
    print(json.dumps({"auroc_rederive_all_match": all(v["match_1e-6"] for v in out["auroc_rederive"].values()),
                      "bounded_vs_unbounded": agree, **integ}, indent=1))


if __name__ == "__main__":
    main()
