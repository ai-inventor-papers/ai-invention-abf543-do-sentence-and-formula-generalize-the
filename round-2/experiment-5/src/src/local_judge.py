#!/usr/bin/env python3
"""LOCAL-GPU SUBSTITUTES after the run-level OpenRouter budget stop (deviation D-BUDGET, results/deviations.json).

The shared per-run OpenRouter budget ('aii_run_budget_exhausted', HTTP 403) was reached at 04:22 UTC while B3 was
running (40/680 back-translations done). Following the round-2 precedent (iter-2 exp-3 src/local_llm.py, vendored as
vendor/iter2/local_llm.py), the SAME frozen prompts are answered by Qwen/Qwen3-8B (bf16, non-thinking, greedy) on the
local RTX 4090:
  b3    B3 back-translation with the frozen B3_PROMPT for all 680 panel items -> vendor gpu_b3.score_b3 (DeBERTa-v3-large
        NLI min-of-both-directions, MiniLM cosine). Stored as B3nli / B3cos with b3_source='local_qwen3_8b'.
  arb   DC+arb verdict: the sentence's truth in a z3 world separating the two heaviest EQUIV clusters, verbalised
        deterministically (simplified re-implementation of vendor verbalize: predicate names split into words).
Qwen shares a model family with generator qwen-2.5-7b (reported).
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict

from common import RES, ROOT, VENDOR, WORK, jdump, jload, read_jsonl, setup_logger, write_jsonl

logger = setup_logger("local_judge")
sys.path.insert(0, str(VENDOR / "iter2"))
sys.path.insert(0, str(ROOT))
B3_PROMPT = ("Translate this first-order logic formula into one plain English sentence. Read predicate and "
             "constant names as words. Formula: {f}")
ARB_PROMPT = ("Here are all the facts of a small situation. Anything not listed is false. The individuals are exactly: "
              "{inds}.\nFacts:\n{facts}\n\nSentence: {s}\n\nIs the SENTENCE true in this situation (interpret general "
              "statements as being about the listed individuals)? Answer yes or no only.")
FRESH = ["Alex", "Blair", "Casey", "Drew"]


def run_b3() -> None:
    from baselines import cand_items, sample_ids
    from local_llm import LocalLLM
    ids = sample_ids()
    items = {it["key"]: it for it in cand_items(set(ids))}
    items = [items[i] for i in ids]
    llm = LocalLLM("Qwen/Qwen3-8B", vram_frac=0.85)
    outs = llm.generate([B3_PROMPT.format(f=it["fol"]) for it in items], max_new_tokens=160, cache_name="b3_local",
                        batch_size=24)
    for it, o in zip(items, outs):
        t = (o["text"] or "").strip().split("\n")[0].strip()
        it["back"] = t or None
        it["b3_local_sec"] = o["seconds"]
    llm.close()
    del llm
    import torch
    torch.cuda.empty_cache()
    from gpu_b3 import score_b3
    scored = score_b3(items)
    by = defaultdict(dict)
    for r in scored:
        by[r["key"]][r["metric"]] = r
    api = {r["key"]: r for r in read_jsonl(WORK / "b3.jsonl")}
    rows = []
    for it in items:
        d = by[it["key"]]
        rows.append({"key": it["key"], "back": it["back"], "b3_source": "local_qwen3_8b",
                     "B3nli": d["B3nli"]["score"], "B3nli_cov": d["B3nli"]["covered"], "B3cos": d["B3cos"]["score"],
                     "B3cos_cov": d["B3cos"]["covered"], "B3_sec": (it["b3_local_sec"] or 0) + (d["B3nli"]["seconds"] or 0),
                     "back_api_flash": (api.get(it["key"]) or {}).get("back")})
    write_jsonl(WORK / "b3_api_partial.jsonl", list(api.values()))
    write_jsonl(WORK / "b3.jsonl", rows)
    jdump({"n": len(rows), "covered": sum(r["B3nli_cov"] for r in rows), "source": "local_qwen3_8b",
           "api_flash_backtranslations_before_budget_stop": sum(1 for r in api.values() if r.get("back"))}, RES / "b3_info.json")
    logger.info(f"B3 local done: {len(rows)}")


# ------------------------------------------------------------------------------------------------ DC+arb
def words(name: str) -> str:
    s = name.lstrip("~").replace("_", " ")
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)
    return s.lower()


def world(A, Bp, n_max: int = 3):
    """minimal-fact world over domain <= n_max satisfying exactly one of A, B' (z3 Optimize over the grounding)."""
    import z3
    from fol_equiv import _Grounder
    from fol_parse import signature
    pa, ca = signature(A)
    pb, cb = signature(Bp)
    consts = sorted(set(ca) | set(cb))
    for n in range(1, n_max + 1):
        cv = {c: z3.Int(f"c#{c}") for c in consts}
        ga, gb = _Grounder(n, None, cv), _Grounder(n, None, cv)
        fa, fb = ga.g(A, {}), gb.g(Bp, {})
        atoms = {**ga.atoms, **gb.atoms}
        opt = z3.Optimize()
        opt.set("timeout", 5000)
        for v in cv.values():
            opt.add(v >= 0, v < n)
        opt.add(z3.Xor(fa, fb))
        opt.minimize(z3.Sum([z3.If(b, 1, 0) for b in atoms.values()]) if atoms else z3.IntVal(0))
        if opt.check() == z3.sat:
            m = opt.model()
            facts = [(name, args) for (name, args), b in atoms.items() if z3.is_true(m.eval(b, model_completion=True))]
            cval = {c: m.eval(v, model_completion=True).as_long() for c, v in cv.items()}
            a_true = z3.is_true(m.eval(fa, model_completion=True))
            return {"n": n, "facts": facts, "consts": cval, "A_true": a_true}
    return None


def verbalize(w: dict) -> tuple[str, str]:
    names = {}
    for c, v in w["consts"].items():
        names.setdefault(v, " ".join(x.capitalize() for x in words(c).split()))
    inds = [names.get(i, FRESH[i]) for i in range(w["n"])]
    lines = []
    for p, args in sorted(w["facts"]):
        if not args:
            lines.append(f"- it is the case that: {words(p)}")
        elif len(args) == 1:
            lines.append(f"- {inds[args[0]]} is/has: {words(p)}")
        else:
            lines.append(f"- {words(p)}: " + ", ".join(inds[a] for a in args))
    return ", ".join(inds), ("\n".join(lines) if lines else "- (no facts: every property and relation is false)")


def run_arb() -> None:
    from dc.core import Formula, rename_ast, substitute_defs
    from dc_score import Rel, clusters
    cfg = jload(RES / "dc_config.json")
    W = cfg["ds_weights"]["w"]
    R = Rel("legal")
    sents = {s["sentence_id"]: s for s in jload(WORK / "sentences.json")}
    cands = read_jsonl(WORK / "candidates.jsonl")
    dc = {r["cand_id"]: r for r in read_jsonl(RES / "dc_scores_frozen.jsonl")}
    by = defaultdict(list)
    for c in cands:
        if c["frame"] == "pilot" or c["sample_idx"] == 0:
            by[c["sentence_id"]].append(c)
    jobs = []
    for sid, cs in by.items():
        raters = [c for c in cs if c["parse_ok"] and c["frame"] == "system"]
        pil = [c for c in cs if c["parse_ok"] and c["frame"] == "pilot"]
        allr = raters + pil
        if len(allr) < 2:
            continue
        cl = clusters(allr, lambda a, b: R.get(a, b) == "EQUIV")
        cw = defaultdict(float)
        for c in allr:
            cw[cl[c["cand_id"]]] += W.get(c["system"], 1.0) if c["frame"] == "system" else W.get("pilot", 1.0) / len(pil)
        top = sorted(cw, key=lambda k: -cw[k])[:2]
        if len(top) < 2:
            continue
        reps = []
        for k in top:
            mem = [c for c in allr if cl[c["cand_id"]] == k]
            reps.append(max(mem, key=lambda c: (W.get(c["system"], 1.0), c["cand_id"])))
        rec, fwd = R.rec(reps[0]["fol_canon"], reps[1]["fol_canon"])
        if rec is None or rec.get("relation") in (None, "UNKNOWN", "UNALIGNABLE", "EQUIV"):
            continue
        a_rep, b_rep = (reps[0], reps[1]) if fwd else (reps[1], reps[0])
        FA, FB = Formula(a_rep["fol_canon"]), Formula(b_rep["fol_canon"])
        if rec.get("direction") == "A_in_B":
            FA, FB = FB, FA
            a_rep, b_rep = b_rep, a_rep
        Bp = rename_ast(FB.ast, rec.get("map") or {}, rec.get("cmap") or {})
        if rec.get("defs"):
            Bp = substitute_defs(Bp, {(rec.get("map") or {}).get(b, "~" + b): [tuple(x) for x in lits] for b, lits in rec["defs"].items()})
        try:
            w = world(FA.ast, Bp)
        except Exception as e:  # noqa: BLE001 - z3 / grounding failures are recorded, the sentence is skipped
            logger.warning(f"arb world failed {sid}: {e!r}")
            continue
        if w is None:
            continue
        inds, facts = verbalize(w)
        jobs.append({"sid": sid, "clusters": [cl[a_rep["cand_id"]], cl[b_rep["cand_id"]]], "A_true": w["A_true"],
                     "prompt": ARB_PROMPT.format(inds=inds, facts=facts, s=sents[sid]["sentence"]), "n_facts": len(w["facts"]),
                     "members": {c["cand_id"]: cl[c["cand_id"]] for c in allr}})
    logger.info(f"arb worlds for {len(jobs)} sentences")
    from local_llm import LocalLLM
    llm = LocalLLM("Qwen/Qwen3-8B", vram_frac=0.85)
    outs = llm.generate([j["prompt"] for j in jobs], max_new_tokens=8, cache_name="arb_local", batch_size=16)
    llm.close()
    verdict = {}
    for j, o in zip(jobs, outs):
        t = (o["text"] or "").strip().lower()
        v = True if t.startswith("yes") else (False if t.startswith("no") else None)
        j["verdict"] = v
        if v is None:
            continue
        agree_cluster = j["clusters"][0] if v == j["A_true"] else j["clusters"][1]
        for cid, k in j["members"].items():
            if k in j["clusters"]:
                verdict[cid] = int(k == agree_cluster)
    rows = []
    for cid, d in dc.items():
        base = d["DC"]
        if cid in verdict and d.get("DC_cov"):
            rows.append({"key": cid, "DC_arb": 0.5 * base + 0.5 * verdict[cid], "DC_arb_applied": True})
        else:
            rows.append({"key": cid, "DC_arb": base, "DC_arb_applied": False})
    write_jsonl(WORK / "dc_arb.jsonl", rows)
    jdump({"n_sentences_with_world": len(jobs), "n_verdicts": sum(j["verdict"] is not None for j in jobs),
           "n_candidates_adjusted": sum(r["DC_arb_applied"] for r in rows), "judge": "local Qwen/Qwen3-8B (substitute for flash)",
           "examples": [{k: j[k] for k in ("sid", "prompt", "verdict", "A_true", "n_facts")} for j in jobs[:5]]},
          RES / "dc_arb_info.json")
    logger.info(f"arb: {len(jobs)} worlds, {len(verdict)} candidates adjusted")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    a = ap.parse_args()
    {"b3": run_b3, "arb": run_arb}[a.cmd]()


if __name__ == "__main__":
    main()
