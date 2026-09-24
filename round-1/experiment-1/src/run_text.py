#!/usr/bin/env python3
"""STEP 3 + B6: text side.

 --stage pilot : B6 PROBE-CONFIG PILOT on 100 MED items (50 up / 50 down), gemini-2.5-flash thinking-off vs
                 thinking budget 1024; pre-registered choice (thinking-off unless its downward accuracy < 0.80
                 AND thinking-on raises downward accuracy by >= 0.05). Writes results/probe_config.json.
 --stage probe : concept extraction, specialised copies, relativized copies, A3-rules marker for the 300 screen
                 sentences; ONE substitution-entailment probe call per sentence (two if > 40 questions).
                 Writes results/text_sigs.json.
 --stage b6    : B6 on 400 items (MED 300 = 150 up / 150 down balanced on gold; HELP 100 = 50 up / 50 down),
                 same probe format with the chosen config, + zero-LLM marker accuracy on single-span MED edits.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import difflib
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
import llm  # noqa: E402
import text_sig  # noqa: E402

logger.remove()
logger.add(sys.stdout, level="INFO", format="{time:HH:mm:ss}|{level:<7}|{message}")
logger.add(ROOT / "logs" / "run_text.log", rotation="30 MB", level="DEBUG")

MODEL = "google/gemini-2.5-flash"
THINK_OFF = {"max_tokens": 0}
THINK_ON = {"max_tokens": 1024}
RAW = ROOT / "data" / "raw"
RES = ROOT / "results"


def load_med():
    rows = list(csv.DictReader((RAW / "MED.tsv").open(encoding="utf-8"), delimiter="\t"))
    out = []
    for r in rows:
        g = r.get("genre", "")
        d = "up" if "upward_monotone" in g else "down" if "downward_monotone" in g else None
        if d is None or r.get("gold_label") not in ("entailment", "neutral"):
            continue
        out.append({"src": "MED", "id": f"MED-{r['index']}", "dir": d, "gold": r["gold_label"],
                    "s1": r["sentence1"].strip(), "s2": r["sentence2"].strip(), "genre": g})
    return out


def load_help():
    rows = list(csv.DictReader((RAW / "HELP_pmb_train_v1.0.tsv").open(encoding="utf-8"), delimiter="\t"))
    out = []
    for r in rows:
        m = r.get("monotonicity", "")
        d = "up" if m == "upward_monotone" else "down" if m == "downward_monotone" else None
        if d is None or r.get("gold_label") not in ("entailment", "neutral"):
            continue
        out.append({"src": "HELP", "id": f"HELP-{r['']}", "dir": d, "gold": r["gold_label"],
                    "s1": r["ori_sentence"].strip(), "s2": r["new_sentence"].strip(), "genre": m})
    return out


def balanced(items, n_per_dir, rng):
    out = []
    for d in ("up", "down"):
        for g in ("entailment", "neutral"):
            pool = [x for x in items if x["dir"] == d and x["gold"] == g]
            rng.shuffle(pool)
            out += pool[: n_per_dir // 2]
    return out


def b6_sample():
    rng = random.Random(0)
    med = balanced(load_med(), 150, rng)
    hp = balanced(load_help(), 50, rng)
    return med, hp


async def run_pairs(items, reasoning, purpose, batch=20):
    jobs, spans = [], []
    for i in range(0, len(items), batch):
        chunk = items[i:i + batch]
        qs = [{"A": x["s1"], "B": x["s2"]} for x in chunk]
        prompt = text_sig.render_prompt(qs)
        jobs.append(dict(model=MODEL, messages=[{"role": "user", "content": prompt}], purpose=purpose,
                         reasoning=reasoning, max_tokens=4000 if reasoning.get("max_tokens") else 1500))
        spans.append(chunk)
    res = await llm.run_batch(jobs, concurrency=8, est_cost_each=0.004)
    preds = {}
    n_fail = 0
    for chunk, r in zip(spans, res):
        if isinstance(r, Exception):
            n_fail += len(chunk)
            continue
        ans = text_sig.parse_answers(r[0])
        for j, x in enumerate(chunk):
            if (j + 1) in ans:
                preds[x["id"]] = "entailment" if ans[j + 1] else "neutral"
            else:
                n_fail += 1
    return preds, n_fail


def acc_table(items, preds):
    t = {}
    def a(xs):
        xs = [x for x in xs if x["id"] in preds]
        return (sum(preds[x["id"]] == x["gold"] for x in xs) / len(xs)) if xs else None, len(xs)
    t["overall"] = a(items)
    for d in ("up", "down"):
        t[d] = a([x for x in items if x["dir"] == d])
        for g in ("entailment", "neutral"):
            t[f"{d}_{g}"] = a([x for x in items if x["dir"] == d and x["gold"] == g])
    cells = [t[f"{d}_{g}"][0] for d in ("up", "down") for g in ("entailment", "neutral") if t[f"{d}_{g}"][0] is not None]
    t["balanced_acc"] = (sum(cells) / len(cells), len(cells)) if cells else (None, 0)
    return {k: {"acc": v[0], "n": v[1]} for k, v in t.items()}


def stage_pilot():
    med, _ = b6_sample()
    rng = random.Random(1)
    up = [x for x in med if x["dir"] == "up"]
    dn = [x for x in med if x["dir"] == "down"]
    pil = []
    for pool in (up, dn):
        e = [x for x in pool if x["gold"] == "entailment"][:25]
        n = [x for x in pool if x["gold"] == "neutral"][:25]
        pil += e + n
    rng.shuffle(pil)
    out = {}
    for name, rz in (("thinking_off", THINK_OFF), ("thinking_1024", THINK_ON)):
        preds, nf = asyncio.run(run_pairs(pil, rz, f"b6_pilot_{name}"))
        out[name] = {"table": acc_table(pil, preds), "n_parse_fail": nf}
        logger.info(f"pilot {name}: {json.dumps(out[name]['table'])}")
    off_dn = out["thinking_off"]["table"]["down"]["acc"] or 0
    on_dn = out["thinking_1024"]["table"]["down"]["acc"] or 0
    choose_on = off_dn < 0.80 and (on_dn - off_dn) >= 0.05
    cfg = {"model": MODEL, "chosen": "thinking_1024" if choose_on else "thinking_off",
           "reasoning": THINK_ON if choose_on else THINK_OFF, "rule": "thinking-off unless its downward accuracy < 0.80 "
           "AND thinking-on raises downward accuracy by >= 0.05", "pilot": out, "b1_config": "thinking_off",
           "fallback_gpt41mini_triggered": bool(max(off_dn, on_dn) < 0.70)}
    (RES / "probe_config.json").write_text(json.dumps(cfg, indent=1))
    logger.info(f"chosen probe config: {cfg['chosen']} (down off={off_dn:.3f} on={on_dn:.3f}); spent={llm.spent():.4f}")


def stage_probe(n_limit: int | None):
    cfg = json.loads((RES / "probe_config.json").read_text())
    d = json.loads((ROOT / "data" / "screen_set.json").read_text())
    sents = d["sentences"][:n_limit] if n_limit else d["sentences"]
    out_path = RES / "text_sigs.json"
    exs = {}
    jobs, meta = [], []
    for s in sents:
        ex = text_sig.extract(s["nl"])
        qs = text_sig.probe_questions(ex, with_rel=True)
        exs[s["sid"]] = {"ex": ex, "qs": qs}
        chunks = [qs] if len(qs) <= 40 else [qs[: (len(qs) + 1) // 2], qs[(len(qs) + 1) // 2:]]
        for ci, ch in enumerate(chunks):
            if not ch:
                continue
            prompt = text_sig.render_prompt(ch)
            jobs.append(dict(model=cfg["model"], messages=[{"role": "user", "content": prompt}],
                             purpose="probe_A1A2", reasoning=cfg["reasoning"],
                             max_tokens=4000 if cfg["reasoning"].get("max_tokens") else 1200))
            meta.append((s["sid"], ci, len(chunks)))
    logger.info(f"probe: {len(sents)} sentences, {len(jobs)} calls, {sum(len(v['qs']) for v in exs.values())} questions")
    res = asyncio.run(llm.run_batch(jobs, concurrency=8, est_cost_each=0.004))
    answers = defaultdict(dict)
    usage = defaultdict(lambda: {"cost": 0.0, "calls": 0, "reasoning_tokens": 0, "parse_fail": 0})
    offsets = {}
    for (sid, ci, nch), r in zip(meta, res):
        qs = exs[sid]["qs"]
        half = (len(qs) + 1) // 2
        off = 0 if ci == 0 else half
        if isinstance(r, Exception):
            usage[sid]["parse_fail"] += 1
            logger.error(f"probe failed {sid}: {r}")
            continue
        ans = text_sig.parse_answers(r[0])
        if not ans:
            usage[sid]["parse_fail"] += 1
        for k, v in ans.items():
            answers[sid][k + off] = v
        usage[sid]["cost"] += r[1].get("cost", 0.0)
        usage[sid]["calls"] += 1
        usage[sid]["reasoning_tokens"] += r[1].get("reasoning_tokens", 0)
    out = {}
    for s in sents:
        sid = s["sid"]
        ex, qs = exs[sid]["ex"], exs[sid]["qs"]
        T = text_sig.labels_from_answers(ex, qs, answers.get(sid, {}))
        # A3 relativized coordinates from coordination (zero-LLM)
        a3_rel = {}
        for c, q, kind in ex["coord"]:
            for (x, y) in ((c, q), (q, c)):
                lx = ex["marker"].get(x, "+")
                if kind == "and":
                    a3_rel[f"{x}|{y}|out"], a3_rel[f"{x}|{y}|in"] = "0", lx
                elif kind == "or":
                    a3_rel[f"{x}|{y}|in"], a3_rel[f"{x}|{y}|out"] = "0", lx
        out[sid] = {"nl": s["nl"], "concepts": ex["concepts"], "anchors": ex["anchors"], "coord": ex["coord"],
                    "copies": ex["copies"], "relpairs": ex["relpairs"], "marker": ex["marker"],
                    "llm_labels": T["concept_labels"], "llm_per_mod": T["per_mod"],
                    "llm_rel": {f"{c}|{q}|{sd}": v for (c, q, sd), v in T["rel_labels"].items()},
                    "a3_rel": a3_rel, "consistency": T["consistency"], "n_questions": len(qs),
                    "answers": answers.get(sid, {}), "usage": usage[sid]}
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    labs = Counter(v for o in out.values() for v in o["llm_labels"].values())
    mk = Counter(v for o in out.values() for v in o["marker"].values())
    cons = [o["consistency"] for o in out.values() if o["consistency"] is not None]
    logger.info(f"probe done: llm labels {dict(labs)}; marker {dict(mk)}; mean m1/m2 consistency "
                f"{sum(cons) / max(1, len(cons)):.3f}; parse_fail={sum(u['parse_fail'] for u in usage.values())}; "
                f"reasoning_tokens={sum(u['reasoning_tokens'] for u in usage.values())}; spent={llm.spent():.4f}")


def stage_b6():
    cfg = json.loads((RES / "probe_config.json").read_text())
    med, hp = b6_sample()
    items = med + hp
    preds, nf = asyncio.run(run_pairs(items, cfg["reasoning"], "b6_full"))
    res = {"config": cfg["chosen"], "n_items": len(items), "n_parse_fail": nf,
           "all": acc_table(items, preds), "MED": acc_table(med, preds), "HELP": acc_table(hp, preds)}
    # zero-LLM marker on single-span MED edits
    usable, correct, parsed = 0, 0, 0
    per_dir = Counter()
    per_dir_ok = Counter()
    for x in load_med():
        a, b = x["s1"].split(), x["s2"].split()
        sm = difflib.SequenceMatcher(a=a, b=b)
        ops = [o for o in sm.get_opcodes() if o[0] != "equal"]
        if len(ops) != 1 or ops[0][0] == "insert":
            continue
        parsed += 1
        i1, i2 = ops[0][1], ops[0][2]
        try:
            doc = text_sig.nlp()(x["s1"])
        except Exception:  # noqa: BLE001
            continue
        # map whitespace-token span to spacy tokens by character offsets
        char_start = len(" ".join(a[:i1])) + (1 if i1 > 0 else 0)
        char_end = char_start + len(" ".join(a[i1:i2]))
        toks = [t for t in doc if t.idx >= char_start and t.idx < char_end and t.is_alpha]
        if not toks:
            continue
        fake = [{"cid": 0, "head_i": toks[-1].i}]
        pol = text_sig.rules_marker(doc, fake)[0]
        if pol == "±":
            continue
        usable += 1
        want = "+" if x["dir"] == "up" else "-"
        per_dir[x["dir"]] += 1
        if pol == want:
            correct += 1
            per_dir_ok[x["dir"]] += 1
    res["marker_zero_llm"] = {"n_single_span_edits": parsed, "n_usable": usable,
                              "acc": correct / usable if usable else None,
                              "acc_up": per_dir_ok["up"] / per_dir["up"] if per_dir["up"] else None,
                              "acc_down": per_dir_ok["down"] / per_dir["down"] if per_dir["down"] else None,
                              "n_up": per_dir["up"], "n_down": per_dir["down"]}
    (RES / "b6_results.json").write_text(json.dumps(res, indent=1))
    logger.info(f"B6: {json.dumps(res['all'])} marker={res['marker_zero_llm']} spent={llm.spent():.4f}")


@logger.catch(reraise=True)
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True, choices=["pilot", "probe", "b6"])
    ap.add_argument("--n", type=int, default=None)
    a = ap.parse_args()
    {"pilot": stage_pilot, "probe": lambda: stage_probe(a.n), "b6": stage_b6}[a.stage]()


if __name__ == "__main__":
    main()
