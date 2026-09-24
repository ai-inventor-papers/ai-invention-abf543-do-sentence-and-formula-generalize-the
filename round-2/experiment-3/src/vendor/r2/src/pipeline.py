"""Stages S1-S4 (frame, adapter, zero-LLM metrics, LLM metrics). Every stage reads/writes content-keyed caches in
work/, so any stage can be re-run (mini -> full) without recomputation or re-billing."""
from __future__ import annotations

import hashlib
import json
import random
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from loguru import logger

from common import (ROOT, SAMPLE_SYSTEMS, WORK, jdump, load_frame, read_jsonl, sha1, write_jsonl)

PY = sys.executable
TERC_ORDER = {"bottom": 0, "middle": 1, "top": 2}


def pkey(a: str, b: str) -> str:
    return hashlib.sha1((a + "||" + b).encode("utf-8")).hexdigest()


def run_worker(args: list[str], log_name: str, timeout: float | None = None) -> None:
    """Run a worker subprocess (own interpreter => own sys.path, no module collisions)."""
    t0 = time.time()
    lp = ROOT / "logs" / f"{log_name}.log"
    with open(lp, "a") as lf:
        lf.write(f"\n==== {time.ctime()} {' '.join(args)}\n")
        lf.flush()
        r = subprocess.run([PY, *args], cwd=ROOT, stdout=lf, stderr=subprocess.STDOUT, timeout=timeout)
    tail = lp.read_text().splitlines()[-6:]
    logger.info(f"worker {args[0]} {args[1] if len(args) > 1 else ''} exit={r.returncode} in {time.time() - t0:.0f}s | "
                + " / ".join(t[:160] for t in tail[-3:]))
    if r.returncode != 0:
        raise RuntimeError(f"worker {args} failed (see logs/{log_name}.log)")


# ------------------------------------------------------------------------------------------------ frame
class Frame:
    def __init__(self, limit_sents: int | None = None):
        rows = load_frame()
        self.all = rows
        ids = Counter(r["item_id"] for r in rows)
        dup = [k for k, v in ids.items() if v > 1]
        assert not dup, f"duplicate item ids {dup[:5]}"
        self.G = [r for r in rows if r["fold"] == "heldout_confirm"]
        self.S = [r for r in rows if r["fold"] == "heldout_samples"]
        self.C = [r for r in rows if r["fold"] == "contamination"]
        self.SA = [r for r in rows if r["fold"] == "screen_gold_audit"]
        self.T = [r for r in rows if r["fold"] == "transfer_unlabeled"]
        assert len(self.G) == 6300 and len({r["sentence_id"] for r in self.G}) == 700, "heldout_confirm shape"
        self.sids = sorted({r["sentence_id"] for r in self.G})
        if limit_sents:
            self.sids = mini_sids(self.G, limit_sents)
            keep = set(self.sids)
            self.G = [r for r in self.G if r["sentence_id"] in keep]
            self.S = [r for r in self.S if r["sentence_id"] in keep]
            gid = {r["item_id"] for r in self.G}
            self.C = [r for r in self.C if r["original_item_id"] in gid]
            self.T = self.T[:40]
        self.by_id = {r["item_id"]: r for r in rows}
        self.canon = {r["h"]: r for r in read_jsonl(WORK / "canon.jsonl")}

    def string_for(self, r: dict) -> str:
        """Metric input string: dataset-parser canon when it parses, else the raw extracted candidate."""
        raw = r.get("candidate_fol") or ""
        c = self.canon.get(sha1(raw))
        return c["canon"] if (c and c.get("canon")) else raw


def mini_sids(G: list[dict], n: int) -> list[str]:
    """n sentences stratified by corpus x tercile, preferring sentences with panel items (>= 40 panel items)."""
    by = defaultdict(list)
    panel_n = Counter(r["sentence_id"] for r in G if r["label_source"] == "panel3")
    info = {}
    for r in G:
        info[r["sentence_id"]] = (r["corpus"], r["complexity_tercile"])
    for sid, k in info.items():
        by[k].append(sid)
    rng = random.Random(0)
    cells = sorted(by)
    out = []
    per = max(1, n // len(cells))
    for c in cells:
        L = sorted(by[c], key=lambda s: (-panel_n[s], s))
        head = [s for s in L if panel_n[s] > 0][: per // 2 + 1]
        rest = [s for s in L if s not in head]
        rng.shuffle(rest)
        out += (head + rest)[:per]
    return sorted(out[:n])


def stage_frame() -> dict:
    rows = load_frame()
    strings = {}
    for r in rows:
        s = r.get("candidate_fol") or ""
        strings[sha1(s)] = s
        if r.get("candidate_fol_original"):
            strings[sha1(r["candidate_fol_original"])] = r["candidate_fol_original"]
    write_jsonl(WORK / "strings.jsonl", [{"h": h, "s": s} for h, s in strings.items()])
    c = Counter(r["fold"] for r in rows)
    logger.info(f"frame: {dict(c)}; {len(strings)} distinct candidate strings")
    return {"folds": dict(c), "n_strings": len(strings)}


def stage_adapter() -> dict:
    run_worker(["workers/adapter.py"], "adapter")
    run_worker(["workers/armB.py", "parsecheck"], "armB")
    run_worker(["workers/armA.py", "parsecheck"], "armA")
    return coverage_table()


def coverage_table() -> dict:
    F = Frame()
    canon = F.canon
    pa = {r["h"]: r for r in read_jsonl(WORK / "armA_parse.jsonl")}
    pb = {r["h"]: r for r in read_jsonl(WORK / "armB_parse.jsonl")}
    tab = defaultdict(Counter)
    causes = Counter()
    rt = Counter()
    for r in F.G + F.C + F.T + F.SA + F.S:
        h = sha1(r.get("candidate_fol") or "")
        c, a, b = canon.get(h, {}), pa.get(h, {}), pb.get(h, {})
        keyc = f"{r['fold']}|{r.get('corpus')}|{r.get('system')}"
        t = tab[keyc]
        t["n"] += 1
        t["dataset_parse_ok_field"] += bool(r.get("parse_ok"))
        t["ds_ok"] += bool(c.get("ds_ok"))
        t["armA_ok_raw"] += bool(a.get("armA_ok_raw"))
        t["armA_ok_canon"] += bool(a.get("armA_ok_canon")) or (not c.get("canon") and bool(a.get("armA_ok_raw")))
        t["armB_ok_raw"] += bool(b.get("armB_ok_raw"))
        t["armB_ok_canon"] += bool(b.get("armB_ok_canon")) or (not c.get("canon") and bool(b.get("armB_ok_raw")))
        if r["fold"] == "heldout_confirm":
            rt[c.get("roundtrip_same_ast")] += 1
            if not c.get("ds_ok"):
                raw = r.get("candidate_fol") or ""
                cause = ("empty" if not raw.strip() else "latex" if "\\" in raw else "subset_or_set" if any(
                    x in raw for x in "∈⊆⊂") else "arith_or_compare" if any(x in raw for x in "<>≤≥+*") else
                         "function_term_or_other")
                causes[cause] += 1
            elif not b.get("armB_ok_canon"):
                causes["armB_rejects_canon:" + (b.get("armB_err_canon") or "?")] += 1
    out = {"per_fold_corpus_system": {k: dict(v) for k, v in sorted(tab.items())},
           "heldout_uncovered_causes": dict(causes), "heldout_canon_roundtrip_same_ast": {str(k): v for k, v in rt.items()}}
    tot = defaultdict(Counter)
    for k, v in tab.items():
        fold = k.split("|")[0]
        for kk, vv in v.items():
            tot[fold][kk] += vv
    out["per_fold"] = {k: dict(v) for k, v in tot.items()}
    jdump(out, ROOT / "results" / "coverage_adapter.json")
    logger.info(f"coverage per fold: {json.dumps(out['per_fold'])[:900]}")
    return out


# ------------------------------------------------------------------------------------------------ zero-LLM
def build_lc_inputs(F: Frame) -> dict:
    pb = {r["h"]: r for r in read_jsonl(WORK / "armB_parse.jsonl")}

    def armb_ok(r):
        raw = r.get("candidate_fol") or ""
        h = sha1(raw)
        c = F.canon.get(h, {})
        b = pb.get(h, {})
        return bool(b.get("armB_ok_canon")) if c.get("canon") else bool(b.get("armB_ok_raw"))
    panel_sids = {r["sentence_id"] for r in F.G if r["label_source"] == "panel3"}
    terc = {r["sentence_id"]: r["complexity_tercile"] for r in F.G}
    prio = sorted(F.sids, key=lambda s: (0 if s in panel_sids else 1 if terc[s] == "top" else 2, s))
    by = defaultdict(dict)
    for r in F.G:
        by[r["sentence_id"]][r["system"]] = r
    ss = {"sentences": [{"sid": s, "tercile": TERC_ORDER[terc[s]]} for s in F.sids], "real_items": []}
    pairs_spec, jobs = {}, []
    for sid in prio:
        items = by[sid]
        for sysn in sorted(items):
            r = items[sysn]
            ss["real_items"].append({"item_id": f"{sid}:{sysn}", "sid": sid, "system": sysn, "parse_ok": armb_ok(r)})
        pl = {}
        systems = sorted(items)
        for i in range(len(systems)):
            for j in range(i + 1, len(systems)):
                a, b = items[systems[i]], items[systems[j]]
                if not (armb_ok(a) and armb_ok(b)):
                    continue
                sa, sb = F.string_for(a), F.string_for(b)
                k = pkey(sa, sb)
                pl[f"{systems[i]}|{systems[j]}"] = k
                jobs.append({"a": sa, "b": sb, "sid": sid})
        pairs_spec[sid] = pl
    # within-system raters (greedy + 5 samples)
    samples = defaultdict(dict)
    for r in F.S:
        samples[(r["sentence_id"], r["system"])][f"s{r['sample_idx']}"] = r
    within, wjobs = {}, []
    for sysn in SAMPLE_SYSTEMS:
        wss = {"sentences": ss["sentences"], "real_items": []}
        wp = {}
        for sid in prio:
            raters = {"greedy": by[sid][sysn], **samples.get((sid, sysn), {})}
            names = sorted(raters)
            for n in names:
                wss["real_items"].append({"item_id": f"{sid}:{n}", "sid": sid, "system": n, "parse_ok": armb_ok(raters[n])})
            pl = {}
            for i in range(len(names)):
                for j in range(i + 1, len(names)):
                    a, b = raters[names[i]], raters[names[j]]
                    if not (armb_ok(a) and armb_ok(b)):
                        continue
                    sa, sb = F.string_for(a), F.string_for(b)
                    k = pkey(sa, sb)
                    pl[f"{names[i]}|{names[j]}"] = k
                    wjobs.append({"a": sa, "b": sb, "sid": sid})
            wp[sid] = pl
        within[sysn] = {"ss": wss, "pairs": wp}
    (WORK / "lc_input.json").write_text(json.dumps({"ss": ss, "pairs": pairs_spec, "within": within}))
    write_jsonl(WORK / "pair_jobs_greedy.jsonl", jobs)
    write_jsonl(WORK / "pair_jobs_within.jsonl", wjobs)
    logger.info(f"LC inputs: {len(jobs)} greedy pair jobs ({len({pkey(j['a'], j['b']) for j in jobs})} unique), "
                f"{len(wjobs)} within jobs")
    return {"n_greedy_jobs": len(jobs), "n_within_jobs": len(wjobs)}


def build_granular_jobs() -> int:
    cache = {r["k"]: r for r in read_jsonl(WORK / "pairs_cache.jsonl")}
    spec = json.loads((WORK / "lc_input.json").read_text())
    jobs = {}
    strings = {}
    for j in read_jsonl(WORK / "pair_jobs_greedy.jsonl"):
        strings[pkey(j["a"], j["b"])] = (j["a"], j["b"])
    for sid, pl in spec["pairs"].items():
        for name, k in pl.items():
            r = cache.get(k)
            if r and r["bij"] == "nonequiv" and r["reason"] in ("vocab_mismatch", "no_equiv_map") and k in strings:
                jobs[k] = {"k": k, "a": strings[k][0], "b": strings[k][1]}
    write_jsonl(WORK / "granular_jobs.jsonl", list(jobs.values()))
    return len(jobs)


def build_b7(F: Frame) -> None:
    """B7 ported structural metric (no declared predicate lists in held-out outputs)."""
    def group_of(r):
        return f"story:{r['corpus']}:{r['story_id']}" if r.get("story_id") not in (None, "") else f"src:{r['source_id']}"
    groups = defaultdict(list)
    for r in F.G:
        groups[(r["system"], group_of(r))].append(r)
    jobs = []
    for (sysn, g), rs in groups.items():
        fols = [F.string_for(r) for r in rs if F.canon.get(sha1(r.get("candidate_fol") or ""), {}).get("ds_ok")]
        jobs.append({"key": f"{sysn}|{g}", "fols": fols})
    write_jsonl(WORK / "b7_jobs.jsonl", jobs)
    run_worker(["workers/armB.py", "b7joint", "--workers", "12"], "armB")
    joint = json.loads((WORK / "b7_joint.json").read_text())
    samples = defaultdict(list)
    for r in F.S:
        samples[(r["sentence_id"], r["system"])].append(r)
    rows = []
    for (sysn, g), rs in groups.items():
        ar_story = defaultdict(set)
        for r in rs:
            c = F.canon.get(sha1(r.get("candidate_fol") or ""), {})
            for p, a in (c.get("arity") or {}).items():
                ar_story[p] |= set(a)
        for r in rs:
            c = F.canon.get(sha1(r.get("candidate_fol") or ""), {})
            ok = bool(c.get("ds_ok"))
            a_self = bool(c.get("arity_self_ok")) if ok else False
            a_story = ok and all(len(ar_story[p]) == 1 for p in (c.get("arity") or {}))
            st = joint.get(f"{sysn}|{g}")
            j_ok = ok and st != "unsat"  # unknown -> 1 (plan), unsat -> 0
            rec = {"key": r["item_id"], "B7_arity_self": int(a_self), "B7_arity_story": int(a_story),
                   "B7_joint": int(j_ok), "B7": int(ok and a_self and a_story and j_ok), "joint_status": st,
                   "story_size": len(rs)}
            if sysn in SAMPLE_SYSTEMS:
                P0 = set(c.get("preds") or [])
                js = []
                for s in samples.get((r["sentence_id"], sysn), []):
                    cs = F.canon.get(sha1(s.get("candidate_fol") or ""), {})
                    if ok and cs.get("ds_ok"):
                        P1 = set(cs.get("preds") or [])
                        js.append(len(P0 & P1) / len(P0 | P1) if (P0 | P1) else 1.0)
                rec["B7_jacc"] = sum(js) / len(js) if js else None
            rows.append(rec)
    write_jsonl(WORK / "b7_scores.jsonl", rows)
    logger.info(f"B7: {Counter(r['B7'] for r in rows)}; joint {Counter(r['joint_status'] for r in rows)}")


def stage_zero_llm(F: Frame, workers: int = 12, pair_limit_s: float = 0.0) -> dict:
    info = build_lc_inputs(F)
    run_worker(["workers/armB.py", "pairs", "--jobs", "pair_jobs_greedy.jsonl", "--workers", str(workers),
                "--want_str", "--limit_s", str(pair_limit_s)], "armB_pairs")
    run_worker(["workers/armB.py", "pairs", "--jobs", "pair_jobs_within.jsonl", "--workers", str(workers),
                "--limit_s", str(pair_limit_s)], "armB_pairs")
    info["n_granular_jobs"] = build_granular_jobs()
    run_worker(["workers/granular.py", "--workers", str(workers), "--cpu_min_cap", "40"], "granular")
    run_worker(["workers/armB.py", "lc"], "armB_lc")
    build_b7(F)
    # Arm A zero-LLM signature metrics on G + C + T
    items = []
    for r in F.G + F.C + F.T:
        items.append({"key": r["item_id"], "sentence": r["sentence"], "fol": F.string_for(r)})
    write_jsonl(WORK / "armA_items.jsonl", items)
    run_worker(["workers/armA.py", "score", "--items", "armA_items.jsonl", "--out", "armA_scores.jsonl",
                "--variants", "A3,A0,Ccov", "--workers", str(workers)], "armA_score")
    return info


# ------------------------------------------------------------------------------------------------ LLM
def contamination_slice(F: Frame) -> tuple[list[dict], list[dict]]:
    sl = {"gpt-4.1-mini", "deepseek-v3.1", "llama-3.1-8b"}
    C = [r for r in F.C if r["system"] in sl]
    O = [F.by_id[r["original_item_id"]] for r in C if r["original_item_id"] in F.by_id]
    return C, O


def stage_llm(F: Frame, parts: set[str]) -> dict:
    import llm_stages as L
    info = {}
    if "b1" in parts:
        items = [{"key": r["item_id"], "sentence": r["sentence"], "fol": r.get("candidate_fol") or ""} for r in F.G + F.C]
        info["B1"] = L.run_b1(items, "b1_scores.jsonl")
        info["B1_retest"] = L.run_b1_retest([{"key": r["item_id"], "sentence": r["sentence"],
                                              "fol": r.get("candidate_fol") or ""} for r in F.G])
    if "a1" in parts:
        # shared-key frugality (plan fallback (5)): A1 restricted to the panel sentences + the contamination pairs
        # (originals and paraphrases). a1_prompts.jsonl (built for all sentences by the local stage) is reused.
        keep = ({r["sentence"] for r in F.G if r["label_source"] == "panel3"} | {r["sentence"] for r in F.C} |
                {F.by_id[r["original_item_id"]]["sentence"] for r in F.C if r["original_item_id"] in F.by_id})
        prompts = [p for p in read_jsonl(WORK / "a1_prompts.jsonl") if p["prompts"] and p["sentence"] in keep]
        logger.info(f"A1 (gemini): {len(prompts)} sentences (panel + contamination), "
                    f"{sum(len(p['prompts']) for p in prompts)} calls")
        info["A1_probe"] = L.run_a1(prompts)
        run_worker(["workers/armA.py", "score", "--items", "armA_items_a1.jsonl", "--out", "armA_scores_a1.jsonl",
                    "--variants", "A1", "--workers", "12"], "armA_score")
    Cs, Os = contamination_slice(F)
    panel = [r for r in F.G if r["label_source"] == "panel3"]
    b3_rows = {r["item_id"]: r for r in panel + Os + Cs}
    if "b3" in parts:
        items = [{"key": k, "fol": r.get("candidate_fol") or ""} for k, r in b3_rows.items()]
        info["B3_back"] = L.run_b3_back(items)
        back = {r["key"]: r for r in read_jsonl(WORK / "b3_back.jsonl")}
        from gpu_b3 import score_b3
        rows = score_b3([{"key": k, "sentence": r["sentence"], "back": (back.get(k) or {}).get("back")}
                         for k, r in b3_rows.items()])
        for x in rows:
            x["usd"] = (back.get(x["key"]) or {}).get("usd", 0.0)
        write_jsonl(WORK / "b3_scores.jsonl", rows)
    if "b3c" in parts:
        back = {r["key"]: r for r in read_jsonl(WORK / "b3_back.jsonl")}
        info["B3c"] = L.run_b3c([{"key": k, "sentence": r["sentence"], "back": (back.get(k) or {}).get("back")}
                                 for k, r in b3_rows.items()])
    if "b1plus" in parts:
        prio = [{"key": r["item_id"], "sid": r["sentence_id"], "sentence": r["sentence"],
                 "fol": r.get("candidate_fol") or ""} for r in panel]
        pk = {x["key"] for x in prio}
        # shared-key frugality: the frontier judge runs on the 609 panel items only (plan fallback (5): the B1+
        # contamination slice is the first thing sacrificed under budget pressure)
        rest = []
        info["B1plus"] = L.run_b1plus(prio + rest, priority_n=len(prio))
    if "recall" in parts:
        seen = {}
        for r in F.C:
            seen.setdefault(r["sentence_id"], r)
        items = []
        for sid, r in seen.items():
            items.append({"key": f"{sid}:orig", "sentence": r["original_sentence"]})
            items.append({"key": f"{sid}:para", "sentence": r["sentence"]})
        info["RECALL"] = L.run_recall(items)
    old = json.loads((ROOT / "results" / "llm_stage_info.json").read_text()) if (
        ROOT / "results" / "llm_stage_info.json").exists() else {}
    old.update(info)
    jdump(old, ROOT / "results" / "llm_stage_info.json")
    return info


# ------------------------------------------------------------------------------------------------ LOCAL substitutes
def _local_b1(M, L, F, info):
    items = list(F.G + F.C)
    prompts = [L.B1_PROMPT.format(s=r["sentence"], f=r.get("candidate_fol") or "") for r in items]
    res = M.generate(prompts, 16, "B1L", batch_size=64)
    retry = [i for i, x in enumerate(res) if L.first_number(x["text"]) is None]
    if retry:
        rr = M.generate([prompts[i] for i in retry], 48, "B1L", batch_size=64)
        for i, x in zip(retry, rr):
            if L.first_number(x["text"]) is not None:
                res[i] = x
    rows = []
    for r, p, x in zip(items, prompts, res):
        v = L.first_number(x["text"])
        rows.append({"key": r["item_id"], "metric": "B1L", "score": 0.5 if v is None else v, "covered": v is not None,
                     "usd": 0.0, "seconds": x["seconds"], "raw": x["text"][:24], "prompt_sha1": sha1(p),
                     "model": M.tag, "cached": False})
    write_jsonl(WORK / "b1L_scores.jsonl", rows)
    # retest: 300 random unique prompts regenerated in a different batch composition (batch size 7, own cache key)
    uniq = {}
    for r, p in zip(items, prompts):
        if r["fold"] == "heldout_confirm":
            uniq.setdefault(p, r["item_id"])
    ks = sorted(uniq)
    random.Random(0).shuffle(ks)
    ks = ks[:300]
    tag0 = M.tag
    M.tag = tag0 + ":retest_bs7"
    try:
        rt = M.generate(ks, 16, "B1L_retest", batch_size=7)
    finally:
        M.tag = tag0
    write_jsonl(WORK / "b1L_retest.jsonl", [{"key": uniq[p], "score2": L.first_number(x["text"]), "raw2": x["text"][:24]}
                                           for p, x in zip(ks, rt)])
    info["B1L"] = {"n": len(rows), "parse_rate": sum(r["covered"] for r in rows) / len(rows),
                   "n_unique_prompts": len(set(prompts)), "n_retry_48": len(retry)}


def _local_a1(M, L, F, info):
    sents = sorted({r["sentence"] for r in F.G} | {r["sentence"] for r in F.C})
    write_jsonl(WORK / "a1_sentences.jsonl", [{"sentence": s} for s in sents])
    if not (WORK / "a1_prompts.jsonl").exists() or len(read_jsonl(WORK / "a1_prompts.jsonl")) != len(sents):
        run_worker(["workers/armA.py", "probes"], "armA")
    P = [p for p in read_jsonl(WORK / "a1_prompts.jsonl") if p["prompts"]]
    flat = [(i, ch["offset"], ch["prompt"]) for i, p in enumerate(P) for ch in p["prompts"]]
    res = M.generate([f[2] for f in flat], 1024, "A1L", batch_size=24)
    per = {}
    for (i, off, _), x in zip(flat, res):
        d = per.setdefault(i, {"sentence": P[i]["sentence"], "chunks": [], "usd": 0.0, "seconds": 0.0, "failed": 0})
        d["chunks"].append({"offset": off, "text": x["text"]})
        d["seconds"] += x["seconds"]
    write_jsonl(WORK / "a1L_raw.jsonl", list(per.values()))
    info["A1L"] = {"n_sentences": len(per), "n_prompts": len(flat)}


def _local_b3(M, L, b3_rows, info):
    keys = list(b3_rows)
    res = M.generate([L.B3_PROMPT.format(f=b3_rows[k].get("candidate_fol") or "") for k in keys], 200, "B3L",
                     batch_size=48)
    backs = {k: (x["text"].strip().split("\n")[0].strip() or None) for k, x in zip(keys, res)}
    write_jsonl(WORK / "b3L_back.jsonl", [{"key": k, "back": backs[k], "seconds": x["seconds"]}
                                          for k, x in zip(keys, res)])
    info["B3L_back"] = {"n": len(keys), "n_nonempty": sum(1 for v in backs.values() if v)}


def _local_b3c(M, L, b3_rows, info):
    back = {r["key"]: r["back"] for r in read_jsonl(WORK / "b3L_back.jsonl")}
    keys = [k for k in b3_rows if back.get(k)]
    res = M.generate([L.B3C_PROMPT.format(a=b3_rows[k]["sentence"], b=back[k]) for k in keys], 800, "B3cL",
                     batch_size=32)
    by = dict(zip(keys, res))
    rows = []
    for k in b3_rows:
        x = by.get(k)
        sc, extra = L._b3c_score(None if x is None else x["text"])
        rows.append({"key": k, "metric": "B3cL", "score": 0.5 if sc is None else sc, "covered": sc is not None,
                     "usd": 0.0, "seconds": None if x is None else x["seconds"], "extra": extra})
    write_jsonl(WORK / "b3cL_scores.jsonl", rows)
    info["B3cL"] = {"coverage": sum(r["covered"] for r in rows) / max(1, len(rows))}


def _local_recall(M, L, F, info):
    seen = {}
    for r in F.C:
        seen.setdefault(r["sentence_id"], r)
    items = []
    for sid, r in seen.items():
        items.append((f"{sid}:orig", r["original_sentence"]))
        items.append((f"{sid}:para", r["sentence"]))
    res = M.generate([L.RECALL_PROMPT.format(s=s) for _, s in items], 300, "RECALL_L", batch_size=32)
    write_jsonl(WORK / "recallL.jsonl", [{"key": k, "text": x["text"]} for (k, _), x in zip(items, res)])
    info["RECALL_L"] = {"n": len(items)}


def _local_b1plus(M, L, uniq_items, info):
    prompts = [L.B1_PROMPT.format(s=r["sentence"], f=r.get("candidate_fol") or "") for r in uniq_items]
    # budget: thinking capped at 1024 new tokens, batch 16 (KV cache fits beside the 16.4 GB of weights); an
    # unfinished reasoning trace has no final answer -> uncovered (0.5). Panel items only (see deviations D-B1plusL).
    res = M.generate(prompts, 1024, "B1plusL", batch_size=16, thinking=True)
    # second pass: items whose reasoning did not finish within 1024 tokens are regenerated with a 2048-token cap
    retry = [i for i, x in enumerate(res) if L.first_number(x["text"]) is None]
    info["B1plusL_retry_2048"] = len(retry)
    if retry:
        rr = M.generate([prompts[i] for i in retry], 2048, "B1plusL", batch_size=12, thinking=True)
        for i, x in zip(retry, rr):
            if L.first_number(x["text"]) is not None:
                res[i] = x
    rows = []
    for r, x in zip(uniq_items, res):
        v = L.first_number(x["text"])
        rows.append({"key": r["item_id"], "metric": "B1plusL", "score": 0.5 if v is None else v,
                     "covered": v is not None, "usd": 0.0, "seconds": x["seconds"], "raw": x["text"][:24],
                     "model": M.tag + ":thinking", "n_out_tokens": x.get("n_out")})
    write_jsonl(WORK / "b1plusL_scores.jsonl", rows)
    info["B1plusL"] = {"n": len(rows), "parse_rate": sum(r["covered"] for r in rows) / max(1, len(rows))}


def stage_local(F: Frame, parts: set[str]) -> dict:
    """Local-GPU substitute judges (see src/local_llm.py docstring). Same prompts as the frozen gemini metrics.
    One model session for all parts; each part is fail-safe (an error is logged and the next part runs)."""
    import llm_stages as L
    from local_llm import MODEL_8B, LocalLLM
    info = {"errors": {}}
    Cs, Os = contamination_slice(F)
    panel = [r for r in F.G if r["label_source"] == "panel3"]
    b3_rows = {r["item_id"]: r for r in panel + Os + Cs}
    seen, uniq_items = set(), []
    for r in panel:  # B1plusL: panel items only (time budget; 10 s/item with thinking)
        if r["item_id"] not in seen:
            seen.add(r["item_id"])
            uniq_items.append(r)
    order = [("b1", lambda M: _local_b1(M, L, F, info)), ("b3", lambda M: _local_b3(M, L, b3_rows, info)),
             ("recall", lambda M: _local_recall(M, L, F, info)), ("a1", lambda M: _local_a1(M, L, F, info)),
             ("b3c", lambda M: _local_b3c(M, L, b3_rows, info)),
             ("b1plus", lambda M: _local_b1plus(M, L, uniq_items, info))]
    if parts & {p for p, _ in order}:
        M = LocalLLM(MODEL_8B)
        for name, fn in order:
            if name not in parts:
                continue
            t0 = time.time()
            try:
                fn(M)
                info.setdefault("seconds", {})[name] = round(time.time() - t0, 1)
                logger.info(f"local part {name} done in {time.time() - t0:.0f}s")
            except Exception as e:  # noqa: BLE001 - logged; next part continues
                logger.exception(f"local part {name} failed: {e!r}")
                info["errors"][name] = repr(e)[:300]
        M.close()
        del M
    if "b3" in parts and (WORK / "b3L_back.jsonl").exists():
        try:
            back = {r["key"]: r["back"] for r in read_jsonl(WORK / "b3L_back.jsonl")}
            from gpu_b3 import score_b3
            rows = score_b3([{"key": k, "sentence": r["sentence"], "back": back.get(k)} for k, r in b3_rows.items()])
            for x in rows:
                x["metric"] = x["metric"] + "L"
                x["usd"] = 0.0
            write_jsonl(WORK / "b3L_scores.jsonl", rows)
        except Exception as e:  # noqa: BLE001
            logger.exception(f"B3L scoring failed: {e!r}")
            info["errors"]["b3_score"] = repr(e)[:300]
    if "a1" in parts and (WORK / "a1L_raw.jsonl").exists():
        items = [{"key": r["item_id"], "sentence": r["sentence"], "fol": F.string_for(r)} for r in F.G + F.C]
        write_jsonl(WORK / "armA_items_a1.jsonl", items)
        run_worker(["workers/armA.py", "score", "--items", "armA_items_a1.jsonl", "--out", "armA_scores_a1L.jsonl",
                    "--variants", "A1", "--workers", "12", "--a1_raw", "a1L_raw.jsonl", "--rename", "A1L"], "armA_score")
    old = json.loads((ROOT / "results" / "local_stage_info.json").read_text()) if (
        ROOT / "results" / "local_stage_info.json").exists() else {}
    old.update(info)
    jdump(old, ROOT / "results" / "local_stage_info.json")
    return info


def rescore_b3cL(F: Frame) -> dict:
    """Re-read the cached Qwen3 B3c generations (no model load) with the current _b3c_score parser."""
    import llm_stages as L
    from local_llm import CACHE, MODEL_8B
    Cs, Os = contamination_slice(F)
    panel = [r for r in F.G if r["label_source"] == "panel3"]
    b3_rows = {r["item_id"]: r for r in panel + Os + Cs}
    back = {r["key"]: r["back"] for r in read_jsonl(WORK / "b3L_back.jsonl")}
    cache = {r["k"]: r for r in read_jsonl(CACHE / "B3cL.jsonl")}
    tag = MODEL_8B + ":bf16"
    rows = []
    for k, r in b3_rows.items():
        x = None
        if back.get(k):
            x = cache.get(sha1(f"{tag}|800||{L.B3C_PROMPT.format(a=r['sentence'], b=back[k])}"))
        sc, extra = L._b3c_score(None if x is None else x["text"])
        rows.append({"key": k, "metric": "B3cL", "score": 0.5 if sc is None else sc, "covered": sc is not None,
                     "usd": 0.0, "seconds": None if x is None else x["seconds"], "extra": extra})
    write_jsonl(WORK / "b3cL_scores.jsonl", rows)
    return {"n": len(rows), "coverage": sum(r["covered"] for r in rows) / max(1, len(rows))}
