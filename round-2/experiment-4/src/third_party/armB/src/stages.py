"""Pipeline stages after `build`: b1, tvjt, nli, lc, analysis, export. Each stage is resumable: CPU
artefacts go to data/*.jsonl caches, LLM responses to cache/llm/ (sha1-keyed), scores to
results/screen_scores.jsonl (one row per item x metric; a stage rewrites only its own metrics)."""
from __future__ import annotations

import asyncio
import json
import multiprocessing as mp
import re
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).resolve().parents[1]
B1_PROMPT = ("Sentence: {s}\nFOL: {f}\nGive the probability (0-100) that this FOL is a faithful formalization of "
             "the sentence. Reply with a number only.")
NLI_GEMINI_PROMPT = ("Read a passage and several hypotheses. For each hypothesis, decide whether it is ENTAILED by "
                     "the passage, CONTRADICTED by the passage, or NEITHER. Use only the passage; treat the named "
                     "individuals as distinct.\n\n{PAIRS}\n\nAnswer with JSON only: {{{KEYS}}}")
PRIORITY = {"real": 0, "gold": 1, "mutant": 2, "rewrite": 3, "supplement": 4}


def dirs(limit):
    d = ROOT / ("data" if limit is None else f"runs/mini_{limit}/data")
    r = ROOT / ("results" if limit is None else f"runs/mini_{limit}/results")
    r.mkdir(parents=True, exist_ok=True)
    return d, r


def read_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]


def write_jsonl(p: Path, rows: list[dict]) -> None:
    with p.open("w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def load_targets(limit) -> tuple[dict, list[dict]]:
    d, _ = dirs(limit)
    ss = json.loads((d / "screen_set.json").read_text())
    sent = {s["sid"]: s for s in ss["sentences"]}
    T = []
    for r in ss["real_items"]:
        T.append({"item_id": r["item_id"], "kind": "real", "sid": r["sid"], "fol": r["fol"], "op": None,
                  "parse_ok": r["parse_ok"], "glosses": r.get("glosses") or {}, "nl": sent[r["sid"]]["nl"]})
    for s in ss["sentences"]:
        T.append({"item_id": f"{s['sid']}:gold", "kind": "gold", "sid": s["sid"], "fol": s["gold_fol"], "op": None,
                  "parse_ok": 1, "glosses": {}, "nl": s["nl"]})
    for m in ss["mutants"]:
        T.append({"item_id": m["item_id"], "kind": "mutant", "sid": m["sid"], "fol": m["fol"], "op": m["op"],
                  "parse_ok": 1, "glosses": {}, "nl": sent[m["sid"]]["nl"]})
    for m in ss["rewrites"]:
        T.append({"item_id": m["item_id"], "kind": "rewrite", "sid": m["sid"], "fol": m["fol"], "op": m["kind"],
                  "parse_ok": 1, "glosses": {}, "nl": sent[m["sid"]]["nl"]})
    return ss, T


def update_scores(limit, metrics: set[str], rows: list[dict]) -> None:
    _, r = dirs(limit)
    p = r / "screen_scores.jsonl"
    old = [x for x in read_jsonl(p) if x["metric"] not in metrics]
    write_jsonl(p, old + rows)
    logger.info(f"screen_scores: wrote {len(rows)} rows for {sorted(metrics)} (total {len(old) + len(rows)})")


def row(t: dict, metric: str, score: float, covered: bool, et: str | None = None, usd: float = 0.0,
        seconds: float = 0.0, **extra) -> dict:
    return {"item_id": t["item_id"], "item_kind": t["kind"], "operator": t.get("op"), "sid": t["sid"], "metric": metric,
            "score": float(score) if covered else 0.5, "raw_score": float(score) if score is not None else None,
            "error_type_pred": et, "covered": bool(covered), "usd": usd, "seconds": seconds, **extra}


# ============================================================================================ B1 / B2
def _parse_prob(text: str) -> float | None:
    m = re.search(r"-?\d+(\.\d+)?", text or "")
    if not m:
        return None
    v = float(m.group(0))
    if v < 0 or v > 100:
        return None
    return v / 100.0


async def _run_b1(T: list[dict], res_dir: Path) -> list[dict]:
    from llm import LLM, BudgetExceeded
    out = [None] * len(T)
    async with LLM() as L:
        async def one(i, t):
            msgs = [{"role": "user", "content": B1_PROMPT.format(s=t["nl"], f=t["fol"])}]
            if i == 0:
                (res_dir / "b1_request_example.json").write_text(json.dumps(L._payload(msgs, 8, 0.0), ensure_ascii=False, indent=1))
            try:
                r = await L.call(msgs, stage="B1", item_id=t["item_id"], max_tokens=8)
            except BudgetExceeded as e:
                logger.error(f"B1 budget stop: {e}")
                out[i] = row(t, "B1", 0.5, False, reason="budget")
                return
            except RuntimeError as e:
                out[i] = row(t, "B1", 0.5, False, reason=str(e)[:100])
                return
            v = _parse_prob(r["text"])
            out[i] = row(t, "B1", v if v is not None else 0.5, v is not None, usd=r["cost"], seconds=r["seconds"],
                         reply=r["text"][:20])
        await asyncio.gather(*[one(i, t) for i, t in enumerate(T)])
        logger.info(f"B1: {L.n_calls} paid calls, {L.n_cached} cached, cum ${L.cum:.3f}, reasoning_tokens={L.reasoning_tokens}")
    return out


def stage_b1(limit, workers):
    ss, T = load_targets(limit)
    _, r = dirs(limit)
    T.sort(key=lambda t: PRIORITY[t["kind"]])
    rows = asyncio.run(_run_b1(T, r))
    b2 = [row(t, "B2", float(t["parse_ok"]), True) for t in T]
    update_scores(limit, {"B1", "B2"}, rows + b2)


# ============================================================================================ TVJT
def _tvjt_worker(job: dict) -> dict:
    import os
    os.environ.setdefault("NLTK_DATA", str(ROOT / "nltk_data"))
    import fol_core as fc
    from tvjt import build_prompt, worlds_for, find_world
    t0 = time.time()
    F, err = fc.try_parse(job["fol"])
    if F is None:
        return {"item_id": job["item_id"], "worlds": [], "prompt": None, "prompt_gloss": None, "cpu_s": 0.0, "err": err}
    try:
        if job.get("fixed_mutants"):  # supplement: worlds only against the given SCOPE/CARD mutants
            worlds = []
            for j, m in enumerate(job["fixed_mutants"]):
                M = fc.parse(m["fol"])
                w = find_world(F, M, prefer=j % 2)
                if w is not None:
                    w.update({"op": m["op"], "variant": m.get("variant"), "mutant_fol": m["fol"], "mutant_item_id": m["item_id"]})
                    worlds.append(w)
        else:
            worlds = worlds_for(F, job["seed_key"], max_worlds=12, nonvacuous=bool(job.get("nonvacuous")))
    except Exception as e:  # noqa: BLE001 - z3/verbalizer failure -> uncovered item, logged by caller
        return {"item_id": job["item_id"], "worlds": [], "prompt": None, "prompt_gloss": None,
                "cpu_s": time.time() - t0, "err": f"world_error:{e!r}"[:200]}
    prompt = build_prompt(job["nl"], F, worlds) if worlds else None
    pg = build_prompt(job["nl"], F, worlds, job["glosses"]) if (worlds and job.get("glosses")) else None
    from verbalize import pred_fail
    preds = fc.predicates(F)
    vf = {p: pred_fail(p) for p in preds}
    return {"item_id": job["item_id"], "worlds": worlds, "prompt": prompt, "prompt_gloss": pg, "cpu_s": time.time() - t0,
            "verbalizer_fail_preds": vf, "err": None}


def compute_worlds(jobs: list[dict], cache_path: Path, workers: int) -> dict:
    cache = {r["item_id"]: r for r in read_jsonl(cache_path)}
    todo = [j for j in jobs if j["item_id"] not in cache]
    logger.info(f"worlds: {len(cache)} cached, {len(todo)} to compute on {workers} workers")
    if todo:
        ctx = mp.get_context("spawn")
        t0 = time.time()
        with ProcessPoolExecutor(max_workers=workers, mp_context=ctx) as ex, cache_path.open("a") as f:
            futs = {ex.submit(_tvjt_worker, j): j["item_id"] for j in todo}
            for i, fu in enumerate(as_completed(futs)):
                try:
                    r = fu.result(timeout=600)
                except Exception as e:  # noqa: BLE001
                    logger.error(f"world worker failed {futs[fu]}: {e!r}")
                    r = {"item_id": futs[fu], "worlds": [], "prompt": None, "prompt_gloss": None, "cpu_s": 0.0,
                         "err": f"worker:{e!r}"[:200]}
                cache[r["item_id"]] = r
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
                if (i + 1) % 200 == 0:
                    logger.info(f"  worlds {i + 1}/{len(todo)} ({time.time() - t0:.0f}s)")
    return cache


async def _judge(L, prompt: str, k: int, stage: str, item_id: str):
    from tvjt import parse_answer
    r = await L.call([{"role": "user", "content": prompt}], stage=stage, item_id=item_id, max_tokens=300)
    ans = parse_answer(r["text"], k)
    usd, sec = r["cost"], r["seconds"]
    if ans is None:  # one retry with an explicit format reminder
        r2 = await L.call([{"role": "user", "content": prompt + "\nReturn ONLY the JSON object, with every key."}],
                          stage=stage, item_id=item_id + ":retry", max_tokens=400)
        ans = parse_answer(r2["text"], k)
        usd += r2["cost"]
        sec += r2["seconds"]
    return ans, usd, sec


async def _run_tvjt(T, W, metric, use_gloss, budget_gate=None):
    from llm import LLM, BudgetExceeded
    from tvjt import score_answers
    out = {}
    async with LLM() as L:
        if budget_gate is not None and L.cum > budget_gate:
            logger.warning(f"{metric}: cumulative ${L.cum:.2f} > gate ${budget_gate}; skipped")
            return {}, L.cum

        async def one(t):
            w = W.get(t["item_id"]) or {}
            prompt = w.get("prompt_gloss") if use_gloss else w.get("prompt")
            worlds = w.get("worlds") or []
            if not prompt or not worlds:
                out[t["item_id"]] = row(t, metric, 0.5, False, seconds=w.get("cpu_s", 0.0), reason=w.get("err") or "no_world")
                return
            try:
                ans, usd, sec = await _judge(L, prompt, len(worlds), metric, t["item_id"])
            except BudgetExceeded:
                out[t["item_id"]] = row(t, metric, 0.5, False, reason="budget")
                return
            except RuntimeError as e:
                out[t["item_id"]] = row(t, metric, 0.5, False, reason=str(e)[:100])
                return
            if ans is None:
                out[t["item_id"]] = row(t, metric, 0.5, False, usd=usd, seconds=sec + w.get("cpu_s", 0), reason="malformed")
                return
            sc, agrees, et = score_answers(worlds, ans)
            out[t["item_id"]] = row(t, metric, sc, True, et, usd=usd, seconds=sec + w.get("cpu_s", 0),
                                    agrees=agrees, ops=[x["op"] for x in worlds], n_worlds=len(worlds),
                                    answers=[ans[i + 1] for i in range(len(worlds))],
                                    mutant_item_ids=[x.get("mutant_item_id") for x in worlds])
        # priority order (real > gold > mutant > rewrite > supplement) so a budget stop hits the least important
        for kind in ("real", "gold", "mutant", "rewrite", "supplement"):
            batch = [t for t in T if t["kind"] == kind]
            await asyncio.gather(*[one(t) for t in batch])
            logger.info(f"{metric} {kind}: {len(batch)} items; paid {L.n_calls} cached {L.n_cached} cum ${L.cum:.3f}")
        return out, L.cum


def supplement_targets(limit) -> list[dict]:
    d, _ = dirs(limit)
    sup = read_jsonl(d / "blindspot_supplement.jsonl")
    by = {}
    for m in sup:
        g = by.setdefault(m["sid"], {"item_id": f"{m['sid']}:supgold", "kind": "supplement", "sid": m["sid"],
                                     "fol": m["gold_fol"], "op": None, "parse_ok": 1, "glosses": {}, "nl": m["nl"],
                                     "split": m["split"], "fixed_mutants": []})
        g["fixed_mutants"].append({"op": m["op"], "variant": m["variant"], "fol": m["fol"], "item_id": m["item_id"]})
    return list(by.values())


def stage_tvjt(limit, workers):
    ss, T = load_targets(limit)
    d, r = dirs(limit)
    SUP = supplement_targets(limit)
    jobs = [{"item_id": t["item_id"], "fol": t["fol"], "nl": t["nl"], "glosses": t["glosses"],
             "seed_key": t["item_id"]} for t in T if t["parse_ok"]]
    jobs += [{"item_id": t["item_id"], "fol": t["fol"], "nl": t["nl"], "glosses": {}, "seed_key": t["item_id"],
              "fixed_mutants": t["fixed_mutants"]} for t in SUP]
    W = compute_worlds(jobs, d / "worlds_cache.jsonl", workers)
    res, cum = asyncio.run(_run_tvjt(T + SUP, W, "TVJT", use_gloss=False))
    rows = [res.get(t["item_id"]) or row(t, "TVJT", 0.5, False, reason="missing") for t in T + SUP]
    for rw_ in rows:
        if rw_["item_kind"] == "supplement":
            rw_["split"] = next((t["split"] for t in SUP if t["item_id"] == rw_["item_id"]), None)
    update_scores(limit, {"TVJT"}, rows)
    # TVJT-GLOSS on real candidates, only if spend so far <= $4.5 (plan)
    real = [t for t in T if t["kind"] == "real"]
    res_g, cum = asyncio.run(_run_tvjt(real, W, "TVJT_gloss", use_gloss=True, budget_gate=4.5))
    if res_g:
        update_scores(limit, {"TVJT_gloss"}, [res_g.get(t["item_id"]) or row(t, "TVJT_gloss", 0.5, False) for t in real])


def stage_tvjt_nv(limit, workers):
    """Secondary (not a rule candidate): TVJT with non-vacuous worlds (>=1 instance of each ∀-restrictor)."""
    ss, T = load_targets(limit)
    d, r = dirs(limit)
    jobs = [{"item_id": t["item_id"], "fol": t["fol"], "nl": t["nl"], "glosses": {}, "seed_key": t["item_id"],
             "nonvacuous": True} for t in T if t["parse_ok"]]
    W = compute_worlds(jobs, d / "worlds_cache_nv.jsonl", workers)
    res, cum = asyncio.run(_run_tvjt(T, W, "TVJT_nv", use_gloss=False))
    rows = []
    for t in T:
        rr = res.get(t["item_id"]) or row(t, "TVJT_nv", 0.5, False, reason="missing")
        w = W.get(t["item_id"]) or {}
        rr["nv_fallback_worlds"] = sum(1 for x in (w.get("worlds") or []) if x.get("nv_fallback"))
        rows.append(rr)
    update_scores(limit, {"TVJT_nv"}, rows)


# ============================================================================================ NLI
def _nli_worker(job: dict) -> dict:
    import os
    os.environ.setdefault("NLTK_DATA", str(ROOT / "nltk_data"))
    import fol_core as fc
    from instance_nli import label_pairs, process_target
    t0 = time.time()
    F, err = fc.try_parse(job["fol"])
    if F is None:
        return {"item_id": job["item_id"], "ok": False, "err": err, "cpu_s": 0.0}
    try:
        out = process_target(F, job["nl"], job["seed_key"], job.get("glosses") or None)
        if job.get("extra_mutants"):  # supplement: relabel gold's pairs under the given mutants
            from instance_nli import build_items
            items = build_items(F, job["seed_key"])
            pairs = [tuple(int(x) for x in p.split("|")) for p in out["pairs"]]
            for m in job["extra_mutants"]:
                lab = label_pairs(fc.parse(m["fol"]), items, pairs=pairs)
                out["mutant_labels"][f"SUP:{m['item_id']}"] = {f"{k[0]}|{k[1]}": v for k, v in lab["labels"].items()}
    except Exception as e:  # noqa: BLE001
        return {"item_id": job["item_id"], "ok": False, "err": f"nli_error:{e!r}"[:200], "cpu_s": time.time() - t0}
    return {"item_id": job["item_id"], "ok": True, **out, "cpu_s": time.time() - t0}


def deberta_probs(pairs: list[tuple[str, str]], batch: int = 64) -> list[dict]:
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    name = "MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli"
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    if dev == "cuda":
        torch.cuda.set_per_process_memory_fraction(0.8)
    tok = AutoTokenizer.from_pretrained(name)
    model = AutoModelForSequenceClassification.from_pretrained(name, torch_dtype=torch.float16 if dev == "cuda" else torch.float32).to(dev).eval()
    id2label = {int(k): v.lower() for k, v in model.config.id2label.items()}
    logger.info(f"DeBERTa id2label={id2label} device={dev}")
    out = []
    i = 0
    while i < len(pairs):
        chunk = pairs[i:i + batch]
        try:
            enc = tok([p for p, _ in chunk], [h for _, h in chunk], truncation=True, max_length=512, padding=True,
                      return_tensors="pt").to(dev)
            with torch.no_grad():
                logits = model(**enc).logits.float()
            pr = torch.softmax(logits, dim=-1).cpu().numpy()
        except torch.cuda.OutOfMemoryError:
            torch.cuda.empty_cache()
            batch = max(1, batch // 2)
            logger.warning(f"OOM -> batch {batch}")
            continue
        for row_ in pr:
            out.append({id2label[j]: float(row_[j]) for j in range(len(row_))})
        i += len(chunk)
    del model
    torch.cuda.empty_cache()
    return out


async def _run_nli_gemini(T, N):
    from llm import LLM, BudgetExceeded
    from tvjt import parse_answer  # noqa: F401
    out = {}
    async with LLM() as L:
        async def one(t):
            n = N.get(t["item_id"])
            if not n or not n.get("ok") or len(n["texts"]) < 3:
                out[t["item_id"]] = None
                return
            blocks = [f"Pair {i}:\nPassage: {p}\nHypothesis: {h}" for i, (p, h) in enumerate(n["texts"], 1)]
            keys = ", ".join(f'"{i}": "ENTAILED"|"CONTRADICTED"|"NEITHER"' for i in range(1, len(blocks) + 1))
            prompt = NLI_GEMINI_PROMPT.format(PAIRS="\n\n".join(blocks), KEYS=keys)
            try:
                r = await L.call([{"role": "user", "content": prompt}], stage="NLI_gemini", item_id=t["item_id"], max_tokens=300)
            except (BudgetExceeded, RuntimeError):
                out[t["item_id"]] = None
                return
            m = re.search(r"\{.*\}", r["text"] or "", re.S)
            ans = None
            if m:
                try:
                    dd = json.loads(m.group(0))
                    ans = [str(dd.get(str(i), "")).upper() for i in range(1, len(blocks) + 1)]
                    if any(a not in ("ENTAILED", "CONTRADICTED", "NEITHER") for a in ans):
                        ans = None
                except json.JSONDecodeError:
                    ans = None
            out[t["item_id"]] = {"ans": ans, "usd": r["cost"], "seconds": r["seconds"]}
        for kind in ("real", "gold"):
            await asyncio.gather(*[one(t) for t in T if t["kind"] == kind])
            logger.info(f"NLI_gemini {kind}: paid {L.n_calls} cached {L.n_cached} cum ${L.cum:.3f}")
    return out


def stage_nli(limit, workers):
    from instance_nli import agree_scores, error_type
    ss, T = load_targets(limit)
    d, r = dirs(limit)
    SUP = supplement_targets(limit)
    cache_p = d / "consequences_cache.jsonl"
    cache = {x["item_id"]: x for x in read_jsonl(cache_p)}
    gold_sup = {}
    for t in SUP:
        if t["split"] == "screen":
            gold_sup[f"{t['sid']}:gold"] = t["fixed_mutants"]
    jobs = []
    for t in T:
        if t["parse_ok"] and t["item_id"] not in cache:
            jobs.append({"item_id": t["item_id"], "fol": t["fol"], "nl": t["nl"], "seed_key": t["item_id"],
                         "glosses": t["glosses"] if t["kind"] == "real" else None,
                         "extra_mutants": gold_sup.get(t["item_id"])})
    for t in SUP:
        if t["split"] != "screen" and t["item_id"] not in cache:
            jobs.append({"item_id": t["item_id"], "fol": t["fol"], "nl": t["nl"], "seed_key": t["item_id"],
                         "glosses": None, "extra_mutants": t["fixed_mutants"]})
    logger.info(f"NLI consequence labelling: {len(cache)} cached, {len(jobs)} to do")
    if jobs:
        ctx = mp.get_context("spawn")
        t0 = time.time()
        with ProcessPoolExecutor(max_workers=workers, mp_context=ctx) as ex, cache_p.open("a") as f:
            futs = {ex.submit(_nli_worker, j): j["item_id"] for j in jobs}
            for i, fu in enumerate(as_completed(futs)):
                try:
                    res = fu.result(timeout=900)
                except Exception as e:  # noqa: BLE001
                    logger.error(f"nli worker failed {futs[fu]}: {e!r}")
                    res = {"item_id": futs[fu], "ok": False, "err": f"worker:{e!r}"[:200], "cpu_s": 0}
                cache[res["item_id"]] = res
                f.write(json.dumps(res, ensure_ascii=False) + "\n")
                if (i + 1) % 200 == 0:
                    logger.info(f"  consequences {i + 1}/{len(jobs)} ({time.time() - t0:.0f}s)")
    # DeBERTa scoring (both name-verbalized and, for real items, gloss-verbalized pairs)
    flat, index = [], []
    for iid, c in cache.items():
        if c.get("ok"):
            for j, (p, h) in enumerate(c["texts"]):
                flat.append((p, h))
                index.append((iid, "plain", j))
            for j, (p, h) in enumerate(c.get("gloss_texts") or []):
                flat.append((p, h))
                index.append((iid, "gloss", j))
    t0 = time.time()
    probs = deberta_probs(flat) if flat else []
    gpu_s = time.time() - t0
    per_pair_s = gpu_s / max(1, len(flat))
    P = {}
    for (iid, var, j), pr in zip(index, probs):
        P.setdefault((iid, var), {})[j] = pr
    rows = []
    all_t = T + SUP
    for t in all_t:
        c = cache.get(t["item_id"])
        ok = bool(c and c.get("ok") and len(c["labels"]) >= 3)
        for var, metric in (("plain", "NLI_deberta"), ("gloss", "NLI_deberta_gloss")):
            if var == "gloss" and t["kind"] != "real":
                continue
            if not ok or (t["item_id"], var) not in P:
                rows.append(row(t, metric, 0.5, False, seconds=(c or {}).get("cpu_s", 0.0),
                                reason=(c or {}).get("err") or "few_hypotheses"))
                continue
            pr = [P[(t["item_id"], var)][j] for j in range(len(c["labels"]))]
            sb, s3 = agree_scores(c["labels"], pr)
            et = error_type(c["labels"], c["pairs"], pr, {k: v for k, v in c["mutant_labels"].items() if not k.startswith("SUP:")})
            # pairwise detection vs each (controlled / supplement) mutant: does NLI side with F's labels?
            pw = {}
            for mk, ml in c["mutant_labels"].items():
                idx = [i for i, k in enumerate(c["pairs"]) if k in ml and (ml[k] == "E") != (c["labels"][i] == "E")]
                if not idx:
                    pw[mk] = {"detect": 0.5, "n_diff": 0}
                    continue
                af = sum(pr[i]["entailment"] if c["labels"][i] == "E" else 1 - pr[i]["entailment"] for i in idx) / len(idx)
                am = sum(pr[i]["entailment"] if ml[c["pairs"][i]] == "E" else 1 - pr[i]["entailment"] for i in idx) / len(idx)
                pw[mk] = {"detect": 1.0 if af > am else (0.5 if af == am else 0.0), "n_diff": len(idx), "margin": af - am}
            rows.append(row(t, metric, sb, True, et, seconds=c["cpu_s"] + per_pair_s * len(pr), agree_3=s3,
                            n_hyp=len(pr), hyp_kinds=c["hyp_kinds"], labels=c["labels"], pairwise=pw,
                            split=t.get("split")))
    update_scores(limit, {"NLI_deberta", "NLI_deberta_gloss"}, rows)
    # NLI-GEMINI variant on golds + real candidates
    G = asyncio.run(_run_nli_gemini([t for t in T if t["kind"] in ("real", "gold")], cache))
    grows = []
    for t in T:
        if t["kind"] not in ("real", "gold"):
            continue
        g = G.get(t["item_id"])
        c = cache.get(t["item_id"])
        if not g or not g.get("ans") or not c:
            grows.append(row(t, "NLI_gemini", 0.5, False, usd=(g or {}).get("usd", 0.0)))
            continue
        pr = [{"entailment": float(a == "ENTAILED"), "contradiction": float(a == "CONTRADICTED"),
               "neutral": float(a == "NEITHER")} for a in g["ans"]]
        sb, s3 = agree_scores(c["labels"], pr)
        et = error_type(c["labels"], c["pairs"], pr, {k: v for k, v in c["mutant_labels"].items() if not k.startswith("SUP:")})
        grows.append(row(t, "NLI_gemini", sb, True, et, usd=g["usd"], seconds=g["seconds"] + c["cpu_s"], agree_3=s3))
    update_scores(limit, {"NLI_gemini"}, grows)


# ============================================================================================ LC
def stage_lc(limit, workers):
    from latent_class import run_latent_class
    ss, T = load_targets(limit)
    d, r = dirs(limit)
    pairs = json.loads((d / "candidate_pairs.json").read_text())
    alts = read_jsonl(d / "alt_candidates.jsonl")
    rows, info = run_latent_class(ss, pairs, alts)
    tmap = {t["item_id"]: t for t in T}
    out = []
    for rr in rows:
        t = tmap[rr.pop("item_id")]
        out.append(row(t, rr.pop("metric"), rr.pop("score"), rr.pop("covered"), None, **rr))
    update_scores(limit, {"LC_onecoin", "LC_huiwalter", "LC_maj", "LC_ds_binary", "LC_onecoin_str", "B3sc"}, out)
    (r / "latent_class_info.json").write_text(json.dumps(info, indent=1))


def stage_analysis(limit, workers):
    from analysis import run_analysis
    run_analysis(limit)


def stage_export(limit, workers):
    from export import run_export
    run_export(limit)
