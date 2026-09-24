#!/usr/bin/env python3
"""M1(a) build + score: vocabulary x meaning crossed design on constructed truth.

S1 = dev sentences with gold_faithful_final AND parseable audited gold AND a weighted M0 mode cluster (>= 2 peers)
EQUIV to the gold; up to 300, stratified by corpus (seed 0). Per sentence: F_conf (gold rendered into the highest-
weight renderable mode member's vocabulary, EQUIV under identity asserted), F_tok (fresh random tokens), F_syn
(WordNet synonyms); the SAME operator edit (DROP_CONJ, ADD_CONJ-existing-predicate, QUANT, IMPL_REV, NEG, ARG_SWAP)
rendered in each vocabulary. iso = mutant EQUIV to gold under SOME L1 bijection (automorphism blind spot).
Probes are scored against the 9 real outputs with the FROZEN weights: DC, DC_L2w, S0_L1, S2_L3, LC_maj*, VC, and DC
error typing (contract + repair). Output: work/m1_probes.jsonl, work/m1_build_info.json.
Usage: m1_build_score.py [n_sentences|all]"""
import json
import multiprocessing as mp
import random
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from loguru import logger  # noqa: E402

from dc.common import (LOGS, WORK, PairStore, _init_worker, detect_cpus, jdump, load_frame, rj, wj)  # noqa: E402

logger.remove()
logger.add(sys.stdout, level="INFO", format="{time:HH:mm:ss}|{level:<7}|{message}")
logger.add(str(LOGS / "m1.log"), level="DEBUG")
N_TARGET = 300


def frozen_weights() -> dict:
    return json.loads((ROOT / "frozen_dc_config.json").read_text())["weights"]


def sentence_table():
    rows = [r for r in load_frame() if r["fold"] == "heldout_confirm"]
    cm = {c["raw"]: (c["canon"] if c["ok"] else None) for c in rj(WORK / "canon.jsonl")}
    by = defaultdict(list)
    for r in rows:
        by[r["sentence_id"]].append(r)
    T = {}
    for sid, rs in by.items():
        rs = sorted(rs, key=lambda r: r["system"])
        T[sid] = {"sid": sid, "sentence": rs[0]["sentence"], "corpus": rs[0]["corpus"],
                  "tercile": rs[0]["complexity_tercile"], "gold_faithful_final": rs[0]["gold_faithful_final"],
                  "gold": cm.get(rs[0]["gold_fol_audited"] or ""), "systems": [r["system"] for r in rs],
                  "outs": [cm.get(r["candidate_fol"] or "") for r in rs], "item_ids": [r["item_id"] for r in rs],
                  "y": [r["output"] for r in rs], "label_source": [r["label_source"] for r in rs]}
    return T


def mode_of(t: dict, st: PairStore, W: dict, key: str = "rel"):
    from dc.core import clusters

    def rr(a, b):
        x = st.get(a, b)
        return x.get(key) if x else "UNKNOWN"
    cl = clusters(t["outs"], rr)
    mass, size = Counter(), Counter()
    for c, s in zip(cl, t["systems"]):
        if c >= 0:
            mass[c] += W[s]
            size[c] += 1
    if not mass:
        return cl, None
    mode = max(mass, key=lambda c: (mass[c], size[c], -c))
    return cl, mode


# ------------------------------------------------------------------------------------------ build (worker)
_ST = None


def _winit():
    _init_worker(4.0)
    global _ST
    from dc.common import PairStore as PS
    _ST = PS()


def build_sentence(job: dict) -> dict:
    import fol_core as fc
    from dc import front, probes as PR
    from dc.relation import pair_relation
    t, W, members = job["t"], job["W"], job["members"]
    G = front.parse_canon(t["gold"])
    res = {"sid": t["sid"], "ok": False, "probes": [], "why": None}
    rendered = None
    for i in members:
        R = t["outs"][i]
        rec = _ST.get(t["gold"], R)
        if rec is None:
            continue
        mpp = PR.map_to_peer(t["gold"], R, rec)
        if mpp is None:
            continue
        Fc = fc.rename(G, mpp[0], mpp[1])
        pr = pair_relation(Fc, front.parse_canon(R))
        if pr["rel"] == "EQUIV":
            rendered = (i, mpp, Fc, rec.get("level"))
            break
    if rendered is None:
        res["why"] = "no_renderable_mode_member"
        return res
    ri, (pm, cm), Fc, lvl = rendered
    tpm, tcm = PR.tokmap(G, t["sid"])
    spm, scm = PR.synmap(G)
    arms = {"conf": (pm, cm), "tok": (tpm, tcm), "syn": (spm, scm)}
    probes = []

    def add(arm, kind, ast, op=None, fresh=False):
        s = fc.to_str(ast)
        c = front.canon(s)
        probes.append({"sid": t["sid"], "arm": arm, "kind": kind, "op": op, "fol": c["canon"] if c["ok"] else None,
                       "canon_same_ast": bool(c["ok"] and c["ast"] == ast), "fresh_pred": fresh})
    for arm, (a, b) in arms.items():
        add(arm, "F", fc.rename(G, a, b))
    mut_info = {}
    for op in PR.OPS:
        m = PR.mutant(G, op, t["sid"])
        if not m.get("kept"):
            mut_info[op] = {"kept": False, "applicable": m.get("applicable")}
            continue
        M = m["ast"]
        mut_info[op] = {"kept": True, "fresh_pred": m.get("fresh_pred", False), "fol_gold_vocab": fc.to_str(M)}
        for arm, (a, b) in arms.items():
            if arm == "conf" and m.get("fresh_pred"):
                continue
            add(arm, "M", fc.rename(M, a, b), op=op, fresh=m.get("fresh_pred", False))
    res.update(ok=True, probes=probes, mut=mut_info, rep_index=ri, rep_system=t["systems"][ri], render_level=lvl,
               gold_vocab_mutants={op: v.get("fol_gold_vocab") for op, v in mut_info.items() if v.get("kept")})
    return res


# ------------------------------------------------------------------------------------------ score (worker)
def score_sentence(job: dict) -> list[dict]:
    from dc.core import clusters, directional_consensus, repair_type, vocab_conformity, rel_of
    t, W, probes = job["t"], job["W"], job["probes"]
    rf = lambda a, b: _ST.get(a, b) or {"rel": "UNKNOWN", "rel_L1": "UNKNOWN", "rel_L2": "UNKNOWN", "rel_L3": "UNKNOWN"}  # noqa: E731
    out = []
    pid = t["systems"]
    for p in probes:
        rec = dict(p)
        if p["fol"] is None:
            rec.update(DC=0.5, DC_cov=False)
            out.append(rec)
            continue
        for name, key, weighted in (("DC", "rel_L3", True), ("DC_L2w", "rel_L2", True), ("S0_L1", "rel_L1", False),
                                    ("S2_L3", "rel_L3", False)):
            r = directional_consensus(None, p["fol"], t["outs"], pid, W if weighted else None, rel_fn=rf, rel_key=key,
                                      self_weight=sorted(W.values())[len(W) // 2] if weighted else 1.0,
                                      with_type=(name == "DC" and p["kind"] == "M"))
            rec[name] = r["score"]
            rec[name + "_cov"] = r["covered"]
            if name == "DC":
                rec["rels"] = [x["rel"] for x in r["per_peer"]]
                if p["kind"] == "M":
                    rec["type_contract"] = r.get("error_type")
                    rec["rel_to_mode"] = r.get("rel_to_mode")
                    rep = r.get("mode_rep")
                    if rep is not None and not r.get("in_mode"):
                        try:
                            rec["type_repair"] = repair_type(p["fol"], rep, rf(p["fol"], rep)) or "other"
                        except Exception as e:  # noqa: BLE001
                            rec["type_repair"] = f"error:{type(e).__name__}"
                    else:
                        rec["type_repair"] = "none"
        items = [p["fol"]] + t["outs"]
        cl = clusters(items, lambda a, b: rel_of(rf(a, b), "rel_L1"))
        n_parse = sum(c is not None for c in items)
        size = sum(1 for d in cl if d == cl[0])
        rec["LC_maj_star"] = (size - 1) / (n_parse - 1) if n_parse >= 2 else 0.5
        vc = vocab_conformity(p["fol"], t["outs"])
        rec["VC"] = vc["score"]
        out.append(rec)
    return out


def pool_map(fn, jobs, workers):
    out = []
    with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn"), initializer=_winit) as ex:
        futs = {ex.submit(fn, j): j for j in jobs}
        for i, fu in enumerate(as_completed(futs)):
            try:
                out.append(fu.result())
            except Exception as e:  # noqa: BLE001
                logger.error(f"job failed: {e!r}")
            if i % 50 == 0:
                logger.info(f"  {fn.__name__} {i}/{len(jobs)}")
    return out


@logger.catch(reraise=True)
def main():
    t0 = time.time()
    lim = sys.argv[1] if len(sys.argv) > 1 else "all"
    workers = max(1, detect_cpus() - 1)
    W = frozen_weights()
    st = PairStore()
    T = sentence_table()
    elig, relaxed = [], []
    for sid, t in T.items():
        if t["gold_faithful_final"] is not True or t["gold"] is None:
            continue
        cl, mode = mode_of(t, st, W)
        if mode is None:
            continue
        members = sorted([i for i, c in enumerate(cl) if c == mode], key=lambda i: (-W[t["systems"][i]], i))
        eq_members = [i for i in members if (st.get(t["gold"], t["outs"][i]) or {}).get("rel") == "EQUIV"]
        some_eq = [i for i, o in enumerate(t["outs"]) if o and (st.get(t["gold"], o) or {}).get("rel") == "EQUIV"]
        if len(members) >= 2 and eq_members:
            elig.append((sid, members))
        elif len(some_eq) >= 1:
            relaxed.append((sid, sorted(some_eq, key=lambda i: (-W[t["systems"][i]], i))))
    logger.info(f"S1 eligible (mode>=2 EQUIV gold): {len(elig)}; relaxed pool: {len(relaxed)}")
    by_c = defaultdict(list)
    for sid, mem in elig:
        by_c[T[sid]["corpus"]].append((sid, mem))
    rng = random.Random(0)
    tot = len(elig)
    n_target = N_TARGET if lim == "all" else int(lim)
    chosen = []
    for c in sorted(by_c):
        L = sorted(by_c[c])
        rng.shuffle(L)
        k = round(n_target * len(L) / tot) if tot > n_target else len(L)
        chosen += L[:k]
    chosen = chosen[:n_target]
    flag_relaxed = False
    if len(chosen) < 150 and lim == "all":
        flag_relaxed = True
        rest = sorted(relaxed)
        rng.shuffle(rest)
        chosen += rest[: n_target - len(chosen)]
    logger.info(f"S1 chosen {len(chosen)} {Counter(T[s]['corpus'] for s, _ in chosen)} relaxed={flag_relaxed}")
    jobs = [{"t": T[sid], "W": W, "members": mem} for sid, mem in chosen]
    built = pool_map(build_sentence, jobs, workers)
    ok = [b for b in built if b["ok"]]
    logger.info(f"built {len(ok)}/{len(built)} ({Counter(b['why'] for b in built if not b['ok'])}) in {time.time()-t0:.0f}s")
    probes = [p for b in ok for p in b["probes"]]
    # pairs: probes x 9 outputs, and iso: gold-vocab mutant vs gold
    pairs = []
    for b in ok:
        t = T[b["sid"]]
        for p in b["probes"]:
            if p["fol"]:
                pairs += [(p["fol"], o) for o in t["outs"] if o]
        from dc import front
        for op, f in b["gold_vocab_mutants"].items():
            c = front.canon(f)
            if c["ok"]:
                pairs.append((c["canon"], t["gold"]))
    st.compute(pairs, workers=workers, want_lex=False, log=logger.info)
    # iso flags
    from dc import front
    for b in ok:
        t = T[b["sid"]]
        iso = {}
        for op, f in b["gold_vocab_mutants"].items():
            c = front.canon(f)
            r = st.get(c["canon"], t["gold"]) if c["ok"] else None
            iso[op] = {"iso_L1": bool(r and r.get("rel_L1") == "EQUIV"), "rel_L3_to_gold": (r or {}).get("rel"),
                       "rel_L2_to_gold": (r or {}).get("rel_L2")}
        b["iso"] = iso
    isomap = {(b["sid"], op): v for b in ok for op, v in b["iso"].items()}
    for p in probes:
        if p["kind"] == "M":
            p.update(isomap.get((p["sid"], p["op"]), {}))
    # score (workers reload the store)
    by_s = defaultdict(list)
    for p in probes:
        by_s[p["sid"]].append(p)
    sj = [{"t": T[sid], "W": W, "probes": ps} for sid, ps in by_s.items()]
    scored = pool_map(score_sentence, sj, workers)
    rows = [r for x in scored for r in x]
    for r in rows:
        t = T[r["sid"]]
        r["corpus"], r["tercile"], r["sentence"] = t["corpus"], t["tercile"], t["sentence"]
    tag = "" if lim == "all" else f"_mini{lim}"
    wj(WORK / f"m1_probes{tag}.jsonl", rows)
    jdump({"n_eligible": len(elig), "n_relaxed_pool": len(relaxed), "flag_relaxed": flag_relaxed,
           "n_chosen": len(chosen), "n_built": len(ok), "build_fail": dict(Counter(b["why"] for b in built if not b["ok"])),
           "per_corpus": dict(Counter(T[b["sid"]]["corpus"] for b in ok)),
           "render_level": dict(Counter(str(b["render_level"]) for b in ok)),
           "mutants": {op: dict(Counter((b["mut"].get(op, {}).get("kept"), b["mut"].get(op, {}).get("fresh_pred"))
                                        for b in ok)) for op in ["DROP_CONJ", "ADD_CONJ", "QUANT", "IMPL_REV", "NEG", "ARG_SWAP"]},
           "iso_counts": {op: sum(1 for b in ok if b["iso"].get(op, {}).get("iso_L1")) for op in
                          ["DROP_CONJ", "ADD_CONJ", "QUANT", "IMPL_REV", "NEG", "ARG_SWAP"]},
           "canon_same_ast_rate": sum(p["canon_same_ast"] for p in probes) / max(1, len(probes)),
           "n_probes": len(probes), "seconds": time.time() - t0}, WORK / f"m1_build_info{tag}.json")
    logger.info(f"M1 done: {len(rows)} probe rows in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
