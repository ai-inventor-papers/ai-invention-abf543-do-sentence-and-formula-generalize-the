#!/usr/bin/env python3
"""S5: sentence-only (no-gold) adjudication by the calibrated family-disjoint panel.

Members (round-1 panel_config): M1 anthropic/claude-haiku-4.5 (T=0), M2 x-ai/grok-4.3 (reasoning low),
M3 z-ai/glm-4.6 (non-thinking). Fallbacks: M1 -> claude-sonnet-4.5; M2 -> grok-4.20; M3 -> glm-4.6 low reasoning
-> kimi-k2-thinking. System identity is never shown; item order is shuffled with a seed.

Subcommands:
  smoke        5 calibration items x member (JSON parse rate, $/item)
  calibrate    40 known-label calibration items (single-formula no-gold form); gate accuracy >= 0.80
  l1           vendor-L1 equivalence of greedy pairs (for the sampling strata and LC_maj)  [no API]
  sample       draw the adjudication sample (frame A: 480 greedy system items; frame B: 200 pilot items), seed
  run          panel on the sample (--first N for a first batch), cached / resumable
  sensitivity  30 solver-verified exception/restriction mutants of unanimously-faithful items
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import random
import time
from collections import Counter, defaultdict

from common import RES, ROOT, SEED, SYSTEMS, VENDOR, WORK, append_jsonl, jdump, jload, read_jsonl, setup_logger, sha1

logger = setup_logger("panel_nogold")
from llm import BudgetExceeded, Client  # noqa: E402

# vendor panel constants (copied text; vendor/ds/panel.py is the source; sha1 recorded in frozen_manifest)
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("vpanel", VENDOR / "ds" / "panel.py")
_src = (VENDOR / "ds" / "panel.py").read_text()
_ns: dict = {"__file__": str(VENDOR / "ds" / "panel.py"), "__name__": "vpanel"}
exec(compile(_src.split("def save_prompts")[0].replace("from or_client import Client  # noqa: E402", ""), "vpanel", "exec"), _ns)
STANDARD, SYNTAX, TAXONOMY_TXT, ERROR_TYPES = _ns["STANDARD"], _ns["SYNTAX"], _ns["TAXONOMY_TXT"], _ns["ERROR_TYPES"]
MEMBERS_R1 = jload(VENDOR / "ds" / "work" / "panel_config.json")["members"]
parse_json = None
exec(compile("import re, json\n" + _src[_src.index("def parse_json"):_src.index("def load_cache")], "vpanel2", "exec"), _ns)
parse_json, yn, norm_errs = _ns["parse_json"], _ns["yn"], _ns["norm_errs"]

MEMBERS = {m: {"model": c["model"], "params": c["params"]} for m, c in MEMBERS_R1.items()}
FALLBACKS = {
    "M1": [{"model": "anthropic/claude-sonnet-4.5", "params": {"temperature": 0.0, "max_tokens": 900}}],
    "M2": [{"model": "x-ai/grok-4.20", "params": {"temperature": 0.0, "max_tokens": 4000, "reasoning": {"effort": "low"}}}],
    "M3": [{"model": "z-ai/glm-4.6", "params": {"temperature": 0.0, "max_tokens": 4000, "reasoning": {"effort": "low"}}},
           {"model": "moonshotai/kimi-k2-thinking", "params": {"temperature": 0.0, "max_tokens": 4000}}],
}
NOGOLD_TMPL = (
    "You are checking a first-order logic (FOL) formalization of an English sentence taken from a legal text.\n\n"
    "Sentence: {sentence}\nFormula: {formula}\n\n" + SYNTAX + "\n" + STANDARD + "\n"
    "Cross-references to other provisions (e.g. 'as referred to in Article 6', 'within the meaning of section 152') "
    "may be represented as opaque named conditions (a predicate); their content does not need to be spelled out.\n\n"
    "Error types (use exactly these names):\n" + TAXONOMY_TXT + "\n\n"
    "Judge whether the formula is faithful to the sentence. If an error concerns an exception, carve-out or restriction "
    "introduced by unless / except / other than / provided that / excluding / without prejudice / only, set "
    "exception_involved to \"yes\".\n"
    "Return ONLY a JSON object, no other text:\n"
    '{{"faithful": "yes" or "no", "error_types": [list of error type names, ["none"] if faithful], '
    '"primary_error": "<one error type name>", "exception_involved": "yes" or "no", '
    '"sentence_ambiguous": "yes" or "no", "explanation": "<at most 40 words>"}}')
PANEL_CACHE = WORK / "panel_votes.jsonl"
CFG_PATH = RES / "panel_config_used.json"


def save_prompt() -> None:
    (ROOT / "prompts").mkdir(exist_ok=True)
    (ROOT / "prompts" / "adjudication_nogold.txt").write_text(NOGOLD_TMPL)


def body(cfg: dict, sentence: str, formula: str) -> dict:
    return {"model": cfg["model"], "messages": [{"role": "user", "content": NOGOLD_TMPL.format(sentence=sentence, formula=formula)}],
            **cfg["params"]}


async def judge(client: Client, cfg: dict, member: str, item_id: str, sentence: str, formula: str, phase_tag: str) -> dict:
    parsed, r = None, None
    for attempt in range(2):
        b = body(cfg, sentence, formula)
        if attempt:
            b = {**b, "messages": b["messages"] + [{"role": "user", "content": "Return the JSON object only."}]}
        try:
            r = await client.chat(b, tag=f"{phase_tag}:{member}:{item_id}")
        except BudgetExceeded as e:
            return {"item_id": item_id, "member": member, "model": cfg["model"], "parsed": None, "error": f"budget:{e}",
                    "cost_usd": 0.0}
        parsed = parse_json(r.get("text"))
        if parsed is not None and yn(parsed.get("faithful")) is not None:
            break
    p = parsed or {}
    return {"item_id": item_id, "member": member, "model": cfg["model"], "faithful": yn(p.get("faithful")),
            "error_types": norm_errs(p.get("error_types")), "primary_error": norm_errs(p.get("primary_error"))[:1] or [None],
            "exception_involved": yn(p.get("exception_involved")), "sentence_ambiguous": yn(p.get("sentence_ambiguous")),
            "explanation": str(p.get("explanation", ""))[:400], "cost_usd": (r or {}).get("cost_usd", 0.0),
            "cached": (r or {}).get("cached"), "raw": ((r or {}).get("text") or "")[:1500], "phase": phase_tag,
            "ts": time.time()}


def fix_primary(v: dict) -> dict:
    v["primary_error"] = v["primary_error"][0] if isinstance(v.get("primary_error"), list) else v.get("primary_error")
    return v


# ------------------------------------------------------------------------------------------------ calibration
async def calib_member(cfg: dict, member: str, items: list[dict], phase: str = "calibration") -> dict:
    async with Client(phase, concurrency=12) as c:
        res = await asyncio.gather(*[judge(c, cfg, member, it["cal_id"], it["sentence"], it["formula"], "cal") for it in items])
    res = [fix_primary(r) for r in res]
    correct = sum(1 for it, r in zip(items, res) if r["faithful"] is not None and r["faithful"] == it["label_faithful"])
    parsed = sum(r["faithful"] is not None for r in res)
    return {"member": member, "model": cfg["model"], "params": cfg["params"], "accuracy": correct / len(items),
            "parse_rate": parsed / len(items), "usd": sum(r["cost_usd"] or 0 for r in res),
            "usd_per_item": sum(r["cost_usd"] or 0 for r in res) / len(items),
            "per_item": [{"cal_id": it["cal_id"], "kind": it["kind"], "op": it["op"], "label": it["label_faithful"],
                          "vote": r["faithful"]} for it, r in zip(items, res)]}


def calibrate(smoke: bool = False) -> None:
    items = jload(VENDOR / "ds" / "work" / "calibration_set.json")
    if smoke:
        items = items[:5]

        async def go():
            return await asyncio.gather(*[calib_member(cfg, m, items, "smoke") for m, cfg in MEMBERS.items()])
        outs = asyncio.run(go())
        jdump({o["member"]: {k: v for k, v in o.items() if k != "per_item"} for o in outs}, RES / "panel_smoke.json")
        logger.info(f"smoke: {[(o['member'], o['parse_rate'], round(o['usd_per_item'], 5)) for o in outs]}")
        return

    async def go():
        return await asyncio.gather(*[calib_member(cfg, m, items) for m, cfg in MEMBERS.items()])
    outs = asyncio.run(go())
    results = {o["member"]: [o] for o in outs}
    config = {}
    for o in outs:
        logger.info(f"{o['member']} {o['model']} acc={o['accuracy']:.3f} parse={o['parse_rate']:.2f} ${o['usd']:.4f}")
        config[o["member"]] = {"model": o["model"], "params": o["params"]} if o["accuracy"] >= 0.8 else None
    for m in MEMBERS:
        if config[m] is None:
            for fb in FALLBACKS[m]:
                o = asyncio.run(calib_member(fb, m, items))
                results[m].append(o)
                logger.info(f"{m} FALLBACK {o['model']} acc={o['accuracy']:.3f}")
                if o["accuracy"] >= 0.8:
                    config[m] = {"model": o["model"], "params": o["params"]}
                    break
    jdump(results, RES / "calibration.json")
    jdump({"members": config, "failed": [m for m, c in config.items() if c is None],
           "gate": ">=0.80 accuracy on 40 known-label single-formula items (no-gold prompt)"}, CFG_PATH)


def panel_members() -> dict:
    cfg = jload(CFG_PATH)["members"]
    return {m: c for m, c in cfg.items() if c}


# ------------------------------------------------------------------------------------------------ vendor L1 pairs
def _l1_job(args):
    import sys
    sys.path.insert(0, str(VENDOR / "ds"))
    from fol_equiv import equivalence
    from fol_parse import parse
    key, a, b = args
    t = time.time()
    r = equivalence(parse(a).ast, parse(b).ast, time_limit=6.0, want_entailment=False)
    return key, r["status"], round(time.time() - t, 3)


def l1_pairs(workers: int = 2) -> None:
    """vendor fol_equiv.equivalence (round-1 L1, blind bijection, cap 5,040) on all greedy pairs of each sentence."""
    import multiprocessing as mp
    from concurrent.futures import ProcessPoolExecutor
    cands = read_jsonl(WORK / "candidates.jsonl")
    by = defaultdict(list)
    for c in cands:
        if c["frame"] == "system" and c["sample_idx"] == 0 and c["parse_ok"]:
            by[c["sentence_id"]].append(c)
    for c in cands:  # also samples vs their greedy (B8 uses L1 equivalence)
        pass
    out = WORK / "l1_vendor_pairs.jsonl"
    done = {r["key"] for r in read_jsonl(out)}
    jobs = []
    for sid, cs in by.items():
        for i in range(len(cs)):
            for j in range(i + 1, len(cs)):
                a, b = sorted([cs[i]["fol_canon"], cs[j]["fol_canon"]])
                k = sha1(a + "␞" + b)
                if k in done or a == b:
                    continue
                done.add(k)
                jobs.append((k, a, b))
    greedy_by_sys = {(c["sentence_id"], c["system"]): c for cs in by.values() for c in cs}
    for c in cands:
        if c["frame"] == "system" and c["sample_idx"] > 0 and c["parse_ok"]:
            g = greedy_by_sys.get((c["sentence_id"], c["system"]))
            if g:
                a, b = sorted([g["fol_canon"], c["fol_canon"]])
                k = sha1(a + "␞" + b)
                if k not in done and a != b:
                    done.add(k)
                    jobs.append((k, a, b))
    for c in cands:  # pilot formulas vs every greedy system formula of the same sentence (LC_maj for pilot rows)
        if c["frame"] == "pilot" and c["parse_ok"]:
            for g in by.get(c["sentence_id"], []):
                a, b = sorted([g["fol_canon"], c["fol_canon"]])
                k = sha1(a + "\u241e" + b)
                if k not in done and a != b:
                    done.add(k)
                    jobs.append((k, a, b))
    logger.info(f"vendor L1 jobs {len(jobs)}")
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn")) as ex:
        buf = []
        for n, res in enumerate(ex.map(_l1_job, jobs, chunksize=8)):
            buf.append({"key": res[0], "status": res[1], "seconds": res[2]})
            if len(buf) >= 200:
                append_jsonl(out, buf)
                buf = []
                logger.info(f"L1 {n + 1}/{len(jobs)} {time.time() - t0:.0f}s")
        append_jsonl(out, buf)
    logger.info(f"vendor L1 done in {time.time() - t0:.0f}s")


def l1_status(a: str, b: str, table: dict) -> str:
    if a == b:
        return "equiv_identical"
    x, y = sorted([a, b])
    return table.get(sha1(x + "␞" + y), "missing")


def l1_equiv(st: str) -> bool:
    return st in ("equiv_identical", "equiv_proved", "equiv_bounded")


# ------------------------------------------------------------------------------------------------ sampling
def draw_sample() -> None:
    sents = {s["sentence_id"]: s for s in jload(WORK / "sentences.json")}
    cands = read_jsonl(WORK / "candidates.jsonl")
    table = {r["key"]: r["status"] for r in read_jsonl(WORK / "l1_vendor_pairs.jsonl")}
    greedy = [c for c in cands if c["frame"] == "system" and c["sample_idx"] == 0]
    by = defaultdict(list)
    for c in greedy:
        by[c["sentence_id"]].append(c)
    for sid, cs in by.items():
        for c in cs:
            if not c["parse_ok"]:
                c["agree"] = "single"
                continue
            eq = sum(1 for d in cs if d is not c and d["parse_ok"] and l1_equiv(l1_status(c["fol_canon"], d["fol_canon"], table)))
            c["agree"] = "cluster" if eq >= 1 else "single"
    strata = defaultdict(list)
    for c in greedy:
        strata[(c["system"], c["agree"], sents[c["sentence_id"]]["marker_bin"])].append(c)
    rng = random.Random(SEED)
    target = 480
    alloc = {h: min(4, len(v)) for h, v in strata.items()}
    fac = {h: (1.5 if h[1] == "single" else 1.0) * (1.5 if h[0] in ("gpt-4.1-mini", "llama-3.1-8b") else 1.0) for h in strata}
    rem = target - sum(alloc.values())
    wsum = sum(len(v) * fac[h] for h, v in strata.items())
    raw = {h: rem * len(v) * fac[h] / wsum for h, v in strata.items()}
    for h in strata:
        alloc[h] = min(len(strata[h]), alloc[h] + int(math.floor(raw[h])))
    left = target - sum(alloc.values())
    for h in sorted(strata, key=lambda h: -(raw[h] - math.floor(raw[h]))):
        if left <= 0:
            break
        if alloc[h] < len(strata[h]):
            alloc[h] += 1
            left -= 1
    sample = []
    for h in sorted(strata):
        v = sorted(strata[h], key=lambda c: c["cand_id"])
        pick = rng.sample(v, alloc[h])
        for c in pick:
            sample.append({"item_id": c["cand_id"], "frame": "A", "stratum": "|".join(h), "N_h": len(v), "n_h": alloc[h],
                           "weight": len(v) / alloc[h], "sentence_id": c["sentence_id"], "system": c["system"],
                           "agree": c["agree"], "marker_bin": h[2]})
    per_sys = Counter(s["system"] for s in sample)
    # frame B: pilot rows
    pil = [c for c in cands if c["frame"] == "pilot"]
    byd = defaultdict(list)
    for c in pil:
        byd[c["sentence_id"]].append(c)
    chosen = set()
    for d in sorted(byd):
        v = sorted(byd[d], key=lambda c: c["cand_id"])
        for c in rng.sample(v, min(2, len(v))):
            chosen.add(c["cand_id"])
    rest = [c for c in pil if c["cand_id"] not in chosen]
    n_extra = 200 - len(chosen)
    for ok in (True, False):
        grp = sorted([c for c in rest if c["parse_ok"] == ok], key=lambda c: c["cand_id"])
        k = round(n_extra * len(grp) / max(1, len(rest)))
        for c in rng.sample(grp, min(k, len(grp))):
            chosen.add(c["cand_id"])
    nd = Counter(c["sentence_id"] for c in pil if c["cand_id"] in chosen)
    for c in pil:
        if c["cand_id"] in chosen:
            N = len(byd[c["sentence_id"]])
            sample.append({"item_id": c["cand_id"], "frame": "B", "stratum": "def|" + c["sentence_id"], "N_h": N,
                           "n_h": nd[c["sentence_id"]], "weight": N / nd[c["sentence_id"]], "sentence_id": c["sentence_id"],
                           "system": "pilot", "agree": None, "marker_bin": sents[c["sentence_id"]]["marker_bin"]})
    order = list(range(len(sample)))
    random.Random(SEED + 1).shuffle(order)
    for rank, i in enumerate(order):
        sample[i]["order"] = rank
    sample.sort(key=lambda s: s["order"])
    info = {"n_frameA": sum(s["frame"] == "A" for s in sample), "n_frameB": sum(s["frame"] == "B" for s in sample),
            "N_frameA": len(greedy), "N_frameB": len(pil), "n_strata_A": len(strata), "per_system": dict(per_sys),
            "agree_counts_frame": dict(Counter(c["agree"] for c in greedy)), "drawn_at": time.time(), "seed": SEED,
            "l1_pairs_available": len(table)}
    jdump({"info": info, "items": sample}, WORK / "panel_sample.json")
    logger.info(f"sample: {info}")


# ------------------------------------------------------------------------------------------------ panel run
async def run_items(items: list[dict], members: dict, phase: str = "panel", tag: str = "adj") -> list[dict]:
    done = {(r["item_id"], r["member"], r["model"]) for r in read_jsonl(PANEL_CACHE) if r.get("faithful") is not None}
    lock = asyncio.Lock()
    out = []
    async with Client(phase, concurrency=24) as c:
        async def one(it, m, cfg):
            if (it["item_id"], m, cfg["model"]) in done:
                return None
            r = fix_primary(await judge(c, cfg, m, it["item_id"], it["sentence"], it["formula"], tag))
            async with lock:
                append_jsonl(PANEL_CACHE, [r])
            return r
        tasks = [one(it, m, cfg) for it in items for m, cfg in members.items()]
        for k, fut in enumerate(asyncio.as_completed(tasks)):
            r = await fut
            if r is not None:
                out.append(r)
            if (k + 1) % 150 == 0:
                logger.info(f"panel {k + 1}/{len(tasks)} phase ${c.spent_phase:.3f} total ${c.spent_total:.3f}")
    return out


def item_payload(ids: list[str]) -> list[dict]:
    sents = {s["sentence_id"]: s for s in jload(WORK / "sentences.json")}
    cands = {c["cand_id"]: c for c in read_jsonl(WORK / "candidates.jsonl")}
    out = []
    for i in ids:
        c = cands[i]
        f = c["fol"] if c["fol"] else (c.get("raw_output") or "")
        out.append({"item_id": i, "sentence": sents[c["sentence_id"]]["sentence"], "formula": f if f.strip() else "(empty output)"})
    return out


def run_panel(first: int, pilot_cost: bool) -> None:
    samp = jload(WORK / "panel_sample.json")["items"]
    members = panel_members()
    ids = [s["item_id"] for s in samp]
    if pilot_cost:
        ids = ids[:30]
    elif first:
        ids = ids[:first]
    items = item_payload(ids)
    t0 = time.time()
    res = asyncio.run(run_items(items, members))
    usd = sum(r["cost_usd"] or 0 for r in res if not r.get("cached"))
    info = {"n_items": len(items), "n_new_votes": len(res), "usd_new": usd, "usd_per_item": usd / max(1, len(items)),
            "wall_s": round(time.time() - t0, 1)}
    if pilot_cost:
        info["projected_total_usd"] = info["usd_per_item"] * len(samp)
        jdump(info, RES / "panel_pilot_cost.json")
    logger.info(f"panel run: {info}")


# ------------------------------------------------------------------------------------------------ sensitivity
def build_mutants() -> list[dict]:
    """30 parseable greedy items from B1/B2 sentences, unanimously faithful; one exception/restriction mutant each:
    drop a negated antecedent literal / remove its negation / drop one restrictor conjunct; bounded non-equivalent."""
    import sys
    sys.path.insert(0, str(VENDOR / "ds"))
    from fol_equiv import bounded_check
    from fol_parse import SYM, parse, signature, to_str
    sents = {s["sentence_id"]: s for s in jload(WORK / "sentences.json")}
    cands = {c["cand_id"]: c for c in read_jsonl(WORK / "candidates.jsonl")}
    votes = defaultdict(dict)
    for r in read_jsonl(PANEL_CACHE):
        if r.get("phase") == "adj" and r.get("faithful") is not None:
            votes[r["item_id"]][r["member"]] = r["faithful"]
    base = [i for i, v in votes.items() if len(v) == 3 and all(v.values()) and i in cands and cands[i]["parse_ok"]
            and cands[i]["frame"] == "system" and sents[cands[i]["sentence_id"]]["marker_bin"] in ("B1", "B2")]
    if len(base) < 30:  # widen to all bins (recorded)
        base += [i for i, v in votes.items() if len(v) == 3 and all(v.values()) and i in cands and cands[i]["parse_ok"]
                 and cands[i]["frame"] == "system" and i not in base]
    rng = random.Random(SEED + 5)
    rng.shuffle(base)

    def paths(n, p=()):
        yield p, n
        if n[0] in ("forall", "exists"):
            yield from paths(n[2], p + (2,))
        elif n[0] == "not":
            yield from paths(n[1], p + (1,))
        elif n[0] in SYM:
            yield from paths(n[1], p + (1,))
            yield from paths(n[2], p + (2,))

    def get(n, p):
        for i in p:
            n = n[i]
        return n

    def repl(n, p, new):
        if not p:
            return new
        l = list(n)
        l[p[0]] = repl(n[p[0]], p[1:], new)
        return tuple(l)

    def in_ante(ast, p):
        n = ast
        for i in p:
            if n[0] == "imp" and i == 1:
                return True
            n = n[i]
        return False

    muts = []
    for cid in base:
        if len(muts) >= 30:
            break
        ast = parse(cands[cid]["fol"]).ast
        ops = []
        for p, n in paths(ast):
            if n[0] == "and" and in_ante(ast, p):
                for k in (1, 2):
                    child = n[k]
                    if child[0] == "not":
                        ops.append(("drop_exception", p, n[3 - k]))
                        ops.append(("invert_exception", p + (k,), child[1]))
                    else:
                        ops.append(("drop_restrictor", p, n[3 - k]))
        rng.shuffle(ops)
        ops.sort(key=lambda o: {"drop_exception": 0, "invert_exception": 1, "drop_restrictor": 2}[o[0]])
        for kind, p, new in ops:
            m = repl(ast, p, new)
            preds, consts = signature(ast)
            r, _ = bounded_check(ast, m, sorted(consts), {}, "equiv", ns=(1, 2, 3), timeout_ms=5000)
            if r == "countermodel":
                muts.append({"item_id": f"mut:{cid}:{kind}", "base_id": cid, "kind": kind, "formula": to_str(m),
                             "sentence_id": cands[cid]["sentence_id"], "bin": sents[cands[cid]["sentence_id"]]["marker_bin"]})
                break
    return muts


def sensitivity() -> None:
    muts = build_mutants()
    jdump(muts, WORK / "sensitivity_mutants.json")
    sents = {s["sentence_id"]: s for s in jload(WORK / "sentences.json")}
    items = [{"item_id": m["item_id"], "sentence": sents[m["sentence_id"]]["sentence"], "formula": m["formula"]} for m in muts]
    members = panel_members()
    asyncio.run(run_items(items, members, phase="sensitivity", tag="sens"))
    votes = defaultdict(dict)
    for r in read_jsonl(PANEL_CACHE):
        if r.get("phase") == "sens" and r.get("faithful") is not None:
            votes[r["item_id"]][r["member"]] = r
    per = {m: [] for m in members}
    maj = []
    exc = []
    for mu in muts:
        v = votes.get(mu["item_id"], {})
        flags = {m: (not r["faithful"]) for m, r in v.items()}
        for m, f in flags.items():
            per[m].append(f)
        if flags:
            maj.append(sum(flags.values()) >= 2 if len(flags) >= 2 else list(flags.values())[0])
            exc.append(sum(bool(r.get("exception_involved")) for r in v.values() if not r["faithful"]) >= 1)
    res = {"n_mutants": len(muts), "kinds": dict(Counter(m["kind"] for m in muts)), "bins": dict(Counter(m["bin"] for m in muts)),
           "member_flag_rate": {m: (sum(v) / len(v) if v else None) for m, v in per.items()},
           "majority_flag_rate": sum(maj) / len(maj) if maj else None,
           "exception_flag_rate_among_flagged": sum(exc) / len(exc) if exc else None,
           "target": ">=0.8 (reported, not gating); majority < 0.6 => every downstream result labelled 'panel weak on exceptions'"}
    res["panel_weak_on_exceptions"] = res["majority_flag_rate"] is not None and res["majority_flag_rate"] < 0.6
    jdump(res, RES / "sensitivity_check.json")
    logger.info(f"sensitivity: {res}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    ap.add_argument("--first", type=int, default=0)
    ap.add_argument("--pilot-cost", action="store_true")
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args()
    save_prompt()
    if a.cmd == "smoke":
        calibrate(smoke=True)
    elif a.cmd == "calibrate":
        calibrate()
    elif a.cmd == "l1":
        l1_pairs(a.workers)
    elif a.cmd == "sample":
        draw_sample()
    elif a.cmd == "run":
        run_panel(a.first, a.pilot_cost)
    elif a.cmd == "sensitivity":
        sensitivity()


if __name__ == "__main__":
    main()
