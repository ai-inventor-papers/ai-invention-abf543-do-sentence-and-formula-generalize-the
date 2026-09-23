"""Zero-LLM held-out baselines: LC_onecoin over the 9 systems (all 700 sentences = S_all) and B3sc
(self-consistency: share of the same system's 5 temperature samples bijection-equivalent to its greedy output;
gpt-4.1-mini and llama-3.1-8b only). Pairwise blind-bijection equivalence runs in a spawn ProcessPool with a
per-pair wall; a timeout / 'unlabeled' counts as NOT equivalent and is logged.
"""
from __future__ import annotations

import collections as C
import itertools
import json
import multiprocessing as mp
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np
from loguru import logger

import common
from common import DATA, RESULTS, append_jsonl, read_jsonl

PAIRS = DATA / "lc_pairs.jsonl"


def _pair_worker(job: tuple[str, str, str]) -> dict:
    import common  # noqa: F401,F811
    import fol_core as fc
    key, a, b = job
    t0 = time.time()
    try:
        r = fc.find_bijections(fc.parse(a), fc.parse(b), wall_s=10.0)
        lab = r["label"]
        reason = r.get("reason")
    except Exception as e:  # noqa: BLE001
        lab, reason = "unlabeled", f"err:{type(e).__name__}"
    return {"key": key, "label": lab, "reason": reason, "s": round(time.time() - t0, 3)}


def pair_labels(jobs: list[tuple[str, str, str]], workers: int) -> dict[str, str]:
    done = {r["key"]: r["label"] for r in read_jsonl(PAIRS)}
    todo = [j for j in jobs if j[0] not in done]
    logger.info(f"pairs: {len(done)} cached, {len(todo)} to run")
    if todo:
        t0 = time.time()
        with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn")) as ex:
            futs = [ex.submit(_pair_worker, j) for j in todo]
            buf = []
            for i, fu in enumerate(as_completed(futs)):
                r = fu.result()
                done[r["key"]] = r["label"]
                buf.append(r)
                if len(buf) >= 200:
                    append_jsonl(PAIRS, buf)
                    buf = []
                if (i + 1) % 2000 == 0:
                    logger.info(f"  pairs {i + 1}/{len(todo)} ({time.time() - t0:.0f}s)")
            append_jsonl(PAIRS, buf)
    return done


def run(workers: int = 2) -> dict:
    sys.path.insert(0, str(common.ARMB / "src"))
    from latent_class import em
    tg = [json.loads(l) for l in (DATA / "heldout_targets.jsonl").read_text().splitlines()]
    hc = [t for t in tg if t["group"] == "heldout_confirm"]
    samples = [json.loads(l) for l in (DATA / "heldout_samples.jsonl").read_text().splitlines()]
    by_sid = C.defaultdict(dict)
    for t in hc:
        by_sid[t["sid"]][t["system"]] = t
    jobs = []
    for sid, d in by_sid.items():
        for a, b in itertools.combinations(sorted(d), 2):
            fa, fb = d[a]["fol_folio"], d[b]["fol_folio"]
            if fa and fb:
                jobs.append((f"{sid}|{a}|{b}", fa, fb))
    # B3sc jobs: greedy vs each sample of the same system
    greedy = {(t["sid"], t["system"]): t for t in hc}
    sjobs = []
    for s in samples:
        g = greedy.get((s["sid"], s["system"]))
        if g and g["fol_folio"] and s["fol_folio"]:
            sjobs.append((f"S|{s['item_id']}", g["fol_folio"], s["fol_folio"]))
    labels = pair_labels(jobs + sjobs, workers)
    n_unl = sum(1 for j in jobs + sjobs if labels.get(j[0]) == "unlabeled")

    # one-coin latent class over 9 systems (unlabeled pairs = not equivalent)
    systems = sorted({t["system"] for t in hc})
    obs = []
    for sid, d in sorted(by_sid.items()):
        po = {s: bool(d[s]["fol_folio"]) for s in systems if s in d}
        syss = sorted(po)
        parent = {s: s for s in syss}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        for a, b in itertools.combinations(syss, 2):
            if po[a] and po[b] and labels.get(f"{sid}|{a}|{b}") == "equiv":
                parent[find(a)] = find(b)
        roots, cl = {}, {}
        for s in syss:
            cl[s] = roots.setdefault(find(s), len(roots))
        obs.append({"sid": sid, "systems": syss, "cls": cl, "parse_ok": po,
                    "valid": sorted({cl[s] for s in syss if po[s]})})
    t0 = time.time()
    fit = em(obs, systems, restarts=5, n_iter=150)
    logger.info(f"EM done in {time.time() - t0:.0f}s: pi={fit['pi'][0]:.3f} rho={fit['rho']:.3f}")
    rows = []
    for ob, post in zip(obs, fit["post"]):
        n_parse = sum(ob["parse_ok"].values())
        for s in ob["systems"]:
            iid = by_sid[ob["sid"]][s]["item_id"]
            cov = ob["parse_ok"][s] and n_parse >= 2
            sc = post.get(ob["cls"][s], 0.0) if ob["parse_ok"][s] else 0.0
            size = sum(1 for s2 in ob["systems"] if ob["parse_ok"][s2] and ob["cls"][s2] == ob["cls"][s])
            maj = (size - 1) / (n_parse - 1) if (ob["parse_ok"][s] and n_parse >= 2) else 0.0
            rows.append({"item_id": iid, "metric": "LC_onecoin", "score": float(sc), "covered": bool(cov)})
            rows.append({"item_id": iid, "metric": "LC_maj", "score": float(maj), "covered": bool(cov)})
    # B3sc
    per = C.defaultdict(list)
    for s in samples:
        g = greedy.get((s["sid"], s["system"]))
        if g is None:
            continue
        lab = labels.get(f"S|{s['item_id']}")
        if lab is not None:
            per[g["item_id"]].append(lab == "equiv")
    for g in hc:
        if g["system"] not in ("gpt-4.1-mini", "llama-3.1-8b"):
            continue
        eq = per.get(g["item_id"], [])
        rows.append({"item_id": g["item_id"], "metric": "B3sc",
                     "score": float(np.mean(eq)) if (eq and g["fol_folio"]) else 0.5,
                     "covered": bool(eq and g["fol_folio"]), "n_samples": len(eq)})
    info = {"p_w": {s: fit["p"][(0, s)] for s in systems}, "pi": fit["pi"][0], "rho": fit["rho"],
            "loglik": fit["ll"], "iters": fit["iters"], "n_pairs": len(jobs), "n_sample_pairs": len(sjobs),
            "n_unlabeled_pairs_counted_nonequiv": n_unl,
            "equiv_share": float(np.mean([labels.get(j[0]) == "equiv" for j in jobs])) if jobs else None}
    (RESULTS / "lc_info.json").write_text(json.dumps(info, indent=1))
    with open(RESULTS / "zero_llm_scores.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return info


def run_contamination(workers: int = 2) -> dict:
    """LC posteriors for the entity-renamed contamination sentences (9 systems each), computed with ONE E-step
    under the p_w / pi / rho fitted on heldout_confirm (same model for originals and paraphrases)."""
    sys.path.insert(0, str(common.ARMB / "src"))
    from latent_class import _lik
    info = json.loads((RESULTS / "lc_info.json").read_text())
    tg = [json.loads(l) for l in (DATA / "heldout_targets.jsonl").read_text().splitlines()]
    con = [t for t in tg if t["group"] == "contamination"]
    by_sid = C.defaultdict(dict)
    for t in con:
        by_sid[t["sid"]][t["system"]] = t
    jobs = []
    for sid, d in by_sid.items():
        for a, b in itertools.combinations(sorted(d), 2):
            if d[a]["fol_folio"] and d[b]["fol_folio"]:
                jobs.append((f"C|{sid}|{a}|{b}", d[a]["fol_folio"], d[b]["fol_folio"]))
    labels = pair_labels(jobs, workers)
    p, pi, rho = info["p_w"], info["pi"], info["rho"]
    rows = []
    for sid, d in by_sid.items():
        syss = sorted(d)
        po = {s: bool(d[s]["fol_folio"]) for s in syss}
        parent = {s: s for s in syss}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        for a, b in itertools.combinations(syss, 2):
            if po[a] and po[b] and labels.get(f"C|{sid}|{a}|{b}") == "equiv":
                parent[find(a)] = find(b)
        roots, cl = {}, {}
        for s in syss:
            cl[s] = roots.setdefault(find(s), len(roots))
        ob = {"systems": syss, "cls": cl, "parse_ok": po, "valid": sorted({cl[s] for s in syss if po[s]})}
        K = len(ob["valid"])
        w = {c: pi / K * _lik(ob, c, p, rho) for c in ob["valid"]}
        w[None] = (1 - pi) * _lik(ob, None, p, rho) if K else _lik(ob, None, p, rho)
        Z = sum(w.values())
        n_parse = sum(po.values())
        for s in syss:
            sc = (w.get(cl[s], 0.0) / Z) if po[s] else 0.0
            size = sum(1 for s2 in syss if po[s2] and cl[s2] == cl[s])
            maj = (size - 1) / (n_parse - 1) if (po[s] and n_parse >= 2) else 0.0
            cov = po[s] and n_parse >= 2
            rows.append({"item_id": d[s]["item_id"], "metric": "LC_onecoin", "score": float(sc), "covered": bool(cov)})
            rows.append({"item_id": d[s]["item_id"], "metric": "LC_maj", "score": float(maj), "covered": bool(cov)})
    append_jsonl(RESULTS / "zero_llm_scores.jsonl", rows)
    return {"n_contamination_rows_scored": len(rows) // 2, "n_pairs": len(jobs)}


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[2] == "contamination":
        logger.remove()
        logger.add(sys.stdout, level="INFO")
        print(run_contamination(int(sys.argv[1])))
        sys.exit(0)
    logger.remove()
    logger.add(sys.stdout, level="INFO")
    logger.add(common.ROOT / "logs" / "stage_lc.log", level="DEBUG", rotation="20 MB")
    print(json.dumps(run(int(sys.argv[1]) if len(sys.argv) > 1 else 2), indent=1))
