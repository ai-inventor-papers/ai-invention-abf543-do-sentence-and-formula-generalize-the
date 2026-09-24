#!/usr/bin/env python3
"""STEP 1: build the FROZEN SCREEN SET (shared recipe with Arm B).

Logic-LM released FOLIO-dev outputs (gpt-3.5-turbo, gpt-4, text-davinci-003) are matched line-by-line
to FOLIO v0.0 validation gold by normalised NL equality; the sha1-first 300 matched sentences form
the screen. Gold = curated release of arXiv:2606.02837 (HF DSAVlab-UNIUD/FOLIO_validation-curated)
where its NL sentence matches exactly, else the original v0.0 gold. Labels (blind bijection
equivalence, plus a lexical secondary label) are computed under BOTH golds where both exist.
Also builds solver-verified mutants (10 typed operators) and rewrites (2 per gold).

Usage: .venv/bin/python build_screen_set.py [--n_sent 300] [--workers 5]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import random
import re
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
from fol_parse import ParseError, depth, n_binconn, n_quant, parse, preds, to_str  # noqa: E402

RAW = ROOT / "data" / "raw"
SYSTEMS = ["gpt-3.5-turbo", "gpt-4", "text-davinci-003"]

logger.remove()
logger.add(sys.stdout, level="INFO", format="{time:HH:mm:ss}|{level:<7}|{message}")
(ROOT / "logs").mkdir(exist_ok=True)
logger.add(ROOT / "logs" / "build_screen_set.log", rotation="30 MB", level="DEBUG")


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip().rstrip(".")


def sha1(s: str) -> str:
    return hashlib.sha1(norm(s).encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ Logic-LM parsing
def parse_logic_program(raw: str) -> dict:
    blocks = {"Predicates": [], "Premises": [], "Conclusion": []}
    cur = None
    for line in raw.split("\n"):
        s = line.strip()
        if not s:
            continue
        m = re.match(r"^(Predicates|Premises|Conclusion)\s*:\s*(.*)$", s)
        if m:
            cur = m.group(1)
            rest = m.group(2).strip()
            if rest:
                blocks[cur].append(rest)
            continue
        if cur:
            blocks[cur].append(s)
    decl = []
    for s in blocks["Predicates"]:
        sig = s.split(":::", 1)[0].strip()
        gloss = s.split(":::", 1)[1].strip() if ":::" in s else ""
        m = re.match(r"^(\w+)\s*\(([^)]*)\)", sig, re.U)
        if m:
            args = [a for a in m.group(2).split(",") if a.strip()]
            decl.append({"name": m.group(1), "arity": len(args), "gloss": gloss})
        elif re.fullmatch(r"\w+", sig, re.U):
            decl.append({"name": sig, "arity": 0, "gloss": gloss})
    lines = []
    for kind in ("Premises", "Conclusion"):
        for s in blocks[kind]:
            if ":::" not in s:
                continue
            fol, nl = s.split(":::", 1)
            lines.append({"kind": kind, "fol": fol.strip(), "nl": nl.strip()})
    return {"declared": decl, "lines": lines}


def as_list(x) -> list[str]:
    if isinstance(x, list):
        return [str(a) for a in x]
    return [a for a in str(x).split("\n") if a.strip()]


# ------------------------------------------------------------------ corrected gold
def split_top_and(s: str) -> list[str]:
    """Split a story-level FOL string at top-level ' ∧ ' (paren depth 0)."""
    parts, depth_, cur = [], 0, []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "(":
            depth_ += 1
        elif ch == ")":
            depth_ -= 1
        if ch == "∧" and depth_ == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
        i += 1
    parts.append("".join(cur).strip())
    return [p for p in parts if p]


def load_corrected() -> tuple[dict, dict]:
    """Returns (map norm(NL) -> {fol_new, fol_old, corrected, ambiguity, id}, stats)."""
    path = RAW / "dsav_FOLIO_instances.jsonl"
    stats = Counter()
    cmap = {}
    if not path.exists():
        logger.warning("corrected release not found")
        return cmap, dict(stats)
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    for r in rows:
        corr = str(r.get("corrected", "")).lower() in ("yes", "true", "1")
        amb = bool(r.get("ambiguity"))
        if r["id"].startswith("concl"):
            cmap[norm(r["NL_sentence"])] = {"fol_new": r["FOL_sentence"], "fol_old": r["FOL_sentence_old"],
                                           "corrected": corr, "ambiguity": amb, "id": r["id"]}
            stats["concl"] += 1
            continue
        sents = [s for s in re.split(r"(?<=[.!?])\s+", r["NL_sentence"].strip()) if s.strip()]
        new_parts = split_top_and(r["FOL_sentence"])
        old_parts = split_top_and(r["FOL_sentence_old"])
        if len(new_parts) == len(sents):
            for i, s in enumerate(sents):
                old = old_parts[i] if len(old_parts) == len(sents) else None
                cmap.setdefault(norm(s), {"fol_new": new_parts[i], "fol_old": old,
                                          "corrected": corr and (old is None or norm(old) != norm(new_parts[i])),
                                          "ambiguity": amb, "id": f"{r['id']}#{i}"})
            stats["story_split_ok"] += 1
        else:
            stats["story_split_fail"] += 1
            logger.debug(f"story split fail {r['id']}: {len(sents)} sents vs {len(new_parts)} conjuncts")
    return cmap, dict(stats)


# ------------------------------------------------------------------ workers (spawn-safe)
def _label_worker(args):
    sys.path.insert(0, str(ROOT / "src"))
    from fol_parse import parse as p_
    from labeler import label
    item_id, cand, gold_new, gold_orig, seed = args
    out = {"item_id": item_id}
    try:
        ca = p_(cand).ast
    except Exception as e:  # noqa: BLE001
        return {**out, "error": f"cand_parse:{e}"}
    for tag, g in (("corr", gold_new), ("orig", gold_orig)):
        if g is None:
            continue
        try:
            ga = p_(g).ast
            out[tag] = label(ca, ga, seed=seed)
        except Exception as e:  # noqa: BLE001
            out[tag] = {"status": "unlabeled", "reason": f"error:{type(e).__name__}:{e}"}
    return out


def _mutant_worker(args):
    sys.path.insert(0, str(ROOT / "src"))
    from fol_parse import parse as p_
    from fol_parse import to_str as ts
    from labeler import identity_equiv, label
    from mutate import OPERATORS, REWRITES, mutate, rewrite
    sid, gold, pool, seed = args
    ga = p_(gold).ast
    rng = random.Random(seed)
    muts, rews, log = [], [], []
    for op in OPERATORS:
        r2 = random.Random(f"{seed}:{op}")
        try:
            m = mutate(ga, op, r2, pool)
        except Exception as e:  # noqa: BLE001
            log.append((op, "error", str(e)))
            continue
        if m is None or m == ga:
            log.append((op, "NA", ""))
            continue
        ms = ts(m)
        try:
            mast = p_(ms).ast
            eq = identity_equiv(mast, ga)
        except Exception as e:  # noqa: BLE001
            log.append((op, "error", str(e)))
            continue
        if eq != "nonequiv":
            log.append((op, "equiv_dropped" if eq == "equiv" else "unknown_dropped", ms))
            continue
        muts.append({"mid": f"{sid}:M:{op}", "sid": sid, "operator": op, "fol": ms})
        log.append((op, "kept", ""))
    order = list(REWRITES)
    rng.shuffle(order)
    for kind in order:
        if len(rews) >= 2:
            break
        r2 = random.Random(f"{seed}:{kind}")
        try:
            r, rmap = rewrite(ga, kind, r2)
        except Exception as e:  # noqa: BLE001
            log.append((kind, "error", str(e)))
            continue
        if r is None or (r == ga and not rmap):
            log.append((kind, "NA", ""))
            continue
        rs = ts(r)
        try:
            rast = p_(rs).ast
            if rmap:
                inv = {v: k for k, v in rmap.items()}
                from fol_parse import rename as rn
                eq = identity_equiv(rn(rast, inv), ga)
            else:
                eq = identity_equiv(rast, ga)
        except Exception as e:  # noqa: BLE001
            log.append((kind, "error", str(e)))
            continue
        if eq != "equiv":
            log.append((kind, "nonequiv_dropped", rs))
            continue
        rews.append({"rid": f"{sid}:R:{kind}", "sid": sid, "kind": kind, "fol": rs, "rename_map": rmap})
        log.append((kind, "kept", ""))
    return sid, muts, rews, log


def _sat_worker(args):
    sys.path.insert(0, str(ROOT / "src"))
    from fol_parse import parse as p_
    from labeler import satisfiable
    key, fols = args
    try:
        asts = [p_(f).ast for f in fols]
    except Exception as e:  # noqa: BLE001
        return key, "parse_error", str(e)
    conj = ("and", tuple(asts)) if len(asts) > 1 else asts[0]
    try:
        return key, satisfiable(conj, N=3), ""
    except Exception as e:  # noqa: BLE001
        return key, "error", str(e)


def run_pool(fn, jobs, workers, desc, timeout_each=None):
    res = []
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn")) as ex:
        futs = {ex.submit(fn, j): j for j in jobs}
        for i, fu in enumerate(as_completed(futs)):
            try:
                res.append(fu.result())
            except Exception as e:  # noqa: BLE001
                logger.error(f"{desc} job failed: {e}")
            if (i + 1) % 100 == 0:
                logger.info(f"{desc}: {i + 1}/{len(jobs)} ({time.time() - t0:.0f}s)")
    logger.info(f"{desc}: done {len(res)}/{len(jobs)} in {time.time() - t0:.0f}s")
    return res


# ------------------------------------------------------------------ main
@logger.catch(reraise=True)
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n_sent", type=int, default=300)
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--out", default=str(ROOT / "data" / "screen_set.json"))
    a = ap.parse_args()
    counts: dict = {}

    # 1.1 gold v0.0
    V = [json.loads(l) for l in (RAW / "folio-validation.jsonl").read_text().splitlines() if l.strip()]
    gold_by_story: dict[int, dict] = {}
    gold_first: dict[str, tuple] = {}
    for k, v in enumerate(V):
        P, F = as_list(v["premises"]), as_list(v["premises-FOL"])
        if len(P) != len(F):
            logger.warning(f"story {k}: {len(P)} premises vs {len(F)} FOL; zipping shortest")
        pairs = list(zip(P, F)) + [(v["conclusion"], v["conclusion-FOL"])]
        gold_by_story[k] = {norm(nl): fol for nl, fol in pairs}
        for nl, fol in pairs:
            gold_first.setdefault(norm(nl), (k, nl, fol))
    counts["gold_v0_unique_sentences"] = len(gold_first)
    corrected, cstats = load_corrected()
    counts["corrected_release"] = {"source": "HF DSAVlab-UNIUD/FOLIO_validation-curated (arXiv:2606.02837)",
                                   "n_sentence_entries": len(corrected), **cstats}
    logger.info(f"gold v0 sentences={len(gold_first)} corrected entries={len(corrected)} {cstats}")

    # 1.2 Logic-LM
    sys_lines: dict[str, dict[str, list]] = {}
    story_programs: dict[tuple, dict] = {}
    for s in SYSTEMS:
        data = json.loads((RAW / f"FOLIO_dev_{s}.json").read_text())
        per = defaultdict(list)
        n_lines = n_matched = 0
        for e in data:
            k = int(e["id"].split("_")[-1])
            prog = parse_logic_program(e["raw_logic_programs"][0] if e.get("raw_logic_programs") else "")
            story_programs[(s, k)] = prog
            for ln in prog["lines"]:
                n_lines += 1
                key = norm(ln["nl"])
                if key in gold_first:
                    n_matched += 1
                    per[key].append((k, ln["fol"], ln["kind"]))
        sys_lines[s] = per
        counts[f"logiclm_{s}"] = {"n_lines": n_lines, "n_matched": n_matched, "n_unmatched": n_lines - n_matched,
                                  "n_unique_matched_sentences": len(per)}
        logger.info(f"{s}: lines={n_lines} matched={n_matched} unique={len(per)}")

    # fuzzy-match diagnostic only
    try:
        from rapidfuzz import fuzz, process
        gkeys = list(gold_first)
        fuzzy = 0
        for s in SYSTEMS:
            data = json.loads((RAW / f"FOLIO_dev_{s}.json").read_text())
            for e in data:
                for ln in parse_logic_program(e["raw_logic_programs"][0])["lines"]:
                    key = norm(ln["nl"])
                    if key not in gold_first:
                        m = process.extractOne(key, gkeys, scorer=fuzz.ratio)
                        if m and m[1] >= 95:
                            fuzzy += 1
        counts["diag_fuzzy95_unmatched_lines"] = fuzzy
    except ImportError:
        pass

    # 1.5 gold per sentence + exclusion
    matched = sorted(set().union(*[set(v) for v in sys_lines.values()]))
    counts["n_unique_matched_sentences"] = len(matched)
    sentences = []
    excl = Counter()
    excl_examples = defaultdict(list)
    for key in matched:
        story_ids = sorted({k for s in SYSTEMS for (k, _, _) in sys_lines[s].get(key, [])})
        story_id = story_ids[0]
        gold_orig = gold_by_story.get(story_id, {}).get(key) or gold_first[key][2]
        nl = gold_first[key][1]
        c = corrected.get(key)
        gold_new = c["fol_new"] if c else None
        gold = gold_new if gold_new else gold_orig
        gsrc = "corrected" if gold_new else "original"
        sentences.append({"key": key, "nl": nl, "story_id": story_id, "gold_fol": gold, "gold_source": gsrc,
                          "gold_fol_orig": gold_orig, "gold_fol_corr": gold_new,
                          "corr_flag": (c or {}).get("corrected"), "ambiguity": (c or {}).get("ambiguity"),
                          "corr_id": (c or {}).get("id"), "sha1": sha1(nl)})
    # parse + sat check golds (parallel)
    jobs = [(i, [s["gold_fol"]]) for i, s in enumerate(sentences)]
    sat_res = {k: (st, msg) for k, st, msg in run_pool(_sat_worker, jobs, a.workers, "gold-sat")}
    kept = []
    for i, s in enumerate(sentences):
        st, msg = sat_res.get(i, ("error", "missing"))
        if st == "parse_error":
            excl["gold_unparseable"] += 1
            excl_examples["gold_unparseable"].append((s["nl"][:80], s["gold_fol"][:120], msg[:80]))
            continue
        if st != "sat":
            excl[f"gold_{st}"] += 1
            excl_examples[f"gold_{st}"].append((s["nl"][:80], s["gold_fol"][:120]))
            continue
        kept.append(s)
    counts["gold_exclusions"] = dict(excl)
    counts["gold_exclusion_examples"] = {k: v[:5] for k, v in excl_examples.items()}
    logger.info(f"gold kept {len(kept)}/{len(sentences)} exclusions={dict(excl)}")

    # 1.6 sha1-first N
    kept.sort(key=lambda s: s["sha1"])
    screen = kept[: a.n_sent]
    counts["n_screen_sentences"] = len(screen)
    if len(screen) < a.n_sent:
        logger.warning(f"only {len(screen)} sentences available (< {a.n_sent})")
    real = []
    dup_diag = Counter()
    for s in screen:
        sid = s["sha1"][:10]
        s["sid"] = sid
        for sysn in SYSTEMS:
            occ = sorted(sys_lines[sysn].get(s["key"], []), key=lambda t: t[0])
            if not occ:
                continue
            k, fol, kind = occ[0]
            dup_diag[len(occ)] += 1
            prog = story_programs[(sysn, k)]
            try:
                pa = parse(fol)
                parse_ok, free, err = True, pa.free_vars, ""
            except (ParseError, RecursionError) as e:
                parse_ok, free, err = False, False, str(e)[:100]
            real.append({"item_id": f"{sid}:{sysn}", "sid": sid, "system": sysn, "cand_fol": fol,
                         "cand_story": k, "line_kind": kind, "parse_ok": parse_ok, "free_vars": free,
                         "parse_error": err, "declared_preds": prog["declared"],
                         "alt_cands": [o[1] for o in occ[1:]]})
    counts["n_real"] = len(real)
    counts["real_per_system"] = dict(Counter(r["system"] for r in real))
    counts["duplicate_occurrence_hist"] = {str(k): v for k, v in sorted(dup_diag.items())}
    counts["n_real_parse_ok"] = sum(r["parse_ok"] for r in real)
    logger.info(f"real candidates={len(real)} parse_ok={counts['n_real_parse_ok']}")

    # 1.8 labels (both golds)
    gmap = {s["sid"]: s for s in screen}
    jobs = []
    for r in real:
        if not r["parse_ok"]:
            continue
        s = gmap[r["sid"]]
        seed = int(s["sha1"][:8], 16)
        jobs.append((r["item_id"], r["cand_fol"], s["gold_fol_corr"], s["gold_fol_orig"], seed))
    lab = {x["item_id"]: x for x in run_pool(_label_worker, jobs, a.workers, "label")}
    for r in real:
        s = gmap[r["sid"]]
        L = lab.get(r["item_id"], {})
        for tag in ("corr", "orig"):
            if not r["parse_ok"]:
                r[f"label_{tag}"] = {"status": "nonequiv", "status_lex": "nonequiv", "reason": "unparseable"} \
                    if (tag == "orig" or s["gold_fol_corr"]) else None
            else:
                r[f"label_{tag}"] = L.get(tag) if (tag == "orig" or s["gold_fol_corr"]) else None
                if r[f"label_{tag}"] is None and (tag == "orig" or s["gold_fol_corr"]):
                    r[f"label_{tag}"] = {"status": "unlabeled", "reason": L.get("error", "missing")}
        lc = r["label_corr"] if r["label_corr"] is not None else r["label_orig"]
        r["status"] = lc["status"]
        r["status_lex"] = lc.get("status_lex") or lc["status"]
        r["correct"] = None if lc["status"] == "unlabeled" else int(lc["status"] == "equiv")
        r["correct_lex"] = None if r["status_lex"] == "unlabeled" else int(r["status_lex"] == "equiv")
        lo = r["label_orig"]
        r["correct_orig"] = None if lo["status"] == "unlabeled" else int(lo["status"] == "equiv")
        r["correct_orig_lex"] = None if (lo.get("status_lex") or lo["status"]) == "unlabeled" else \
            int((lo.get("status_lex") or lo["status"]) == "equiv")
        r["gold_source"] = s["gold_source"]
    counts["label_status"] = dict(Counter(r["status"] for r in real))
    counts["label_status_by_system"] = {sy: dict(Counter(r["status"] for r in real if r["system"] == sy))
                                        for sy in SYSTEMS}
    counts["label_orig_status_by_system"] = {sy: dict(Counter(r["label_orig"]["status"] for r in real
                                                               if r["system"] == sy)) for sy in SYSTEMS}
    logger.info(f"labels: {counts['label_status']} by system {counts['label_status_by_system']}")

    # 1.9 mutants + rewrites from the (primary) gold
    story_pool: dict[int, set] = defaultdict(set)
    for k, gs in gold_by_story.items():
        for fol in gs.values():
            try:
                story_pool[k] |= {p for p, ar in parse(fol).preds.items() if ar == 1}
            except (ParseError, RecursionError):
                pass
    jobs = []
    for s in screen:
        seed = int(s["sha1"][:8], 16)
        gpreds = set(parse(s["gold_fol"]).preds)
        pool = sorted(story_pool[s["story_id"]] - gpreds)
        jobs.append((s["sid"], s["gold_fol"], pool, seed))
    mres = run_pool(_mutant_worker, jobs, a.workers, "mutants")
    mutants, rewrites = [], []
    mlog = defaultdict(Counter)
    for sid, ms, rs, lg in mres:
        mutants += ms
        rewrites += rs
        for op, st, _ in lg:
            mlog[op][st] += 1
    mutants.sort(key=lambda m: m["mid"])
    rewrites.sort(key=lambda r: r["rid"])
    counts["mutant_log"] = {k: dict(v) for k, v in mlog.items()}
    counts["n_mutants"] = len(mutants)
    counts["n_rewrites"] = len(rewrites)
    counts["mutants_per_operator"] = dict(Counter(m["operator"] for m in mutants))
    counts["rewrites_per_kind"] = dict(Counter(r["kind"] for r in rewrites))
    logger.info(f"mutants={len(mutants)} {counts['mutants_per_operator']} rewrites={len(rewrites)} "
                f"{counts['rewrites_per_kind']}")

    # 1.10 complexity features
    try:
        import spacy
        nlp = spacy.load("en_core_web_sm", disable=["ner"])
        ntok = lambda t: len([x for x in nlp(t) if not x.is_punct])  # noqa: E731
        tok_src = "spacy"
    except (ImportError, OSError):
        ntok = lambda t: len(re.findall(r"\w+", t))  # noqa: E731
        tok_src = "regex"
    counts["n_tokens_source"] = tok_src
    MARK = {"if", "unless", "except", "only", "either", "neither", "not", "no", "none", "without", "whether"}
    import numpy as np
    feats = []
    for s in screen:
        g = parse(s["gold_fol"]).ast
        words = re.findall(r"[a-z']+", s["nl"].lower())
        nmark = sum(1 for w in words if w in MARK or w.endswith("n't"))
        f = {"n_tokens": ntok(s["nl"]), "n_quant": n_quant(g), "depth": depth(g),
             "n_cond": nmark + n_binconn(g), "n_text_markers": nmark, "n_gold_binconn": n_binconn(g)}
        s["features"] = f
        feats.append([f["n_tokens"], f["n_quant"], f["depth"], f["n_cond"]])
    X = np.array(feats, dtype=float)
    Z = (X - X.mean(0)) / np.where(X.std(0) > 0, X.std(0), 1)
    comp = Z.mean(1)
    q1, q2 = np.percentile(comp, [100 / 3, 200 / 3])
    for s, c in zip(screen, comp):
        s["features"]["composite"] = float(c)
        s["tercile"] = "low" if c <= q1 else ("mid" if c <= q2 else "top")
    counts["tercile_sizes"] = dict(Counter(s["tercile"] for s in screen))
    counts["gold_source"] = dict(Counter(s["gold_source"] for s in screen))
    counts["gold_corr_flag_true"] = sum(1 for s in screen if s.get("corr_flag"))

    out = {"recipe": "Logic-LM FOLIO-dev {gpt-3.5-turbo,gpt-4,text-davinci-003} x FOLIO v0.0 validation; "
                     "norm(s)=re.sub(r'\\s+',' ',s.lower()).strip().rstrip('.'); sha1(norm(nl)) sort; first 300",
           "sentences": [{k: v for k, v in s.items() if k != "key"} for s in screen],
           "real": real, "mutants": mutants, "rewrites": rewrites, "counts": counts}
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1))
    (ROOT / "data" / "screen_set_ids.txt").write_text("\n".join(sorted(r["item_id"] for r in real)) + "\n")
    logger.info(f"wrote {a.out}; counts={json.dumps({k: v for k, v in counts.items() if 'example' not in k})[:2000]}")


if __name__ == "__main__":
    main()
