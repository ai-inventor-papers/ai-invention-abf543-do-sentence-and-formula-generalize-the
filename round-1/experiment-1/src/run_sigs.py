#!/usr/bin/env python3
"""STEP 2 + B7: solver signatures (sig_abs, anchors, sig_rel) for every formula in the screen set
(gold, original gold, parseable real candidates, mutants, rewrites), cached by canonical string, plus the
B7 structural features (arity consistency vs Logic-LM's declared predicates, undefined predicates,
story-level joint satisfiability of each system's premises).
Output: results/formula_sigs.json, results/b7_structural.json
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
from fol_parse import ParseError, parse, to_str  # noqa: E402

logger.remove()
logger.add(sys.stdout, level="INFO", format="{time:HH:mm:ss}|{level:<7}|{message}")
logger.add(ROOT / "logs" / "run_sigs.log", rotation="30 MB", level="DEBUG")


def _sig_worker(fol: str):
    sys.path.insert(0, str(ROOT / "src"))
    from fol_parse import parse as p_
    from solver_sig import signature
    try:
        ast = p_(fol).ast
        return fol, signature(ast, N=3, timeout_ms=5000, with_rel=True, rel_max_unary=8)
    except Exception as e:  # noqa: BLE001
        return fol, {"error": f"{type(e).__name__}: {e}"}


def _sat_worker(args):
    sys.path.insert(0, str(ROOT / "src"))
    from fol_parse import parse as p_
    from labeler import satisfiable
    key, fols = args
    asts = []
    n_bad = 0
    for f in fols:
        try:
            asts.append(p_(f).ast)
        except Exception:  # noqa: BLE001
            n_bad += 1
    if not asts:
        return key, "no_parseable", n_bad
    conj = ("and", tuple(asts)) if len(asts) > 1 else asts[0]
    try:
        return key, satisfiable(conj, N=3), n_bad
    except Exception as e:  # noqa: BLE001
        return key, f"error:{e}", n_bad


@logger.catch(reraise=True)
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--screen", default=str(ROOT / "data" / "screen_set.json"))
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--out", default=str(ROOT / "results" / "formula_sigs.json"))
    a = ap.parse_args()
    d = json.loads(Path(a.screen).read_text())
    fols = set()
    for s in d["sentences"]:
        fols.add(s["gold_fol"])
        if s.get("gold_fol_orig"):
            fols.add(s["gold_fol_orig"])
    for r in d["real"]:
        if r["parse_ok"]:
            fols.add(r["cand_fol"])
    for m in d["mutants"]:
        fols.add(m["fol"])
    for rw in d["rewrites"]:
        fols.add(rw["fol"])
    outp = Path(a.out)
    cache = json.loads(outp.read_text()) if outp.exists() else {}
    todo = sorted(f for f in fols if f not in cache)
    logger.info(f"{len(fols)} formulas, {len(todo)} to compute")
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=a.workers, mp_context=mp.get_context("spawn")) as ex:
        futs = [ex.submit(_sig_worker, f) for f in todo]
        for i, fu in enumerate(as_completed(futs)):
            try:
                f, sig = fu.result(timeout=600)
                cache[f] = sig
            except Exception as e:  # noqa: BLE001
                logger.error(f"sig failed: {e}")
            if (i + 1) % 200 == 0:
                logger.info(f"sigs {i + 1}/{len(todo)} {time.time() - t0:.0f}s")
                outp.write_text(json.dumps(cache, ensure_ascii=False))
    outp.write_text(json.dumps(cache, ensure_ascii=False))
    secs = [v.get("seconds", 0) for v in cache.values() if "seconds" in v]
    logger.info(f"sigs done in {time.time() - t0:.0f}s; errors={sum(1 for v in cache.values() if 'error' in v)} "
                f"mean_s={sum(secs) / max(1, len(secs)):.2f} unknown_total={sum(v.get('n_unknown', 0) for v in cache.values())}")

    # ---- B7 structural
    raw = ROOT / "data" / "raw"
    sys.path.insert(0, str(ROOT))
    from build_screen_set import parse_logic_program
    jobs = []
    for sysn in ("gpt-3.5-turbo", "gpt-4", "text-davinci-003"):
        data = json.loads((raw / f"FOLIO_dev_{sysn}.json").read_text())
        for e in data:
            k = int(e["id"].split("_")[-1])
            prog = parse_logic_program(e["raw_logic_programs"][0])
            prem = [ln["fol"] for ln in prog["lines"] if ln["kind"] == "Premises"]
            jobs.append((f"{sysn}|{k}", prem))
    story_sat = {}
    with ProcessPoolExecutor(max_workers=a.workers, mp_context=mp.get_context("spawn")) as ex:
        for fu in as_completed([ex.submit(_sat_worker, j) for j in jobs]):
            key, st, nb = fu.result()
            story_sat[key] = {"status": st, "n_unparseable_premises": nb}
    b7 = {}
    for r in d["real"]:
        decl = {p["name"]: p["arity"] for p in r["declared_preds"]}
        used = {}
        if r["parse_ok"]:
            used = parse(r["cand_fol"]).preds
        arity_ok = all(decl.get(p.split("#")[0]) in (None, k) for p, k in used.items()) and \
            not any("#" in p for p in used)
        undefined = [p for p in used if p.split("#")[0] not in decl]
        ss = story_sat.get(f"{r['system']}|{r['cand_story']}", {}).get("status")
        joint = ss == "sat"
        b7[r["item_id"]] = {"arity_consistent": bool(arity_ok and r["parse_ok"]), "n_undefined": len(undefined),
                            "story_joint_sat": joint, "story_sat_status": ss,
                            "b7": int(bool(arity_ok and r["parse_ok"]) and len(undefined) == 0 and joint)}
    (ROOT / "results" / "b7_structural.json").write_text(json.dumps({"items": b7, "story_sat": story_sat}, indent=1))
    logger.info(f"B7: {Counter(v['b7'] for v in b7.values())} story_sat={Counter(v['status'] for v in story_sat.values())}")


if __name__ == "__main__":
    main()
