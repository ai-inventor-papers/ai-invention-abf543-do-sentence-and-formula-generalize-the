"""Held-out LLM scoring (label-blind): TVJT (frozen protocol) + B1 on identical items, for one judge backend.

  python stage_judge.py gemini  [--sets P,Ccon,T] [--votes 3] [--b1x3]   (TVJT*, B1, B1x3 — needs the key)
  python stage_judge.py local   [--sets P]      [--votes 1]              (TVJT_local, B1_local — $0, CPU)

Items are processed sentence by sentence in sha1(sid) order, so a stopped run is an unbiased subset. Every
call is cached (world-level for TVJT, whole-prompt for B1); re-running resumes. Output rows are appended
to results/heldout_llm_scores.jsonl as {item_id, metric, score, covered, ...}.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

from loguru import logger

import common
import judge as J
import worlds as WW
from common import DATA, RESULTS, append_jsonl, read_jsonl, sha1

OUT = RESULTS / "heldout_llm_scores.jsonl"
LOCAL_MODEL = ("/tmp/claude-0/-ai-inventor-aii-data-runs-run-qY2a2IS-WLIs-3-invention-loop-iter-2-gen-art-"
               "gen-art-experiment-4/8b14f1ec-f26d-4913-b8c9-e25a2b90c82c/scratchpad/models/"
               "qwen2.5-1.5b-instruct-q4_k_m.gguf")


def targets(sets: list[str]) -> list[dict]:
    tg = [json.loads(l) for l in (DATA / "heldout_targets.jsonl").read_text().splitlines()]
    ids = {t["original_item_id"] for t in tg if t["group"] == "contamination"}
    out = []
    for t in tg:
        s = set()
        if t["panel"]:
            s.add("P")
        if t["group"] == "contamination" or t["item_id"] in ids:
            s.add("Ccon")
        if t["group"] == "heldout_confirm" and t["tercile"] == "top":
            s.add("T")
        if s & set(sets):
            out.append(t)
    rank = {"P": 0, "Ccon": 1, "T": 2}
    out.sort(key=lambda t: (min(rank[x] for x in sets if (x == "P" and t["panel"]) or
                                (x == "Ccon" and (t["group"] == "contamination" or t["item_id"] in ids)) or
                                (x == "T" and t["group"] == "heldout_confirm" and t["tercile"] == "top")),
                            sha1(t["sid"]), t["item_id"]))
    return out


async def run(backend: str, sets: list[str], votes: int, b1x3: bool, limit: int | None, lite: bool = False) -> None:
    if backend == "gemini":
        ok, msg = J.gemini_available()
        logger.info(f"gemini key: {msg}")
        if not ok:
            raise J.JudgeUnavailable(msg)
        if lite:   # flash-lite TVJT variant (frozen protocol, different judge); no B1
            be_ctx = J.GeminiBackend(model=J.GEMINI_LITE, stage_caps={"TVJT_lite": 0.4})
            m_tvjt, m_b1 = "TVJT_lite", None
        else:
            be_ctx = J.GeminiBackend(stage_caps={"TVJT*": 2.6 + 3.0 + 0.9, "B1": 0.6, "B1x3": 0.6})
            m_tvjt, m_b1 = "TVJT_frozen", "B1"
    else:
        be_ctx = J.LocalBackend(LOCAL_MODEL, n_threads=3)
        m_tvjt, m_b1 = "TVJT_local", "B1_local"
    T = targets(sets)[: limit or None]
    by_key, by_src = WW.load_cache()
    done = {(r["item_id"], r["metric"]) for r in read_jsonl(OUT)}
    async with be_ctx as be:
        wc = J.WorldCache(be.name)
        cc = J.CallCache(be.name)
        t0 = time.time()
        stop = {"flag": False}
        n_done = {"n": 0}

        async def one_item(t):
            rows = []
            # ---- B1 (the candidate exactly as the system produced it)
            if m_b1 and (t["item_id"], m_b1) not in done:
                r = await J.judge_b1(be, cc, t["nl"], t["fol_raw"], 0, "B1", t["item_id"])
                rows.append({"item_id": t["item_id"], "metric": m_b1, "score": r["p"] if r["p"] is not None else 0.5,
                             "covered": r["p"] is not None, "usd": r["usd"], "seconds": r["seconds"]})
            if b1x3 and (t["item_id"], "B1x3") not in done:
                ps, usd = [], 0.0
                for k in range(3):
                    r = await J.judge_b1(be, cc, t["nl"], t["fol_raw"], k, "B1x3" if k else "B1", t["item_id"])
                    usd += r["usd"]
                    if r["p"] is not None:
                        ps.append(r["p"])
                rows.append({"item_id": t["item_id"], "metric": "B1x3", "score": sum(ps) / len(ps) if ps else 0.5,
                             "covered": bool(ps), "usd": usd})
            # ---- TVJT
            if (t["item_id"], m_tvjt) not in done:
                rec = by_key.get(by_src.get(t["fol_folio"])) if t["fol_folio"] else None
                ws = [w for w in (rec or {}).get("worlds", []) if w.get("text")]
                if not t["fol_folio"]:
                    rows.append({"item_id": t["item_id"], "metric": m_tvjt, "score": 0.5, "covered": False,
                                 "reason": "unparseable"})
                elif not ws:
                    rows.append({"item_id": t["item_id"], "metric": m_tvjt, "score": 0.5, "covered": False,
                                 "reason": "no_world" if rec else "worlds_missing"})
                else:
                    o = await J.judge_target(be, wc, t["nl"], ws, votes, "TVJT_lite" if lite else "TVJT*", t["item_id"])
                    sc = J.score_tvjt(ws, o["answers"], votes)
                    main = sc["C3"]
                    rows.append({"item_id": t["item_id"], "metric": m_tvjt,
                                 "score": main if main is not None else 0.5, "covered": main is not None,
                                 "C1": sc["C1"], "C2": sc["C2"], "C3": sc["C3"], "n_worlds": sc["n_worlds"],
                                 "n_judged": sc["n_judged"], "error_type_pred": sc["error_type"],
                                 "per_world_agree": sc["per_world_agree"], "ops": [w["op"] for w in ws],
                                 "usd": o["usd"], "seconds": o["seconds"], "malformed": o["malformed"],
                                 "canon_fallback": rec.get("fallback"), "votes": votes})
            append_jsonl(OUT, rows)

        async def one_sentence(items, sem):
            async with sem:
                for t in items:
                    if stop["flag"]:
                        return
                    try:
                        await one_item(t)
                    except J.BudgetExceeded as e:
                        logger.warning(f"budget stop: {e}")
                        stop["flag"] = True
                        return
                    except (RuntimeError, J.JudgeUnavailable) as e:
                        logger.error(f"{t['item_id']}: {e!r}"[:200])
                    n_done["n"] += 1
                    if n_done["n"] % 100 == 0:
                        el = time.time() - t0
                        logger.info(f"{be.name}: {n_done['n']}/{len(T)} items, {el:.0f}s, cum ${be.cum:.3f}")

        groups: dict[str, list] = {}
        for t in T:
            groups.setdefault(t["sid"], []).append(t)
        sem = asyncio.Semaphore(12)
        await asyncio.gather(*[one_sentence(v, sem) for v in groups.values()])
        logger.info(f"done {n_done['n']}/{len(T)}; cum ${be.cum:.3f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("backend", choices=["gemini", "local"])
    ap.add_argument("--sets", default="P")
    ap.add_argument("--votes", type=int, default=1)
    ap.add_argument("--b1x3", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--lite", action="store_true")
    a = ap.parse_args()
    logger.remove()
    logger.add(sys.stdout, level="INFO")
    logger.add(common.ROOT / "logs" / f"stage_judge_{a.backend}.log", level="DEBUG", rotation="20 MB")
    asyncio.run(run(a.backend, a.sets.split(","), a.votes, a.b1x3, a.limit, a.lite))
