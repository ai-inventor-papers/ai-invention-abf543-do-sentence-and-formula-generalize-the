#!/usr/bin/env python3
"""Arm A worker (vendor/armA + vendor/armA/src ONLY on sys.path in this interpreter).

Subcommands
  parsecheck : Arm A fol_parse.parse on raw and canon strings              -> work/armA_parse.jsonl
  score      : method.signature_faithfulness(text, fol, variant) for A3 / A0 / Ccov (zero-LLM) and, when a cached
               probe answer exists for the sentence, A1. The vendored function is called UNCHANGED; only two
               module attributes are wrapped with memoisation (re-wiring logged in results/deviations.json):
                 * solver_sig.signature   -> cached per canonical formula AST (pure function of the AST)
                 * method._text_side      -> cached per (sentence, variant); for A1 the LLM call inside it is
                   replaced by the cached probe answer produced by src/llm_stages.py with the SAME prompt
                   (text_sig.render_prompt(text_sig.probe_questions(extract(text)))) and the same
                   request params (gemini-2.5-flash, reasoning max_tokens 1024, max_tokens 4000), built exactly
                   as the iter-1 screen probe (run_text.stage_probe: with_rel=True, >40 questions -> 2 chunks).
  probes     : write the A1 probe prompts per sentence                     -> work/a1_prompts.jsonl
  preflight  : recompute A3/A0 on 50 screen real items from Arm A data/screen_set.json vs results/screen_scores.jsonl
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import signal
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("NLTK_DATA", str(ROOT / ".nltk_data"))
AROOT = ROOT / "vendor" / "armA"
sys.path.insert(0, str(AROOT / "src"))
sys.path.insert(0, str(AROOT))
WORK = ROOT / "work"
SIG_TIMEOUT_S = 120


def jl(p):
    p = Path(p)
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


class _Timeout(Exception):
    pass


def _alarm(signum, frame):
    raise _Timeout()


_PATCHED = {"done": False}
_A1_ANS: dict = {}


def _patch():
    """Memoise the pure helpers of the vendored code path (see module docstring)."""
    if _PATCHED["done"]:
        return
    import method
    import solver_sig
    import text_sig
    orig_sig = solver_sig.signature
    sig_cache: dict = {}

    def cached_signature(ast, N=3, timeout_ms=5000, with_rel=True, rel_max_unary=8):
        k = (ast, N, timeout_ms, with_rel, rel_max_unary)
        if k not in sig_cache:
            sig_cache[k] = orig_sig(ast, N=N, timeout_ms=timeout_ms, with_rel=with_rel, rel_max_unary=rel_max_unary)
        return sig_cache[k]
    solver_sig.signature = cached_signature
    orig_ts = method._text_side
    ts_cache: dict = {}

    def cached_text_side(text, variant):
        k = (text, variant if variant in ("A1", "A2") else "A3")
        if k in ts_cache:
            return ts_cache[k]
        if variant in ("A1", "A2"):
            ex = text_sig.extract(text)
            # the iter-1 SCREEN probe (run_text.stage_probe): with_rel=True questions, split in two chunks if > 40,
            # answers merged with the chunk offset; concept labels via labels_from_answers (unchanged)
            qs = text_sig.probe_questions(ex, with_rel=True)
            ans = _A1_ANS.get(text)
            if ans is None:
                raise KeyError("no cached A1 probe answer")
            T = text_sig.labels_from_answers(ex, qs, {int(k): v for k, v in ans.items()})
            val = (ex, {"labels": T["concept_labels"], "anchors": ex["anchors"],
                        "rel": T["rel_labels"] if variant == "A2" else {}})
        else:
            val = orig_ts(text, variant)
        ts_cache[k] = val
        return val
    method._text_side = cached_text_side
    _PATCHED["done"] = True


_WARM = {"done": False}


def _warm():
    """Load spaCy, WordNet and MiniLM ONCE per process outside the per-item timeout (the workspace filesystem is
    slow to read model files; a cold load inside the alarm window made items time out in the first pre-flight)."""
    if _WARM["done"]:
        return
    import text_sig
    from align import _embed
    from nltk.stem import WordNetLemmatizer
    text_sig.nlp()("All dogs bark.")
    WordNetLemmatizer().lemmatize("dogs")
    _embed(["warm up"])
    _WARM["done"] = True


def _score_batch(batch: list[dict], variants: list[str], a1_answers: dict) -> list[dict]:
    os.environ["CUDA_VISIBLE_DEVICES"] = ""  # MiniLM (aligner fallback) on CPU inside the pool
    from loguru import logger
    logger.remove()
    _A1_ANS.update(a1_answers)
    _patch()
    import method
    _warm()
    signal.signal(signal.SIGALRM, _alarm)
    out = []
    for it in batch:
        for v in variants:
            if v == "A1" and it["sentence"] not in _A1_ANS:
                continue
            t0 = time.time()
            signal.alarm(SIG_TIMEOUT_S)
            try:
                r = method.signature_faithfulness(it["sentence"], it["fol"], v)
                signal.alarm(0)
                rec = {"key": it["key"], "metric": v, "score": float(r.get("score", 0.5)),
                       "covered": bool(r.get("covered", False)), "raw_score": r.get("raw_score"),
                       "error_type_pred": r.get("error_type_pred"), "why_uncovered": r.get("why_uncovered", r.get("error")),
                       "coverage": r.get("coverage"), "n_coords": r.get("n_coords"),
                       "mismatches": [{k: (str(x) if not isinstance(x, (int, float, str, bool, type(None))) else x)
                                       for k, x in m.items()} for m in (r.get("mismatches") or [])[:10]],
                       "seconds": round(time.time() - t0, 4)}
                if v == "Ccov":
                    rec["score"] = float(r.get("score", 0.5))
            except _Timeout:
                rec = {"key": it["key"], "metric": v, "score": 0.5, "covered": False, "raw_score": None,
                       "error_type_pred": "other", "why_uncovered": f"timeout>{SIG_TIMEOUT_S}s",
                       "seconds": round(time.time() - t0, 4)}
            except Exception as e:  # noqa: BLE001 - uncovered, recorded
                signal.alarm(0)
                rec = {"key": it["key"], "metric": v, "score": 0.5, "covered": False, "raw_score": None,
                       "error_type_pred": "other", "why_uncovered": f"error:{type(e).__name__}:{str(e)[:80]}",
                       "seconds": round(time.time() - t0, 4)}
            out.append(rec)
    return out


def cmd_score(items_file: str, out_file: str, variants: list[str], workers: int, a1_raw: str = "a1_raw.jsonl",
              rename: str | None = None):
    """rename: store variant 'A1' under another metric name (e.g. 'A1L' when the probe was answered locally)."""
    items = jl(WORK / items_file)
    outp = WORK / out_file
    ren = (lambda m: rename if (rename and m == "A1") else m)
    have = {(r["key"], r["metric"]) for r in jl(outp)}
    a1 = {}
    if "A1" in variants:
        import text_sig  # Arm A interpreter: parse the cached probe replies exactly like run_text.stage_probe
        for r in jl(WORK / a1_raw):
            ans = {}
            for ch in r.get("chunks") or []:
                for k, v in text_sig.parse_answers(ch["text"]).items():
                    ans[k + ch["offset"]] = v
            if r.get("chunks"):
                a1[r["sentence"]] = ans
    todo = [it for it in items if any((it["key"], ren(v)) not in have for v in variants if v != "A1" or it["sentence"] in a1)]
    # group by sentence so each process reuses the text side
    by_s: dict = {}
    for it in todo:
        by_s.setdefault(it["sentence"], []).append(it)
    groups = list(by_s.values())
    batches, cur = [], []
    for g in groups:
        cur += g
        if len(cur) >= 30:
            batches.append(cur)
            cur = []
    if cur:
        batches.append(cur)
    print(f"armA score: {len(items)} items, {len(todo)} to score in {len(batches)} batches; variants={variants}",
          flush=True)
    t0 = time.time()
    n = 0
    with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn")) as ex, \
            open(outp, "a", encoding="utf-8") as f:
        futs = [ex.submit(_score_batch, b, variants, {s: a1[s] for s in {x["sentence"] for x in b} if s in a1})
                for b in batches]
        for fu in as_completed(futs):
            try:
                rs = fu.result()
            except Exception as e:  # noqa: BLE001
                print(f"batch failed: {e!r}", flush=True)
                continue
            for r in rs:
                r["metric"] = ren(r["metric"])
                if (r["key"], r["metric"]) not in have:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            n += 1
            if n % 20 == 0:
                print(f"armA batches {n}/{len(batches)} {time.time() - t0:.0f}s", flush=True)
    print(f"armA score done in {time.time() - t0:.0f}s", flush=True)


def cmd_parsecheck():
    from fol_parse import ParseError, parse
    out = []
    for r in jl(WORK / "canon.jsonl"):
        res = {"h": r["h"]}
        for tag, s in (("raw", r["raw"]), ("canon", r["canon"])):
            ok, err = False, ""
            if s:
                try:
                    parse(s)
                    ok = True
                except (ParseError, RecursionError, IndexError) as e:
                    err = str(e)[:80]
            else:
                err = "empty"
            res[f"armA_ok_{tag}"], res[f"armA_err_{tag}"] = ok, err
        out.append(res)
    with open(WORK / "armA_parse.jsonl", "w", encoding="utf-8") as f:
        for o in out:
            f.write(json.dumps(o) + "\n")
    print(f"armA parsecheck {len(out)}", flush=True)


def cmd_probes():
    import text_sig
    sents = jl(WORK / "a1_sentences.jsonl")
    out = []
    for s in sents:
        ex = text_sig.extract(s["sentence"])
        qs = text_sig.probe_questions(ex, with_rel=True)
        chunks = [qs] if len(qs) <= 40 else [qs[: (len(qs) + 1) // 2], qs[(len(qs) + 1) // 2:]]
        prompts = [{"offset": 0 if ci == 0 else (len(qs) + 1) // 2, "prompt": text_sig.render_prompt(ch)}
                   for ci, ch in enumerate(chunks) if ch]
        out.append({"sentence": s["sentence"], "n_q": len(qs), "prompts": prompts})
    with open(WORK / "a1_prompts.jsonl", "w", encoding="utf-8") as f:
        for o in out:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
    print(f"probes {len(out)} sentences; no-question={sum(not o['prompts'] for o in out)}", flush=True)


def cmd_preflight(n: int):
    A = Path("../../../../../../round-1/experiment-1/src")
    d = json.loads((A / "data" / "screen_set.json").read_text())
    S = {s["sid"]: s for s in d["sentences"]}
    ref = {}
    for r in jl(A / "results" / "screen_scores.jsonl"):
        if r["set"] == "real" and r["metric"] in ("A3", "A0"):
            ref[(r["item_id"], r["metric"])] = r
    reals = sorted(d["real"], key=lambda r: r["item_id"])[:n]
    items = [{"key": r["item_id"], "sentence": S[r["sid"]]["nl"], "fol": r["cand_fol"]} for r in reals]
    rs = _score_batch(items, ["A3", "A0"], {})
    diffs = {"A3": [], "A0": []}
    detail = []
    for r in rs:
        rr = ref.get((r["key"], r["metric"]))
        if rr is None:
            continue
        dlt = abs(r["score"] - rr["score"])
        diffs[r["metric"]].append(dlt)
        if dlt > 1e-9:
            detail.append({"item": r["key"], "metric": r["metric"], "mine": r["score"], "iter1": rr["score"],
                           "cov_mine": r["covered"], "cov_iter1": rr["covered"]})
    res = {m: {"n": len(v), "max_abs_diff": max(v) if v else None, "share_exact": sum(x <= 1e-9 for x in v) / max(1, len(v)),
               "share_lt_0.01": sum(x < 0.01 for x in v) / max(1, len(v))} for m, v in diffs.items()}
    res["mismatch_detail"] = detail[:20]
    print(json.dumps(res)[:1500], flush=True)
    (WORK / "preflight_armA.json").write_text(json.dumps(res, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["parsecheck", "score", "probes", "preflight"])
    ap.add_argument("--items", default="armA_items.jsonl")
    ap.add_argument("--out", default="armA_scores.jsonl")
    ap.add_argument("--variants", default="A3,A0,Ccov")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--a1_raw", default="a1_raw.jsonl")
    ap.add_argument("--rename", default=None)
    a = ap.parse_args()
    if a.cmd == "parsecheck":
        cmd_parsecheck()
    elif a.cmd == "score":
        cmd_score(a.items, a.out, a.variants.split(","), a.workers, a.a1_raw, a.rename)
    elif a.cmd == "probes":
        cmd_probes()
    elif a.cmd == "preflight":
        cmd_preflight(a.n)


if __name__ == "__main__":
    main()
