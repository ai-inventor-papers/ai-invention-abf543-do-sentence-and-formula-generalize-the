"""Deterministic rebuild of the frozen screen set (strategy recipe) + labels + controlled items.

Real candidates: Logic-LM released FOLIO_dev translations (gpt-3.5-turbo, gpt-4, text-davinci-003).
Gold: FOLIO v1 validation (Yale-LILY/FOLIO data/v0.0), replaced by DSAVlab-UNIUD curated gold where the NL
matches (see gold-selection policy in method_out.json). 300 sentences by sha1(norm(nl)).
"""
from __future__ import annotations

import hashlib
import json
import multiprocessing as mp
import re
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

import fol_core as fc
from mutants import OPERATORS, make_mutant, make_rewrites

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
SYSTEMS = ["gpt-3.5-turbo", "gpt-4", "text-davinci-003"]
RECIPE_VERSION = "screen_recipe_v1(armB)"
FEATURE_SPEC = '''n_tokens = len(nl.split())
n_quant = count of '∀' and '∃' in gold_fol (string count)
depth = max AST nesting depth of parsed gold (atoms = 1)
n_cond = len(re.findall(r'\\b(if|unless|except|only|either|neither|not)\\b', nl, re.I)) + sum(gold_fol.count(c) for c in '→↔⊕∧∨')
composite = mean of z-scores (ddof=0) of the 4 features over the screen sentences
tercile = pd.qcut(composite.rank(method='first'), 3, labels=[0, 1, 2])'''


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip().rstrip(".").strip()


def sha(s: str) -> str:
    return hashlib.sha1(norm(s).encode()).hexdigest()


# ------------------------------------------------------------------------------------------- loading
def parse_program(prog: str) -> dict:
    out = {"glosses": {}, "lines": []}
    sec = None
    for raw in prog.split("\n"):
        line = raw.strip()
        if not line:
            continue
        low = line.lower().rstrip(":")
        if low in ("predicates", "premises", "conclusion", "conclusions"):
            sec = low
            continue
        if ":::" not in line:
            continue
        left, right = line.split(":::", 1)
        if sec == "predicates":
            from verbalize import parse_gloss_head
            h = parse_gloss_head(left)
            if h:
                out["glosses"][h[0]] = {"params": h[1], "text": right.strip()}
        elif sec in ("premises", "conclusion", "conclusions"):
            out["lines"].append({"fol": left.strip(), "nl": right.strip(), "section": sec})
    return out


def load_logiclm() -> tuple[dict, dict]:
    """Returns {system: [ {example_k, line_idx, fol, nl, glosses} ]}, stats."""
    res, stats = {}, {}
    for s in SYSTEMS:
        data = json.loads((RAW / f"FOLIO_dev_{s}.json").read_text())
        rows, empty = [], 0
        for e in data:
            k = int(str(e["id"]).split("_")[-1])
            progs = e.get("raw_logic_programs") or []
            if not progs or not str(progs[0]).strip():
                empty += 1
                continue
            p = parse_program(progs[0])
            for i, ln in enumerate(p["lines"]):
                rows.append({"example_k": k, "line_idx": i, "fol": ln["fol"], "nl": ln["nl"], "glosses": p["glosses"]})
        res[s] = rows
        stats[s] = {"entries": len(data), "empty_programs": empty, "lines": len(rows)}
        logger.info(f"Logic-LM {s}: {len(data)} entries, {empty} empty, {len(rows)} FOL:::NL lines")
    return res, stats


def load_gold() -> tuple[dict, dict]:
    gold, conflicts, stories = {}, 0, 0
    mism = 0
    for line in (RAW / "folio-validation.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        stories += 1
        pairs = []
        if len(d["premises"]) == len(d["premises-FOL"]):
            pairs += list(zip(d["premises"], d["premises-FOL"]))
        else:
            mism += 1
        pairs.append((d["conclusion"], d["conclusion-FOL"]))
        for nl, fol in pairs:
            k = norm(nl)
            if k in gold:
                if gold[k]["fol"].strip() != fol.strip():
                    conflicts += 1
                continue
            gold[k] = {"nl": nl.strip(), "fol": fol.strip()}
    st = {"examples": stories, "unique_sentences": len(gold), "gold_conflicts_same_nl": conflicts,
          "premise_count_mismatch_examples": mism}
    logger.info(f"FOLIO v1 validation gold: {st}")
    return gold, st


def _top_conjuncts(ast) -> list:
    return list(ast[1:]) if ast[0] == "and" else [ast]


def _names(ast) -> set[str]:
    return set(fc.predicates(ast, strict=False) or {}) | set(fc.constants(ast))


def _partition(conj: list, old: list) -> list | None:
    """Split curated top-level conjuncts into len(old) contiguous groups maximizing name-Jaccard."""
    n, k = len(conj), len(old)
    if n < k:
        return None
    cn = [_names(c) for c in conj]
    on = [_names(o) for o in old]
    NEG = -1e9
    best = np.full((k + 1, n + 1), NEG)
    back = np.zeros((k + 1, n + 1), dtype=int)
    best[0, 0] = 0
    for i in range(1, k + 1):
        for j in range(i, n - (k - i) + 1):
            for s in range(i - 1, j):
                if best[i - 1, s] == NEG:
                    continue
                grp = set().union(*cn[s:j])
                sc = len(grp & on[i - 1]) / max(1, len(grp | on[i - 1]))
                if best[i - 1, s] + sc > best[i, j]:
                    best[i, j] = best[i - 1, s] + sc
                    back[i, j] = s
    if best[k, n] == NEG:
        return None
    cuts, j = [], n
    for i in range(k, 0, -1):
        s = back[i, j]
        cuts.append((s, j))
        j = s
    cuts.reverse()
    return [conj[a] if b - a == 1 else ("and",) + tuple(conj[a:b]) for a, b in cuts]


def load_curated() -> tuple[dict, dict]:
    p = RAW / "curated_FOLIO_instances.jsonl"
    st = Counter()
    cur = {}
    if not p.exists():
        logger.warning("curated gold unavailable -> all gold_source=original")
        st["unavailable"] = 1
        return cur, dict(st)
    import spacy
    nlp = spacy.blank("en")
    nlp.add_pipe("sentencizer")
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        corrected = str(r.get("corrected")).lower() in ("yes", "true", "1")
        if r["id"].startswith("concl"):
            cur.setdefault(norm(r["NL_sentence"]), {"fol": r["FOL_sentence"], "old": r["FOL_sentence_old"],
                                                    "corrected": corrected, "id": r["id"]})
            st["concl_rows"] += 1
            continue
        st["story_rows"] += 1
        sents = [s.text.strip() for s in nlp(r["NL_sentence"]).sents if s.text.strip()]
        old_lines = [x for x in r["FOL_sentence_old"].split("\n") if x.strip()]
        new_ast, _ = fc.try_parse(r["FOL_sentence"])
        old_asts = [fc.try_parse(x)[0] for x in old_lines]
        if len(sents) != len(old_lines) or new_ast is None or any(a is None for a in old_asts):
            st["curated_unalignable_story"] += 1
            continue
        parts = _partition(_top_conjuncts(new_ast), old_asts)
        if parts is None:
            st["curated_unalignable_story"] += 1
            continue
        st["story_aligned"] += 1
        for nl, o, nw in zip(sents, old_lines, parts):
            cur.setdefault(norm(nl), {"fol": fc.to_str(nw), "old": o, "corrected": fc.to_str(nw) != fc.to_str(fc.try_parse(o)[0]),
                                      "id": r["id"]})
            st["story_sentences"] += 1
    logger.info(f"curated gold: {dict(st)}; {len(cur)} NL keys")
    return cur, dict(st)


# ------------------------------------------------------------------------------------------- workers
def _lab(res: dict) -> str:
    return {"equiv": "correct", "nonequiv": "incorrect"}.get(res["label"], "unlabeled")


def label_candidate(fol: str, gold_fol: str, gold_orig: str, curated_fol: str | None) -> dict:
    t0 = time.time()
    F, err = fc.try_parse(fol)
    out = {"parse_ok": int(F is not None), "parse_err": err}
    if F is None:
        for k in ("L_bij", "L_bij_orig", "L_str", "L_str_orig", "L_bij_cur"):
            out[k] = "incorrect"
        out.update({"n_equiv_maps": 0, "bounded_vs_unbounded": None, "label_reason": f"unparseable:{err}"})
        if curated_fol is None:
            out["L_bij_cur"] = None
        out["L_any"] = "incorrect"
        out["label_seconds"] = time.time() - t0
        return out
    G = fc.parse(gold_fol)
    r = fc.find_bijections(F, G)
    out["L_bij"] = _lab(r)
    out["label_reason"] = r["reason"]
    out["n_equiv_maps"] = r["n_equiv_maps"]
    out["bij_map"] = r["map"]
    if r["label"] == "equiv":
        RF = fc.rename(F, r["map"]["P"], r["map"]["C"])
        out["bounded_vs_unbounded"] = fc.unbounded_equiv(RF, G, timeout_ms=5000)
    else:
        out["bounded_vs_unbounded"] = None
    out["L_str"] = _lab(fc.label_trigram(F, G))
    if gold_orig == gold_fol:
        out["L_bij_orig"], out["L_str_orig"] = out["L_bij"], out["L_str"]
    else:
        Go = fc.parse(gold_orig)
        out["L_bij_orig"] = _lab(fc.find_bijections(F, Go))
        out["L_str_orig"] = _lab(fc.label_trigram(F, Go))
    if curated_fol is not None:
        Gc, e2 = fc.try_parse(curated_fol)
        out["L_bij_cur"] = _lab(fc.find_bijections(F, Gc)) if Gc is not None else "unlabeled"
    else:
        out["L_bij_cur"] = None
    out["L_any"] = "correct" if "correct" in (out["L_bij"], out["L_bij_orig"], out["L_bij_cur"]) else (
        "unlabeled" if "unlabeled" in (out["L_bij"], out["L_bij_cur"]) else "incorrect")
    out["label_seconds"] = time.time() - t0
    return out


def sentence_worker(job: dict) -> dict:
    """All z3 work for one screen sentence: labels of its 3 candidates, pairwise candidate equivalence
    (latent class), self-consistency against alternates, controlled mutants and rewrites."""
    import fol_core as fc2  # noqa: F401  (spawned process)
    sid = job["sid"]
    out = {"sid": sid, "cands": {}, "pairs": {}, "alt_equiv": {}, "mutants": [], "rewrites": [], "mut_stats": {}}
    for s, c in job["cands"].items():
        out["cands"][s] = label_candidate(c["fol"], job["gold_fol"], job["gold_orig"], job.get("curated_fol"))
    # pairwise equivalence between the systems' primary candidates (blind map + trigram map)
    systems = sorted(job["cands"])
    asts = {s: fc.try_parse(job["cands"][s]["fol"])[0] for s in systems}
    for i in range(len(systems)):
        for j in range(i + 1, len(systems)):
            a, b = asts[systems[i]], asts[systems[j]]
            if a is None or b is None:
                continue
            out["pairs"][f"{systems[i]}|{systems[j]}"] = {"bij": fc.find_bijections(a, b, wall_s=15)["label"],
                                                         "str": fc.label_trigram(a, b)["label"]}
    for s, alts in job.get("alts", {}).items():
        a = asts.get(s)
        res = []
        for alt in alts[:10]:
            b, _ = fc.try_parse(alt)
            if a is None or b is None:
                res.append(None)
                continue
            res.append(fc.find_bijections(a, b, wall_s=10)["label"])
        out["alt_equiv"][s] = res
    G = fc.parse(job["gold_fol"])
    if job.get("controlled", True):
        for op in OPERATORS:
            m = make_mutant(G, op, f"{sid}:gold")
            out["mut_stats"][op] = {"applicable": m["applicable"], "kept": m["kept"]}
            if m["kept"]:
                out["mutants"].append({"op": op, "fol": m["fol"], "variant": m.get("variant")})
        for rw in make_rewrites(G, f"{sid}:gold", k=2):
            out["rewrites"].append({"kind": rw["kind"], "fol": rw["fol"], "map": rw["map"]})
    # blind-spot supplement mutants (SCOPE_SWAP + both CARD variants)
    sup = []
    for op, var in (("SCOPE_SWAP", None), ("CARD", "two"), ("CARD", "unique")):
        m = make_mutant(G, op, f"{sid}:gold:sup", variant=var)
        if m["kept"]:
            sup.append({"op": op, "variant": var, "fol": m["fol"]})
    out["supplement"] = sup
    return out


def gold_check_worker(item: tuple[str, str]) -> tuple[str, str, str | None]:
    k, fol = item
    ast, err = fc.try_parse(fol)
    if ast is None:
        return k, "unparseable", err
    sat = fc.satisfiable(ast, nmax=4, timeout_ms=5000)
    return k, sat, None


def gold_vs_curated_worker(item) -> tuple[str, dict]:
    k, orig, cur = item
    a, _ = fc.try_parse(orig)
    b, _ = fc.try_parse(cur)
    if a is None or b is None:
        return k, {"label": "unparseable"}
    r = fc.find_bijections(a, b, wall_s=15)
    return k, {"label": r["label"], "reason": r["reason"]}


# ------------------------------------------------------------------------------------------- main
def complexity(nl: str, gold_fol: str) -> dict:
    ast = fc.parse(gold_fol)
    return {"n_tokens": len(nl.split()), "n_quant": gold_fol.count("∀") + gold_fol.count("∃"),
            "depth": fc.depth(ast),
            "n_cond": len(re.findall(r"\b(if|unless|except|only|either|neither|not)\b", nl, re.I))
            + sum(gold_fol.count(c) for c in "→↔⊕∧∨")}


def build(limit: int | None, workers: int = 6) -> dict:
    t0 = time.time()
    llm_rows, llm_stats = load_logiclm()
    gold, gold_stats = load_gold()
    curated, cur_stats = load_curated()
    # candidates grouped by normalized nl, per system, tie-break smallest example_k then line order
    by_sent: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    unmatched = Counter()
    for s, rows in llm_rows.items():
        for r in rows:
            k = norm(r["nl"])
            if k in gold:
                by_sent[k][s].append(r)
            else:
                unmatched[s] += 1
    for k in by_sent:
        for s in by_sent[k]:
            by_sent[k][s].sort(key=lambda r: (r["example_k"], r["line_idx"]))
    logger.info(f"unmatched candidate lines per system: {dict(unmatched)}")
    # gold checks (parseable + satisfiable)
    gold_items = [(k, v["fol"]) for k, v in gold.items() if k in by_sent]
    gcheck = {}
    ctx = mp.get_context("spawn")
    with ProcessPoolExecutor(max_workers=workers, mp_context=ctx) as ex:
        for k, st, err in ex.map(gold_check_worker, gold_items, chunksize=8):
            gcheck[k] = (st, err)
    # curated selection policy: curated FOL is used as gold only when it is parseable and satisfiable
    cur_items = [(k, gold[k]["fol"], curated[k]["fol"]) for k in by_sent if k in curated]
    gvc = {}
    with ProcessPoolExecutor(max_workers=workers, mp_context=ctx) as ex:
        for k, r in ex.map(gold_vs_curated_worker, cur_items, chunksize=4):
            gvc[k] = r
    eligible = []
    drop = Counter()
    usable = {}
    for k in by_sent:
        cur = curated.get(k)
        cur_ok = False
        if cur is not None:
            ca, _ = fc.try_parse(cur["fol"])
            cur_ok = ca is not None and fc.satisfiable(ca) == "sat"
        orig_ok = gcheck.get(k, ("unparseable",))[0] == "sat"
        usable[k] = (orig_ok, cur_ok)
        # recipe: gold = curated if matched else original; drop if that gold is unparseable/unsatisfiable
        recipe_ok = cur_ok if cur is not None else orig_ok
        if not recipe_ok:
            drop["curated_unusable" if cur is not None else f"gold_{gcheck.get(k, ('unparseable',))[0]}"] += 1
            continue
        eligible.append(k)
    logger.info(f"eligible sentences: {len(eligible)}; dropped {dict(drop)}")
    eligible.sort(key=lambda k: hashlib.sha1(k.encode()).hexdigest())
    n_take = 300 if limit is None else limit
    screen_keys = eligible[:300][:n_take]
    screen_set_keys = set(eligible[:300])
    sentences, jobs, alt_rows = [], [], []
    for k in screen_keys:
        h = hashlib.sha1(k.encode()).hexdigest()
        sid = h[:10]
        cur = curated.get(k)
        orig_fol = gold[k]["fol"]
        orig_ok, cur_ok = usable[k]
        # PRIMARY label gold (documented deviation): FOLIO v1 gold when usable (same annotation round and
        # vocabulary conventions as the Logic-LM candidates); curated FOLIO-v2 gold only if v1 is unusable.
        if orig_ok:
            gold_fol, src = orig_fol, "original"
        else:
            gold_fol, src = cur["fol"], "corrected"
        recipe_src = "corrected" if cur is not None else "original"
        orig_fol_eff = orig_fol if orig_ok else gold_fol
        cands, alts = {}, {}
        for s in SYSTEMS:
            occ = by_sent[k].get(s, [])
            if not occ:
                continue
            p = occ[0]
            cands[s] = {"fol": p["fol"], "example_k": p["example_k"], "line_idx": p["line_idx"], "glosses": p["glosses"]}
            alts[s] = [o["fol"] for o in occ[1:]]
            for o in occ[1:]:
                alt_rows.append({"sid": sid, "system": s, "fol": o["fol"], "example_k": o["example_k"],
                                 "line_idx": o["line_idx"], "primary_item_id": f"{sid}:{s}"})
        feats = complexity(gold[k]["nl"], gold_fol)
        sentences.append({"sid": sid, "sha1": h, "nl": gold[k]["nl"], "gold_fol": gold_fol, "gold_source": src,
                          "gold_fol_original": orig_fol, "original_gold_usable": orig_ok, "recipe_gold_source": recipe_src,
                          "curated_fol": cur["fol"] if cur else None,
                          "curated_changed": (fc.to_str(fc.try_parse(cur["fol"])[0]) != fc.to_str(fc.try_parse(cur["old"])[0])
                                              if cur and cur_ok and fc.try_parse(cur["old"])[0] is not None
                                              else (cur["corrected"] if cur else None)),
                          "curated_corrected_flag": cur["corrected"] if cur else None,
                          "orig_vs_curated": gvc.get(k), "n_systems": len(cands), **feats})
        jobs.append({"sid": sid, "gold_fol": gold_fol, "gold_orig": orig_fol_eff, "curated_fol": cur["fol"] if cur_ok else None,
                     "cands": {s: {"fol": c["fol"]} for s, c in cands.items()}, "alts": alts, "_cands_full": cands})
    # supplement golds: eligible sentences NOT in the 300 (only when building the full set)
    sup_jobs = []
    if limit is None:
        for k in eligible[300:]:
            h = hashlib.sha1(k.encode()).hexdigest()
            cur = curated.get(k)
            cur_ast = fc.try_parse(cur["fol"])[0] if cur else None
            gf = gold[k]["fol"] if usable[k][0] else cur["fol"]
            sup_jobs.append({"sid": h[:10], "gold_fol": gf, "nl": gold[k]["nl"], "gold_orig": gf, "cands": {}, "alts": {},
                             "controlled": False})
        # FOLIO has almost no nested/∃ formulas, so the blind-spot supplement also draws on public FOLIO-train
        # gold and the curated MALLS subset (2606.02837). Supplement rows are NEVER used for gates or ranking.
        seen = {norm(gold[k]["nl"]) for k in eligible}
        extra = []
        tr = RAW / "folio-train.jsonl"
        if tr.exists():
            for line in tr.read_text().splitlines():
                if not line.strip():
                    continue
                d = json.loads(line)
                pairs_ = list(zip(d.get("premises", []), d.get("premises-FOL", []))) + [(d.get("conclusion", ""), d.get("conclusion-FOL") or "")]
                for nl, fol in pairs_:
                    if "∃" in fol and norm(nl) not in seen:
                        seen.add(norm(nl))
                        extra.append(("supplement_folio_train", nl, fol))
        ml = RAW / "malls_curated_MALLS_instances.jsonl"
        if ml.exists():
            for line in ml.read_text().splitlines():
                if not line.strip():
                    continue
                d = json.loads(line)
                fol = d.get("FOL_sentence_new") or d.get("FOL_sentence") or ""
                if "∃" in fol and norm(d["NL_sentence"]) not in seen:
                    seen.add(norm(d["NL_sentence"]))
                    extra.append(("supplement_malls_curated", d["NL_sentence"], fol))
        mt = RAW / "MALLS-v0.1-test.json"
        if mt.exists():  # uncurated MALLS test: only mixed-quantifier formulas (scope-swap supply)
            for d in json.loads(mt.read_text()):
                fol, nl = d.get("FOL", ""), d.get("NL", "")
                if "∃" in fol and "∀" in fol and norm(nl) not in seen:
                    seen.add(norm(nl))
                    extra.append(("supplement_malls_test", nl, fol))
        for split, nl, fol in extra:
            a, _ = fc.try_parse(fol)
            if a is None or fc.satisfiable(a) != "sat":
                continue
            sup_jobs.append({"sid": {"supplement_folio_train": "tr", "supplement_malls_curated": "mc",
                                     "supplement_malls_test": "mt"}[split] + sha(nl)[:8], "gold_fol": fol, "nl": nl.strip(),
                             "gold_orig": fol, "cands": {}, "alts": {}, "controlled": False, "split": split})
    logger.info(f"z3 labelling {len(jobs)} screen sentences + {len(sup_jobs)} supplement golds on {workers} workers")
    results = {}
    with ProcessPoolExecutor(max_workers=workers, mp_context=ctx) as ex:
        futs = {ex.submit(sentence_worker, {k2: v for k2, v in j.items() if k2 not in ("_cands_full", "split", "nl")}): j["sid"]
                for j in jobs + sup_jobs}
        for i, f in enumerate(as_completed(futs)):
            sid = futs[f]
            try:
                results[sid] = f.result(timeout=900)
            except Exception as e:  # noqa: BLE001 - log and keep going; item becomes unlabeled
                logger.error(f"worker failed for {sid}: {e!r}")
                results[sid] = None
            if (i + 1) % 50 == 0:
                logger.info(f"  labelled {i + 1}/{len(futs)} ({time.time() - t0:.0f}s)")
    # assemble
    real, mutants, rewrites, supplement = [], [], [], []
    mut_stats = defaultdict(Counter)
    pairs, alt_equiv = {}, {}
    for j, sent in zip(jobs, sentences):
        r = results.get(j["sid"])
        for s, c in j["_cands_full"].items():
            lab = (r or {}).get("cands", {}).get(s) or {"parse_ok": int(fc.try_parse(c["fol"])[0] is not None),
                                                          "L_bij": "unlabeled", "L_bij_orig": "unlabeled",
                                                          "L_str": "unlabeled", "L_str_orig": "unlabeled",
                                                          "L_bij_cur": None, "label_reason": "worker_failed"}
            real.append({"item_id": f"{j['sid']}:{s}", "sid": j["sid"], "system": s, "fol": c["fol"],
                         "example_k": c["example_k"], "line_idx": c["line_idx"], "glosses": c["glosses"], **lab})
        if r is None:
            continue
        pairs[j["sid"]] = r["pairs"]
        alt_equiv[j["sid"]] = r["alt_equiv"]
        for op, stt in r["mut_stats"].items():
            mut_stats[op]["golds"] += 1
            mut_stats[op]["applicable"] += int(stt["applicable"])
            mut_stats[op]["kept"] += int(stt["kept"])
        for m in r["mutants"]:
            mutants.append({"item_id": f"{j['sid']}:mut:{m['op']}", "sid": j["sid"], **m})
        for rw in r["rewrites"]:
            rewrites.append({"item_id": f"{j['sid']}:rw:{rw['kind']}", "sid": j["sid"], **rw})
        for m in r["supplement"]:
            supplement.append({"item_id": f"{j['sid']}:sup:{m['op']}:{m['variant']}", "sid": j["sid"], "split": "screen",
                               "gold_fol": j["gold_fol"], "nl": sent["nl"], **m})
    for j in sup_jobs:
        r = results.get(j["sid"])
        if r is None:
            continue
        for m in r["supplement"]:
            supplement.append({"item_id": f"{j['sid']}:sup:{m['op']}:{m['variant']}", "sid": j["sid"],
                               "split": j.get("split", "supplement"), "gold_fol": j["gold_fol"], "nl": j["nl"], **m})
    # complexity terciles
    df = pd.DataFrame(sentences)
    feats = ["n_tokens", "n_quant", "depth", "n_cond"]
    z = (df[feats] - df[feats].mean()) / df[feats].std(ddof=0).replace(0, 1)
    df["composite"] = z.mean(axis=1)
    df["tercile"] = pd.qcut(df["composite"].rank(method="first"), 3, labels=[0, 1, 2]).astype(int)
    for s, (_, row) in zip(sentences, df.iterrows()):
        s["composite"] = float(row["composite"])
        s["tercile"] = int(row["tercile"])
    real_ids = sorted(r["item_id"] for r in real)
    fingerprint = hashlib.sha1("\n".join(real_ids).encode()).hexdigest()
    lab_dist = {k: dict(Counter(r.get(k) for r in real)) for k in ("L_bij", "L_bij_orig", "L_str", "L_str_orig", "L_bij_cur", "L_any")}
    counts = {
        "logiclm": llm_stats, "gold": gold_stats, "curated": cur_stats,
        "unmatched_lines_per_system": dict(unmatched),
        "sentences_with_any_match": len(by_sent), "eligible": len(eligible), "dropped_gold": dict(drop),
        "screen_sentences": len(sentences), "screen_set_size_full": len(screen_set_keys),
        "matched_by_all_3": int(sum(1 for s in sentences if s["n_systems"] == 3)),
        "real_items": len(real), "real_per_system": dict(Counter(r["system"] for r in real)),
        "unparseable_per_system": dict(Counter(r["system"] for r in real if not r["parse_ok"])),
        "parse_err_classes": dict(Counter(r.get("parse_err") for r in real if not r["parse_ok"])),
        "label_distribution": lab_dist,
        "gold_source": dict(Counter(s["gold_source"] for s in sentences)),
        "recipe_gold_source": dict(Counter(s["recipe_gold_source"] for s in sentences)),
        "orig_vs_curated_equivalence": dict(Counter((s["orig_vs_curated"] or {}).get("label") for s in sentences
                                                    if s["curated_fol"])),
        "n_equiv_maps_gt1": int(sum(1 for r in real if (r.get("n_equiv_maps") or 0) > 1)),
        "bounded_vs_unbounded": dict(Counter(r.get("bounded_vs_unbounded") for r in real if r.get("L_bij") == "correct")),
        "mutants": {op: dict(v) for op, v in mut_stats.items()}, "n_mutants": len(mutants),
        "n_rewrites": len(rewrites), "rewrite_kinds": dict(Counter(r["kind"] for r in rewrites)),
        "n_supplement": len(supplement), "supplement_split": dict(Counter(s["split"] for s in supplement)),
        "supplement_ops": dict(Counter(f"{s['op']}:{s['variant']}" for s in supplement)),
        "alternates": len(alt_rows), "tie_break": "primary = smallest integer k in FOLIO_dev_k, first line within it",
        "build_seconds": round(time.time() - t0, 1),
    }
    logger.info(f"screen built: fingerprint {fingerprint}; counts {json.dumps({k: counts[k] for k in ['screen_sentences', 'real_items', 'n_mutants', 'n_rewrites', 'n_supplement']})}")
    logger.info(f"label distribution: {lab_dist}")
    return {"recipe_version": RECIPE_VERSION, "fingerprint": fingerprint, "counts": counts, "sentences": sentences,
            "real_items": real, "mutants": mutants, "rewrites": rewrites, "feature_spec": FEATURE_SPEC,
            "_pairs": pairs, "_alt_equiv": alt_equiv, "_alt_rows": alt_rows, "_supplement": supplement}
