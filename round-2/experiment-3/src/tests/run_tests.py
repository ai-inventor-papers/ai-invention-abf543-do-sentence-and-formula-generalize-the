#!/usr/bin/env python3
"""T0 unit tests (no API). `uv run tests/run_tests.py` -> results/unit_tests.json (non-zero exit on failure)."""
from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from common import WORK, load_frame, read_jsonl, sha1  # noqa: E402
from stats import StratBoot, soft_auc, wauc, wauc_pairwise  # noqa: E402


def t_adapter():
    """(a) canon re-parses to the same AST (dataset parser) and the arms accept canon; 30 per corpus + worst failures."""
    rows = [r for r in load_frame() if r["fold"] == "heldout_confirm"]
    canon = {r["h"]: r for r in read_jsonl(WORK / "canon.jsonl")}
    pa = {r["h"]: r for r in read_jsonl(WORK / "armA_parse.jsonl")}
    pb = {r["h"]: r for r in read_jsonl(WORK / "armB_parse.jsonl")}
    res, fails = {}, []
    by = defaultdict(list)
    for r in rows:
        by[r["corpus"]].append(r)
    for corp, rs in by.items():
        rs = [r for r in rs if canon.get(sha1(r["candidate_fol"] or ""), {}).get("ds_ok")][:30]
        c = Counter()
        for r in rs:
            h = sha1(r["candidate_fol"] or "")
            c["roundtrip"] += bool(canon[h].get("roundtrip_same_ast"))
            c["armA_canon"] += bool(pa[h]["armA_ok_canon"])
            c["armB_canon"] += bool(pb[h]["armB_ok_canon"])
            if not (pa[h]["armA_ok_canon"] and pb[h]["armB_ok_canon"]):
                fails.append({"raw": r["candidate_fol"][:120], "canon": canon[h]["canon"][:120],
                              "armA": pa[h]["armA_err_canon"], "armB": pb[h]["armB_err_canon"]})
        res[corp] = {"n": len(rs), **c}
    ok = all(v["roundtrip"] == v["n"] for v in res.values())
    return ok, {"per_corpus": res, "worst_failures": fails[:10]}


def t_auc():
    """(b) weighted AUROC == sklearn(sample_weight) == pairwise to 1e-9; soft labels in {0,1} == hard AUROC."""
    from sklearn.metrics import roc_auc_score
    rng = np.random.default_rng(1)
    diffs = []
    for _ in range(20):
        n = rng.integers(20, 300)
        y = rng.integers(0, 2, n)
        s = np.round(rng.random(n), 1)
        w = rng.random(n) * 3
        a = wauc(y, s, w)
        diffs.append(max(abs(a - roc_auc_score(y, s, sample_weight=w)), abs(a - wauc_pairwise(y, s, w)),
                         abs(soft_auc(y.astype(float), s) - wauc(y, s))))
    return max(diffs) < 1e-9, {"max_absdiff": max(diffs)}


def t_boot():
    """(c) stratified sentence bootstrap keeps each stratum's sentence count."""
    sids = [f"s{i // 3}" for i in range(300)]
    strata = {f"s{j}": ("A" if j < 40 else "B") for j in range(100)}
    b = StratBoot(sids, strata, n=50)
    ok = True
    for idx in b:
        picked = [sids[i] for i in idx]
        per = Counter(strata[s] for s in picked)
        ok &= per["A"] == 40 * 3 and per["B"] == 60 * 3
    return ok, {"strata": b.by_stratum}


def t_lc_toy():
    """(d) toy LC: 3 sentences x 3 systems through latent_class.em -> posteriors in [0,1], classes consistent."""
    code = r'''
import sys, json
sys.path.insert(0, "vendor/armB/src")
import latent_class as lc
ss = {"sentences": [{"sid": f"t{i}", "tercile": 0} for i in range(3)],
      "real_items": [{"item_id": f"t{i}:{s}", "sid": f"t{i}", "system": s, "parse_ok": True} for i in range(3) for s in "abc"]}
pairs = {"t0": {"a|b": {"bij": "equiv"}, "a|c": {"bij": "equiv"}, "b|c": {"bij": "equiv"}},
         "t1": {"a|b": {"bij": "equiv"}, "a|c": {"bij": "nonequiv"}, "b|c": {"bij": "nonequiv"}},
         "t2": {"a|b": {"bij": "nonequiv"}, "a|c": {"bij": "nonequiv"}, "b|c": {"bij": "nonequiv"}}}
obs = lc.build_obs(ss, pairs, "bij")
fit = lc.em(obs, ["a", "b", "c"])
post = [{str(k): v for k, v in p.items()} for p in fit["post"]]
cls = [ob["cls"] for ob in obs]
print(json.dumps({"post": post, "cls": cls}))
'''
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    d = json.loads(r.stdout.strip().splitlines()[-1])
    ok = all(0 <= v <= 1 for p in d["post"] for v in p.values())
    ok &= d["cls"][0]["a"] == d["cls"][0]["b"] == d["cls"][0]["c"]
    ok &= d["cls"][1]["a"] == d["cls"][1]["b"] != d["cls"][1]["c"]
    ok &= len(set(d["cls"][2].values())) == 3
    return ok, d


def t_prompt():
    """(e) B1 prompt equals the frozen Arm B template; request differs from b1_request_example only in content and
    the documented max_tokens (16 vs 8)."""
    import llm_stages as L
    pf = json.loads((ROOT / "vendor" / "armB" / "results" / "prompts_frozen.json").read_text())
    ex = json.loads((ROOT / "vendor" / "armB" / "results" / "b1_request_example.json").read_text())
    mine = {**L.b1_body("x", "y"), "usage": {"include": True}}
    diff = {k for k in set(ex) | set(mine) if k != "messages" and ex.get(k) != mine.get(k)}
    ok = L.B1_PROMPT == pf["B1_PROMPT"] and diff == {"max_tokens"}
    ok &= ex["messages"][0]["content"] == L.B1_PROMPT.format(s="Some evergreens are not objects of worship.",
                                                            f="∃x (Evergreen(x) ∧ ¬ObjectOfWorship(x))")
    return ok, {"sha1_B1_PROMPT": sha1(L.B1_PROMPT), "request_diff_keys": sorted(diff)}


def main():
    out, all_ok = {}, True
    for name, fn in (("a_adapter_roundtrip", t_adapter), ("b_weighted_auc", t_auc), ("c_strat_bootstrap", t_boot),
                     ("d_toy_latent_class", t_lc_toy), ("e_b1_prompt_request", t_prompt)):
        try:
            ok, info = fn()
        except Exception as e:  # noqa: BLE001 - reported as failure
            ok, info = False, {"error": repr(e)}
        out[name] = {"pass": bool(ok), "info": info}
        all_ok &= bool(ok)
        print(f"{name}: {'PASS' if ok else 'FAIL'}")
    out["all_pass"] = all_ok
    (ROOT / "results" / "unit_tests.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
