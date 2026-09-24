#!/usr/bin/env python3
"""STEP 6: fresh LABELS (refuse to run before the freeze receipt, except the calibration gate which touches no
fresh item). Panel = round-1 members (vendor/ds/work/panel_config.json): M1 claude-haiku-4.5, M2 grok-4.3
(reasoning low), M3 glm-4.6 (non-thinking); prompts = round-1 frozen templates (vendor/ds/src/panel.py).

  gate : 40 known-label calibration items x 3 members, gold-audit prompt; >= 0.80 required per member (drift
         vs round 1 reported)
  l0   : gold audit of the 450 fresh golds. BUDGET CASCADE (deviation D-L0-cascade): M3 on every gold; M3
         'faithful' -> accepted; otherwise M1; M1 'unfaithful' -> unfaithful; M1 'faithful' -> M2 tie-break.
         A seeded 10% subset gets all 3 (Fleiss kappa, cascade-vs-majority agreement). On the round-1 dev votes
         this cascade agrees with the 3-member majority on 512/530 (96.6%) golds where all needed votes exist.
         Corrections: vendor audit.validate_correction (parses, satisfiable, non-equivalent to the original).
  l1   : audited-solver label for every parseable fresh output vs the audited gold: vendor fol_equiv.equivalence
         (lexical-free bijection, time_limit 30 s) -> faithful {equiv_proved, equiv_bounded} / unfaithful
         {non_equiv, non_equiv_no_bijection} / unknown
  l3   : blinded A/B adjudication (gold vs candidate, seeded order) of a stratified, sentence-PAIRED sample of
         greedy rows with audited gold. CASCADE (label-identical to the full-panel majority): M1 + M3 on every
         item; M2 only if they disagree on the candidate, plus a seeded 10% subset with all 3. Post-stratified
         weights N_h / n_h over strata L1 status x LC_maj position x tercile (+ unparseable stratum).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import time
from collections import Counter, defaultdict

import numpy as np
from loguru import logger

from common import DEP, RES, ROOT, SAMPLE_SYSTEMS, WORK, assert_frozen, log_reads, read_jsonl, setup_logging, write_jsonl
from orc import BudgetExceeded, Client

import importlib.util
_spec = importlib.util.spec_from_file_location("ds_panel", ROOT / "vendor" / "ds" / "src" / "panel.py")
ds_panel = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ds_panel)
ADJ_TMPL, GOLD_AUDIT_TMPL, parse_json, yn, norm_errs = (ds_panel.ADJ_TMPL, ds_panel.GOLD_AUDIT_TMPL, ds_panel.parse_json,
                                                        ds_panel.yn, ds_panel.norm_errs)
CFG = json.loads((ROOT / "vendor" / "ds" / "work" / "panel_config.json").read_text())["members"]
FR = WORK / "fresh_frame.jsonl"


def body(member: str, prompt: str) -> dict:
    c = CFG[member]
    return {"model": c["model"], "messages": [{"role": "user", "content": prompt}], **c["params"]}


async def ask(client: Client, member: str, prompt: str, tag: str) -> dict:
    """One panel call with the round-1 retry-once-on-unparseable-JSON rule."""
    r = None
    parsed = None
    for attempt in range(2):
        b = body(member, prompt)
        if attempt:
            b = {**b, "seed": 1}  # a distinct request body so the cache does not return the unparseable answer
        r = await client.chat(b, tag=f"{member}|{tag}")
        parsed = parse_json(r["text"])
        if parsed is not None:
            break
    return {"member": member, "model": CFG[member]["model"], "parsed": parsed, "raw": (r["text"] or "")[:2000],
            "cost_usd": r["cost_usd"], "cached": r.get("cached"), "error": r["error"]}


def audit_vote(rec: dict) -> dict | None:
    p = rec.get("parsed")
    if not p:
        return None
    return {"faithful": yn(p.get("faithful")), "sentence_ambiguous": yn(p.get("sentence_ambiguous")),
            "error_types": norm_errs(p.get("error_types")),
            "primary_error": (norm_errs(p.get("primary_error")) or ["other"])[0],
            "explanation": str(p.get("explanation", ""))[:400], "corrected_fol": str(p.get("corrected_fol") or "")[:600],
            "model": rec["model"]}


# ------------------------------------------------------------------------------------------------- gate
async def cmd_gate(cap: float) -> None:
    items = json.loads((DEP / "work" / "calibration_set.json").read_text())
    r1 = json.loads((DEP / "work" / "calibration_results.json").read_text())
    out = {}
    async with Client("calibration", phase_cap=cap, concurrency=24, cache_name="calibration") as client:
        for m in ("M1", "M2", "M3"):
            recs = await asyncio.gather(*[ask(client, m, GOLD_AUDIT_TMPL.format(sentence=it["sentence"], formula=it["formula"]),
                                              f"cal|{it['cal_id']}") for it in items])
            per = []
            for it, rec in zip(items, recs):
                v = audit_vote(rec)
                f = v["faithful"] if v else None
                per.append({"cal_id": it["cal_id"], "kind": it["kind"], "op": it["op"], "label": it["label_faithful"],
                            "vote": f, "ok": f is not None and f == it["label_faithful"]})
            acc = sum(p["ok"] for p in per) / len(per)
            out[m] = {"model": CFG[m]["model"], "accuracy": acc, "pass": acc >= 0.80, "per_item": per}
            logger.info(f"gate {m} {CFG[m]['model']}: {acc:.3f}")
        logger.info(f"gate spend ${client.spent_phase:.4f}")
    out["round1"] = r1 if isinstance(r1, dict) else {"raw": r1}
    (RES / "calibration_gate.json").write_text(json.dumps(out, indent=1, default=str))


# ------------------------------------------------------------------------------------------------- L0
def validate_correction(orig: str, corr: str):
    from fol_equiv import bounded_check, sat_valid_check
    from fol_parse import parse, signature
    if not corr.strip():
        return False, "empty"
    pc = parse(corr)
    if not pc.ok:
        return False, "unparseable: " + pc.error[:80]
    sv = sat_valid_check(pc.ast)
    if not sv["satisfiable"]:
        return False, "unsat"
    po = parse(orig)
    if po.ok:
        _, c1 = signature(po.ast)
        _, c2 = signature(pc.ast)
        r, _ = bounded_check(pc.ast, po.ast, sorted(c1 | c2), {}, "equiv")
        if r == "none":
            return False, "equivalent_to_original"
    return True, "ok"


async def cmd_l0(cap: float) -> None:
    assert_frozen()
    log_reads("l0")
    from fol_parse import parse, to_str
    sents = json.loads((RES / "fresh_sentences.json").read_text())
    rng = random.Random(20260924)
    full = {s["sid"] for s in sents if rng.random() < 0.10}
    out = {}
    async with Client("gold_audit", phase_cap=cap, concurrency=24, cache_name="gold_audit") as client:
        async def one(s):
            prompt = GOLD_AUDIT_TMPL.format(sentence=s["sentence"], formula=s["gold_fol_original"])
            tag = f"l0|{s['sid']}"
            votes = {}
            v3 = audit_vote(await ask(client, "M3", prompt, tag))
            votes["M3"] = v3
            is_full = s["sid"] in full
            f3 = v3["faithful"] if v3 else None
            if is_full or f3 is not True:
                votes["M1"] = audit_vote(await ask(client, "M1", prompt, tag))
            f1 = votes["M1"]["faithful"] if votes.get("M1") else None
            if is_full or (f3 is not True and f1 is not False):
                votes["M2"] = audit_vote(await ask(client, "M2", prompt, tag))
            f2 = votes["M2"]["faithful"] if votes.get("M2") else None
            # cascade decision (identical rule for the full subset, whose extra votes are for agreement stats)
            if f3 is True:
                final, rule = True, "M3_accept"
            elif f1 is False:
                final, rule = False, "M3+M1_reject" if f3 is False else "M1_reject(M3 missing)"
            elif f2 is not None:
                final, rule = f2, "M2_tiebreak"
            else:
                avail = [f for f in (f1, f2, f3) if f is not None]
                final = Counter(avail).most_common(1)[0][0] if avail else None
                rule = "majority_available"
            fv = [v["faithful"] for v in votes.values() if v and v["faithful"] is not None]
            maj3 = (Counter(fv).most_common(1)[0][0] if len(fv) == 3 else None)
            amb = [v["sentence_ambiguous"] for v in votes.values() if v and v["sentence_ambiguous"] is not None]
            rec = {"sid": s["sid"], "votes": votes, "gold_faithful_final": final, "cascade_rule": rule,
                   "full_panel_subset": is_full, "full_majority": maj3,
                   "sentence_ambiguous": (sum(amb) > len(amb) / 2) if amb else None, "correction": None,
                   "correction_status": None, "primary_error": None}
            if final is False:
                order = [m for m in ("M1", "M2", "M3") if votes.get(m) and votes[m]["faithful"] is False]
                tried = []
                for m in order:
                    ok, why = validate_correction(s["gold_fol_original"], votes[m]["corrected_fol"])
                    tried.append(f"{m}:{why}")
                    if ok:
                        rec["correction"] = to_str(parse(votes[m]["corrected_fol"]).ast)
                        rec["correction_by"] = m
                        break
                rec["correction_status"] = ";".join(tried)
                pe = Counter(votes[m]["primary_error"] for m in order)
                rec["primary_error"] = pe.most_common(1)[0][0] if pe else None
            if s.get("paper_corrected_flag") is not None and s.get("gold_fol_paper"):
                rec["paper_gold"] = s["gold_fol_paper"]
            out[s["sid"]] = rec
        try:
            await asyncio.gather(*[one(s) for s in sents])
        except BudgetExceeded as e:
            logger.error(f"budget stop: {e}")
        logger.info(f"L0 spend ${client.spent_phase:.4f}")
    # audited gold
    for s in sents:
        r = out.get(s["sid"])
        if r is None:
            continue
        if s.get("gold_fol_paper") and s.get("paper_corrected_flag") is not None:
            r["gold_fol_audited"], r["gold_source"] = s["gold_fol_paper"], "paper_corrected"
        elif r["gold_faithful_final"] is True:
            r["gold_fol_audited"], r["gold_source"] = s["gold_fol_original"], "original"
        elif r["gold_faithful_final"] is False and r["correction"]:
            r["gold_fol_audited"], r["gold_source"] = r["correction"], "panel_corrected"
        else:
            r["gold_fol_audited"], r["gold_source"] = None, "panel_flagged_uncorrected"
    (WORK / "l0_results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    by = defaultdict(list)
    for s in sents:
        r = out.get(s["sid"])
        if r and r["gold_faithful_final"] is not None:
            by[s["corpus"]].append(not r["gold_faithful_final"])
    sub = [r for r in out.values() if r["full_panel_subset"] and r["full_majority"] is not None]
    logger.info(f"L0 wrong-gold by corpus: { {k: (round(float(np.mean(v)), 3), len(v)) for k, v in by.items()} }; "
                f"rules {Counter(r['cascade_rule'] for r in out.values())}; sources {Counter(r['gold_source'] for r in out.values())}; "
                f"full-subset cascade==majority {sum(r['gold_faithful_final'] == r['full_majority'] for r in sub)}/{len(sub)}")


# ------------------------------------------------------------------------------------------------- L1
def _l1_worker(batch):
    import resource
    import sys
    resource.setrlimit(resource.RLIMIT_AS, (6 * 1024 ** 3, 6 * 1024 ** 3))
    sys.path.insert(0, str(ROOT / "vendor" / "ds" / "src"))
    from fol_equiv import equivalence
    from fol_parse import parse
    out = []
    for key, cand, gold in batch:
        t0 = time.time()
        pc, pg = parse(cand), parse(gold)
        if not pc.ok:
            out.append({"key": key, "status": "unparseable"})
            continue
        if not pg.ok:
            out.append({"key": key, "status": "no_audited_gold"})
            continue
        try:
            r = equivalence(pc.ast, pg.ast, time_limit=30.0)
            out.append({"key": key, "status": r["status"], "entail_cand_to_gold": r["entail_cand_to_gold"],
                        "entail_gold_to_cand": r["entail_gold_to_cand"], "method": r["method"],
                        "seconds": round(time.time() - t0, 3)})
        except (MemoryError, RecursionError, ValueError, KeyError) as e:
            out.append({"key": key, "status": "unknown_error", "error": repr(e)[:100]})
    return out


def cmd_l1(workers: int) -> None:
    assert_frozen()
    log_reads("l1")
    import multiprocessing as mp
    from concurrent.futures import ProcessPoolExecutor, as_completed
    l0 = json.loads((WORK / "l0_results.json").read_text())
    rows = read_jsonl(FR)
    jobs = []
    res = {}
    for r in rows:
        g = (l0.get(r["sid"]) or {}).get("gold_fol_audited")
        go = (l0.get(r["sid"]) or {}).get("gold_faithful_final")
        if not r["parse_ok_dataset_parser"]:
            res[r["item_id"]] = {"key": r["item_id"], "status": "unparseable"}
        elif g is None:
            res[r["item_id"]] = {"key": r["item_id"], "status": "no_audited_gold"}
        else:
            jobs.append((r["item_id"], r["cand"], g))
    B = 20
    batches = [jobs[i:i + B] for i in range(0, len(jobs), B)]
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn")) as ex:
        futs = [ex.submit(_l1_worker, b) for b in batches]
        for fu in as_completed(futs):
            for x in fu.result():
                res[x["key"]] = x
    write_jsonl(WORK / "l1_fresh.jsonl", list(res.values()))
    logger.info(f"L1 fresh {len(res)} in {time.time() - t0:.0f}s: {Counter(x['status'] for x in res.values())}")


# ------------------------------------------------------------------------------------------------- L3
def l1_group(status: str | None) -> str:
    if status in ("equiv_proved", "equiv_bounded"):
        return "equiv"
    if status == "non_equiv":
        return "bij_nonequiv"
    if status == "non_equiv_no_bijection":
        return "arity_mismatch"
    return "other"


def build_l3_frame():
    rows = [r for r in read_jsonl(FR) if r["fold"] == "fresh_greedy"]
    l0 = json.loads((WORK / "l0_results.json").read_text())
    l1 = {x["key"]: x for x in read_jsonl(WORK / "l1_fresh.jsonl")}
    lcs = {}
    for x in read_jsonl(WORK / "lc_scores_fresh.jsonl"):
        if x["metric"] == "LC_maj":
            lcs[x["item_id"]] = x
    struct = defaultdict(dict)
    # mode / minority by LC_maj class size: an item is 'mode' if its LC_maj share is the sentence maximum
    for r in rows:
        x = lcs.get(f"{r['sid']}:{r['system']}")
        struct[r["sid"]][r["item_id"]] = x["score"] if (x and x["covered"]) else None
    frame = []
    for r in rows:
        g = (l0.get(r["sid"]) or {}).get("gold_fol_audited")
        if g is None:
            continue
        st = l1.get(r["item_id"], {}).get("status")
        if not r["parse_ok_dataset_parser"]:
            stratum = f"unparseable|{r['tercile']}"
            pos = "na"
        else:
            vals = [v for v in struct[r["sid"]].values() if v is not None]
            v = struct[r["sid"]].get(r["item_id"])
            pos = "mode" if (v is not None and vals and v >= max(vals) - 1e-9) else "minority"
            stratum = f"{l1_group(st)}|{pos}|{r['tercile']}"
        frame.append({**r, "gold_audited": g, "L1_status": st, "lc_pos": pos, "stratum": stratum})
    return frame


def build_l3_sample(frame, n_target: int, n_unparse: int, seed: int = 0):
    """Sentence-paired design: sentences drawn stratified by tercile (top x1.5); per sentence one MODE and one
    MINORITY member when both exist (else two random members), with the two T4 systems preferred inside each
    role; plus n_unparse unparseable items. Post-stratified weights are computed afterwards."""
    rng = random.Random(seed)
    by_sid = defaultdict(list)
    for r in frame:
        if not r["stratum"].startswith("unparseable"):
            by_sid[r["sid"]].append(r)
    sids = sorted(by_sid)
    w = {s: (1.5 if by_sid[s][0]["tercile"] == "top" else 1.0) for s in sids}
    order = sorted(sids, key=lambda s: rng.random() ** (1.0 / w[s]), reverse=True)  # weighted sampling w/o replacement
    chosen = []
    n_pairs = (n_target - n_unparse) // 2
    t4_count = Counter()
    for s in order:
        if len(chosen) >= 2 * n_pairs:
            break
        items = by_sid[s]
        mode = [r for r in items if r["lc_pos"] == "mode"]
        mino = [r for r in items if r["lc_pos"] == "minority"]

        def pick(L):
            pref = [r for r in L if r["system"] in SAMPLE_SYSTEMS and t4_count[r["system"]] < 90]
            src = pref if (pref and rng.random() < 0.6) else L
            return src[rng.randrange(len(src))]
        if mode and mino:
            a, b = pick(mode), pick(mino)
            pair_kind = "mode+minority"
        elif len(items) >= 2:
            a, b = rng.sample(items, 2)
            pair_kind = "random2"
        else:
            continue
        for x, role in ((a, "A"), (b, "B")):
            chosen.append({**x, "pair_kind": pair_kind})
            t4_count[x["system"]] += 1
    unp = [r for r in frame if r["stratum"].startswith("unparseable")]
    rng.shuffle(unp)
    chosen += [{**r, "pair_kind": "unparseable"} for r in unp[:n_unparse]]
    # post-stratified weights over the frame
    N = Counter(r["stratum"] for r in frame)
    n = Counter(r["stratum"] for r in chosen)
    for r in chosen:
        r["w_design"] = N[r["stratum"]] / n[r["stratum"]]
        r["gold_is_A"] = rng.random() < 0.5
    return chosen, {"frame_N": dict(N), "sample_n": dict(n), "t4_counts": dict(t4_count)}


async def cmd_l3(n_target: int, n_unparse: int, cap: float, limit: int) -> None:
    assert_frozen()
    log_reads("l3")
    frame = build_l3_frame()
    items, design = build_l3_sample(frame, n_target, n_unparse)
    if limit:
        items = items[:limit]
    rng = random.Random(7)
    full = {x["item_id"] for x in items if rng.random() < 0.10}
    logger.info(f"L3 frame {len(frame)}; sample {len(items)}; full-panel subset {len(full)}; design {design['t4_counts']}")
    out = {}
    async with Client("l3_adjudication", phase_cap=cap, concurrency=24, cache_name="l3_adjudication") as client:
        async def one(x):
            a, b = (x["gold_audited"], x["cand"]) if x["gold_is_A"] else (x["cand"], x["gold_audited"])
            prompt = ADJ_TMPL.format(sentence=x["sentence"], a=a, b=b)
            tag = f"l3|{x['item_id']}|{int(x['gold_is_A'])}"
            r1, r3 = await asyncio.gather(ask(client, "M1", prompt, tag), ask(client, "M3", prompt, tag))
            votes = {"M1": ds_panel_vote(r1, x["gold_is_A"]), "M3": ds_panel_vote(r3, x["gold_is_A"])}
            c1 = votes["M1"]["cand_faithful"] if votes["M1"] else None
            c3 = votes["M3"]["cand_faithful"] if votes["M3"] else None
            if x["item_id"] in full or c1 is None or c3 is None or c1 != c3:
                votes["M2"] = ds_panel_vote(await ask(client, "M2", prompt, tag), x["gold_is_A"])
            cf = [v["cand_faithful"] for v in votes.values() if v and v["cand_faithful"] is not None]
            if c1 is not None and c1 == c3:
                maj = c1  # identical to the 3-member majority whatever M2 says
            else:
                cnt = Counter(cf)
                maj = True if cnt[True] > len(cf) / 2 else (False if cnt[False] > len(cf) / 2 else None)
            agree = [m for m, v in votes.items() if v and v["cand_faithful"] is not None and v["cand_faithful"] == maj]
            if maj is False:
                pes = Counter(votes[m]["primary_error"] for m in agree)
                top = pes.most_common()
                if len(top) > 1 and top[0][1] == top[1][1]:
                    pe = votes["M2"]["primary_error"] if votes.get("M2") and "M2" in agree else votes[agree[0]]["primary_error"]
                else:
                    pe = top[0][0] if top else "other"
            else:
                pe = "none" if maj else None
            out[x["item_id"]] = {**{k: x[k] for k in ("item_id", "sid", "system", "stratum", "lc_pos", "pair_kind",
                                                       "w_design", "gold_is_A", "L1_status", "tercile", "corpus")},
                                 "L3_votes": votes, "L3_majority": maj, "L3_primary_error": pe,
                                 "full_panel_subset": x["item_id"] in full,
                                 "sentence_ambiguous": _amb(votes), "gold_faithful_votes": {m: (v or {}).get("gold_faithful") for m, v in votes.items()}}
        try:
            await asyncio.gather(*[one(x) for x in items])
        except BudgetExceeded as e:
            logger.error(f"budget stop: {e}")
        logger.info(f"L3 spend ${client.spent_phase:.4f}; total ${client.spent_total:.4f}")
    (WORK / "l3_fresh.json").write_text(json.dumps({"design": design, "results": out}, ensure_ascii=False, indent=1))
    logger.info(f"L3 majority {Counter(str(v['L3_majority']) for v in out.values())}; "
                f"types {Counter(v['L3_primary_error'] for v in out.values())}")


def ds_panel_vote(rec: dict, gold_is_a: bool) -> dict | None:
    p = rec.get("parsed")
    if not p:
        return None
    gk, ck = ("A", "B") if gold_is_a else ("B", "A")
    c = p.get(ck) or {}
    g = p.get(gk) or {}
    return {"cand_faithful": yn(c.get("faithful")), "gold_faithful": yn(g.get("faithful")),
            "error_types": norm_errs(c.get("error_types")), "primary_error": (norm_errs(c.get("primary_error")) or ["other"])[0],
            "ambiguous": yn(p.get("sentence_ambiguous")), "same_meaning": yn(p.get("same_meaning")), "model": rec["model"]}


def _amb(votes):
    a = [v["ambiguous"] for v in votes.values() if v and v["ambiguous"] is not None]
    return (sum(a) > len(a) / 2) if a else None


if __name__ == "__main__":
    setup_logging("s06_labels")
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["gate", "l0", "l1", "l3"])
    ap.add_argument("--cap", type=float, default=1.0)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--n", type=int, default=400)
    ap.add_argument("--n_unparse", type=int, default=16)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    if a.cmd == "gate":
        asyncio.run(cmd_gate(a.cap))
    elif a.cmd == "l0":
        asyncio.run(cmd_l0(a.cap))
    elif a.cmd == "l1":
        cmd_l1(a.workers)
    else:
        asyncio.run(cmd_l3(a.n, a.n_unparse, a.cap, a.limit))
