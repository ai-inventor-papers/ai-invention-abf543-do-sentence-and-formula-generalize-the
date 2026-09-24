#!/usr/bin/env python3
"""STEP 5 ($0; not labels, may run before the freeze): fresh frame, DC relation cache, frozen neighbours.

Subcommands
  frame   : work/fresh_frame.jsonl, one row per fresh output (9 x greedy + 2 x 5 samples)
  dcpairs : DC config-agnostic relation cache for fresh greedy pairs + within-system pairs (src/pairs.py)
  lcpairs : FROZEN round-2 LC pair labels: Arm B fol_core.find_bijections(wall_s=15) on the round-2 input strings
            (dataset-parser canon, else raw), exactly as vendor/r2/workers/armB.py _pair_worker
  lc      : FROZEN latent_class.run_latent_class (LC_onecoin, LC_maj, LC_ds_binary, LC_huiwalter) + LC_within/B8
  b7      : B7 structural metric port (vendor/r2/src/pipeline.py build_b7) + B7_jacc; B2 parse
  vc      : vocabulary-conformity control VC
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import itertools
import json
import multiprocessing as mp
import re
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed

from loguru import logger

from common import RES, ROOT, SAMPLE_SYSTEMS, SYSTEMS, WORK, read_jsonl, setup_logging, write_jsonl

ARMB = ROOT / "vendor" / "r2" / "armB"
FR = WORK / "fresh_frame.jsonl"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------------------------------------ frame
def cmd_frame() -> None:
    from dc import canon, parse_fol
    from fol_parse import parse as vparse, to_str
    sents = {s["sid"]: s for s in json.loads((RES / "fresh_sentences.json").read_text())}
    out = []
    for sysn in SYSTEMS:
        seen = set()
        recs = read_jsonl(WORK / "generations" / f"{sysn}.jsonl")
        for r in recs:
            key = (r["sid"], r["sample_idx"])
            if key in seen:
                continue
            seen.add(key)
            s = sents[r["sid"]]
            cand = r.get("candidate_fol") or ""
            ast = parse_fol(cand)
            pr = vparse(cand) if cand else None
            r2c = to_str(pr.ast) if (pr is not None and pr.ok) else cand
            out.append({"item_id": f"{r['sid']}:{sysn}:{r['sample_idx']}", "sid": r["sid"], "sentence": s["sentence"],
                        "system": sysn, "model": r["model"], "sample_idx": r["sample_idx"],
                        "fold": "fresh_greedy" if r["sample_idx"] == 0 else "fresh_samples",
                        "raw_output": r["raw_output"], "cand": cand, "parse_ok_dataset_parser": bool(r["parse_ok"]),
                        "parse_ok": ast is not None, "canon": canon(ast) if ast is not None else None, "r2canon": r2c,
                        "provider": r["provider"], "finish_reason": r["finish_reason"], "gen_usd": r["gen_usd"],
                        "gen_seconds": r["gen_seconds"], "prompt_sha1": r["prompt_sha1"], "api_error": r.get("api_error"),
                        "corpus": s["corpus"], "corpus_subset": s["corpus_subset"], "story_id": s["story_id"],
                        "source_id": s["source_id"], "tercile": s["complexity_tercile"],
                        **{k: s[k] for k in ("n_tokens", "n_quantifiers", "nesting_depth", "n_conditions",
                                             "complexity_composite")}})
    write_jsonl(FR, out)
    G = [r for r in out if r["fold"] == "fresh_greedy"]
    logger.info(f"fresh frame {len(out)} rows; greedy {len(G)} ({Counter(r['system'] for r in G).most_common(2)}...); "
                f"greedy parse_ok {sum(r['parse_ok'] for r in G)}; samples {len(out) - len(G)}")


def frame():
    return read_jsonl(FR)


# ------------------------------------------------------------------------------------------------ DC pairs
def cmd_dcpairs(workers: int) -> None:
    import pairs
    rows = frame()
    by = defaultdict(dict)
    for r in rows:
        if r["fold"] == "fresh_greedy" and r["parse_ok"]:
            by[r["sid"]][r["system"]] = r["canon"]
    jobs = [(a, b) for g in by.values() for a, b in itertools.combinations(list(g.values()), 2)]
    wg = defaultdict(list)
    for r in rows:
        if r["system"] in SAMPLE_SYSTEMS and r["parse_ok"]:
            wg[(r["sid"], r["system"])].append(r["canon"])
    wjobs = [(a, b) for cs in wg.values() for a, b in itertools.combinations(cs, 2)]
    logger.info(f"DC fresh pair jobs: greedy {len(jobs)}, within {len(wjobs)}")
    st = pairs.run(jobs + wjobs, workers=workers, log=logger.info)
    (WORK / "fresh_pairs_stats.json").write_text(json.dumps(st))


# ------------------------------------------------------------------------------------------------ LC (frozen)
def _lc_worker(batch):
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (6 * 1024 ** 3, 6 * 1024 ** 3))
    sys.path.insert(0, str(ARMB))
    import fol_core as fc2
    res = []
    for key, a, b in batch:
        t0 = time.time()
        A, _ = fc2.try_parse(a)
        B, _ = fc2.try_parse(b)
        if A is None or B is None:
            res.append({"k": key, "bij": None, "reason": "unparseable", "str": None, "s": 0.0})
            continue
        try:
            r = fc2.find_bijections(A, B, wall_s=15)
            lab, reason = r["label"], r["reason"]
        except Exception as e:  # noqa: BLE001 - recorded as unlabeled, never silently dropped (frozen behaviour)
            lab, reason = "unlabeled", f"error:{type(e).__name__}"
        res.append({"k": key, "bij": lab, "reason": reason, "str": None, "s": round(time.time() - t0, 4)})
    return res


def _armb_ok_map(strings: set[str]) -> dict:
    sys.path.insert(0, str(ARMB))
    import fol_core as fc
    return {s: fc.try_parse(s)[0] is not None for s in strings}


def _pk(a, b):
    return hashlib.sha1((a + "||" + b).encode("utf-8")).hexdigest()


def _lc_spec(rows):
    ok = _armb_ok_map({r["r2canon"] for r in rows if r["r2canon"]})
    G = [r for r in rows if r["fold"] == "fresh_greedy"]
    by = defaultdict(dict)
    for r in G:
        by[r["sid"]][r["system"]] = r
    terc = {"bottom": 0, "middle": 1, "top": 2}
    ss = {"sentences": [{"sid": s, "tercile": terc[next(iter(by[s].values()))["tercile"]]} for s in sorted(by)],
          "real_items": []}
    pairs_spec, jobs = {}, []
    aok = lambda r: bool(r["r2canon"]) and ok.get(r["r2canon"], False)  # noqa: E731
    for sid in sorted(by):
        items = by[sid]
        systems = sorted(items)
        for sysn in systems:
            ss["real_items"].append({"item_id": f"{sid}:{sysn}", "sid": sid, "system": sysn, "parse_ok": aok(items[sysn])})
        pl = {}
        for i, j in itertools.combinations(range(len(systems)), 2):
            a, b = items[systems[i]], items[systems[j]]
            if not (aok(a) and aok(b)):
                continue
            k = _pk(a["r2canon"], b["r2canon"])
            pl[f"{systems[i]}|{systems[j]}"] = k
            jobs.append((k, a["r2canon"], b["r2canon"]))
        pairs_spec[sid] = pl
    samples = defaultdict(dict)
    for r in rows:
        if r["fold"] == "fresh_samples":
            samples[(r["sid"], r["system"])][f"s{r['sample_idx']}"] = r
    within = {}
    for sysn in SAMPLE_SYSTEMS:
        wss = {"sentences": ss["sentences"], "real_items": []}
        wp = {}
        for sid in sorted(by):
            if sysn not in by[sid]:
                continue
            raters = {"greedy": by[sid][sysn], **samples.get((sid, sysn), {})}
            names = sorted(raters)
            for n in names:
                wss["real_items"].append({"item_id": f"{sid}:{n}", "sid": sid, "system": n, "parse_ok": aok(raters[n])})
            pl = {}
            for i, j in itertools.combinations(range(len(names)), 2):
                a, b = raters[names[i]], raters[names[j]]
                if not (aok(a) and aok(b)):
                    continue
                k = _pk(a["r2canon"], b["r2canon"])
                pl[f"{names[i]}|{names[j]}"] = k
                jobs.append((k, a["r2canon"], b["r2canon"]))
            wp[sid] = pl
        within[sysn] = {"ss": wss, "pairs": wp}
    return {"ss": ss, "pairs": pairs_spec, "within": within}, jobs


def cmd_lcpairs(workers: int) -> None:
    rows = frame()
    spec, jobs = _lc_spec(rows)
    (WORK / "lc_input_fresh.json").write_text(json.dumps(spec))
    cache_p = WORK / "lc_pairs_cache.jsonl"
    have = {r["k"] for r in read_jsonl(cache_p)}
    todo, seen = [], set()
    for k, a, b in jobs:
        if k in seen or k in have:
            continue
        seen.add(k)
        todo.append((k, a, b))
    logger.info(f"LC pairs: {len(jobs)} jobs, {len(todo)} to compute")
    B = 20
    batches = [todo[i:i + B] for i in range(0, len(todo), B)]
    t0 = time.time()
    n = 0
    with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn")) as ex, \
            open(cache_p, "a", encoding="utf-8") as f:
        futs = [ex.submit(_lc_worker, b) for b in batches]
        for fu in as_completed(futs):
            for r in fu.result():
                f.write(json.dumps(r) + "\n")
                n += 1
            f.flush()
    logger.info(f"LC pairs done {n} in {time.time() - t0:.0f}s")


def cmd_lc() -> None:
    sys.path.insert(0, str(ARMB))
    lc = _load("latent_class", ARMB / "latent_class.py")
    spec = json.loads((WORK / "lc_input_fresh.json").read_text())
    cache = {r["k"]: r for r in read_jsonl(WORK / "lc_pairs_cache.jsonl")}
    pairs = {}
    miss = 0
    for sid, pl in spec["pairs"].items():
        d = {}
        for name, k in pl.items():
            r = cache.get(k)
            if r is None:
                miss += 1
                continue
            d[name] = {"bij": r["bij"], "str": r.get("str")}
        pairs[sid] = d
    rows, info = lc.run_latent_class(spec["ss"], pairs, [])
    out = [r for r in rows if r["metric"] != "B3sc"]
    for sysn, w in spec["within"].items():
        wpairs = {sid: {name: {"bij": cache[k]["bij"]} for name, k in pl.items() if k in cache}
                  for sid, pl in w["pairs"].items()}
        raters = sorted({r["system"] for r in w["ss"]["real_items"]})
        wobs = lc.build_obs(w["ss"], wpairs, "bij")
        fit = lc.em(wobs, raters)
        for ob, po in zip(wobs, fit["post"]):
            if "greedy" not in ob["systems"]:
                continue
            n_parse = sum(ob["parse_ok"].values())
            s = "greedy"
            cov = ob["parse_ok"][s] and n_parse >= 2
            out.append({"item_id": f"{ob['sid']}:{sysn}", "metric": "LC_within",
                        "score": po.get(ob["cls"][s], 0.0) if ob["parse_ok"][s] else 0.0, "covered": cov})
            ps = [x for x in ob["systems"] if x != "greedy" and ob["parse_ok"][x]]
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
    write_jsonl(WORK / "lc_scores_fresh.jsonl", out)
    (WORK / "lc_info_fresh.json").write_text(json.dumps({"pairs_missing": miss, **info}, default=str, indent=1))
    logger.info(f"LC fresh: {Counter(r['metric'] for r in out)}; missing pairs {miss}")


# ------------------------------------------------------------------------------------------------ B7 / B2
def _sat_worker(job):
    sys.path.insert(0, str(ARMB))
    import fol_core as fc2
    key, fols = job
    asts = [fc2.try_parse(f)[0] for f in fols]
    asts = [a for a in asts if a is not None]
    if not asts:
        return key, "no_parseable"
    conj = ("and",) + tuple(asts) if len(asts) > 1 else asts[0]
    try:
        return key, fc2.satisfiable(conj, nmax=3, timeout_ms=5000)
    except Exception as e:  # noqa: BLE001 - frozen behaviour: recorded status
        return key, f"error:{type(e).__name__}"


def _atoms(n, acc):
    op = n[0]
    if op in ("forall", "exists"):
        _atoms(n[2], acc)
    elif op == "not":
        _atoms(n[1], acc)
    elif op in ("and", "or", "imp", "iff", "xor"):
        _atoms(n[1], acc)
        _atoms(n[2], acc)
    elif op == "atom":
        acc.setdefault(n[1], set()).add(len(n[2]))
    return acc


def cmd_b7(workers: int) -> None:
    from fol_parse import parse as vparse
    rows = frame()
    info = {}
    for r in rows:
        pr = vparse(r["cand"]) if r["cand"] else None
        if pr is not None and pr.ok:
            ar = _atoms(pr.ast, {})
            info[r["item_id"]] = {"ok": True, "arity_self_ok": all(len(v) == 1 for v in ar.values()),
                                  "preds": sorted(ar), "arity": {k: sorted(v) for k, v in ar.items()}}
        else:
            info[r["item_id"]] = {"ok": False}
    G = [r for r in rows if r["fold"] == "fresh_greedy"]

    def group_of(r):
        return f"story:{r['corpus']}:{r['story_id']}" if r.get("story_id") not in (None, "") else f"src:{r['source_id']}"
    groups = defaultdict(list)
    for r in G:
        groups[(r["system"], group_of(r))].append(r)
    jobs = [(f"{s}|{g}", [r["r2canon"] for r in rs if info[r["item_id"]]["ok"]]) for (s, g), rs in groups.items()]
    joint = {}
    with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn")) as ex:
        for k, st in ex.map(_sat_worker, jobs, chunksize=8):
            joint[k] = st
    samples = defaultdict(list)
    for r in rows:
        if r["fold"] == "fresh_samples":
            samples[(r["sid"], r["system"])].append(r)
    out = []
    for (sysn, g), rs in groups.items():
        ar_story = defaultdict(set)
        for r in rs:
            for p, a in (info[r["item_id"]].get("arity") or {}).items():
                ar_story[p] |= set(a)
        for r in rs:
            c = info[r["item_id"]]
            ok = c["ok"]
            a_self = bool(c.get("arity_self_ok")) if ok else False
            a_story = ok and all(len(ar_story[p]) == 1 for p in (c.get("arity") or {}))
            st = joint.get(f"{sysn}|{g}")
            j_ok = ok and st != "unsat"
            rec = {"item_id": r["item_id"], "B2": float(ok), "B7_arity_self": int(a_self), "B7_arity_story": int(a_story),
                   "B7_joint": int(j_ok), "B7": int(ok and a_self and a_story and j_ok), "joint_status": st}
            if sysn in SAMPLE_SYSTEMS:
                P0 = set(c.get("preds") or [])
                js = []
                for s in samples.get((r["sid"], sysn), []):
                    cs = info[s["item_id"]]
                    if ok and cs["ok"]:
                        P1 = set(cs.get("preds") or [])
                        js.append(len(P0 & P1) / len(P0 | P1) if (P0 | P1) else 1.0)
                rec["B7_jacc"] = sum(js) / len(js) if js else None
            out.append(rec)
    write_jsonl(WORK / "b7_fresh.jsonl", out)
    logger.info(f"B7 fresh: {Counter(r['B7'] for r in out)}; joint {Counter(r['joint_status'] for r in out)}")


# ------------------------------------------------------------------------------------------------ VC
_SPLIT = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|\d+")


def norm_pred(name: str, lem) -> tuple:
    toks = []
    for part in name.replace("-", "_").split("_"):
        toks += _SPLIT.findall(part)
    return tuple(sorted(lem(t.lower()) for t in toks if t))


def vc_scores(rows_by_sid: dict) -> dict:
    """VC(C) = mean over parseable peers of 0.5 * Jaccard(norm predset) + 0.5 * 1[arity multiset equal]."""
    import nltk
    nltk.data.path.insert(0, str(ROOT / ".nltk_data"))
    try:
        from nltk.stem import WordNetLemmatizer
        wl = WordNetLemmatizer()
        wl.lemmatize("dogs")
        lem = lambda t: wl.lemmatize(wl.lemmatize(t), "v")  # noqa: E731
        lem_kind = "wordnet"
    except LookupError:
        lem = lambda t: t[:-1] if t.endswith("s") and len(t) > 3 else t  # noqa: E731
        lem_kind = "suffix_fallback"
    from dc import parse_fol
    from dc.parse import sig
    out = {}
    for sid, items in rows_by_sid.items():
        feats = {}
        for key, cand in items.items():
            A = parse_fol(cand) if cand else None
            if A is None:
                continue
            preds, _ = sig(A)
            feats[key] = ({norm_pred(p.split("/")[0].split("__")[0], lem) for p in preds}, tuple(sorted(preds.values())))
        for key in items:
            if key not in feats:
                out[key] = (0.5, False)
                continue
            vals = []
            for k2, f2 in feats.items():
                if k2 == key:
                    continue
                P0, a0 = feats[key]
                P1, a1 = f2
                jac = len(P0 & P1) / len(P0 | P1) if (P0 | P1) else 1.0
                vals.append(0.5 * jac + 0.5 * float(a0 == a1))
            out[key] = (sum(vals) / len(vals), True) if vals else (0.5, False)
    out["_lemmatizer"] = lem_kind
    return out


def cmd_vc() -> None:
    rows = frame()
    by = defaultdict(dict)
    for r in rows:
        if r["fold"] == "fresh_greedy":
            by[r["sid"]][r["item_id"]] = r["cand"] if r["parse_ok"] else None
    sc = vc_scores(by)
    lk = sc.pop("_lemmatizer")
    write_jsonl(WORK / "vc_fresh.jsonl", [{"item_id": k, "VC": v[0], "covered": v[1]} for k, v in sc.items()])
    logger.info(f"VC fresh {len(sc)} (lemmatizer {lk})")


if __name__ == "__main__":
    setup_logging("s05_fresh")
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["frame", "dcpairs", "lcpairs", "lc", "b7", "vc"])
    ap.add_argument("--workers", type=int, default=12)
    a = ap.parse_args()
    {"frame": cmd_frame, "dcpairs": lambda: cmd_dcpairs(a.workers), "lcpairs": lambda: cmd_lcpairs(a.workers),
     "lc": cmd_lc, "b7": lambda: cmd_b7(a.workers), "vc": cmd_vc}[a.cmd]()
