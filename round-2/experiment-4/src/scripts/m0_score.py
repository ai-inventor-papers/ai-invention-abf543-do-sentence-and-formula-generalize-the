#!/usr/bin/env python3
"""M0: L1 cross-check vs exp3 pairs_cache, DS weights, DC (+ ladder variants, DC_lex, LC_maj*, VC) for every dev
greedy row (leave-self-out, peers = the other 8 systems), M7 gold-as-peer scores, dev anchor AUROCs, frozen config.
Outputs: work/dc_scores.jsonl, work/gold_scores.jsonl, results/m0_anchor.json, frozen_dc_config.json (once)."""
import hashlib
import json
import math
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing as mp
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from loguru import logger  # noqa: E402

from dc.common import (EXP3, RES, WORK, LOGS, SYSTEMS, PairStore, detect_cpus, jdump, load_frame, rj, wj,  # noqa: E402
                       _init_worker)

logger.remove()
logger.add(sys.stdout, level="INFO", format="{time:HH:mm:ss}|{level:<7}|{message}")
logger.add(str(LOGS / "m0_score.log"), level="DEBUG")

VARIANTS = {  # name -> (relation key, weighted)
    "DC": ("rel_L3", True), "S0_L1": ("rel_L1", False), "S1_L2": ("rel_L2", False), "S2_L3": ("rel_L3", False),
    "DC_L2w": ("rel_L2", True), "DC_lex": ("rel_lex", True)}


def canon_map() -> dict:
    return {c["raw"]: (c["canon"] if c["ok"] else None) for c in rj(WORK / "canon.jsonl")}


# ------------------------------------------------------------------------------------------ workers
_ST = None


def _winit():
    _init_worker(4.0)
    global _ST
    from dc.common import PairStore as PS
    _ST = PS()


def _rel_fn():
    from dc.pairs import compute_record, oriented, pkey
    local = {}

    def f(a, b):
        r = _ST.get(a, b)
        if r is None:
            k = pkey(a, b)
            if k not in local:
                local[k] = compute_record(a, b)
            rr = local[k]
            r = oriented(rr, a == rr["lo"])
        return r
    return f


def score_sentence(job: dict) -> list[dict]:
    """job: {sid, items: [{item_id, system, canon}], gold_orig, weights}."""
    from dc.core import directional_consensus, clusters, vocab_conformity
    rf = _rel_fn()
    W = job["weights"]
    items = job["items"]
    out = []
    for it in items:
        peers = [x for x in items if x["item_id"] != it["item_id"]]
        pc = [x["canon"] for x in peers]
        pid = [x["system"] for x in peers]
        rec = {"item_id": it["item_id"], "sid": job["sid"], "system": it["system"]}
        for name, (key, weighted) in VARIANTS.items():
            r = directional_consensus(None, it["canon"], pc, pid, W if weighted else None, rel_fn=rf, rel_key=key,
                                      self_weight=W.get(it["system"]) if weighted else 1.0,
                                      with_type=(name == "DC"))
            rec[name] = r["score"]
            rec[name + "_cov"] = r["covered"]
            if name == "DC":
                rec["strength_profile"] = r["strength_profile"]
                rec["coverage"] = r["coverage"]
                rec["error_type"] = r.get("error_type")
                rec["rel_to_mode"] = r.get("rel_to_mode")
                rec["in_mode"] = r.get("in_mode")
                rec["mode_mass"] = r.get("mode_mass")
                rec["per_peer"] = r["per_peer"]
                rec["seconds"] = r["cost"]["seconds"]
        vc = vocab_conformity(it["canon"], pc)
        rec["VC"], rec["VC_cov"] = vc["score"], vc["covered"]
        out.append(rec)
    # LC_maj* : exp3-style cluster majority with L1 clusters
    cs = [x["canon"] for x in items]

    def r1(a, b):
        return rf(a, b).get("rel_L1")
    cl = clusters(cs, r1)
    n_parse = sum(c is not None for c in cs)
    for rec, c in zip(out, cl):
        size = sum(1 for d in cl if d == c) if c >= 0 else 0
        rec["LC_maj_star"] = (size - 1) / (n_parse - 1) if (c >= 0 and n_parse >= 2) else 0.0
        rec["LC_maj_star_cov"] = bool(c >= 0 and n_parse >= 2)
    # M7 gold as a 10th peer: DC(gold) against all 9 outputs
    g = job.get("gold_orig")
    if g is not None or job.get("gold_orig_raw"):
        r = directional_consensus(None, g, cs, [x["system"] for x in items], W, rel_fn=rf, rel_key="rel_L3",
                                  self_weight=float(sorted(W.values())[len(W) // 2]))
        r2 = directional_consensus(None, g, cs, [x["system"] for x in items], None, rel_fn=rf, rel_key="rel_L1",
                                   with_type=False)
        out.append({"item_id": f"{job['sid']}:GOLD", "sid": job["sid"], "system": "GOLD", "DC": r["score"],
                    "DC_cov": r["covered"], "S0_L1": r2["score"], "error_type": r.get("error_type"),
                    "rel_to_mode": r.get("rel_to_mode"), "in_mode": r.get("in_mode"),
                    "strength_profile": r["strength_profile"], "per_peer": r["per_peer"], "is_gold": True})
    return out


def run_jobs(jobs: list[dict], workers: int) -> list[dict]:
    out = []
    with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn"), initializer=_winit) as ex:
        futs = [ex.submit(score_sentence, j) for j in jobs]
        for i, fu in enumerate(as_completed(futs)):
            try:
                out.extend(fu.result())
            except Exception as e:  # noqa: BLE001
                logger.error(f"sentence failed: {e!r}")
            if i % 100 == 0:
                logger.info(f"  scored {i}/{len(jobs)} sentences")
    return out


# ------------------------------------------------------------------------------------------ main
def l1_crosscheck(G, st) -> dict:
    from dc.front import canon_str
    from dc.common import sha1
    ex = {r["k"]: r for r in rj(EXP3 / "work" / "pairs_cache.jsonl")}
    cm = canon_map()
    by = defaultdict(dict)
    for r in G:
        by[r["sentence_id"]][r["system"]] = r
    agree = n = 0
    dis = []
    cnt = Counter()
    for sid, d in by.items():
        ss = sorted(d)
        for i in range(len(ss)):
            for j in range(i + 1, len(ss)):
                a, b = d[ss[i]], d[ss[j]]
                ca, cb = cm.get(a["candidate_fol"] or ""), cm.get(b["candidate_fol"] or "")
                if ca is None or cb is None:
                    continue
                sa = canon_str(a["candidate_fol"]) or a["candidate_fol"]
                sb = canon_str(b["candidate_fol"]) or b["candidate_fol"]
                k = sha1(sa + "||" + sb)
                e = ex.get(k)
                if e is None or e["bij"] not in ("equiv", "nonequiv"):
                    cnt["exp3_missing_or_unlabeled"] += 1
                    continue
                mine = st.get(ca, cb)
                if mine is None:
                    cnt["mine_missing"] += 1
                    continue
                m_eq = mine.get("rel_L1") == "EQUIV"
                e_eq = e["bij"] == "equiv"
                n += 1
                agree += m_eq == e_eq
                cnt[f"exp3={e['bij']}|dc_L1={mine.get('rel_L1')}"] += 1
                if m_eq != e_eq and len(dis) < 25:
                    dis.append({"sid": sid, "a": ca, "b": cb, "exp3": e["bij"], "exp3_reason": e.get("reason"),
                                "dc_L1": mine.get("rel_L1"), "dc_rel": mine.get("rel")})
    return {"n_compared": n, "agreement": agree / n if n else None, "counts": dict(cnt), "disagreements": dis}


@logger.catch(reraise=True)
def main():
    t0 = time.time()
    limit = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1] != "all" else None
    workers = max(1, detect_cpus() - 1)
    rows = load_frame()
    G = [r for r in rows if r["fold"] == "heldout_confirm"]
    cm = canon_map()
    st = PairStore()
    by = defaultdict(list)
    for r in G:
        by[r["sentence_id"]].append(r)
    sids = sorted(by)
    if limit:
        import random
        random.Random(0).shuffle(sids)
        sids = sorted(sids[:limit])
    # ---- L1 cross-check
    xc = l1_crosscheck([r for r in G if r["sentence_id"] in set(sids)], st)
    logger.info(f"L1 cross-check vs exp3: n={xc['n_compared']} agreement={xc['agreement']}")
    # ---- DS weights on EQUIV clusters (best relation)
    from dc.core import clusters, ds_weights
    obs = []
    terc = {"bottom": 0, "middle": 1, "top": 2}
    for sid in sids:
        d = {r["system"]: r for r in by[sid]}
        systems = sorted(d)
        cs = [cm.get(d[s]["candidate_fol"] or "") for s in systems]

        def rr(a, b):
            x = st.get(a, b)
            return x.get("rel") if x else "UNKNOWN"
        cl = clusters(cs, rr)
        po = {s: c is not None for s, c in zip(systems, cs)}
        clm = {s: (c if c >= 0 else 1000 + i) for i, (s, c) in enumerate(zip(systems, cl))}
        obs.append({"sid": sid, "systems": systems, "cls": clm, "parse_ok": po,
                    "valid": sorted({clm[s] for s in systems if po[s]}), "tercile": terc[d[systems[0]]["complexity_tercile"]]})
    ds = ds_weights(obs, SYSTEMS)
    logger.info(f"DS: p={ {k: round(v, 3) for k, v in ds['p'].items()} } degenerate={ds['degenerate']}")
    W = ds["w"] if not ds["degenerate"] else {s: 1.0 for s in SYSTEMS}
    # ---- score
    jobs = []
    for sid in sids:
        items = [{"item_id": r["item_id"], "system": r["system"], "canon": cm.get(r["candidate_fol"] or "")}
                 for r in sorted(by[sid], key=lambda r: r["system"])]
        g = by[sid][0].get("gold_fol_original")
        jobs.append({"sid": sid, "items": items, "gold_orig": cm.get(g) if g else None, "gold_orig_raw": g,
                     "weights": W})
    out = run_jobs(jobs, workers)
    sc = [o for o in out if not o.get("is_gold")]
    gs = [o for o in out if o.get("is_gold")]
    tag = "" if not limit else f"_mini{limit}"
    wj(WORK / f"dc_scores{tag}.jsonl", sc)
    wj(WORK / f"gold_dc_scores{tag}.jsonl", gs)
    logger.info(f"scored {len(sc)} items + {len(gs)} golds in {time.time() - t0:.0f}s")
    info = {"ds": ds, "weights_used": W, "l1_crosscheck": xc, "n_items": len(sc), "n_gold": len(gs),
            "seconds": time.time() - t0, "sids": len(sids)}
    jdump(info, WORK / f"m0_info{tag}.json")


if __name__ == "__main__":
    main()
