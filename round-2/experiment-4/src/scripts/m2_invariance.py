#!/usr/bin/env python3
"""M2: invariance under 7 solver-verified meaning-preserving rewrites + contamination (entity-renamed paraphrases).

C1000 = all parseable panel items + random parseable dev greedy rows up to 1,000 (stratified by system, seed 1).
Rewrites: syn_rename, tok_rename, var_rename, reorder, contrapositive, demorgan, prenex (each verified equivalent,
bounded n<=4 + unbounded z3; failures/inapplicable counted per kind). DC(R(C)) against the SAME 8 peers, SAME frozen
weights. FA_kind(δ) = share with |DC(R(C)) - DC(C)| > δ, δ in {0, 0.10}; relation-vector / error-type change rates;
UNKNOWN inflation. Contamination: DC on the 104 original sentences (peers = original 9) vs the renamed paraphrase
(peers = renamed 9), mean Δ and AUROC difference with sentence-bootstrap CIs, with/without rename_incomplete rows.
Outputs work/m2_rows.jsonl, work/m2_contam.jsonl, results/m2_invariance.json."""
import json
import multiprocessing as mp
import random
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from loguru import logger  # noqa: E402

from dc.common import (EXP3, LOGS, RES, WORK, PairStore, _init_worker, detect_cpus, jdump, load_frame, rj,  # noqa: E402
                       wj)
from dc import stats as ST  # noqa: E402

logger.remove()
logger.add(sys.stdout, level="INFO", format="{time:HH:mm:ss}|{level:<7}|{message}")
logger.add(str(LOGS / "m2.log"), level="DEBUG")
KINDS = ["syn_rename", "tok_rename", "var_rename", "reorder", "contrapositive", "demorgan", "prenex"]
_ST = None


def _winit():
    _init_worker(4.0)
    global _ST
    from dc.common import PairStore as PS
    _ST = PS()


def rw_job(job):
    from dc import front, probes as PR
    A = front.parse_canon(job["canon"])
    out = []
    for r in PR.rewrites(A, job["item_id"]):
        if r.get("ok"):
            c = front.canon(r["fol"])
            r["canon"] = c["canon"] if c["ok"] else None
            r["canon_ok"] = c["ok"]
        out.append(r)
    return {"item_id": job["item_id"], "rewrites": out}


def _dc(fol, peers, pid, W, rf):
    from dc.core import directional_consensus
    r = directional_consensus(None, fol, peers, pid, W, rel_fn=rf, rel_key="rel_L3",
                              self_weight=sorted(W.values())[len(W) // 2])
    return {"DC": r["score"], "cov": r["covered"], "rels": [x["rel"] for x in r["per_peer"]],
            "etype": r.get("error_type"), "n_unknown": sum(x["rel"] == "UNKNOWN" for x in r["per_peer"])}


def score_job(job):
    rf = lambda a, b: _ST.get(a, b) or {"rel": "UNKNOWN", "rel_L3": "UNKNOWN"}  # noqa: E731
    W = job["W"]
    out = []
    for it in job["items"]:
        base = _dc(it["canon"], it["peers"], it["pid"], W, rf)
        for rw in it["rewrites"]:
            if not rw.get("ok") or not rw.get("canon"):
                out.append({"item_id": it["item_id"], "kind": rw["kind"], "ok": False, "reason": rw.get("reason")})
                continue
            new = _dc(rw["canon"], it["peers"], it["pid"], W, rf)
            out.append({"item_id": it["item_id"], "kind": rw["kind"], "ok": True, "DC0": base["DC"], "DC1": new["DC"],
                        "d": new["DC"] - base["DC"], "rels_changed": base["rels"] != new["rels"],
                        "etype_changed": base["etype"] != new["etype"], "etype0": base["etype"], "etype1": new["etype"],
                        "unk0": base["n_unknown"], "unk1": new["n_unknown"], "identical_string": rw["canon"] == it["canon"]})
    return out


def contam_job(job):
    rf = lambda a, b: _ST.get(a, b) or {"rel": "UNKNOWN", "rel_L3": "UNKNOWN"}  # noqa: E731
    W = job["W"]
    out = []
    for grp in ("orig", "para"):
        items = job[grp]
        for it in items:
            peers = [x for x in items if x["system"] != it["system"]]
            r = _dc(it["canon"], [p["canon"] for p in peers], [p["system"] for p in peers], W, rf)
            out.append({"grp": grp, "sid": job["sid"], "system": it["system"], "item_id": it["item_id"],
                        "DC": r["DC"], "cov": r["cov"], "y": it["y"], "incomplete": it.get("incomplete")})
    return out


def pool(fn, jobs, workers):
    out = []
    with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn"), initializer=_winit) as ex:
        futs = [ex.submit(fn, j) for j in jobs]
        for i, fu in enumerate(as_completed(futs)):
            try:
                out.append(fu.result())
            except Exception as e:  # noqa: BLE001
                logger.error(f"{fn.__name__} failed: {e!r}")
    return out


@logger.catch(reraise=True)
def main():
    t0 = time.time()
    n_target = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
    workers = max(1, detect_cpus() - 1)
    W = json.loads((ROOT / "frozen_dc_config.json").read_text())["weights"]
    rows = load_frame()
    G = [r for r in rows if r["fold"] == "heldout_confirm"]
    C = [r for r in rows if r["fold"] == "contamination"]
    cm = {c["raw"]: (c["canon"] if c["ok"] else None) for c in rj(WORK / "canon.jsonl")}
    by = defaultdict(list)
    for r in G:
        by[r["sentence_id"]].append(r)
    panel = [r for r in G if r["label_source"] == "panel3" and cm.get(r["candidate_fol"] or "")]
    rest = [r for r in G if r["label_source"] != "panel3" and cm.get(r["candidate_fol"] or "")]
    rng = random.Random(1)
    need = max(0, n_target - len(panel))
    bys = defaultdict(list)
    for r in rest:
        bys[r["system"]].append(r)
    extra = []
    for s in sorted(bys):
        L = sorted(bys[s], key=lambda r: r["item_id"])
        rng.shuffle(L)
        extra += L[: round(need * len(L) / len(rest))]
    Cset = (panel + extra)[:n_target] if n_target < len(panel) else panel + extra[:need]
    logger.info(f"C1000: {len(Cset)} ({len(panel)} panel + {len(Cset) - min(len(panel), len(Cset))} extra)")
    rw = pool(rw_job, [{"item_id": r["item_id"], "canon": cm[r["candidate_fol"]]} for r in Cset], workers)
    rwm = {x["item_id"]: x["rewrites"] for x in rw}
    logger.info(f"rewrites built in {time.time() - t0:.0f}s: "
                f"{Counter((y['kind'], y.get('ok')) for x in rw for y in x['rewrites'])}")
    st = PairStore()
    pairs, items_by_sid = [], defaultdict(list)
    for r in Cset:
        peers = [p for p in sorted(by[r["sentence_id"]], key=lambda p: p["system"]) if p["system"] != r["system"]]
        pc = [cm.get(p["candidate_fol"] or "") for p in peers]
        it = {"item_id": r["item_id"], "canon": cm[r["candidate_fol"]], "peers": pc, "pid": [p["system"] for p in peers],
              "rewrites": rwm.get(r["item_id"], [])}
        items_by_sid[r["sentence_id"]].append(it)
        for x in it["rewrites"]:
            if x.get("ok") and x.get("canon"):
                pairs += [(x["canon"], p) for p in pc if p]
    # contamination
    orig_by = defaultdict(list)
    para_by = defaultdict(list)
    for r in C:
        oid = r["original_item_id"]
        o = next((g for g in G if g["item_id"] == oid), None) if False else None
        para_by[r["sentence_id"]].append(r)
    gid = {g["item_id"]: g for g in G}
    cjobs = []
    for psid, prs in para_by.items():
        osid = gid[prs[0]["original_item_id"]]["sentence_id"]
        orig = [{"system": g["system"], "item_id": g["item_id"], "canon": cm.get(g["candidate_fol"] or ""),
                 "y": {"faithful": 1, "unfaithful": 0}.get(g["output"])} for g in by[osid]]
        para = [{"system": r["system"], "item_id": r["item_id"], "canon": cm.get(r["candidate_fol"] or ""),
                 "y": {"faithful": 1, "unfaithful": 0}.get(r["output"]),
                 "incomplete": bool(r.get("contamination_rename_incomplete"))} for r in prs]
        for grp in (orig, para):
            cs = [x["canon"] for x in grp if x["canon"]]
            pairs += [(cs[i], cs[j]) for i in range(len(cs)) for j in range(i + 1, len(cs))]
        cjobs.append({"sid": psid, "orig_sid": osid, "orig": orig, "para": para, "W": W})
    st.compute(pairs, workers=workers, want_lex=False, log=logger.info)
    del st
    sids = sorted(items_by_sid)
    jobs = [{"items": items_by_sid[s], "W": W} for s in sids]
    res = [r for x in pool(score_job, jobs, workers) for r in x]
    wj(WORK / "m2_rows.jsonl", res)
    cres = [r for x in pool(contam_job, cjobs, workers) for r in x]
    wj(WORK / "m2_contam.jsonl", cres)
    analyse(res, cres, Cset, rwm)
    logger.info(f"M2 done in {time.time() - t0:.0f}s")


def analyse(res, cres, Cset, rwm):
    out = {"n_candidates": len(Cset), "per_kind": {}}
    item_sid = {r["item_id"]: r["sentence_id"] for r in Cset}
    for k in KINDS:
        R = [r for r in res if r["kind"] == k]
        ok = [r for r in R if r["ok"]]
        att = sum(1 for x in rwm.values() for y in x if y["kind"] == k)
        blk = {"n_attempted": att, "n_verified_scored": len(ok),
               "n_failed_or_inapplicable": dict(Counter(r.get("reason") for r in R if not r["ok"]))}
        if ok:
            d = np.array([r["d"] for r in ok])
            for delta in (0.0, 0.10):
                v = (np.abs(d) > delta + 1e-12).astype(float)
                cb = ST.cluster_boot_mean(v, np.ones(len(v)), [item_sid[r["item_id"]] for r in ok])
                blk[f"FA_delta_{delta:.2f}"] = {"rate": cb["mean"], "ci": cb["ci"]}
            blk["mean_abs_delta"] = float(np.mean(np.abs(d)))
            blk["relation_vector_change_rate"] = float(np.mean([r["rels_changed"] for r in ok]))
            blk["error_type_change_rate"] = float(np.mean([r["etype_changed"] for r in ok]))
            blk["unknown_inflation"] = float(np.mean([r["unk1"] - r["unk0"] for r in ok]))
            blk["share_identical_canon_string"] = float(np.mean([r["identical_string"] for r in ok]))
            ch = [r for r in ok if abs(r["d"]) > 0.10]
            blk["examples_changed"] = [{k2: r[k2] for k2 in ("item_id", "DC0", "DC1", "etype0", "etype1")} for r in ch[:5]]
        out["per_kind"][k] = blk
    rd = json.loads((RES / "round2_record.json").read_text())
    out["round2_reference"] = {"signature_rename_FA": "0.38-0.52 (exp5/exp4 records)",
                               "TVJT_rename_FA": "heldout_g2 paired_FA RENAME 0.264; screen 0.387 (exp4 verdict)",
                               "exp4_verdict_excerpt": str(rd.get("exp4_verdict"))[:600]}
    # contamination
    cb = {}
    for tag, keep in (("all", lambda r: True), ("complete_renames_only", lambda r: not r.get("incomplete"))):
        para = {(r["sid"], r["system"]): r for r in cres if r["grp"] == "para" and keep(r)}
        orig = {}
        for r in cres:
            if r["grp"] == "orig":
                orig[(r["sid"], r["system"])] = r
        keys = sorted(set(para) & set(orig))
        d = np.array([orig[k]["DC"] - para[k]["DC"] for k in keys])
        sids = [k[0] for k in keys]
        m = ST.cluster_boot_mean(d, np.ones(len(d)), sids)
        lab = [k for k in keys if para[k]["y"] is not None and orig[k]["y"] is not None]
        yo = np.array([orig[k]["y"] for k in lab], float)
        yp = np.array([para[k]["y"] for k in lab], float)
        so = np.array([orig[k]["DC"] for k in lab])
        sp = np.array([para[k]["DC"] for k in lab])
        a_o, a_p = ST.wauc(yo, so), ST.wauc(yp, sp)
        by = defaultdict(list)
        for i, k in enumerate(lab):
            by[k[0]].append(i)
        arrs = [np.array(v) for v in by.values()]
        rng = np.random.default_rng(5)
        bs = []
        for _ in range(ST.NBOOT):
            ix = np.concatenate([arrs[j] for j in rng.integers(0, len(arrs), len(arrs))])
            bs.append(ST.wauc(yo[ix], so[ix]) - ST.wauc(yp[ix], sp[ix]))
        cb[tag] = {"n_pairs": len(keys), "n_sentences": len(set(sids)), "mean_delta_orig_minus_para": m["mean"],
                   "delta_ci": m["ci"], "share_exactly_equal": float(np.mean(d == 0)), "auroc_orig": a_o,
                   "auroc_para": a_p, "auroc_diff": a_o - a_p, "auroc_diff_ci": ST.ci(bs), "n_labelled": len(lab)}
    out["contamination"] = cb
    out["contamination"]["B1_reference"] = (rd.get("exp3_contamination") or {}).get("all", {}).get("B1")
    jdump(out, RES / "m2_invariance.json")


if __name__ == "__main__":
    main()
