#!/usr/bin/env python3
"""STEP 1-3: load the 5 source datasets, filter golds, assert disjointness, compute complexity
features, draw the stratified held-out sample, reproduce the screen set (L4) and build the
40-item known-label calibration set.

Outputs (work/): pool.json, heldout_sentences.json, screen_sentences.json, calibration_set.json,
prep_report.json.
"""
from __future__ import annotations

import ast as pyast
import csv
import hashlib
import json
import math
import multiprocessing as mp
import random
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from _jl import read_jsonl  # noqa: E402
from fol_parse import complexity_ast, has_quantifier, n_all_connectives, parse, to_str, signature  # noqa: E402

RAW = ROOT / "raw"
HF = RAW / "hf_downloads"
WORK = ROOT / "work"
WORK.mkdir(exist_ok=True)
(ROOT / "logs").mkdir(exist_ok=True)
logger.remove()
logger.add(sys.stdout, level="INFO", format="{time:HH:mm:ss}|{level:<7}|{message}")
logger.add(ROOT / "logs" / "prep_sources.log", rotation="30 MB", level="DEBUG")

COND_WORDS = re.compile(r"\b(if|unless|except|only|either|neither|not)\b")


def norm(s: str) -> str:
    s = re.sub(r"\s+", " ", s.strip().lower())
    return s[:-1].strip() if s.endswith(".") else s


def sha(s: str) -> str:
    return hashlib.sha1(norm(s).encode("utf-8")).hexdigest()


def n_conditions_text(sentence: str) -> int:
    low = sentence.lower().replace("n't", " not")
    return len(COND_WORDS.findall(low))


def gold_check(fol: str) -> dict:
    """Parse + bounded sat/validity check of one gold formula (worker)."""
    sys.path.insert(0, str(ROOT / "src"))
    from fol_equiv import sat_valid_check
    r = parse(fol)
    if not r.ok:
        return {"parse_ok": False, "error": r.error}
    try:
        sv = sat_valid_check(r.ast)
    except Exception as e:  # noqa: BLE001 - solver failures are recorded, not fatal
        return {"parse_ok": True, "sv_error": str(e)[:200]}
    c = complexity_ast(r.ast)
    return {"parse_ok": True, **sv, **c, "n_all_conn": n_all_connectives(r.ast),
            "has_quant": has_quantifier(r.ast), "notes": r.notes}


def run_checks(fols: list[str]) -> dict[str, dict]:
    uniq = sorted(set(fols))
    out = {}
    with ProcessPoolExecutor(max_workers=4, mp_context=mp.get_context("spawn")) as pool:
        for f, r in zip(uniq, pool.map(gold_check, uniq, chunksize=64)):
            out[f] = r
    return out


# --------------------------------------------------------------------------- loaders
def load_malls() -> list[dict]:
    test = json.loads((HF / "yuan-yang__MALLS-v0" / "MALLS-v0.1-test.json").read_text())
    cur = read_jsonl(HF / "DSAVlab-UNIUD__MALLS_test_subset-CURATED" / "MALLS_instances.jsonl")
    cur_by_idx = {}
    for c in cur:
        idx = c["id"] - 1
        assert test[idx]["NL"].strip() == c["NL_sentence"].strip(), idx
        cur_by_idx[idx] = c
    rows = []
    for i, x in enumerate(test):
        r = {"corpus": "malls", "corpus_subset": "malls_v0.1_test", "source_id": f"malls_test_{i}",
             "story_id": None, "sentence": x["NL"].strip(), "gold_fol_original": x["FOL"].strip(),
             "licence": "CC BY-NC 4.0"}
        if i in cur_by_idx:
            c = cur_by_idx[i]
            r["gold_fol_paper"] = c["FOL_sentence_new"].strip()
            r["paper_corrected_flag"] = c["corrected"] == "yes"
            r["paper_correction_explanation"] = c.get("correction_explanation", "")
        rows.append(r)
    return rows


def split_story(prem_nl: str, prem_fol: str):
    nl = [l.strip() for l in prem_nl.split("\n") if l.strip()]
    fol = [l.strip() for l in prem_fol.split("\n") if l.strip()]
    return nl, fol


def load_folio_train(report: dict) -> list[dict]:
    tr = read_jsonl(HF / "tasksource__folio" / "folio_v2_train.jsonl")
    ref = list(csv.DictReader(open(HF / "yfxiao__folio-refined" / "train.csv", encoding="utf-8")))
    ref_by_key = {}
    for rr in ref:
        ref_by_key.setdefault((norm(rr["nl premises"]), norm(rr["nl conclusion"])), rr)
    rows, dropped_mismatch, ref_aligned, ref_misaligned = [], 0, 0, 0
    for k, s in enumerate(tr):
        nl, fol = split_story(s["premises"], s["premises-FOL"])
        if len(nl) != len(fol):
            dropped_mismatch += 1
            continue
        rr = ref_by_key.get((norm(s["premises"]), norm(s["conclusion"])), {"nl premises": "", "fol premises": "",
                                                                             "nl conclusion": "", "fol conclusion": ""})
        rnl, rfol = split_story(rr["nl premises"], rr["fol premises"])
        ref_ok = [norm(x) for x in rnl] == [norm(x) for x in nl] and len(rfol) == len(rnl)
        items = list(zip(nl, fol, rfol if ref_ok else [None] * len(nl), [f"p{j}" for j in range(len(nl))]))
        rc_ok = norm(rr["nl conclusion"]) == norm(s["conclusion"])
        items.append((s["conclusion"].strip(), s["conclusion-FOL"].strip(),
                      rr["fol conclusion"].strip() if rc_ok else None, "c"))
        if ref_ok:
            ref_aligned += 1
        else:
            ref_misaligned += 1
        for sent, f, rf, pos in items:
            rows.append({"corpus": "folio", "corpus_subset": "folio_v2_train", "story_id": str(s["story_id"]),
                         "source_id": f"folio_train_story{s['story_id']}_ex{s['example_id']}_{pos}",
                         "sentence": sent, "gold_fol_original": f, "gold_fol_refined": rf, "licence": "MIT"})
    report["folio_train_stories_dropped_count_mismatch"] = dropped_mismatch
    report["folio_refined_story_alignment"] = {"aligned": ref_aligned, "misaligned": ref_misaligned}
    return rows


def folio_validation_sentences() -> tuple[set, set]:
    """Normalized sentences of FOLIO v1 (GitHub v0.0) + v2 validation, and their story ids (v2)."""
    out = set()
    for s in read_jsonl(RAW / "github" / "folio-validation_v0.0.jsonl"):
        p = s["premises"]
        p = pyast.literal_eval(p) if isinstance(p, str) and p.startswith("[") else p
        p = p if isinstance(p, list) else p.split("\n")
        out |= {norm(x) for x in p if x.strip()} | {norm(s["conclusion"])}
    v2ids = set()
    for s in read_jsonl(HF / "tasksource__folio" / "folio_v2_validation.jsonl"):
        out |= {norm(x) for x in s["premises"].split("\n") if x.strip()} | {norm(s["conclusion"])}
        v2ids.add(str(s["story_id"]))
    return out, v2ids


def load_proverqa(level: str) -> list[dict]:
    data = json.loads((HF / "opendatalab__ProverQA" / "dev" / f"{level}.json").read_text())
    rows = []
    for it in data:
        d = it["nl2fol"]
        d = pyast.literal_eval(d) if isinstance(d, str) else d
        for j, (sent, fol) in enumerate(d.items()):
            rows.append({"corpus": "proverqa", "corpus_subset": f"proverqa_{level}", "story_id": f"{level}_{it['id']}",
                         "source_id": f"proverqa_dev_{level}_{it['id']}_{j}", "sentence": sent.strip(),
                         "gold_fol_original": fol.strip(), "licence": "see opendatalab/ProverQA card (ProverGen, ICLR 2025)"})
    return rows


def detemplate(sent: str, fol: str) -> str:
    r = parse(fol)
    t = sent
    if r.ok:
        _, consts = signature(r.ast)
        for c in sorted(consts, key=len, reverse=True):
            t = re.sub(rf"\b{re.escape(c)}\b", "<NAME>", t)
    t = re.sub(r"\b(he|she|his|her|him)\b", "<PRON>", t, flags=re.I)
    return norm(t)


# --------------------------------------------------------------------------- screen (L4)
def logiclm_lines(raw: str):
    out = []
    section = None
    for line in raw.split("\n"):
        st = line.strip()
        if st.rstrip(":") in ("Predicates", "Premises", "Conclusion"):
            section = st.rstrip(":")
            continue
        if ":::" in st and section in ("Premises", "Conclusion"):
            fol, nl = st.split(":::", 1)
            out.append((section, fol.strip(), nl.strip()))
    return out


def build_screen(report: dict, checks_fn) -> list[dict]:
    val = read_jsonl(RAW / "github" / "folio-validation_v0.0.jsonl")
    gold_by_norm = {}
    for si, s in enumerate(val):
        p = s["premises"]
        p = pyast.literal_eval(p) if isinstance(p, str) and p.startswith("[") else p
        pf = s["premises-FOL"]
        pf = pyast.literal_eval(pf) if isinstance(pf, str) and pf.startswith("[") else pf
        pairs = list(zip(p, pf)) + [(s["conclusion"], s["conclusion-FOL"])]
        for nl, f in pairs:
            gold_by_norm.setdefault(norm(nl), {"sentence": nl.strip(), "gold_fol_original": f.strip(), "story_idx": si})
    systems = {"gpt-3.5-turbo": "logiclm_gpt-3.5-turbo", "gpt-4": "logiclm_gpt-4", "text-davinci-003": "logiclm_text-davinci-003"}
    cands = defaultdict(dict)
    unmatched = Counter()
    for fn, sysname in systems.items():
        for ex in json.loads((RAW / "github" / f"FOLIO_dev_{fn}.json").read_text()):
            progs = ex.get("raw_logic_programs") or []
            if not progs:
                continue
            for sec, fol, nl in logiclm_lines(progs[0]):
                k = norm(nl)
                if k not in gold_by_norm:
                    unmatched[sysname] += 1
                    continue
                cands[k].setdefault(sysname, {"raw_output": f"{fol} ::: {nl}", "candidate_fol": fol, "logiclm_id": ex["id"]})
    report["screen_unmatched_lines"] = dict(unmatched)
    keys = sorted(cands, key=lambda k: hashlib.sha1(k.encode()).hexdigest())
    golds = [gold_by_norm[k]["gold_fol_original"] for k in keys]
    chk = checks_fn(golds)
    excl = Counter()
    rows = []
    for k in keys:
        g = gold_by_norm[k]
        c = chk[g["gold_fol_original"]]
        if not c.get("parse_ok"):
            excl["gold_unparseable"] += 1
            continue
        if c.get("unsat_bounded"):
            excl["gold_unsat"] += 1
            continue
        rows.append({"sentence_id": hashlib.sha1(k.encode()).hexdigest()[:10], "norm_sentence": k,
                     "sentence": g["sentence"], "gold_fol_original": g["gold_fol_original"],
                     "corpus": "folio", "corpus_subset": "folio_v1_validation_screen",
                     "source_id": f"folio_v1_val_story{g['story_idx']}", "candidates": cands[k],
                     "gold_check": c, "licence": "MIT"})
    report["screen_matched_unique_sentences"] = len(keys)
    report["screen_gold_exclusions"] = dict(excl)
    report["screen_eligible_sorted"] = len(rows)
    sel = rows[:360]
    for i, r in enumerate(sel):
        r["screen_rank"] = i
        r["in_screen_first300"] = i < 300
    # attach paper-corrected (2606.02837) conclusions + folio-refined validation, by normalized NL
    cur = read_jsonl(HF / "DSAVlab-UNIUD__FOLIO_validation-curated" / "FOLIO_instances.jsonl")
    cur_by = {norm(c["NL_sentence"]): c for c in cur if c["id"].startswith("concl")}
    ref = list(csv.DictReader(open(HF / "yfxiao__folio-refined" / "validation.csv", encoding="utf-8")))
    ref_by = {}
    for rr in ref:
        rnl, rfol = split_story(rr["nl premises"], rr["fol premises"])
        if len(rnl) == len(rfol):
            for a, b in zip(rnl, rfol):
                ref_by.setdefault(norm(a), b)
        ref_by.setdefault(norm(rr["nl conclusion"]), rr["fol conclusion"].strip())
    v2 = read_jsonl(HF / "tasksource__folio" / "folio_v2_validation.jsonl")
    v2_by = {}
    for s in v2:
        nl, fol = split_story(s["premises"], s["premises-FOL"])
        if len(nl) == len(fol):
            for a, b in zip(nl, fol):
                v2_by.setdefault(norm(a), b)
        v2_by.setdefault(norm(s["conclusion"]), s["conclusion-FOL"].strip())
    n_cur = 0
    for r in sel:
        c = cur_by.get(r["norm_sentence"])
        r["gold_fol_v2"] = v2_by.get(r["norm_sentence"])
        r["gold_fol_refined"] = ref_by.get(r["norm_sentence"])
        if c:
            n_cur += 1
            r["gold_fol_paper"] = c["FOL_sentence"]
            r["gold_fol_paper_old_v2"] = c["FOL_sentence_old"]
            r["paper_corrected_flag"] = c["corrected"] == "yes"
            r["paper_ambiguous"] = bool(c.get("ambiguity"))
    report["screen_with_paper_corrected_conclusion"] = n_cur
    return sel


# --------------------------------------------------------------------------- calibration set
def build_calibration(eligible_easy: list[dict], seed: int = 0) -> list[dict]:
    from fol_equiv import equivalence
    rng = random.Random(seed)
    pool = [r for r in eligible_easy]
    rng.shuffle(pool)

    def ok_equiv(a, b):
        return equivalence(a, b, time_limit=10, want_entailment=False)["status"] in ("equiv_proved", "equiv_bounded")

    def strict_non_equiv(a, b):
        # non-equivalent under the identity (same-name) reading: a bounded countermodel must exist
        from fol_equiv import bounded_check
        _, ca = signature(a)
        _, cb = signature(b)
        r, _ = bounded_check(a, b, sorted(ca | cb), {}, "equiv")
        return r == "countermodel"

    def mutate(node, kind):
        """Return a list of single-site mutants of the requested kind."""
        outs = []

        def rec(n, path_fn):
            op = n[0]
            if kind == "negation_flip" and op == "atom":
                outs.append(path_fn(("not", n)))
            if kind == "negation_flip" and op == "not":
                outs.append(path_fn(n[1]))
            if kind == "quantifier_swap" and op in ("forall", "exists"):
                outs.append(path_fn(("exists" if op == "forall" else "forall", n[1], n[2])))
            if kind == "implication_reversal" and op == "imp":
                outs.append(path_fn(("imp", n[2], n[1])))
            if kind == "drop_conjunct" and op == "and":
                outs.append(path_fn(n[1]))
                outs.append(path_fn(n[2]))
            if kind == "argument_swap" and op == "atom" and len(n[2]) >= 2 and n[2][0] != n[2][1]:
                outs.append(path_fn(("atom", n[1], (n[2][1], n[2][0]) + n[2][2:])))
            if kind == "connective_and_or" and op in ("and", "or"):
                outs.append(path_fn(("or" if op == "and" else "and", n[1], n[2])))
            if op in ("forall", "exists"):
                rec(n[2], lambda x, op=op, n=n: path_fn((op, n[1], x)))
            elif op == "not":
                rec(n[1], lambda x: path_fn(("not", x)))
            elif op in ("and", "or", "imp", "iff", "xor"):
                rec(n[1], lambda x, n=n: path_fn((n[0], x, n[2])))
                rec(n[2], lambda x, n=n: path_fn((n[0], n[1], x)))
        rec(node, lambda x: x)
        return outs

    def rewrites(node):
        outs = []
        if node[0] == "forall" and node[2][0] == "imp":
            a, b = node[2][1], node[2][2]
            outs.append(("contrapositive", ("forall", node[1], ("imp", ("not", b), ("not", a)))))
        if node[0] == "imp":
            outs.append(("contrapositive", ("imp", ("not", node[2]), ("not", node[1]))))
            outs.append(("material_implication", ("or", ("not", node[1]), node[2])))
        if node[0] == "not" and node[1][0] in ("and", "or"):
            inner = node[1]
            outs.append(("de_morgan", ("or" if inner[0] == "and" else "and", ("not", inner[1]), ("not", inner[2]))))
        if node[0] in ("and", "or") :
            outs.append(("de_morgan", ("not", ("or" if node[0] == "and" else "and", ("not", node[1]), ("not", node[2])))))
        if node[0] == "xor":
            outs.append(("xor_expansion", ("or", ("and", node[1], ("not", node[2])), ("and", ("not", node[1]), node[2]))))
        return outs

    def rename(node):
        preds, consts = signature(node)
        pm = {p: ("Is" + "".join(w.capitalize() for w in p.split("_")) + "Prop") for p in preds}

        def rw(n):
            if n[0] in ("forall", "exists"):
                return (n[0], n[1], rw(n[2]))
            if n[0] == "not":
                return ("not", rw(n[1]))
            if n[0] in ("and", "or", "imp", "iff", "xor"):
                return (n[0], rw(n[1]), rw(n[2]))
            if n[0] == "atom":
                return ("atom", pm[n[1]], n[2])
            return n
        return rw(node)

    items = []
    used = set()
    # 15 faithful golds
    for r in pool:
        if len([i for i in items if i["kind"] == "gold"]) >= 15:
            break
        items.append({"kind": "gold", "sentence": r["sentence"], "formula": r["gold_fol_original"], "label_faithful": True,
                      "source_id": r["source_id"], "op": "none"})
        used.add(r["source_id"])
    # 15 non-equivalent mutants (3 per op; argument_swap falls back to connective_and_or if absent)
    ops = ["negation_flip", "quantifier_swap", "implication_reversal", "drop_conjunct", "argument_swap"]
    for op in ops:
        got = 0
        for kind in ([op] if op != "argument_swap" else ["argument_swap", "connective_and_or"]):
            for r in pool:
                if got >= 3:
                    break
                if r["source_id"] in used:
                    continue
                a = parse(r["gold_fol_original"]).ast
                muts = mutate(a, kind)
                rng.shuffle(muts)
                for m in muts:
                    if strict_non_equiv(m, a):
                        items.append({"kind": "mutant", "sentence": r["sentence"], "formula": to_str(m),
                                      "label_faithful": False, "source_id": r["source_id"], "op": kind,
                                      "gold": r["gold_fol_original"]})
                        used.add(r["source_id"])
                        got += 1
                        break
    # 10 equivalent rewrites (contrapositive / De Morgan / renaming)
    got = Counter()
    for r in pool:
        if sum(got.values()) >= 10:
            break
        if r["source_id"] in used:
            continue
        a = parse(r["gold_fol_original"]).ast
        cands = rewrites(a)
        if got["predicate_renaming"] < 3:
            cands.append(("predicate_renaming", rename(a)))
        rng.shuffle(cands)
        for name, b in cands:
            if got[name] >= 4:
                continue
            if ok_equiv(b, a):
                items.append({"kind": "rewrite", "sentence": r["sentence"], "formula": to_str(b), "label_faithful": True,
                              "source_id": r["source_id"], "op": name, "gold": r["gold_fol_original"]})
                used.add(r["source_id"])
                got[name] += 1
                break
    for i, it in enumerate(items):
        it["cal_id"] = f"cal{i:02d}"
    return items


# --------------------------------------------------------------------------- main
@logger.catch(reraise=True)
def main() -> None:
    report: dict = {}
    malls = load_malls()
    folio = load_folio_train(report)
    pq = {lvl: load_proverqa(lvl) for lvl in ("easy", "medium", "hard")}
    logger.info(f"loaded malls={len(malls)} folio_train_sents={len(folio)} proverqa="
                f"{ {k: len(v) for k, v in pq.items()} }")

    # --- disjointness of FOLIO train from FOLIO validation (v1 + v2)
    valset, v2ids = folio_validation_sentences()
    bad_story = {r["story_id"] for r in folio if norm(r["sentence"]) in valset}
    n_st = len({r["story_id"] for r in folio})
    folio = [r for r in folio if r["story_id"] not in bad_story and norm(r["sentence"]) not in valset]
    report["folio_disjointness"] = {"train_stories_total": n_st, "stories_excluded_sharing_val_sentence": len(bad_story),
                                    "v2_validation_story_ids_in_train": len(v2ids & {r['story_id'] for r in folio})}
    assert not ({norm(r["sentence"]) for r in folio} & valset)

    # --- dedupe by normalized sentence (keep first)
    def dedupe(rows):
        seen, out = set(), []
        for r in rows:
            k = norm(r["sentence"])
            if k in seen:
                continue
            seen.add(k)
            out.append(r)
        return out
    malls, folio = dedupe(malls), dedupe(folio)

    # ProverQA: keep non-trivial, de-template, <=2 per story
    all_fols = [r["gold_fol_original"] for r in malls + folio] + [r.get("gold_fol_paper") for r in malls if r.get("gold_fol_paper")]
    for lvl in pq:
        all_fols += [r["gold_fol_original"] for r in pq[lvl]]
    logger.info(f"gold checks on {len(set(all_fols))} unique formulas")
    checks = run_checks(all_fols)
    (WORK / "gold_checks.json").write_text(json.dumps(checks, ensure_ascii=False))

    excl = defaultdict(Counter)

    def eligible(r, fol_key="gold_fol_original"):
        c = checks[r[fol_key]]
        if not c.get("parse_ok"):
            excl[r["corpus_subset"]]["gold_unparseable"] += 1
            return False
        if c.get("sv_error"):
            excl[r["corpus_subset"]]["gold_solver_error"] += 1
            return False
        if c["unsat_bounded"]:
            excl[r["corpus_subset"]]["gold_unsat"] += 1
            return False
        if c["valid_bounded"]:
            excl[r["corpus_subset"]]["gold_valid_tautology"] += 1
            return False
        if not (c["has_quant"] or c["n_all_conn"] >= 2):
            excl[r["corpus_subset"]]["ground_fact_or_trivial"] += 1
            return False
        return True

    pool = []
    for r in malls:
        key = "gold_fol_paper" if r.get("gold_fol_paper") else "gold_fol_original"
        if eligible(r, key):
            r["orig_gold_check"] = checks[r["gold_fol_original"]]
            r["gold_parse_ok_original"] = bool(checks[r["gold_fol_original"]].get("parse_ok"))
            pool.append(r)
    for r in folio:
        if eligible(r):
            pool.append(r)
    pq_elig = {}
    for lvl in pq:
        rows = [r for r in pq[lvl] if eligible(r)]
        seen_t, per_story, out = set(), Counter(), []
        for r in rows:
            t = detemplate(r["sentence"], r["gold_fol_original"])
            if t in seen_t:
                excl[r["corpus_subset"]]["duplicate_template"] += 1
                continue
            if per_story[r["story_id"]] >= 2:
                excl[r["corpus_subset"]]["over_2_per_story"] += 1
                continue
            seen_t.add(t)
            per_story[r["story_id"]] += 1
            r["template"] = t
            out.append(r)
        pq_elig[lvl] = out
    pool += pq_elig["medium"] + pq_elig["hard"]
    report["exclusions"] = {k: dict(v) for k, v in excl.items()}
    report["eligible_counts"] = dict(Counter(r["corpus_subset"] for r in pool))
    logger.info(f"eligible: {report['eligible_counts']}")

    # --- complexity features (screen recipe), z over pooled eligible held-out pool
    for r in pool:
        key = "gold_fol_paper" if r.get("gold_fol_paper") else "gold_fol_original"
        c = checks[r[key]]
        r["sentence_id"] = sha(r["sentence"])[:10]
        r["n_tokens"] = len(r["sentence"].split())
        r["n_quantifiers"] = c["n_quantifiers"]
        r["nesting_depth"] = c["nesting_depth"]
        r["n_conditions"] = n_conditions_text(r["sentence"]) + c["n_gold_connectives"]
        r["complexity_gold_used"] = key
    feats = ["n_tokens", "n_quantifiers", "nesting_depth", "n_conditions"]
    zpar = {}
    for f in feats:
        vals = [r[f] for r in pool]
        mu = sum(vals) / len(vals)
        sd = math.sqrt(sum((v - mu) ** 2 for v in vals) / (len(vals) - 1)) or 1.0
        zpar[f] = {"mean": mu, "sd": sd}
    for r in pool:
        r["complexity_composite"] = sum((r[f] - zpar[f]["mean"]) / zpar[f]["sd"] for f in feats) / 4
    comp = sorted(r["complexity_composite"] for r in pool)
    q1, q2 = comp[len(comp) // 3], comp[2 * len(comp) // 3]
    for r in pool:
        x = r["complexity_composite"]
        r["complexity_tercile"] = "bottom" if x < q1 else ("middle" if x < q2 else "top")
    zinfo = {"z_params": zpar, "tercile_cutpoints": [q1, q2], "pool_size": len(pool),
             "composite": "mean of 4 z-scores", "features": feats}
    report["complexity"] = zinfo
    report["tercile_by_corpus_pool"] = {k: dict(Counter(r["complexity_tercile"] for r in pool if r["corpus_subset"] == k))
                                        for k in report["eligible_counts"]}

    # --- stratified sample (seed 0, deterministic sha1 order)
    rng = random.Random(0)
    targets = {"malls": 250, "folio": 250, "proverqa_hard": 120, "proverqa_medium": 80}
    fracs = {"top": 0.45, "middle": 0.30, "bottom": 0.25}
    chosen = []
    shortfall = Counter()
    for grp, n in targets.items():
        if grp.startswith("proverqa"):
            cand = [r for r in pool if r["corpus_subset"] == grp]
        else:
            cand = [r for r in pool if r["corpus"] == grp]
        cand.sort(key=lambda r: sha(r["sentence"]))
        forced = [r for r in cand if r.get("gold_fol_paper")] if grp == "malls" else []
        rest = [r for r in cand if not r.get("gold_fol_paper")] if grp == "malls" else cand
        picked = list(forced)
        need = {t: round(n * fracs[t]) for t in fracs}
        for r in forced:
            need[r["complexity_tercile"]] -= 1
        for t in ("top", "middle", "bottom"):
            avail = [r for r in rest if r["complexity_tercile"] == t]
            k = max(0, need[t])
            if len(avail) < k:
                shortfall[(grp, t)] += k - len(avail)
            picked += avail[:k]
        # top up to n with remaining (prefer top tercile)
        left = [r for r in rest if r not in picked]
        left.sort(key=lambda r: ({"top": 0, "middle": 1, "bottom": 2}[r["complexity_tercile"]], sha(r["sentence"])))
        while len(picked) < n and left:
            picked.append(left.pop(0))
        for r in picked:
            r["sample_group"] = grp
        chosen += picked
    report["sample_shortfall"] = {f"{a}:{b}": v for (a, b), v in shortfall.items()}
    n_top = sum(r["complexity_tercile"] == "top" for r in chosen)
    report["sample_counts"] = dict(Counter(r["sample_group"] for r in chosen))
    report["sample_terciles"] = {g: dict(Counter(r["complexity_tercile"] for r in chosen if r["sample_group"] == g)) for g in targets}
    report["sample_top_share"] = n_top / len(chosen)
    logger.info(f"sample N={len(chosen)} top share={n_top / len(chosen):.3f} {report['sample_terciles']}")
    assert 650 <= len(chosen) <= 750, len(chosen)
    assert n_top / len(chosen) >= 0.40
    assert len({r['sentence_id'] for r in chosen}) == len(chosen)

    # --- screen reproduction (L4)
    screen = build_screen(report, run_checks)
    screen_norm = {r["norm_sentence"] for r in screen}
    assert not (screen_norm & {norm(r["sentence"]) for r in chosen if r["corpus"] == "folio"})
    logger.info(f"screen sentences audited: {len(screen)}")

    # --- calibration set from ProverQA dev-EASY (never used held-out)
    cal = build_calibration(pq_elig["easy"])
    report["calibration_composition"] = dict(Counter(f"{c['kind']}:{c['op']}" for c in cal))
    logger.info(f"calibration items: {len(cal)} {report['calibration_composition']}")

    (WORK / "pool.json").write_text(json.dumps(pool, ensure_ascii=False))
    (WORK / "heldout_sentences.json").write_text(json.dumps(chosen, ensure_ascii=False, indent=1))
    (WORK / "screen_sentences.json").write_text(json.dumps(screen, ensure_ascii=False, indent=1))
    (WORK / "calibration_set.json").write_text(json.dumps(cal, ensure_ascii=False, indent=1))
    (WORK / "prep_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str))
    logger.info("prep done")


if __name__ == "__main__":
    main()
