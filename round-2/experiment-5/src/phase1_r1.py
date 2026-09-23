#!/usr/bin/env python3
"""PHASE 1 / STEP 0-2: regression test, RENAME2 generation, R1 aligner grid on SCREEN_DEV, selection, SCREEN_TEST report.

Stages (python phase1_r1.py --stage X):
  regress   legacy A3/A0 on 50 screen items must reproduce iter-1 screen_scores_signature.jsonl within 1e-9
  rename2   LLM-rename set: gpt-4.1-mini (T=0) renames every predicate of 150 SCREEN_TEST golds; WordNet-derived maps
            (> half of the new names are WordNet synonyms of the old ones) are dropped; the rename is verified to be an
            arity-preserving bijection (renaming back gives the identical AST). Never used for tuning.
  sigs      solver signatures for RENAME2 formulas + blind-spot supplement formulas (results/extra_formula_sigs.json)
  grid      24 aligner configs on SCREEN_DEV (A3, T0 text side): FA_rename, FA_logic, DET[op], AUROC_dev (blind-bijection
            labels, tie-break only); pre-registered selection; SCREEN_TEST report for chosen + legacy.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import random
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import screen_common as sc  # noqa: E402
import align2  # noqa: E402  (sigfaith on path via screen_common)

logger.remove()
logger.add(sys.stdout, level="INFO", format="{time:HH:mm:ss}|{level:<7}|{message}")
(ROOT / "logs").mkdir(exist_ok=True)
logger.add(ROOT / "logs" / "phase1_r1.log", rotation="30 MB", level="DEBUG")
RES = ROOT / "results"
RES.mkdir(exist_ok=True)
DET_OPS = ["NEG", "QUANT", "IMPL_REV", "DROP", "ADD", "ARG_SWAP"]
ALL_OPS = DET_OPS + ["ANDOR", "CARD", "MERGE", "SCOPE"]
LOGIC_RW = ["REORDER", "CONTRAPOS", "DEMORGAN", "PRENEX"]


# ------------------------------------------------------------------ regression
def stage_regress():
    ref = {}
    with (ROOT.parent.parent.parent / "iter_1" / "gen_art" / "gen_art_experiment_1" / "results" /
          "screen_scores_signature.jsonl").open() as f:
        for line in f:
            r = json.loads(line)
            if r["metric"] in ("A3", "A0"):
                ref[(r["item_id"], r["metric"])] = r
    its = sc.items({s["sid"] for s in sc.screen()["sentences"]})
    rng = random.Random(0)
    sample = rng.sample(its, 50)
    maxdiff = {"A3": 0.0, "A0": 0.0}
    n = {"A3": 0, "A0": 0}
    mism = []
    for it in sample:
        for v in ("A3", "A0"):
            # iter-1 run_metrics computed A0 with the A1 (LLM probe) text side: its '?' labels skip concepts
            r = sc.score_item(it, "legacy", side="T0" if v == "A3" else "T1a", variant=v)
            rr = ref.get((it["item_id"], v))
            if rr is None:
                continue
            d = abs(r["score"] - rr["score"])
            n[v] += 1
            maxdiff[v] = max(maxdiff[v], d)
            if d > 1e-9:
                mism.append({"item": it["item_id"], "v": v, "new": r["score"], "ref": rr["score"]})
    ok = all(m <= 1e-9 for m in maxdiff.values()) and all(n.values())
    out = {"n_compared": n, "max_abs_diff": maxdiff, "pass": ok, "mismatches": mism[:20]}
    (RES / "regression_test.json").write_text(json.dumps(out, indent=1))
    logger.info(f"REGRESSION {'PASS' if ok else 'FAIL'}: {out}")


# ------------------------------------------------------------------ RENAME2
RENAME_PROMPT = ("Here is a first-order logic formula:\n{f}\n\nRename EVERY predicate to a DIFFERENT but natural name with "
                 "the same meaning (use a paraphrase, an abbreviation, a different wording, or a compound, e.g. "
                 "IsAGreatPlace -> ExcellentLocation, Teacher -> Educator, OwnsCar -> HasAutomobile). Do NOT just use a "
                 "one-word dictionary synonym of the last word; do not change constants or variables. Predicates: {p}.\n"
                 "Return ONLY a JSON object mapping each old predicate name to its new name.")


def _wn_syn_set(word: str) -> set:
    from nltk.corpus import wordnet as wn
    out = set()
    for s in wn.synsets(word):
        out |= {l.lower() for l in s.lemma_names()}
    return out


def is_wordnet_rename(old: str, new: str) -> bool:
    from align import lem, split_name
    ot = [w for w in split_name(old)]
    nt = [w for w in split_name(new)]
    if not nt:
        return False
    syn = set()
    for w in ot:
        syn |= _wn_syn_set(w) | _wn_syn_set(lem(w))
    return lem(nt[-1]) in syn or nt[-1] in syn


def stage_rename2():
    import llm
    from fol_parse import preds, rename, to_str
    _, test = sc.splits()
    S = {s["sid"]: s for s in sc.screen()["sentences"]}
    jobs, meta = [], []
    for sid in test:
        p = sc.lparse(S[sid]["gold_fol"])
        if p is None or not p.preds:
            continue
        prompt = RENAME_PROMPT.format(f=S[sid]["gold_fol"], p=", ".join(sorted(p.preds)))
        jobs.append(dict(model="openai/gpt-4.1-mini", messages=[{"role": "user", "content": prompt}],
                         purpose="rename2", temperature=0.0, max_tokens=400))
        meta.append(sid)
    logger.info(f"RENAME2: {len(jobs)} calls (dry-run est ${len(jobs) * 0.0004:.3f})")
    res = llm.run(jobs, concurrency=16, est_cost_each=0.0006)
    rows, drops = [], defaultdict(int)
    import re
    for sid, r in zip(meta, res):
        if isinstance(r, Exception):
            drops["api_error"] += 1
            continue
        m = re.search(r"\{.*\}", r[0], re.S)
        try:
            mp_ = json.loads(m.group(0)) if m else None
        except json.JSONDecodeError:
            mp_ = None
        p = sc.lparse(S[sid]["gold_fol"])
        if not isinstance(mp_, dict):
            drops["bad_json"] += 1
            continue
        mp_ = {k: str(v).strip() for k, v in mp_.items() if k in p.preds}
        mp_ = {k: re.sub(r"[^A-Za-z0-9_]", "", v) for k, v in mp_.items()}
        if set(mp_) != set(p.preds) or any(not v or v == k for k, v in mp_.items()):
            drops["incomplete_or_identity"] += 1
            continue
        if len(set(mp_.values())) != len(mp_) or set(mp_.values()) & (set(p.preds) - set(mp_)):
            drops["not_bijective"] += 1
            continue
        n_wn = sum(is_wordnet_rename(k, v) for k, v in mp_.items())
        if n_wn > len(mp_) / 2:
            drops["wordnet_derived"] += 1
            continue
        new_ast = rename(p.ast, mp_)
        fol2 = to_str(new_ast)
        p2 = sc.lparse(fol2)
        inv = {v: k for k, v in mp_.items()}
        if p2 is None or preds(p2.ast) != {mp_[k]: a for k, a in p.preds.items()} or rename(p2.ast, inv) != p.ast:
            drops["verify_failed"] += 1
            continue
        rows.append({"rid": f"{sid}:R:RENAME2", "sid": sid, "kind": "RENAME2", "fol": fol2, "rename_map": mp_,
                     "n_wordnet_like": n_wn})
    (ROOT / "data" / "rename2.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    rep = {"n_requested": len(jobs), "n_kept": len(rows), "drops": dict(drops), "spent_total": llm.spent(),
           "model": "openai/gpt-4.1-mini", "prompt": RENAME_PROMPT}
    (RES / "rename2_report.json").write_text(json.dumps(rep, indent=1))
    logger.info(f"RENAME2: {rep}")


# ------------------------------------------------------------------ extra signatures
def _sig_worker(fol: str):
    sys.path.insert(0, str(ROOT / "legacy_armA" / "src"))
    from fol_parse import parse as p_
    from solver_sig import signature
    try:
        return fol, signature(p_(fol).ast, N=3, timeout_ms=5000, with_rel=True, rel_max_unary=8)
    except Exception as e:  # noqa: BLE001
        return fol, {"error": f"{type(e).__name__}: {e}"}


def compute_sigs(fols: list[str], out_path: Path, workers: int = 4):
    cache = json.loads(out_path.read_text()) if out_path.exists() else {}
    todo = sorted({f for f in fols if f not in cache and f not in sc.fsigs()})
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn")) as ex:
        futs = [ex.submit(_sig_worker, f) for f in todo]
        for fu in as_completed(futs):
            f, s = fu.result()
            cache[f] = s
    out_path.write_text(json.dumps(cache, ensure_ascii=False))
    logger.info(f"extra sigs: {len(todo)} computed in {time.time() - t0:.1f}s")


def stage_sigs():
    fols = []
    rp = ROOT / "data" / "rename2.jsonl"
    if rp.exists():
        fols += [json.loads(l)["fol"] for l in rp.read_text().splitlines()]
    for l in (ROOT / "data" / "blindspot_supplement.jsonl").read_text().splitlines():
        x = json.loads(l)
        fols += [x["fol"], x["gold_fol"]]
    fols = [f for f in fols if sc.lparse(f) is not None]
    compute_sigs(fols, sc.EXTRA_SIG)


# ------------------------------------------------------------------ grid
def evaluate(aligner, sids: set, rename2: list | None = None) -> dict:
    its = sc.items(sids)
    scores = {}
    for it in its:
        r = sc.score_item(it, aligner, side="T0", variant="A3")
        scores[it["item_id"]] = r["score"]
    gold = {it["sid"]: scores[it["item_id"]] for it in its if it["set"] == "gold"}
    out = {}
    fa = defaultdict(lambda: [0, 0])
    for it in its:
        if it["set"] != "rewrite":
            continue
        k = it["kind"]
        fa[k][0] += scores[it["item_id"]] < gold[it["sid"]]
        fa[k][1] += 1
    out["FA_rename"] = fa["SYN_RENAME"][0] / fa["SYN_RENAME"][1] if fa["SYN_RENAME"][1] else None
    nl = sum(fa[k][0] for k in LOGIC_RW)
    dl = sum(fa[k][1] for k in LOGIC_RW)
    out["FA_logic"] = nl / dl if dl else None
    out["FA_by_kind"] = {k: {"rate": v[0] / v[1], "n": v[1]} for k, v in fa.items() if v[1]}
    det = defaultdict(list)
    for it in its:
        if it["set"] != "mutant":
            continue
        m, g = scores[it["item_id"]], gold[it["sid"]]
        det[it["operator"]].append(1.0 if m < g else (0.5 if m == g else 0.0))
    out["DET"] = {op: (sum(v) / len(v), len(v)) for op, v in det.items()}
    real = [it for it in its if it["set"] == "real"]
    out["AUROC_real"] = sc.auroc([it["y_bij"] for it in real], [scores[it["item_id"]] for it in real])
    out["n_real"] = len(real)
    if rename2 is not None:
        rr = [x for x in rename2 if x["sid"] in sids]
        n = 0
        k = 0
        for x in rr:
            r = sc.score_item({"sid": x["sid"], "fol": x["fol"], "parse_ok": True}, aligner, side="T0", variant="A3")
            n += 1
            k += r["score"] < gold[x["sid"]]
        out["FA_RENAME2"] = k / n if n else None
        out["n_RENAME2"] = n
    return out


def make_aligner(cfg: dict):
    def f(preds, consts, concepts, anchors):
        return align2.align2(preds, consts, concepts, anchors, cfg)
    return f


def fallback_aligner(cfg: dict):
    """Pre-registered fallback: after align2, still-unaligned predicates join the argmax concept by
    all-mpnet-base-v2 embedding cosine if >= 0.4."""
    def f(preds, consts, concepts, anchors):
        A = align2.align2(preds, consts, concepts, anchors, cfg)
        left = [P for P, a in A["preds"].items() if a["cid"] is None]
        ncs = [c for c in concepts]
        if left and ncs:
            m = "sentence-transformers/all-mpnet-base-v2"
            Ec = align2.embed([align2.concept_phrase(c) for c in ncs], m)
            Es = align2.embed([" ".join(align2.split_name(P)) or P.lower() for P in left], m)
            sim = Ec @ Es.T
            for j, P in enumerate(left):
                i = int(sim[:, j].argmax())
                if sim[i, j] >= 0.4:
                    A["preds"][P] = {"cid": ncs[i]["cid"], "flip": A["preds"][P]["flip"], "covered": [],
                                     "how": f"fallback_mpnet:{sim[i, j]:.2f}"}
            covered = set()
            for a in A["preds"].values():
                if a["cid"] is not None:
                    covered.add(a["cid"])
                    covered |= set(a["covered"])
            covered |= set(A["consts"].values())
            denom = [c["cid"] for c in concepts if not (align2.is_optional(c) and c["cid"] not in covered)]
            A["coverage"] = (len(covered & set(denom)) / len(denom)) if denom else 0.0
            A["covered_cids"] = sorted(covered)
        return A
    return f


def select(results: dict, legacy: dict) -> tuple[str, bool, list]:
    """Pre-registered rule: among configs with DET[op] >= legacy_DET[op] - 0.03 for all 6 ops and
    FA_logic <= legacy + 0.01, pick min FA_rename; tie -> max AUROC_dev; tie -> simpler config.
    If none meets the DET constraint: max min-over-ops (DET - legacy_DET), flag R1_TARGET_MISSED."""
    ok = []
    for name, r in results.items():
        cond_det = all(r["res"]["DET"].get(op, (1, 0))[0] >= legacy["DET"].get(op, (0, 0))[0] - 0.03 for op in DET_OPS)
        cond_fa = (r["res"]["FA_logic"] or 0) <= (legacy["FA_logic"] or 0) + 0.01
        r["eligible"] = bool(cond_det and cond_fa)
        if r["eligible"]:
            ok.append(name)
    if ok:
        best = sorted(ok, key=lambda n: (results[n]["res"]["FA_rename"], -(results[n]["res"]["AUROC_real"] or 0),
                                         align2.simplicity(results[n]["cfg"])))
        return best[0], False, best
    marg = {n: min(r["res"]["DET"].get(op, (0, 0))[0] - legacy["DET"].get(op, (0, 0))[0] for op in DET_OPS)
            for n, r in results.items()}
    best = sorted(marg, key=lambda n: -marg[n])
    return best[0], True, best


def stage_grid(n_limit: int | None = None):
    dev, test = sc.splits()
    dev_s, test_s = set(dev[:n_limit] if n_limit else dev), set(test[:n_limit] if n_limit else test)
    rename2 = [json.loads(l) for l in (ROOT / "data" / "rename2.jsonl").read_text().splitlines()] \
        if (ROOT / "data" / "rename2.jsonl").exists() else []
    t0 = time.time()
    legacy_dev = evaluate("legacy", dev_s)
    logger.info(f"legacy DEV: FA_rename={legacy_dev['FA_rename']} FA_logic={legacy_dev['FA_logic']} "
                f"DET={ {k: round(v[0], 3) for k, v in legacy_dev['DET'].items()} } AUROC={legacy_dev['AUROC_real']} "
                f"({time.time() - t0:.0f}s)")
    results = {}
    for cfg in align2.grid():
        t1 = time.time()
        name = align2.cfg_name(cfg)
        r = evaluate(make_aligner(cfg), dev_s)
        results[name] = {"cfg": cfg, "res": r}
        logger.info(f"{name}: FA_rename={r['FA_rename']:.3f} FA_logic={r['FA_logic']:.3f} "
                    f"DET={ {k: round(v[0], 3) for k, v in r['DET'].items()} } AUROC={r['AUROC_real']} "
                    f"({time.time() - t1:.0f}s)")
    chosen, missed, ranking = select(results, legacy_dev)
    cfg = results[chosen]["cfg"]
    fallback_used = False
    fb_dev = None
    if missed or (results[chosen]["res"]["FA_rename"] or 0) > 0.05:
        fb_dev = evaluate(fallback_aligner(cfg), dev_s)
        logger.info(f"fallback variant DEV: {fb_dev['FA_rename']} DET={fb_dev['DET']}")
        cond_det = all(fb_dev["DET"].get(op, (1, 0))[0] >= legacy_dev["DET"].get(op, (0, 0))[0] - 0.03 for op in DET_OPS)
        if cond_det and (fb_dev["FA_logic"] or 0) <= (legacy_dev["FA_logic"] or 0) + 0.01 and \
                fb_dev["FA_rename"] < results[chosen]["res"]["FA_rename"]:
            fallback_used = True
    final_cfg = {**cfg, "fallback_mpnet_0.4": fallback_used}
    aligner = fallback_aligner(cfg) if fallback_used else make_aligner(cfg)
    test_chosen = evaluate(aligner, test_s, rename2)
    test_legacy = evaluate("legacy", test_s, rename2)
    dev_r2_chosen = None
    out = {"legacy_dev": legacy_dev, "grid_dev": results, "chosen": chosen, "chosen_cfg": final_cfg,
           "R1_TARGET_MISSED_DET": missed, "fallback_dev": fb_dev, "fallback_used": fallback_used,
           "ranking_top5": ranking[:5], "test_chosen": test_chosen, "test_legacy": test_legacy,
           "dev_rename2_note": "RENAME2 is built on SCREEN_TEST golds only; never used for tuning",
           "R1_TARGET_MISSED": bool((test_chosen["FA_rename"] or 0) > 0.05), "dev_r2_chosen": dev_r2_chosen,
           "seconds": round(time.time() - t0, 1), "n_dev_sentences": len(dev_s), "n_test_sentences": len(test_s),
           "selection_rule": select.__doc__}
    (RES / ("r1_grid.json" if not n_limit else "r1_grid_mini.json")).write_text(json.dumps(out, indent=1))
    logger.info(f"R1 chosen {chosen} fallback={fallback_used}; TEST chosen FA_rename={test_chosen['FA_rename']} "
                f"FA_RENAME2={test_chosen.get('FA_RENAME2')} FA_logic={test_chosen['FA_logic']} "
                f"AUROC={test_chosen['AUROC_real']}; legacy FA_rename={test_legacy['FA_rename']} "
                f"FA_RENAME2={test_legacy.get('FA_RENAME2')} AUROC={test_legacy['AUROC_real']}")


@logger.catch(reraise=True)
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True, choices=["regress", "rename2", "sigs", "grid"])
    ap.add_argument("--n", type=int, default=None)
    a = ap.parse_args()
    {"regress": stage_regress, "rename2": stage_rename2, "sigs": stage_sigs,
     "grid": lambda: stage_grid(a.n)}[a.stage]()


if __name__ == "__main__":
    main()
