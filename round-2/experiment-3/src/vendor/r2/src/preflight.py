"""T0/T1 pre-flight: frozen-code manifest (sha1 of every vendored file vs its iter-1 original), frozen prompt/request
checks, and the reproduction pre-flight (LC_onecoin on Arm B's screen; A3/A0 on 50 Arm A screen items)."""
from __future__ import annotations

import json

from loguru import logger

from common import ARMA_DIR, ARMB_DIR, DS_DIR, RES, ROOT, WORK, jdump, sha1

VENDOR_MAP = {"armA": ARMA_DIR, "armB": ARMB_DIR, "ds": DS_DIR}


def file_sha1(p) -> str:
    import hashlib
    return hashlib.sha1(p.read_bytes()).hexdigest()


def manifest() -> dict:
    out = {"files": {}, "prompts": {}, "all_identical_to_iter1": True}
    for arm, src_root in VENDOR_MAP.items():
        for p in sorted((ROOT / "vendor" / arm).rglob("*")):
            if p.is_dir() or "__pycache__" in p.parts or p.suffix not in (".py", ".json") or "logs" in p.parts:
                continue
            rel = p.relative_to(ROOT / "vendor" / arm)
            orig = src_root / rel
            h = file_sha1(p)
            ho = file_sha1(orig) if orig.exists() else None
            out["files"][f"vendor/{arm}/{rel}"] = {"sha1": h, "iter1_sha1": ho, "identical": h == ho}
            out["all_identical_to_iter1"] &= (h == ho)
    import llm_stages as L
    pf = json.loads((ROOT / "vendor" / "armB" / "results" / "prompts_frozen.json").read_text())
    armA_src = (ROOT / "vendor" / "armA" / "run_baselines.py").read_text()
    out["prompts"]["B1_PROMPT_sha1"] = sha1(L.B1_PROMPT)
    out["prompts"]["B1_equals_armB_prompts_frozen"] = L.B1_PROMPT == pf["B1_PROMPT"]
    out["prompts"]["B1_equals_armA_run_baselines"] = (
        '"Sentence: {s}\\nFOL: {f}\\nGive the probability (0-100) that this FOL is a faithful formalization "' in armA_src)
    out["prompts"]["B3_PROMPT_sha1"] = sha1(L.B3_PROMPT)
    out["prompts"]["B3_in_armA_run_baselines"] = ('"Translate this first-order logic formula into one plain English '
                                                  'sentence. Read predicate and "' in armA_src)
    import re
    ts = (ROOT / "vendor" / "armA" / "src" / "text_sig.py").read_text()
    m = re.search(r'PROBE_INSTR = \((.*?)\)\n', ts, re.S)
    out["prompts"]["A1_PROBE_INSTR_sha1"] = sha1(m.group(1)) if m else None
    # T0e: request diff vs the iter-1 B1 request example (only content may differ; max_tokens 16 per Arm A)
    ex = json.loads((ROOT / "vendor" / "armB" / "results" / "b1_request_example.json").read_text())
    mine = {**L.b1_body("S", "F"), "usage": {"include": True}}
    diff = {k: (ex.get(k), mine.get(k)) for k in set(ex) | set(mine) if k != "messages" and ex.get(k) != mine.get(k)}
    out["b1_request_diff_vs_armB_example"] = diff
    out["b1_request_note"] = ("Arm B sent max_tokens 8; Arm A sent max_tokens 16 with a 48-token retry. The plan fixes "
                              "16 (+48 retry); every other field is identical to b1_request_example.json.")
    return out


def run() -> dict:
    res = {"manifest": manifest()}
    for tag, f in (("T1_LC_onecoin_screen", "preflight_lc.json"), ("T1_A3_A0_screen_50", "preflight_armA.json")):
        p = WORK / f
        res[tag] = json.loads(p.read_text()) if p.exists() else "not run"
    res["T1_notes"] = {
        "LC": "run_latent_class on Arm B data/screen_set.json + data/candidate_pairs.json reproduces Arm B "
              "results/screen_scores.jsonl (uncovered items compared at 0.5, as stages.row() stored them).",
        "A3": "method.signature_faithfulness(...,'A3') on the first 50 screen real items (sorted by item_id).",
        "A0": "iter-1 screen A0 rows were produced by run_metrics.py with the A1 (LLM) text side "
              "(variant base='A1'), whereas the reusable method.signature_faithfulness('A0') uses the zero-LLM "
              "rules text side; A0 therefore matches exactly only where both text sides label the same concepts. "
              "Held-out A0 uses the reusable zero-LLM function (the plan's S3f)."}
    jdump(res["manifest"], RES / "frozen_manifest.json")
    jdump(res, RES / "preflight.json")
    logger.info(f"preflight: identical={res['manifest']['all_identical_to_iter1']} prompts={res['manifest']['prompts']}")
    return res


def verify() -> dict:
    """Re-verify the manifest at the end of the run (fails loudly if any vendored file changed)."""
    old = json.loads((RES / "frozen_manifest.json").read_text())
    now = manifest()
    changed = [k for k, v in old["files"].items() if now["files"].get(k, {}).get("sha1") != v["sha1"]]
    return {"n_files": len(old["files"]), "changed": changed, "ok": not changed and now["all_identical_to_iter1"]}
