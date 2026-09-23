#!/usr/bin/env python3
"""PHASE 1 / STEP 3 (R2): text-side polarity chooser.

Candidates: T0 rules marker | T1a gemini-2.5-flash probe (thinking 1024, iter-1 prompt) | T1b probe when its two
specialised-copy labels agree and lie in {+,-,0}, else rule | T1c rule unless (probe consistent '-' and rule '+') |
T2 = T1b with a stronger model deciding rule/probe disagreements.

DEV data (all pre-freeze, no held-out labels):
 (a) MED/HELP DEV = the 400 iter-1 B6 items (MED 150 up / 150 down; HELP 50 / 50; seeded as iter-1), restricted to the
     single-span-edit items whose edited word is an extracted concept. Gold polarity = '+' (upward) / '-' (downward).
     The probe asks, for the edited concept only, the iter-1 substitution questions (2 specialised copies x down/up),
     batched 10 items per call with the iter-1 render_prompt.
 (b) IN-DOMAIN SILVER on SCREEN_DEV golds that the L4 audit marks faithful: silver label of concept c = solver
     signature label of its aligned gold predicate under the chosen R1 aligner.
Selection (pre-registered): maximise mean(balanced MED/HELP-DEV acc, silver-DEV acc) subject to downward MED-DEV acc
>= T0's - 0.02; tie -> cheaper; T2 eligible only if its projected full-run cost (700 held-out + 300 screen sentences)
<= $1.5. Then the chosen T (and T0) are reported on MED/HELP TEST (fresh seeded 20260923 disjoint sample: MED 400 =
200 up/200 down balanced on gold within direction, HELP 200 = 100/100) with Wilson CIs.

Stages: --stage dev | pilot | select | test
"""
from __future__ import annotations

import argparse
import csv
import difflib
import json
import math
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import screen_common as sc  # noqa: E402
import align2  # noqa: E402
import core  # noqa: E402
import llm  # noqa: E402
import text_sig  # noqa: E402  (legacy)

logger.remove()
logger.add(sys.stdout, level="INFO", format="{time:HH:mm:ss}|{level:<7}|{message}")
logger.add(ROOT / "logs" / "phase1_r2.log", rotation="30 MB", level="DEBUG")
RES = ROOT / "results"
RAW = ROOT / "data" / "raw"
PROBE_MODEL = "google/gemini-2.5-flash"
PROBE_REASONING = {"max_tokens": 1024}
STRONG = {"gemini-2.5-pro": {"model": "google/gemini-2.5-pro", "reasoning": {"max_tokens": 2048}, "max_tokens": 8000},
          "gpt-5-mini": {"model": "openai/gpt-5-mini", "reasoning": {"effort": "low"}, "max_tokens": 6000}}
N_HELDOUT_SENT, N_SCREEN_SENT = 700, 300


# ------------------------------------------------------------------ MED / HELP
def load_med():
    rows = list(csv.DictReader((RAW / "MED.tsv").open(encoding="utf-8"), delimiter="\t"))
    out = []
    for r in rows:
        g = r.get("genre", "")
        d = "up" if "upward_monotone" in g else "down" if "downward_monotone" in g else None
        if d is None or r.get("gold_label") not in ("entailment", "neutral"):
            continue
        out.append({"src": "MED", "id": f"MED-{r['index']}", "dir": d, "gold": r["gold_label"],
                    "s1": r["sentence1"].strip(), "s2": r["sentence2"].strip()})
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
                    "s1": r["ori_sentence"].strip(), "s2": r["new_sentence"].strip()})
    return out


def balanced(items, n_per_dir, rng):
    out = []
    for d in ("up", "down"):
        for g in ("entailment", "neutral"):
            pool = [x for x in items if x["dir"] == d and x["gold"] == g]
            rng.shuffle(pool)
            out += pool[: n_per_dir // 2]
    return out


def dev_items():
    rng = random.Random(0)  # identical to iter-1 run_text.b6_sample
    return balanced(load_med(), 150, rng) + balanced(load_help(), 50, rng)


def test_items():
    dev_ids = {x["id"] for x in dev_items()}
    rng = random.Random(20260923)
    med = [x for x in load_med() if x["id"] not in dev_ids]
    hp = [x for x in load_help() if x["id"] not in dev_ids]
    # oversample then keep usable single-span items up to the target per cell
    out = []
    for pool, n_cell in ((med, 100), (hp, 50)):
        for d in ("up", "down"):
            for g in ("entailment", "neutral"):
                cell = [x for x in pool if x["dir"] == d and x["gold"] == g]
                rng.shuffle(cell)
                out += cell[:n_cell]
    return out


def span_concept(x: dict) -> dict | None:
    """Single-span-edit filter (iter-1 run_text) + the extracted concept whose head is the edited token."""
    a, b = x["s1"].split(), x["s2"].split()
    ops = [o for o in difflib.SequenceMatcher(a=a, b=b).get_opcodes() if o[0] != "equal"]
    if len(ops) != 1 or ops[0][0] == "insert":
        return None
    i1, i2 = ops[0][1], ops[0][2]
    ex = text_sig.extract(x["s1"])
    doc = text_sig.nlp()(x["s1"])
    cs = len(" ".join(a[:i1])) + (1 if i1 > 0 else 0)
    ce = cs + len(" ".join(a[i1:i2]))
    toks = [t for t in doc if cs <= t.idx < ce and t.is_alpha]
    if not toks:
        return None
    rule = text_sig.rules_marker(doc, [{"cid": 0, "head_i": toks[-1].i}])[0]
    tok_ids = {t.i for t in toks}
    cand = [c for c in ex["concepts"] if c["head_i"] in tok_ids and not c["is_const"]]
    if not cand:
        cand = [c for c in ex["concepts"] if not c["is_const"] and c["left_i"] <= toks[-1].i <= c["head_i"]]
    if not cand:
        return {"rule_span": rule, "cid": None}
    c = cand[-1]
    return {"rule_span": rule, "cid": c["cid"], "rule": ex["marker"][c["cid"]], "copies": ex["copies"].get(c["cid"]),
            "sentence": x["s1"], "span": c["span"]}


def probe_jobs(units: list[dict], model: str, reasoning: dict, max_tokens: int, purpose: str, batch: int = 10):
    """units: [{uid, sentence, copies}] -> jobs + index. 4 questions per unit (2 copies x down/up)."""
    jobs, idx = [], []
    for i in range(0, len(units), batch):
        chunk = units[i:i + batch]
        qs = []
        for u in chunk:
            for mi, sp in enumerate(u["copies"][:2]):
                qs.append({"key": (u["uid"], mi, "down"), "A": u["sentence"], "B": sp})
                qs.append({"key": (u["uid"], mi, "up"), "A": sp, "B": u["sentence"]})
        jobs.append(dict(model=model, messages=[{"role": "user", "content": text_sig.render_prompt(qs)}],
                         purpose=purpose, reasoning=reasoning, max_tokens=max_tokens))
        idx.append(qs)
    return jobs, idx


def labels_from(res, idx) -> dict:
    """-> {uid: [lab_m1, lab_m2]}"""
    ans = {}
    for r, qs in zip(res, idx):
        if isinstance(r, Exception):
            continue
        a = text_sig.parse_answers(r[0])
        for j, q in enumerate(qs):
            if (j + 1) in a:
                ans[q["key"]] = a[j + 1]
    out = {}
    uids = {q["key"][0] for qs in idx for q in qs}
    for u in uids:
        out[u] = [text_sig._lab(ans.get((u, mi, "down")), ans.get((u, mi, "up"))) for mi in (0, 1)]
    return out


def cost_of(res) -> float:
    return sum((r[1].get("cost") or 0.0) + (r[1].get("cost_original") or 0.0) for r in res if not isinstance(r, Exception))


def wilson(k: float, n: int, z: float = 1.96):
    if n == 0:
        return [None, None]
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [c - h, c + h]


def decide(side: str, rule: str, pm: list | None, strong_pm: list | None) -> str:
    llm_lab = None
    if pm:
        llm_lab = pm[0] if pm[0] == pm[1] else "?"
    strong = None
    if strong_pm:
        sp = core.probe_consistent(strong_pm)
        strong = sp if sp is not None else None
    out = core.choose_labels({0: rule}, {0: llm_lab} if pm else None, {0: pm} if pm else None, side,
                             {0: strong} if strong else None)
    return out[0]


def acc_tables(items: list[dict], side: str, strong_key: str | None = None) -> dict:
    t = defaultdict(lambda: [0, 0])
    for x in items:
        lab = decide(side, x["rule"], x.get("probe"), x.get(f"strong_{strong_key}") if strong_key else None)
        gold = "+" if x["dir"] == "up" else "-"
        for k in (x["dir"], f"{x['src']}_{x['dir']}", "all"):
            t[k][0] += lab == gold
            t[k][1] += 1
    out = {k: {"acc": v[0] / v[1] if v[1] else None, "n": v[1], "ci95": wilson(v[0], v[1])} for k, v in t.items()}
    ups, dns = out.get("up", {}).get("acc"), out.get("down", {}).get("acc")
    out["balanced"] = {"acc": (ups + dns) / 2 if ups is not None and dns is not None else None}
    return out


# ------------------------------------------------------------------ stages
def prepare(items: list[dict], tag: str) -> list[dict]:
    out, drop = [], Counter()
    for x in items:
        sc_ = span_concept(x)
        if sc_ is None:
            drop["not_single_span"] += 1
            continue
        if sc_.get("cid") is None or not sc_.get("copies"):
            drop["no_concept"] += 1
            continue
        out.append({**x, **sc_, "uid": x["id"]})
    logger.info(f"{tag}: {len(items)} items -> {len(out)} usable; drops {dict(drop)}")
    return out, dict(drop)


def run_probe(units: list[dict], purpose: str) -> tuple[dict, float]:
    jobs, idx = probe_jobs(units, PROBE_MODEL, PROBE_REASONING, 4000, purpose)
    res = llm.run(jobs, concurrency=16, est_cost_each=0.004)
    return labels_from(res, idx), cost_of(res)


def silver_screen_dev() -> list[dict]:
    """SCREEN_DEV golds with L4 gold_faithful_final True: per concept {sid, cid, rule, probe per_mod, silver}."""
    r1 = json.loads((RES / "r1_grid.json").read_text())
    cfg = r1["chosen_cfg"]
    import phase1_r1
    aligner = phase1_r1.fallback_aligner(cfg) if cfg.get("fallback_mpnet_0.4") else phase1_r1.make_aligner(cfg)
    l4 = {}
    for line in (ROOT / "data" / "screen_l4.jsonl").read_text().splitlines():
        x = json.loads(line)
        l4[x["sentence_id"]] = x["gold_faithful_final"]
    dev, _ = sc.splits()
    S = {s["sid"]: s for s in sc.screen()["sentences"]}
    out = []
    n_faith = 0
    for sid in dev:
        if l4.get(sid) is not True:
            continue
        n_faith += 1
        # the L4 audit judged the ORIGINAL v1 gold; use it (gold_fol_orig if the screen used a corrected one)
        g = S[sid].get("gold_fol_orig") or S[sid]["gold_fol"]
        p = sc.lparse(g)
        Sg = sc.fsigs().get(g)
        if p is None or Sg is None or "error" in Sg:
            continue
        ex = sc.ex_of(sid)
        A = aligner(p.preds, p.consts, ex["concepts"], ex["anchors"])
        ts = sc.tsigs()[sid]
        by_c = defaultdict(list)
        for P, a in A["preds"].items():
            if a["cid"] is not None:
                by_c[a["cid"]].append(P)
        for c in ex["concepts"]:
            if c["is_const"] or c["cid"] not in by_c:
                continue
            P = by_c[c["cid"]][0]
            sl = Sg["labels"].get(P, "?")
            if A["preds"][P]["flip"]:
                sl = core.FLIP[sl] if hasattr(core, "FLIP") else sl
            if sl not in ("+", "-", "0"):
                continue
            pm = ts["llm_per_mod"].get(str(c["cid"]))
            out.append({"sid": sid, "cid": c["cid"], "rule": ex["marker"][c["cid"]], "probe": pm, "silver": sl,
                        "sentence": ts["nl"], "copies": ts["copies"].get(str(c["cid"])), "uid": f"{sid}|{c['cid']}"})
    logger.info(f"silver: {n_faith} L4-faithful SCREEN_DEV golds -> {len(out)} aligned concepts with silver labels "
                f"{Counter(x['silver'] for x in out)}")
    return out


def silver_acc(units: list[dict], side: str, strong_key: str | None = None) -> dict:
    t = defaultdict(lambda: [0, 0])
    for x in units:
        lab = decide(side, x["rule"], x.get("probe"), x.get(f"strong_{strong_key}") if strong_key else None)
        for k in (f"silver_{x['silver']}", "all"):
            t[k][0] += lab == x["silver"]
            t[k][1] += 1
    return {k: {"acc": v[0] / v[1], "n": v[1], "ci95": wilson(v[0], v[1])} for k, v in t.items()}


def disagreement(x: dict) -> bool:
    return decide("T1b", x["rule"], x.get("probe"), None) != x["rule"]


def stage_dev():
    dev, drops = prepare(dev_items(), "MED/HELP DEV")
    probe, cost = run_probe(dev, "r2_dev_probe")
    for x in dev:
        x["probe"] = probe.get(x["uid"])
    silver = silver_screen_dev()
    tabs = {s: {"medhelp": acc_tables(dev, s), "silver": silver_acc(silver, s)} for s in ("T0", "T1a", "T1b", "T1c")}
    n_dis_dev = sum(disagreement(x) for x in dev)
    n_dis_sil = sum(disagreement(x) for x in silver)
    # disagreement rate on ALL screen concepts (cached probe) -> projection of T2 re-asks
    n_c = n_d = 0
    for sid, ts in sc.tsigs().items():
        for k, rl in ts["marker"].items():
            pm = ts["llm_per_mod"].get(k)
            if pm is None:
                continue
            n_c += 1
            n_d += decide("T1b", rl, pm, None) != rl
    per_sent = n_d / len(sc.tsigs())
    out = {"dev_items": dev, "dev_drops": drops, "silver_units": silver, "tables": tabs, "probe_cost_usd": cost,
           "n_disagree_dev": n_dis_dev, "n_disagree_silver": n_dis_sil,
           "screen_concepts": n_c, "screen_disagreements": n_d, "disagreements_per_sentence": per_sent,
           "projected_T2_reasks_full_run": per_sent * (N_HELDOUT_SENT + N_SCREEN_SENT)}
    (RES / "r2_dev.json").write_text(json.dumps(out, indent=1, default=str))
    for s, t in tabs.items():
        logger.info(f"{s}: MED/HELP up={t['medhelp'].get('up', {}).get('acc')} down={t['medhelp'].get('down', {}).get('acc')}"
                    f" bal={t['medhelp']['balanced']['acc']} | silver={t['silver'].get('all', {}).get('acc')}")
    logger.info(f"disagreements: dev {n_dis_dev}/{len(dev)} silver {n_dis_sil}/{len(silver)}; screen {n_d}/{n_c} "
                f"({per_sent:.2f}/sentence); spent {llm.spent():.4f}")


def stage_pilot(pilot_cap: float = 0.60):
    d = json.loads((RES / "r2_dev.json").read_text())
    dev = d["dev_items"]
    down = [x for x in dev if x["dir"] == "down" and x["src"] == "MED"]
    planned = d["projected_T2_reasks_full_run"] + d["n_disagree_dev"] + d["n_disagree_silver"]
    rep = {"planned_reask_units_full_run": planned, "models": {}}
    spent0 = llm.spent()
    for name, m in STRONG.items():
        if llm.spent() - spent0 >= pilot_cap:
            rep["models"][name] = {"status": "skipped_pilot_cap"}
            continue
        first = down[:20]
        jobs, idx = probe_jobs(first, m["model"], m["reasoning"], m["max_tokens"], f"r2_pilot_{name}")
        try:
            res = llm.run(jobs, concurrency=8, est_cost_each=0.06 if "pro" in name else 0.01)
        except llm.BudgetExceeded as e:
            rep["models"][name] = {"status": f"budget: {e}"}
            continue
        c = cost_of(res)
        per_unit = c / max(1, len(first))
        proj = per_unit * planned
        labs = labels_from(res, idx)
        info = {"n_first": len(first), "cost_first": c, "cost_per_unit": per_unit, "projected_full_run": proj,
                "n_failed_calls": sum(isinstance(r, Exception) for r in res)}
        if proj > 1.5:
            info["status"] = "stopped: projected full-run cost > $1.5 (T2 ineligible with this model)"
        else:
            rest = down[20:150]
            jobs2, idx2 = probe_jobs(rest, m["model"], m["reasoning"], m["max_tokens"], f"r2_pilot_{name}")
            if llm.spent() - spent0 + per_unit * len(rest) > pilot_cap:
                rest = rest[: max(0, int((pilot_cap - (llm.spent() - spent0)) / max(per_unit, 1e-6)))]
                jobs2, idx2 = probe_jobs(rest, m["model"], m["reasoning"], m["max_tokens"], f"r2_pilot_{name}")
            res2 = llm.run(jobs2, concurrency=8, est_cost_each=max(per_unit * 10 * 1.5, 0.002)) if jobs2 else []
            labs.update(labels_from(res2, idx2))
            info["cost_total"] = c + cost_of(res2)
            info["status"] = "completed"
        units = [x for x in down if x["uid"] in labs]
        k = sum(core.probe_consistent(labs[x["uid"]]) == "-" for x in units)
        info["down_acc_consistent_label"] = k / len(units) if units else None
        info["n_scored"] = len(units)
        info["ci95"] = wilson(k, len(units))
        rep["models"][name] = info
        logger.info(f"pilot {name}: {info}")
    rep["pilot_spent"] = llm.spent() - spent0
    (RES / "r2_pilot.json").write_text(json.dumps(rep, indent=1))


def stage_select():
    d = json.loads((RES / "r2_dev.json").read_text())
    pil = json.loads((RES / "r2_pilot.json").read_text()) if (RES / "r2_pilot.json").exists() else {"models": {}}
    dev, silver, tabs = d["dev_items"], d["silver_units"], d["tables"]
    # T2: eligible strong model = completed pilot with projected cost <= 1.5, best pilot downward accuracy
    elig = {n: v for n, v in pil["models"].items() if v.get("status") == "completed" and v["projected_full_run"] <= 1.5}
    t2_model = max(elig, key=lambda n: (elig[n]["down_acc_consistent_label"] or 0)) if elig else None
    if t2_model:
        m = STRONG[t2_model]
        units = [x for x in dev if disagreement(x)] + [x for x in silver if disagreement(x)]
        jobs, idx = probe_jobs(units, m["model"], m["reasoning"], m["max_tokens"], f"r2_T2_dev_{t2_model}")
        res = llm.run(jobs, concurrency=8, est_cost_each=max(elig[t2_model]["cost_per_unit"] * 10 * 1.5, 0.002))
        labs = labels_from(res, idx)
        for x in dev + silver:
            if x["uid"] in labs:
                x[f"strong_{t2_model}"] = labs[x["uid"]]
        tabs["T2"] = {"medhelp": acc_tables(dev, "T2", t2_model), "silver": silver_acc(silver, "T2", t2_model),
                      "model": t2_model}
    t0_down = tabs["T0"]["medhelp"]["down"]["acc"]
    cost_rank = {"T0": 0, "T1c": 1, "T1b": 1, "T1a": 1, "T2": 2}
    obj = {}
    for s, t in tabs.items():
        bal = t["medhelp"]["balanced"]["acc"]
        sil = t["silver"]["all"]["acc"]
        feasible = t["medhelp"]["down"]["acc"] >= t0_down - 0.02
        obj[s] = {"objective": (bal + sil) / 2, "balanced_medhelp": bal, "silver": sil,
                  "down": t["medhelp"]["down"]["acc"], "feasible": feasible}
    feas = [s for s in obj if obj[s]["feasible"]]
    chosen = sorted(feas, key=lambda s: (-round(obj[s]["objective"], 12), cost_rank[s]))[0]
    out = {"objectives": obj, "chosen": chosen, "t2_model": t2_model, "t0_down": t0_down,
           "rule": "max mean(balanced MED/HELP-DEV, silver-DEV) s.t. down >= T0-0.02; tie -> cheaper; T2 needs <= $1.5",
           "tables": tabs, "pilot": pil}
    (RES / "r2_select.json").write_text(json.dumps(out, indent=1))
    d["dev_items"], d["silver_units"], d["tables"] = dev, silver, tabs
    (RES / "r2_dev.json").write_text(json.dumps(d, indent=1, default=str))
    logger.info(f"R2 chosen {chosen}: {json.dumps(obj)}")


def stage_test():
    sel = json.loads((RES / "r2_select.json").read_text())
    chosen, t2m = sel["chosen"], sel["t2_model"]
    test, drops = prepare(test_items(), "MED/HELP TEST")
    probe, cost = run_probe(test, "r2_test_probe")
    for x in test:
        x["probe"] = probe.get(x["uid"])
    if chosen == "T2" and t2m:
        m = STRONG[t2m]
        units = [x for x in test if disagreement(x)]
        jobs, idx = probe_jobs(units, m["model"], m["reasoning"], m["max_tokens"], f"r2_T2_test_{t2m}")
        labs = labels_from(llm.run(jobs, concurrency=8, est_cost_each=0.01), idx)
        for x in units:
            x[f"strong_{t2m}"] = labs.get(x["uid"])
    tabs = {s: acc_tables(test, s, t2m if s == "T2" else None) for s in ["T0", "T1a", "T1b", "T1c"] +
            (["T2"] if chosen == "T2" else [])}
    out = {"chosen": chosen, "n_items": len(test), "drops": drops, "tables": tabs, "probe_cost_usd": cost,
           "items": test}
    (RES / "r2_test.json").write_text(json.dumps(out, indent=1, default=str))
    for s, t in tabs.items():
        logger.info(f"TEST {s}: up={t['up']['acc']:.3f} {t['up']['ci95']} down={t['down']['acc']:.3f} "
                    f"{t['down']['ci95']} bal={t['balanced']['acc']:.3f}")


@logger.catch(reraise=True)
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True, choices=["dev", "pilot", "select", "test"])
    a = ap.parse_args()
    {"dev": stage_dev, "pilot": stage_pilot, "select": stage_select, "test": stage_test}[a.stage]()


if __name__ == "__main__":
    main()
