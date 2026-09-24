#!/usr/bin/env python3
"""STEP 6: LLM / model baselines on the identical screen items.

 --stage b1     B1 anchor judge (gemini-2.5-flash, thinking-off, temp 0, EXACT fixed prompt) on real/gold/mutant/rewrite
 --stage b3     B3 round-trip: FOL -> English (same model/config as B1), B3cos (MiniLM), B3nli (DeBERTa-v3-large NLI)
 --stage b4     B4 decomposed per-predicate LLM judge (same model + config as the probe) -> LLM-S scored with score.py
 --stage b1plus B1+ tuned rubric judge (thinking budget 512), real candidates only (sensitivity check)
Writes results/baseline_<stage>.jsonl rows {item_id, set, sid, metric, score, covered, usd, seconds, ...}.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
import llm  # noqa: E402
from fol_parse import ParseError, parse  # noqa: E402

logger.remove()
logger.add(sys.stdout, level="INFO", format="{time:HH:mm:ss}|{level:<7}|{message}")
logger.add(ROOT / "logs" / "run_baselines.log", rotation="30 MB", level="DEBUG")

MODEL = "google/gemini-2.5-flash"
THINK_OFF = {"max_tokens": 0}
B1_PROMPT = ("Sentence: {s}\nFOL: {f}\nGive the probability (0-100) that this FOL is a faithful formalization "
             "of the sentence. Reply with a number only.")
B3_PROMPT = ("Translate this first-order logic formula into one plain English sentence. Read predicate and "
             "constant names as words. Formula: {f}")
B1P_PROMPT = """You are an expert in first-order logic (FOL) semantic parsing. Judge whether the FOL formula is a faithful formalization of the sentence. Predicate names and granularity may legitimately differ from any reference; judge MEANING only.
Check each error type in turn and note whether it occurs:
1. quantifier error (wrong ∀/∃ or wrong quantifier structure)
2. scope error (wrong quantifier/negation scope order)
3. dropped condition (a restriction/condition in the sentence is missing)
4. added condition (the formula adds a restriction/condition not in the sentence)
5. negation/polarity error (a negation missing, extra or misplaced)
6. reversed implication (antecedent and consequent swapped)
7. swapped arguments (arguments of a relation in the wrong order)
8. conflated concepts (two distinct concepts merged into one predicate)
9. wrongly split concept (one concept split so that meaning changes)
10. connective error (and/or/xor/iff confusion)
Sentence: {s}
FOL: {f}
After checking, output a final line 'SCORE: n' where n (0-100) is the probability that the FOL is faithful."""

B4_HEAD = ("Here is a first-order logic formula F:\n{f}\n"
           "Treat predicate and constant names as arbitrary symbols (their English meaning is irrelevant) and answer each "
           "question about F strictly logically. Return JSON {{\"1\":\"yes\",\"2\":\"no\",...}}.\n")


def load_items(which: set[str]) -> list[dict]:
    d = json.loads((ROOT / "data" / "screen_set.json").read_text())
    S = {s["sid"]: s for s in d["sentences"]}
    out = []
    if "gold" in which:
        out += [{"item_id": f"{s['sid']}:gold", "set": "gold", "sid": s["sid"], "nl": s["nl"], "fol": s["gold_fol"]}
                for s in d["sentences"]]
    if "real" in which:
        out += [{"item_id": r["item_id"], "set": "real", "sid": r["sid"], "nl": S[r["sid"]]["nl"], "fol": r["cand_fol"],
                 "parse_ok": r["parse_ok"]} for r in d["real"]]
    if "mutant" in which:
        out += [{"item_id": m["mid"], "set": "mutant", "sid": m["sid"], "nl": S[m["sid"]]["nl"], "fol": m["fol"],
                 "operator": m["operator"]} for m in d["mutants"]]
    if "rewrite" in which:
        out += [{"item_id": r["rid"], "set": "rewrite", "sid": r["sid"], "nl": S[r["sid"]]["nl"], "fol": r["fol"],
                 "kind": r["kind"]} for r in d["rewrites"]]
    return out


def first_number(text: str):
    m = re.search(r"-?\d+(?:\.\d+)?", text or "")
    if not m:
        return None
    return min(100.0, max(0.0, float(m.group(0)))) / 100.0


def write_rows(name: str, rows: list[dict]):
    p = ROOT / "results" / f"baseline_{name}.jsonl"
    with p.open("w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    logger.info(f"wrote {len(rows)} rows to {p.name}; spent={llm.spent():.4f}")


def stage_b1(sets: set[str]):
    items = load_items(sets)
    jobs = [dict(model=MODEL, messages=[{"role": "user", "content": B1_PROMPT.format(s=it["nl"], f=it["fol"])}],
                 purpose="B1", reasoning=THINK_OFF, max_tokens=16) for it in items]
    t0 = time.time()
    res = asyncio.run(llm.run_batch(jobs, concurrency=16, est_cost_each=0.0001))
    retry_idx = [i for i, r in enumerate(res) if isinstance(r, Exception) or first_number(r[0]) is None]
    logger.info(f"B1: {len(items)} calls in {time.time() - t0:.0f}s; retrying {len(retry_idx)}")
    if retry_idx:
        rj = [dict(jobs[i], max_tokens=48, purpose="B1_retry") for i in retry_idx]
        rres = asyncio.run(llm.run_batch(rj, concurrency=16, est_cost_each=0.0001))
        for i, r in zip(retry_idx, rres):
            res[i] = r
    rows = []
    for it, r in zip(items, res):
        if isinstance(r, Exception):
            sc, cov, usd, txt = 0.5, False, 0.0, repr(r)[:100]
        else:
            v = first_number(r[0])
            sc, cov, usd, txt = (0.5, False, r[1]["cost"], r[0]) if v is None else (v, True, r[1]["cost"], r[0])
        rows.append({"item_id": it["item_id"], "set": it["set"], "sid": it["sid"], "metric": "B1", "score": sc,
                     "covered": cov, "usd": usd, "raw": txt[:40], "seconds": None if isinstance(r, Exception) else r[1]["seconds"],
                     "operator": it.get("operator"), "kind": it.get("kind")})
    write_rows("b1" if sets != {"mutant"} else "b1_mutants", rows)


def stage_b1plus():
    items = load_items({"real"})
    jobs = [dict(model=MODEL, messages=[{"role": "user", "content": B1P_PROMPT.format(s=it["nl"], f=it["fol"])}],
                 purpose="B1plus", reasoning={"max_tokens": 512}, max_tokens=1400) for it in items]
    res = asyncio.run(llm.run_batch(jobs, concurrency=16, est_cost_each=0.002))
    rows = []
    for it, r in zip(items, res):
        v = None
        if not isinstance(r, Exception):
            m = re.search(r"SCORE:\s*(\d+(?:\.\d+)?)", r[0])
            v = min(100.0, max(0.0, float(m.group(1)))) / 100 if m else None
        rows.append({"item_id": it["item_id"], "set": it["set"], "sid": it["sid"], "metric": "B1plus",
                     "score": 0.5 if v is None else v, "covered": v is not None,
                     "usd": 0.0 if isinstance(r, Exception) else r[1]["cost"],
                     "seconds": None if isinstance(r, Exception) else r[1]["seconds"]})
    write_rows("b1plus", rows)


def stage_b3():
    items = load_items({"real"})
    jobs = [dict(model=MODEL, messages=[{"role": "user", "content": B3_PROMPT.format(f=it["fol"])}],
                 purpose="B3_backtranslate", reasoning=THINK_OFF, max_tokens=200) for it in items]
    res = asyncio.run(llm.run_batch(jobs, concurrency=16, est_cost_each=0.0002))
    backs = [None if isinstance(r, Exception) else r[0].strip().split("\n")[0] for r in res]
    import torch
    from sentence_transformers import SentenceTransformer
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    st = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2", device=dev)
    ok = [i for i, b in enumerate(backs) if b]
    e1 = st.encode([items[i]["nl"] for i in ok], normalize_embeddings=True, batch_size=128)
    e2 = st.encode([backs[i] for i in ok], normalize_embeddings=True, batch_size=128)
    cos = {i: float(a @ b) for i, a, b in zip(ok, e1, e2)}
    name = "MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli" if dev == "cuda" else \
        "MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli"
    tok = AutoTokenizer.from_pretrained(name)
    mdl = AutoModelForSequenceClassification.from_pretrained(name).to(dev).eval()
    ent = [k for k, v in mdl.config.id2label.items() if v.lower().startswith("entail")][0]

    def p_ent(prem, hyp):
        out = []
        for i in range(0, len(prem), 32):
            b = tok(prem[i:i + 32], hyp[i:i + 32], return_tensors="pt", padding=True, truncation=True, max_length=256).to(dev)
            with torch.no_grad():
                pr = torch.softmax(mdl(**b).logits.float(), -1)[:, ent]
            out += pr.cpu().tolist()
        return out
    pa = p_ent([items[i]["nl"] for i in ok], [backs[i] for i in ok])
    pb = p_ent([backs[i] for i in ok], [items[i]["nl"] for i in ok])
    nli = {i: min(a, b) for i, a, b in zip(ok, pa, pb)}
    rows = []
    for i, (it, r) in enumerate(zip(items, res)):
        usd = 0.0 if isinstance(r, Exception) else r[1]["cost"]
        for m, val in (("B3cos", cos.get(i)), ("B3nli", nli.get(i))):
            rows.append({"item_id": it["item_id"], "set": "real", "sid": it["sid"], "metric": m,
                         "score": 0.5 if val is None else val, "covered": val is not None, "usd": usd,
                         "back": backs[i], "nli_model": name if m == "B3nli" else None})
    write_rows("b3", rows)


def b4_questions(fol: str):
    p = parse(fol)
    P, C = p.preds, p.consts
    qs = []
    for pr, k in P.items():
        sym = f"{pr}" + ("" if k == 0 else f" ({k}-place)")
        qs.append((("down", pr), f"If predicate {sym} is replaced everywhere by a stricter predicate {pr}′ (everything that is {pr}′ is also {pr}), must F stay true whenever it was true?"))
        qs.append((("up", pr), f"If predicate {sym} is replaced everywhere by a looser predicate {pr}″ (everything that is {pr} is also {pr}″), must F stay true whenever it was true?"))
    un = [x for x, k in P.items() if k == 1]
    ords = ["first", "second", "third", "fourth"]
    for r, k in P.items():
        if k < 2:
            continue
        for i in range(k):
            for a in un:
                qs.append((("anch", r, i, a), f"Does F say anything about {r}-tuples whose {ords[min(i, 3)]} argument is not {a}?"))
            for c in C:
                qs.append((("anch", r, i, f"c:{c}"), f"Does F say anything about {r}-tuples whose {ords[min(i, 3)]} argument is not the constant {c}?"))
    return P, qs


def stage_b4(sets: set[str], n_mut_per_op: int, n_rew: int):
    cfg = json.loads((ROOT / "results" / "probe_config.json").read_text())
    items = load_items(sets)
    rng = random.Random(0)
    if "mutant" in sets:
        muts = [it for it in items if it["set"] == "mutant"]
        byop = defaultdict(list)
        for m in muts:
            byop[m["operator"]].append(m)
        keep = []
        for op in sorted(byop):
            L = sorted(byop[op], key=lambda x: x["item_id"])
            rng.shuffle(L)
            keep += L[:n_mut_per_op]
        items = [it for it in items if it["set"] != "mutant"] + keep
    if "rewrite" in sets:
        rews = sorted([it for it in items if it["set"] == "rewrite"], key=lambda x: x["item_id"])
        rng.shuffle(rews)
        items = [it for it in items if it["set"] != "rewrite"] + rews[:n_rew]
    jobs, metas = [], []
    for it in items:
        if it.get("parse_ok") is False:
            continue
        try:
            P, qs = b4_questions(it["fol"])
        except (ParseError, RecursionError):
            continue
        if not qs:
            continue
        body = B4_HEAD.format(f=it["fol"]) + "\n".join(f"{j + 1}. {q}" for j, (_, q) in enumerate(qs))
        jobs.append(dict(model=cfg["model"], messages=[{"role": "user", "content": body}], purpose="B4",
                         reasoning=cfg["reasoning"], max_tokens=3000))
        metas.append((it, P, qs))
    logger.info(f"B4: {len(jobs)} calls ({Counter(m[0]['set'] for m in metas)})")
    res = asyncio.run(llm.run_batch(jobs, concurrency=16, est_cost_each=0.003))
    sys.path.insert(0, str(ROOT / "src"))
    from text_sig import parse_answers
    out = {}
    for (it, P, qs), r in zip(metas, res):
        if isinstance(r, Exception):
            out[it["item_id"]] = {"error": repr(r)[:200]}
            continue
        ans = parse_answers(r[0])
        up, down, anchors = {}, {}, {}
        for j, (key, _) in enumerate(qs):
            a = ans.get(j + 1)
            if key[0] == "down":
                down[key[1]] = a
            elif key[0] == "up":
                up[key[1]] = a
            else:
                anchors[f"{key[1]}|{key[2]}|{key[3]}"] = None if a is None else (not a)
        labels = {}
        for pr in P:
            u, dn = up.get(pr), down.get(pr)
            labels[pr] = "?" if (u is None or dn is None) else \
                {(True, False): "+", (False, True): "-", (True, True): "0", (False, False): "±"}[(u, dn)]
        out[it["item_id"]] = {"labels": labels, "anchors": anchors, "rel": {}, "arity": dict(P),
                              "usd": r[1]["cost"], "seconds": r[1]["seconds"], "set": it["set"], "sid": it["sid"],
                              "fol": it["fol"], "operator": it.get("operator"), "kind": it.get("kind")}
    p = ROOT / "results" / "b4_llm_sigs.json"
    prev = json.loads(p.read_text()) if p.exists() else {}
    prev.update(out)
    p.write_text(json.dumps(prev, ensure_ascii=False))
    logger.info(f"B4 sigs written: {len(out)} (total {len(prev)}); spent={llm.spent():.4f}")


@logger.catch(reraise=True)
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True, choices=["b1", "b1_mutants", "b3", "b4", "b1plus"])
    ap.add_argument("--sets", default="real,gold,rewrite")
    ap.add_argument("--n_mut_per_op", type=int, default=40)
    ap.add_argument("--n_rew", type=int, default=150)
    a = ap.parse_args()
    sets = set(a.sets.split(","))
    if a.stage == "b1":
        stage_b1(sets)
    elif a.stage == "b1_mutants":
        stage_b1({"mutant"})
    elif a.stage == "b3":
        stage_b3()
    elif a.stage == "b4":
        stage_b4(sets, a.n_mut_per_op, a.n_rew)
    elif a.stage == "b1plus":
        stage_b1plus()


if __name__ == "__main__":
    main()
