#!/usr/bin/env python3
"""Arm B worker (vendor/armB/src ONLY on sys.path in this interpreter).

Subcommands
  parsecheck : fol_core.try_parse on raw and canon strings            -> work/armB_parse.jsonl
  pairs      : fol_core.find_bijections(a, b, wall_s=15) [+ label_trigram] for candidate pairs, sha1-cached,
               resumable, spawn ProcessPool                           -> work/pairs_cache.jsonl
  b7joint    : story-level joint satisfiability of each system's formulas (fol_core.satisfiable, nmax 3, 5 s)
  lc         : latent_class.run_latent_class VERBATIM on the 9-system greedy set; LC_within (6 rater slots of
               one system) + B8 self-consistency; LC_granular (post-hoc) -> work/lc_scores.jsonl, work/lc_info.json
  preflight  : recompute LC_onecoin on the iter-1 screen from Arm B data/{screen_set,candidate_pairs}.json and
               compare with Arm B results/screen_scores.jsonl
Frozen parameters: find_bijections defaults cap=5040, max_preds=8, nmax=4, timeout_ms=5000; wall_s=15 exactly as
build_screen.sentence_worker used for candidate pairs.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import multiprocessing as mp
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor" / "armB" / "src"))
WORK = ROOT / "work"


def jl(p):
    p = Path(p)
    if not p.exists():
        return []
    out = []
    for x in p.read_text(encoding="utf-8").splitlines():
        if x.strip():
            try:
                out.append(json.loads(x))
            except json.JSONDecodeError:
                pass
    return out


def pkey(a: str, b: str) -> str:
    return hashlib.sha1((a + "||" + b).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------------------------- parsecheck
def cmd_parsecheck():
    import fol_core as fc
    rows = jl(WORK / "canon.jsonl")
    out = []
    for r in rows:
        a_raw, e_raw = fc.try_parse(r["raw"]) if r["raw"] else (None, "empty")
        if r["canon"]:
            a_c, e_c = fc.try_parse(r["canon"])
        else:
            a_c, e_c = None, "no_canon"
        out.append({"h": r["h"], "armB_ok_raw": a_raw is not None, "armB_err_raw": e_raw,
                    "armB_ok_canon": a_c is not None, "armB_err_canon": e_c})
    with open(WORK / "armB_parse.jsonl", "w", encoding="utf-8") as f:
        for o in out:
            f.write(json.dumps(o) + "\n")
    print(json.dumps(Counter((o["armB_ok_raw"], o["armB_ok_canon"]) for o in out).most_common()
                     .__repr__()))


# --------------------------------------------------------------------------------------------- pairs
def _pair_worker(batch: list[tuple[str, str, str, bool]]) -> list[dict]:
    import fol_core as fc2
    res = []
    for key, a, b, want_str in batch:
        t0 = time.time()
        A, _ = fc2.try_parse(a)
        B, _ = fc2.try_parse(b)
        if A is None or B is None:
            res.append({"k": key, "bij": None, "reason": "unparseable", "str": None, "s": 0.0})
            continue
        try:
            r = fc2.find_bijections(A, B, wall_s=15)
            lab, reason = r["label"], r["reason"]
        except Exception as e:  # noqa: BLE001 - recorded as unlabeled, never silently dropped
            lab, reason = "unlabeled", f"error:{type(e).__name__}"
        st = None
        if want_str:
            try:
                st = fc2.label_trigram(A, B)["label"]
            except Exception as e:  # noqa: BLE001
                st = "unlabeled"
        res.append({"k": key, "bij": lab, "reason": reason, "str": st, "s": round(time.time() - t0, 4)})
    return res


def cmd_pairs(jobs_file: str, workers: int, want_str: bool, limit_s: float):
    cache_p = WORK / "pairs_cache.jsonl"
    have = {r["k"]: r for r in jl(cache_p)}
    jobs = jl(WORK / jobs_file)
    todo, seen = [], set()
    for j in jobs:
        k = pkey(j["a"], j["b"])
        if k in seen:
            continue
        seen.add(k)
        if k in have and (not want_str or have[k].get("str") is not None or have[k]["bij"] is None):
            continue
        todo.append((k, j["a"], j["b"], want_str))
    print(f"pairs: {len(jobs)} jobs, {len(seen)} unique, {len(todo)} to compute", flush=True)
    if not todo:
        return
    # batches of 20 pairs keep per-process parse caches warm and IPC small
    B = 20
    batches = [todo[i:i + B] for i in range(0, len(todo), B)]
    t0 = time.time()
    n_done = 0
    with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn")) as ex, \
            open(cache_p, "a", encoding="utf-8") as f:
        futs = [ex.submit(_pair_worker, b) for b in batches]
        for fu in as_completed(futs):
            try:
                rs = fu.result()
            except Exception as e:  # noqa: BLE001
                print(f"batch failed: {e!r}", flush=True)
                continue
            for r in rs:
                f.write(json.dumps(r) + "\n")
            f.flush()
            n_done += len(rs)
            if n_done % 2000 < B:
                el = time.time() - t0
                print(f"pairs {n_done}/{len(todo)} {el:.0f}s ({n_done / max(el, 1e-9):.1f}/s)", flush=True)
            if limit_s and time.time() - t0 > limit_s:
                print("time limit reached; cancelling remaining batches (resumable)", flush=True)
                for x in futs:
                    x.cancel()
                break
    print(f"pairs done {n_done} in {time.time() - t0:.0f}s", flush=True)


# --------------------------------------------------------------------------------------------- B7 joint
def _sat_worker(job):
    import fol_core as fc2
    key, fols = job
    asts = [fc2.try_parse(f)[0] for f in fols]
    asts = [a for a in asts if a is not None]
    if not asts:
        return key, "no_parseable"
    conj = ("and",) + tuple(asts) if len(asts) > 1 else asts[0]
    try:
        return key, fc2.satisfiable(conj, nmax=3, timeout_ms=5000)
    except Exception as e:  # noqa: BLE001
        return key, f"error:{type(e).__name__}"


def cmd_b7joint(workers: int):
    jobs = jl(WORK / "b7_jobs.jsonl")
    out = {}
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn")) as ex:
        futs = [ex.submit(_sat_worker, (j["key"], j["fols"])) for j in jobs]
        for fu in as_completed(futs):
            k, st = fu.result()
            out[k] = st
    (WORK / "b7_joint.json").write_text(json.dumps(out))
    print(f"b7joint {len(out)} in {time.time() - t0:.0f}s {Counter(out.values())}", flush=True)


# --------------------------------------------------------------------------------------------- LC
def _posterior_rows(obs, fit, metric: str, g: int = 0):
    rows = []
    for ob, po in zip(obs, fit["post"]):
        n_parse = sum(ob["parse_ok"].values())
        for s in ob["systems"]:
            cov = ob["parse_ok"][s] and n_parse >= 2
            sc = po.get(ob["cls"][s], 0.0) if ob["parse_ok"][s] else 0.0
            size = sum(1 for s2 in ob["systems"] if ob["parse_ok"][s2] and ob["cls"][s2] == ob["cls"][s])
            n_cls = len(ob["valid"])
            rows.append({"item_id": f"{ob['sid']}:{s}", "metric": metric, "score": sc, "covered": cov,
                         "cls_size": size if ob["parse_ok"][s] else 0, "n_classes": n_cls, "n_parse": n_parse,
                         "largest": max([sum(1 for s2 in ob["systems"] if ob["parse_ok"][s2] and ob["cls"][s2] == c)
                                         for c in ob["valid"]] or [0])})
    return rows


def _fit_info(fit, systems, g=0):
    return {"loglik": fit["ll"], "p_w": {s: fit["p"][(g, s)] for s in systems}, "pi": fit["pi"][g], "rho": fit["rho"],
            "iters": fit["iters"], "best_restart": fit["restart"],
            "degenerate": bool(any(fit["p"][(g, s)] > 0.99 for s in systems) or fit["pi"][g] < 0.02)}


def cmd_lc():
    import latent_class as lc
    spec = json.loads((WORK / "lc_input.json").read_text())
    cache = {r["k"]: r for r in jl(WORK / "pairs_cache.jsonl")}
    gran = {r["k"]: r for r in jl(WORK / "granular_cache.jsonl")}
    info, out = {}, []
    t0 = time.time()
    # ---------------- 9-system greedy LC (VERBATIM run_latent_class)
    ss = spec["ss"]
    pairs = {}
    missing = Counter()
    for sid, pl in spec["pairs"].items():
        d = {}
        for name, k in pl.items():
            r = cache.get(k)
            if r is None:
                missing["no_cache"] += 1
                continue
            d[name] = {"bij": r["bij"], "str": r.get("str")}
        pairs[sid] = d
    info["pairs_missing"] = dict(missing)
    rows, linfo = lc.run_latent_class(ss, pairs, [])
    info.update(linfo)
    out += [r for r in rows if r["metric"] != "B3sc"]
    print(f"run_latent_class done {time.time() - t0:.0f}s: {json.dumps(linfo.get('LC_onecoin'))[:300]}", flush=True)
    # class-structure extras for circularity test (c)
    systems = sorted({r["system"] for r in ss["real_items"]})
    obs = lc.build_obs(ss, pairs, "bij")
    struct = []
    for ob in obs:
        n_parse = sum(ob["parse_ok"].values())
        sizes = Counter(ob["cls"][s] for s in ob["systems"] if ob["parse_ok"][s])
        largest = max(sizes.values()) if sizes else 0
        for s in ob["systems"]:
            sz = sizes.get(ob["cls"][s], 0) if ob["parse_ok"][s] else 0
            struct.append({"item_id": f"{ob['sid']}:{s}", "cls_size": sz, "largest": largest, "n_parse": n_parse,
                           "n_classes": len(sizes), "singleton": sz == 1,
                           "minority": bool(ob["parse_ok"][s] and sz < largest)})
    (WORK / "lc_struct.jsonl").write_text("\n".join(json.dumps(x) for x in struct) + "\n")
    # ---------------- LC_granular (POST-HOC): bij-equiv OR granular-equiv in either direction
    pairs_g = {}
    n_touch = n_merge = 0
    for sid, pl in spec["pairs"].items():
        d = {}
        for name, k in pl.items():
            r = cache.get(k)
            if r is None:
                continue
            lab = r["bij"]
            g = gran.get(k)
            if g is not None:
                n_touch += 1
                if lab != "equiv" and g.get("merged"):
                    lab = "equiv"
                    n_merge += 1
            d[name] = {"gran": lab}
        pairs_g[sid] = d
    obs_g = lc.build_obs(ss, pairs_g, "gran")
    fit_g = lc.em(obs_g, systems)
    info["LC_granular"] = {**_fit_info(fit_g, systems), "pairs_touched": n_touch, "pairs_merged": n_merge,
                           "label": "post-hoc; never used for CONFIRM"}
    out += [{k: v for k, v in r.items() if k in ("item_id", "metric", "score", "covered")}
            for r in _posterior_rows(obs_g, fit_g, "LC_granular")]
    print(f"LC_granular done: touched {n_touch} merged {n_merge}", flush=True)
    # ---------------- LC_within + B8 (per sample system; raters = greedy + 5 samples)
    for sysn, w in spec.get("within", {}).items():
        wss = w["ss"]
        wpairs = {}
        for sid, pl in w["pairs"].items():
            wpairs[sid] = {name: {"bij": cache[k]["bij"]} for name, k in pl.items() if k in cache}
        raters = sorted({r["system"] for r in wss["real_items"]})
        wobs = lc.build_obs(wss, wpairs, "bij")
        fit = lc.em(wobs, raters)
        info[f"LC_within:{sysn}"] = _fit_info(fit, raters)
        for ob, po in zip(wobs, fit["post"]):
            n_parse = sum(ob["parse_ok"].values())
            s = "greedy"
            cov = ob["parse_ok"][s] and n_parse >= 2
            sc = po.get(ob["cls"][s], 0.0) if ob["parse_ok"][s] else 0.0
            out.append({"item_id": f"{ob['sid']}:{sysn}", "metric": "LC_within", "score": sc, "covered": cov})
            # B8 = (# samples bij-equivalent to greedy) / (# parseable samples); uncovered -> 0.5
            samp = [x for x in ob["systems"] if x != "greedy"]
            ps = [x for x in samp if ob["parse_ok"][x]]
            if not ob["parse_ok"][s] or not ps:
                out.append({"item_id": f"{ob['sid']}:{sysn}", "metric": "B8", "score": 0.5, "covered": False,
                            "n_samples_parse": len(ps)})
            else:
                eq = 0
                for x in ps:
                    a, b = sorted([s, x])
                    k = w["pairs"].get(ob["sid"], {}).get(f"{a}|{b}")
                    if k in cache and cache[k]["bij"] == "equiv":
                        eq += 1
                out.append({"item_id": f"{ob['sid']}:{sysn}", "metric": "B8", "score": eq / len(ps), "covered": True,
                            "n_samples_parse": len(ps)})
        print(f"LC_within {sysn} done", flush=True)
    with open(WORK / "lc_scores.jsonl", "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r) + "\n")
    info["seconds"] = time.time() - t0
    (WORK / "lc_info.json").write_text(json.dumps(info, indent=1, default=str))
    print(f"lc done {len(out)} rows {time.time() - t0:.0f}s", flush=True)


# --------------------------------------------------------------------------------------------- preflight
def cmd_preflight():
    import latent_class as lc
    B = Path("../../../../../../round-1/experiment-2/src")
    ss = json.loads((B / "data" / "screen_set.json").read_text())
    pairs = json.loads((B / "data" / "candidate_pairs.json").read_text())
    rows, info = lc.run_latent_class(ss, pairs, [])
    ref = {}
    for r in jl(B / "results" / "screen_scores.jsonl"):
        if r["metric"] in ("LC_onecoin", "LC_maj", "LC_huiwalter", "LC_onecoin_str"):
            ref[(r["item_id"], r["metric"])] = r["score"]
    diffs = defaultdict(list)
    for r in rows:
        k = (r["item_id"], r["metric"])
        if k in ref:
            mine = r["score"] if r["covered"] or r["metric"] != "x" else r["score"]
            # iter-1 row() stored 0.5 for uncovered items; compare like with like
            mine = r["score"] if r["covered"] else 0.5
            diffs[r["metric"]].append(abs(mine - ref[k]))
    res = {m: {"n": len(v), "max_abs_diff": max(v) if v else None,
               "share_le_1e-6": sum(x <= 1e-6 for x in v) / len(v) if v else None} for m, v in diffs.items()}
    res["info_LC_onecoin_pw"] = info["LC_onecoin"]["p_w"]
    print(json.dumps(res))
    (WORK / "preflight_lc.json").write_text(json.dumps(res, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["parsecheck", "pairs", "b7joint", "lc", "preflight"])
    ap.add_argument("--jobs", default="pair_jobs.jsonl")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--want_str", action="store_true")
    ap.add_argument("--limit_s", type=float, default=0.0)
    a = ap.parse_args()
    if a.cmd == "parsecheck":
        cmd_parsecheck()
    elif a.cmd == "pairs":
        cmd_pairs(a.jobs, a.workers, a.want_str, a.limit_s)
    elif a.cmd == "b7joint":
        cmd_b7joint(a.workers)
    elif a.cmd == "lc":
        cmd_lc()
    elif a.cmd == "preflight":
        cmd_preflight()


if __name__ == "__main__":
    main()
