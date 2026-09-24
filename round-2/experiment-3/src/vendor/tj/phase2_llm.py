#!/usr/bin/env python3
"""LLM baselines (inputs only; no labels are read): B1 anchor judge and TJ typed judge (gemini-2.5-flash).

B1  iter-1 B1_PROMPT verbatim, gemini-2.5-flash, T=0, thinking off (reasoning max_tokens 0), max_tokens 16
    (retry with 48 if no number) -> p_faithful = number/100. Items: the 609 panel-sample greedy rows, the 700 held-out
    ORIGINAL golds (one per sentence), the 360 screen golds (L4-audited v1 gold).
TJ  typed judge, same model, thinking off: faithful? + ONE primary error type from the panel taxonomy (definitions
    copied verbatim from the dataset's prompts/adjudication.txt) + optional secondary + p_faithful. Same items.
TJ+ same prompt with thinking budget 1024, only on the panel-sample rows the stage is given (optional; post-analysis
    selection would need labels, so TJ+ runs on ALL 609 panel-sample rows when budget allows).
Outputs: results/llm_baselines.jsonl rows {unit_id, kind(panel|gold_heldout|gold_screen), method, p_faithful,
          primary, secondary, faithful, parse_ok, usd, cached}.
Usage: python phase2_llm.py --methods B1,TJ [--cap 6.0]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "sigfaith"))
import heldout_io  # noqa: E402
import llm  # noqa: E402

logger.remove()
logger.add(sys.stdout, level="INFO", format="{time:HH:mm:ss}|{level:<7}|{message}")
logger.add(ROOT / "logs" / "phase2_llm.log", rotation="30 MB", level="DEBUG")
OUT = ROOT / "results" / "llm_baselines.jsonl"
MODEL = "google/gemini-2.5-flash"
B1_PROMPT = ("Sentence: {s}\nFOL: {f}\nGive the probability (0-100) that this FOL is a faithful formalization "
             "of the sentence. Reply with a number only.")


def taxonomy_block() -> str:
    txt = (ROOT / "data" / "adjudication.txt").read_text()
    lines = [l for l in txt.splitlines() if l.startswith("- ") and ":" in l and not l.startswith("- none")]
    return "\n".join(lines)


TJ_PROMPT = ("Sentence: {s}\nFOL: {f}\n\nNotation: ∀ ∃ quantifiers; ¬ not; ∧ and; ∨ inclusive or; → implies; ↔ iff; "
             "⊕ exclusive or. Different predicate names, different granularity and logically equivalent rewrites are "
             "acceptable; judge meaning only.\nIs the FOL a faithful formalization of the sentence? If not, choose the "
             "ONE primary error type from this list, and optionally a second:\n{tax}\n\nAnswer JSON only: "
             "{{\"faithful\": true|false, \"primary\": \"<type>\"|null, \"secondary\": \"<type>\"|null, "
             "\"p_faithful\": <0-100>}}")


def first_number(text: str):
    m = re.search(r"-?\d+(?:\.\d+)?", text or "")
    if not m:
        return None
    v = float(m.group(0))
    return max(0.0, min(100.0, v))


def parse_tj(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return {"parse_ok": False}
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"parse_ok": False}
    f = d.get("faithful")
    if isinstance(f, str):
        f = f.strip().lower() in ("true", "yes")
    pf = d.get("p_faithful")
    try:
        pf = float(pf) / 100.0 if pf is not None else None
    except (TypeError, ValueError):
        pf = None
    if pf is None and f is not None:
        pf = 1.0 if f else 0.0
    return {"parse_ok": True, "faithful": f, "primary": d.get("primary"), "secondary": d.get("secondary"),
            "p_faithful": pf}


def units() -> list[dict]:
    rows = heldout_io.load_inputs(with_design=True)
    out = [{"unit_id": r["item_id"], "kind": "panel", "s": r["sentence"], "f": r["candidate_fol"]}
           for r in rows if r["in_panel_sample"]]
    seen = set()
    for r in rows:
        if r["sentence_id"] in seen:
            continue
        seen.add(r["sentence_id"])
        out.append({"unit_id": f"{r['sentence_id']}:gold", "kind": "gold_heldout", "s": r["sentence"],
                    "f": r["gold_fol_original"]})
    seen = set()
    for l in (ROOT / "data" / "screen_l4.jsonl").read_text().splitlines():
        x = json.loads(l)
        if x["sentence_id"] in seen:
            continue
        seen.add(x["sentence_id"])
        out.append({"unit_id": f"{x['sentence_id']}:screen_gold", "kind": "gold_screen", "s": x["sentence"],
                    "f": x["gold_fol_original"]})
    return out


def done_keys() -> set:
    if not OUT.exists():
        return set()
    out = set()
    for l in OUT.read_text().splitlines():
        x = json.loads(l)
        if x.get("error") is None:
            out.add((x["unit_id"], x["method"]))
    return out


def write(rows: list[dict]):
    with OUT.open("a") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def run_b1(us: list[dict]):
    jobs = [dict(model=MODEL, messages=[{"role": "user", "content": B1_PROMPT.format(s=u["s"], f=u["f"])}],
                 purpose="B1", reasoning={"max_tokens": 0}, max_tokens=16) for u in us]
    logger.info(f"B1: {len(us)} units; uncached {llm.n_uncached(jobs)} (dry-run est ${llm.n_uncached(jobs) * 0.00012:.3f})")
    res = llm.run(jobs, concurrency=16, est_cost_each=0.0003)
    retry = [i for i, r in enumerate(res) if isinstance(r, Exception) or first_number(r[0]) is None]
    if retry:
        rj = [dict(jobs[i], max_tokens=48, purpose="B1_retry") for i in retry]
        rr = llm.run(rj, concurrency=16, est_cost_each=0.0004)
        for i, r in zip(retry, rr):
            if not isinstance(r, Exception) and first_number(r[0]) is not None:
                res[i] = r
    rows = []
    for u, r in zip(us, res):
        ok = not isinstance(r, Exception) and first_number(r[0]) is not None
        rows.append({"unit_id": u["unit_id"], "kind": u["kind"], "method": "B1",
                     "p_faithful": first_number(r[0]) / 100.0 if ok else None, "parse_ok": ok,
                     "raw": None if isinstance(r, Exception) else r[0][:60],
                     "usd": 0.0 if isinstance(r, Exception) else (r[1].get("cost") or r[1].get("cost_original") or 0.0),
                     "cached": (not isinstance(r, Exception)) and bool(r[1].get("cached")),
                     "error": repr(r)[:200] if isinstance(r, Exception) else None})
    write(rows)
    logger.info(f"B1 done: parsed {sum(r['parse_ok'] for r in rows)}/{len(rows)}; spent {llm.spent():.4f}")


def run_tj(us: list[dict], plus: bool = False):
    tax = taxonomy_block()
    name = "TJplus" if plus else "TJ"
    jobs = [dict(model=MODEL, messages=[{"role": "user", "content": TJ_PROMPT.format(s=u["s"], f=u["f"], tax=tax)}],
                 purpose=name, reasoning={"max_tokens": 1024} if plus else {"max_tokens": 0},
                 max_tokens=1600 if plus else 200) for u in us]
    est = 0.0035 if plus else 0.0004
    logger.info(f"{name}: {len(us)} units; uncached {llm.n_uncached(jobs)} (dry-run est ${llm.n_uncached(jobs) * est:.3f})")
    res = llm.run(jobs, concurrency=16, est_cost_each=est)
    rows = []
    for u, r in zip(us, res):
        d = parse_tj(r[0]) if not isinstance(r, Exception) else {"parse_ok": False}
        rows.append({"unit_id": u["unit_id"], "kind": u["kind"], "method": name, **d,
                     "usd": 0.0 if isinstance(r, Exception) else (r[1].get("cost") or 0.0),
                     "cached": (not isinstance(r, Exception)) and bool(r[1].get("cached")),
                     "error": repr(r)[:200] if isinstance(r, Exception) else None})
    write(rows)
    logger.info(f"{name} done: parsed {sum(r['parse_ok'] for r in rows)}/{len(rows)}; spent {llm.spent():.4f}")


@logger.catch(reraise=True)
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--methods", default="B1,TJ")
    ap.add_argument("--kinds", default="panel,gold_heldout,gold_screen")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--only-panel-unfaithful", action="store_true",
                    help="TJ+ population: panel3 rows the panel judged unfaithful (post-freeze; reads labels via firewall)")
    a = ap.parse_args()
    us = [u for u in units() if u["kind"] in a.kinds.split(",")]
    if a.only_panel_unfaithful:
        labs = heldout_io.load_labels()
        us = [u for u in us if u["kind"] == "panel" and labs[u["unit_id"]].get("label_source") == "panel3"
              and labs[u["unit_id"]].get("L3_majority") is False]
    if a.limit:
        us = us[: a.limit]
    done = done_keys()
    for m in a.methods.split(","):
        todo = [u for u in us if (u["unit_id"], m) not in done]
        logger.info(f"{m}: {len(todo)} to do ({len(us) - len(todo)} already done)")
        if not todo:
            continue
        if m == "B1":
            run_b1(todo)
        elif m == "TJ":
            run_tj(todo)
        elif m == "TJplus":
            run_tj(todo, plus=True)


if __name__ == "__main__":
    main()
