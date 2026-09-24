#!/usr/bin/env python3
"""STEP 1: sample the FRESH confirmation set (no API).

Excludes (by normalized string AND FOLIO story id) the 700 dev sentences, the 360 screen sentences, the 104
contamination originals and the 40 calibration items; FOLIO stories of the dev set and of both FOLIO validation
versions are excluded. Quotas: MALLS-v0.1-test 170, FOLIO-v2-train 150, ProverQA-dev medium/hard 130 (<= 2 per
story); within corpus >= 50% top tercile, rest middle/bottom 30/20. seed 20260924.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict

import numpy as np
from loguru import logger

from common import DEP, RES, load_dev_rows, norm, setup_logging

SEED = 20260924
QUOTA = {"malls": 170, "folio": 150, "proverqa": 130}
TSHARE = {"top": 0.50, "middle": 0.30, "bottom": 0.20}


@logger.catch(reraise=True)
def main() -> None:
    setup_logging("s01_sample_fresh")
    pool = json.loads((DEP / "work" / "pool.json").read_text())
    held = json.loads((DEP / "work" / "heldout_sentences.json").read_text())
    screen = json.loads((DEP / "work" / "screen_sentences.json").read_text())
    cal = json.loads((DEP / "work" / "calibration_set.json").read_text())
    cont = load_dev_rows(("contamination",))
    excl = {norm(s["sentence"]) for s in held} | {norm(s["sentence"]) for s in screen} | \
           {norm(r["metadata_original_sentence"]) for r in cont} | {norm(r["input"] and json.loads(r["input"])["sentence"]) for r in cont} | \
           {norm(c["sentence"]) for c in cal}
    held_stories = {str(s["story_id"]) for s in held if s["corpus"] == "folio" and s.get("story_id") is not None}
    # FOLIO validation stories (v1 screen + v2 validation) are excluded from the pool by construction in round 1;
    # re-derive v2 validation story ids from the raw source to assert it
    val_stories = set()
    for f in ("tasksource__folio/folio_v2_validation.jsonl",):
        p = DEP / "temp" / "datasets" / f
        if p.exists():
            for line in p.read_text().splitlines():
                if line.strip():
                    val_stories.add(str(json.loads(line).get("story_id")))
    for s in screen:
        if s.get("story_id") is not None:
            val_stories.add(str(s["story_id"]))
    stories_excl = held_stories | val_stories
    logger.info(f"exclusion strings {len(excl)}, FOLIO stories excluded {len(stories_excl)} "
                f"(dev {len(held_stories)}, validation {len(val_stories)})")
    elig = []
    for s in pool:
        if norm(s["sentence"]) in excl:
            continue
        if s["corpus"] == "folio" and str(s.get("story_id")) in stories_excl:
            continue
        if not s.get("gold_parse_ok_original", True):
            continue
        elig.append(s)
    logger.info(f"eligible after exclusions: {len(elig)} of {len(pool)}; {Counter(s['corpus'] for s in elig)}")
    rng = np.random.default_rng(SEED)
    chosen, log = [], {}
    shortfall = 0
    for corpus, q in QUOTA.items():
        cands = [s for s in elig if s["corpus"] == corpus]
        by_t = defaultdict(list)
        for s in cands:
            by_t[s["complexity_tercile"]].append(s)
        picked = []
        per_story = Counter()
        for t, share in TSHARE.items():
            want = int(round(q * share))
            L = by_t[t]
            order = rng.permutation(len(L))
            got = 0
            for i in order:
                s = L[i]
                if corpus == "proverqa" and per_story[s["story_id"]] >= 2:
                    continue
                picked.append(s)
                per_story[s["story_id"]] += 1
                got += 1
                if got >= want:
                    break
            log[f"{corpus}:{t}"] = {"want": want, "got": got, "available": len(L)}
            shortfall += want - got
        chosen += picked
    if shortfall > 0:
        logger.warning(f"shortfall {shortfall} sentences; filling from other corpora is logged")
    # dedupe by norm
    seen, fresh = set(), []
    for s in chosen:
        k = norm(s["sentence"])
        if k in seen:
            continue
        seen.add(k)
        fresh.append({"sid": s["sentence_id"], "sentence": s["sentence"], "corpus": s["corpus"],
                      "corpus_subset": s["corpus_subset"], "source_id": s["source_id"], "story_id": s.get("story_id"),
                      "licence": s.get("licence"), "gold_fol_original": s["gold_fol_original"],
                      "gold_fol_paper": s.get("gold_fol_paper"), "paper_corrected_flag": s.get("paper_corrected_flag"),
                      **{k: s.get(k) for k in ("n_tokens", "n_quantifiers", "nesting_depth", "n_conditions",
                                               "complexity_composite", "complexity_tercile", "complexity_gold_used")}})
    # integrity asserts
    assert not any(norm(s["sentence"]) in excl for s in fresh), "overlap by normalized string"
    assert not any(s["corpus"] == "folio" and str(s["story_id"]) in stories_excl for s in fresh), "overlap by story"
    held_ids = {s["sentence_id"] for s in held}
    assert not any(s["sid"] in held_ids for s in fresh)
    fresh.sort(key=lambda s: s["sid"])
    (RES / "fresh_sentences.json").write_text(json.dumps(fresh, ensure_ascii=False, indent=1))
    summ = {"n": len(fresh), "by_corpus": Counter(s["corpus"] for s in fresh),
            "by_corpus_tercile": Counter(f"{s['corpus']}:{s['complexity_tercile']}" for s in fresh),
            "quota_log": log, "overlap_norm": 0, "overlap_story": 0, "seed": SEED,
            "n_excl_strings": len(excl), "n_excl_stories": len(stories_excl),
            "top_tercile_share": sum(s["complexity_tercile"] == "top" for s in fresh) / len(fresh)}
    (RES / "fresh_sample_report.json").write_text(json.dumps(summ, indent=1, default=dict))
    logger.info(json.dumps(summ, default=dict)[:1500])


if __name__ == "__main__":
    main()
