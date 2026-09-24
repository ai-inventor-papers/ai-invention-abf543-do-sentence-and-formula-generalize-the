#!/usr/bin/env python3
"""M3: shared-bias boundary.
(a) dose curve: S3 = 200 M1 sentences (seed 2), ops DROP_CONJ/ADD_CONJ/QUANT/IMPL_REV (non-iso, tok arm);
    peers8 = 9 real outputs minus one seeded-random system; the first k (nested seeded permutation; sensitivity:
    peers EQUIV to F first) replaced by independent tok-renamed copies of M, each inheriting the replaced weight;
    detection(k) = mean 1[DC(F) > DC(M)] + 0.5 tie, vs the ANALYTIC curve from the real relations.
(b) DC+arb for k in {4,6,8}: two heaviest clusters over peers_k ∪ {F_tok, M_tok}; world separating their reps
    (tvjt.find_world); verbalised in a real peer's vocabulary (else gold vocabulary: oracle_vocab); gemini-2.5-flash
    TRUE/FALSE; DC+arb = 0.5 DC + 0.5 1[C in chosen].
(c) real shared bias on all 700 dev sentences: wrong_conc bins, within-sentence concordance slope, DC+arb (one call
    per sentence with >= 2 clusters).
Outputs work/m3_*.jsonl, results/m3_boundary.json."""
import asyncio
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
sys.path.insert(0, str(ROOT / "scripts"))
from loguru import logger  # noqa: E402

from dc.common import LOGS, RES, WORK, PairStore, _init_worker, detect_cpus, jdump, rj, wj  # noqa: E402
from dc import stats as ST  # noqa: E402

logger.remove()
logger.add(sys.stdout, level="INFO", format="{time:HH:mm:ss}|{level:<7}|{message}")
logger.add(str(LOGS / "m3.log"), level="DEBUG")
OPS3 = ["DROP_CONJ", "ADD_CONJ", "QUANT", "IMPL_REV"]
KS = [0, 2, 4, 6, 8]
ARB_PROMPT = ("Sentence: \"{S}\"\n\n{W}\n\nIs the sentence TRUE or FALSE in this situation? Answer TRUE or FALSE.")
_ST = None


def _winit():
    _init_worker(4.0)
    global _ST
    from dc.common import PairStore as PS
    _ST = PS()


def rf(a, b):
    if a == b:
        return {"rel": "EQUIV", "rel_L3": "EQUIV", "rel_L2": "EQUIV", "rel_L1": "EQUIV"}
    r = _ST.get(a, b)
    if r is None:
        from dc.pairs import compute_record, oriented
        rr = compute_record(a, b, want_lex=False)
        _ST.d[rr["k"]] = rr
        r = oriented(rr, a == rr["lo"])
    return r


# ------------------------------------------------------------------------------------------ worlds / prompts
def world_prompt(sentence: str, A: str, B: str, gloss_vocab_ok: bool) -> dict | None:
    """World separating A from B (B mapped into A's vocabulary by the DC alignment), verbalised in A's vocabulary.
    Returns {prompt, A_value, B_value, n} or None."""
    import fol_core as fc
    import tvjt
    from dc import front
    from dc.align import apply_map
    Aa, Ba = front.parse_canon(A), front.parse_canon(B)
    rec = rf(A, B)
    # rename B into A's symbols along the record's map (unmapped B symbols stay fresh)
    pm, cm = {}, {}
    lo = rec.get("lo") or min(A, B)
    tgt_is_a = (rec.get("target") == "A") == (A == lo)
    for kind, s, t in rec.get("map") or []:
        if t is None:
            continue
        if tgt_is_a:
            (pm if kind == "P" else cm)[s] = t   # source = B
        else:
            (pm if kind == "P" else cm)[t] = s   # source = A: B symbol t <- A symbol s
    pB = fc.predicates(Ba, strict=False) or {}
    pmap = {p: pm.get(p, p if p not in (fc.predicates(Aa, strict=False) or {}) else p + "X") for p in pB}
    cmap = {c: cm.get(c, c) for c in fc.constants(Ba)}
    Bm = fc.rename(Ba, pmap, cmap)
    w = None
    for prefer, nmax in ((1, 4), (0, 4), (0, 5)):
        try:
            w = tvjt.find_world(Aa, Bm, prefer=prefer, nmax=nmax, timeout_ms=3000)
        except Exception:  # noqa: BLE001 - arbiter abstains
            w = None
        if w is not None:
            break
    if w is None:
        return None
    preds = {**(fc.predicates(Aa, strict=False) or {}), **(fc.predicates(Bm, strict=False) or {})}
    try:
        txt, _ = tvjt.verbalize_world(w, preds)
    except Exception:  # noqa: BLE001
        return None
    return {"prompt": ARB_PROMPT.format(S=sentence, W=txt), "A_value": w["F_value"], "B_value": w["M_value"], "n": w["n"]}


def heaviest_two(items: list[str], wts: list[float], relfn=None):
    from dc.core import clusters
    relfn = relfn or rf
    cl = clusters(items, lambda a, b: relfn(a, b).get("rel_L3"))
    mass, size = Counter(), Counter()
    for c, w in zip(cl, wts):
        if c >= 0:
            mass[c] += w
            size[c] += 1
    order = sorted(mass, key=lambda c: (-mass[c], -size[c], c))
    return cl, order[:2], mass


# ------------------------------------------------------------------------------------------ (a)+(b) worker
def dose_job(job):
    """One (sentence, op): scores for k in KS, both orders; arbiter prompt specs for k in {4,6,8}."""
    import fol_core as fc
    from dc import front, probes as PR
    from dc.core import directional_consensus
    W = job["W"]
    t = job["t"]
    F, M = job["F_tok"], job["M_tok"]
    Mg = front.parse_canon(job["M_gold"])
    real = [(s, o) for s, o in zip(t["systems"], t["outs"]) if s != job["drop"]]
    peers8 = real
    rng = random.Random(f"{t['sid']}|{job['op']}|perm")
    perm = list(range(len(peers8)))
    rng.shuffle(perm)
    # sensitivity: faithful-cluster (EQUIV to F) peers first
    feq = [i for i in range(len(peers8)) if peers8[i][1] and rf(F, peers8[i][1]).get("rel_L3") == "EQUIV"]
    perm_f = feq + [i for i in perm if i not in feq]
    copies = []
    for j in range(8):
        pm, cm = PR.tokmap(Mg, f"{t['sid']}|{job['op']}|copy{j}")
        c = front.canon(fc.to_str(fc.rename(Mg, pm, cm)))
        copies.append(c["canon"] if c["ok"] else None)
    med = sorted(W.values())[len(W) // 2]
    out = {"sid": t["sid"], "op": job["op"], "rows": [], "arb": [], "audit": []}
    audit = random.Random(f"{t['sid']}|{job['op']}|audit").random() < 0.10
    for order_name, order in (("random", perm), ("faithful_first", perm_f)):
        for k in KS:
            rep = set(order[:k])
            peers, pid = [], []
            for i, (s, o) in enumerate(peers8):
                peers.append(copies[len(pid) % 8] if i in rep else o)
                pid.append(s)
            # copies: distinct per replaced slot
            ci = 0
            for i in range(len(peers8)):
                if i in rep:
                    peers[i] = copies[ci]
                    ci += 1
            sF = directional_consensus(None, F, peers, pid, W, rel_fn=rf, rel_key="rel_L3", with_type=False,
                                       self_weight=med)["score"]
            sM = directional_consensus(None, M, peers, pid, W, rel_fn=rf, rel_key="rel_L3", with_type=False,
                                       self_weight=med)["score"]
            sF2 = directional_consensus(None, F, peers, pid, W, rel_fn=rf, rel_key="rel_L2", with_type=False,
                                        self_weight=med)["score"]
            sM2 = directional_consensus(None, M, peers, pid, W, rel_fn=rf, rel_key="rel_L2", with_type=False,
                                        self_weight=med)["score"]
            # analytic: real relations of F and M to the unreplaced peers; copies behave like M exactly
            relFM = rf(F, M).get("rel_L3")
            num_f = num_m = den = 0.0
            for i, (s, o) in enumerate(peers8):
                w = W[s]
                if i in rep:
                    den += w
                    num_f += w * (relFM == "EQUIV")
                    num_m += w
                elif o is not None:
                    rF, rM = rf(F, o).get("rel_L3"), rf(M, o).get("rel_L3")
                    if rF == "UNKNOWN" or rM == "UNKNOWN":
                        continue
                    den += w
                    num_f += w * (rF == "EQUIV")
                    num_m += w * (rM == "EQUIV")
            aF, aM = (num_f / den, num_m / den) if den else (0.5, 0.5)
            row = {"order": order_name, "k": k, "DC_F": sF, "DC_M": sM, "det": ST.det(sF, sM),
                   "DCL2_F": sF2, "DCL2_M": sM2, "det_L2": ST.det(sF2, sM2),
                   "analytic_F": aF, "analytic_M": aM, "det_analytic": ST.det(round(aF, 12), round(aM, 12)),
                   "rel_F_M": relFM, "copy_equiv_M": [rf(M, c).get("rel_L3") == "EQUIV" for c in copies[:k] if c]}
            out["rows"].append(row)
            if order_name == "random" and k in (4, 6, 8):
                items = [F, M] + peers
                wts = [med, med] + [W[s] for s in pid]
                cset = set(c for c in copies if c)

                def rel_inh(a, b):
                    # exact for F/M vs copies; copy-copy EQUIV; copy-real inherits M-real (10% audited below)
                    if a in cset and b in cset:
                        return {"rel_L3": "EQUIV"}
                    if a in cset and b not in (F, M):
                        return rf(M, b)
                    if b in cset and a not in (F, M):
                        return rf(a, M)
                    return rf(a, b)
                cl, top2, mass = heaviest_two(items, wts, rel_inh)
                if audit:
                    for c in [x for x in peers if x in cset][:2]:
                        for o in [x for x in peers if x not in cset and x][:3]:
                            ex_, inh = rf(c, o).get("rel_L3"), rf(M, o).get("rel_L3")
                            out["audit"].append({"exact": ex_, "inherited": inh, "match": ex_ == inh})
                spec = {"k": k, "n_clusters": len(mass)}
                if len(top2) < 2:
                    spec["abstain"] = "one_cluster"
                    out["arb"].append(spec)
                    continue
                reps, meaning = [], []
                oracle = False
                for c in top2:
                    mem = [i for i in range(len(items)) if cl[i] == c]
                    real_mem = [i for i in mem if i >= 2 and peers[i - 2] in [o for _, o in peers8]
                                and (i - 2) not in rep]
                    if real_mem:
                        rp = max(real_mem, key=lambda i: wts[i])
                        reps.append(items[rp])
                    else:
                        # no real peer: F or M in the gold vocabulary (oracle vocabulary)
                        oracle = True
                        reps.append(job["F_gold"] if 0 in mem else job["M_gold"])
                    meaning.append("F" if 0 in mem else ("M" if 1 in mem else "other"))
                spec.update({"reps": reps, "meaning": meaning, "oracle_vocab": oracle,
                             "F_cluster": cl[0], "M_cluster": cl[1], "top2": top2})
                wp = world_prompt(t["sentence"], reps[0], reps[1], True)
                if wp is None:
                    spec["abstain"] = "no_world"
                else:
                    spec.update(wp)
                spec["DC_F"], spec["DC_M"] = sF, sM
                spec["F_in"] = [cl[0] == c for c in top2]
                spec["M_in"] = [cl[1] == c for c in top2]
                out["arb"].append(spec)
    return out


# ------------------------------------------------------------------------------------------ (c) worker
def real_job(job):
    t, W = job["t"], job["W"]
    items = t["outs"]
    wts = [W[s] for s in t["systems"]]
    cl, top2, mass = heaviest_two(items, wts)
    res = {"sid": t["sid"], "cl": cl, "mass": {str(k): v for k, v in mass.items()}, "top2": top2}
    if len(top2) == 2:
        reps = []
        for c in top2:
            mem = [i for i in range(len(items)) if cl[i] == c]
            reps.append(items[max(mem, key=lambda i: (wts[i], -i))])
        res["reps"] = reps
        wp = world_prompt(t["sentence"], reps[0], reps[1], True)
        if wp is None:
            res["abstain"] = "no_world"
        else:
            res.update(wp)
    return res


def pool(fn, jobs, workers):
    out = []
    with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn"), initializer=_winit) as ex:
        futs = [ex.submit(fn, j) for j in jobs]
        for i, fu in enumerate(as_completed(futs)):
            try:
                out.append(fu.result())
            except Exception as e:  # noqa: BLE001
                logger.error(f"{fn.__name__} failed: {e!r}")
            if i % 200 == 0:
                logger.info(f"  {fn.__name__} {i}/{len(jobs)}")
    return out


def ask(specs: list[dict], phase: str, cap: float) -> dict:
    """One call per distinct prompt (cache key = prompt; shared across k)."""
    from dc.llm import FLASH, run_bodies
    prompts = sorted({s["prompt"] for s in specs if s.get("prompt")})

    def body(p, mt):
        return {"model": FLASH, "messages": [{"role": "user", "content": p}], "temperature": 0.0, "max_tokens": mt,
                "reasoning": {"max_tokens": 0, "exclude": True}}
    res, info = asyncio.run(run_bodies(phase, cap, [body(p, 5) for p in prompts], [f"{phase}:{i}" for i in range(len(prompts))]))
    ans = {}
    retry = []
    for p, r in zip(prompts, res):
        a = parse_tf((r or {}).get("text"))
        ans[p] = a
        if a is None and r is not None and r.get("text") is not None:
            retry.append(p)
    if retry:
        rr, _ = asyncio.run(run_bodies(phase, cap, [body(p, 16) for p in retry], [f"{phase}:retry{i}" for i in range(len(retry))], n_pilot=0))
        for p, r in zip(retry, rr):
            ans[p] = parse_tf((r or {}).get("text"))
    logger.info(f"[{phase}] {json.dumps(info)} parsed {sum(v is not None for v in ans.values())}/{len(ans)}")
    return {"answers": ans, "info": info}


def parse_tf(t):
    if not t:
        return None
    u = t.strip().upper()
    if u.startswith("TRUE"):
        return True
    if u.startswith("FALSE"):
        return False
    if "TRUE" in u and "FALSE" not in u:
        return True
    if "FALSE" in u and "TRUE" not in u:
        return False
    return None


@logger.catch(reraise=True)
def main():
    t0 = time.time()
    workers = max(1, detect_cpus() - 1)
    from m1_build_score import sentence_table
    W = json.loads((ROOT / "frozen_dc_config.json").read_text())["weights"]
    T = sentence_table()
    P = rj(WORK / "m1_probes.jsonl")
    tokF = {p["sid"]: p["fol"] for p in P if p["arm"] == "tok" and p["kind"] == "F"}
    tokM = {(p["sid"], p["op"]): p for p in P if p["arm"] == "tok" and p["kind"] == "M"}
    # gold-vocabulary F and M (for copies and oracle vocab)
    from dc import front, probes as PR
    sids = sorted(tokF)
    rng = random.Random(2)
    by_c = defaultdict(list)
    for s in sids:
        by_c[T[s]["corpus"]].append(s)
    S3 = []
    for c in sorted(by_c):
        L = list(by_c[c])
        rng.shuffle(L)
        S3 += L[: round(200 * len(L) / len(sids))]
    S3 = sorted(S3)[:200]
    jobs = []
    for s in S3:
        t = T[s]
        G = front.parse_canon(t["gold"])
        drop = random.Random(f"{s}|drop").choice(t["systems"])
        for op in OPS3:
            p = tokM.get((s, op))
            if not p or p.get("iso_L1") or not p.get("fol"):
                continue
            m = PR.mutant(G, op, s)
            if not m.get("kept"):
                continue
            import fol_core as fc
            jobs.append({"t": t, "W": W, "op": op, "F_tok": tokF[s], "M_tok": p["fol"], "drop": drop,
                         "M_gold": front.canon(m["fol"])["canon"], "F_gold": t["gold"]})
    logger.info(f"M3(a) S3={len(S3)} sentences, {len(jobs)} (sentence, op) jobs")
    dres = pool(dose_job, jobs, workers)
    wj(WORK / "m3_dose.jsonl", dres)
    logger.info(f"dose done {time.time() - t0:.0f}s")
    # (c) real: all 700 sentences
    rres = pool(real_job, [{"t": T[s], "W": W} for s in sorted(T)], workers)
    wj(WORK / "m3_real.jsonl", rres)
    logger.info(f"real clusters done {time.time() - t0:.0f}s")
    # LLM arbiter
    specs = [a for d in dres for a in d["arb"] if a.get("prompt")]
    A1 = ask(specs, "M3b_arb", 0.6)
    A2 = ask([r for r in rres if r.get("prompt")], "M3c_arb", 0.4)
    json.dump({"constructed": A1["answers"], "real": A2["answers"], "info": [A1["info"], A2["info"]]},
              open(WORK / "m3_arbiter_answers.json", "w"), ensure_ascii=False)
    logger.info(f"M3 compute done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
