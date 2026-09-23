"""P2d (label-free, zero-cost part): held-out invariance replication of R1.

100 held-out audited golds (metadata_gold_fol_audited, sentence-stratified by corpus, sha1 order) →
mutants.make_rewrites(k=2) (iter-1 rewrite generator, solver-verified equivalent) → canonical worlds for gold and
rewrite. Reports canonical-string identity and world-set identity per rewrite kind (RENAME compared through the
name-normalised iso keys). With a deterministic world-level judge cache, identical world sets (and identical
verbalisations for non-RENAME kinds) imply identical TVJT scores, i.e. paired FA = 0 for those items by construction.
"""
from __future__ import annotations

import collections as C
import json

import common
import worlds as WW
from common import RESULTS, sha1


def main(n: int = 100) -> dict:
    import fol_core as fc
    import mutants
    rows = common.load_dataset_rows(blind=True)
    golds = {}
    for r in rows:
        if r["group"] == "heldout_confirm" and r.get("metadata_gold_fol_audited"):
            golds.setdefault(r["metadata_sentence_id"], (r["metadata_corpus"], r["metadata_gold_fol_audited"]))
    from bridge import to_folio_str
    by_c = C.defaultdict(list)
    for sid in sorted(golds, key=sha1):
        corp, g = golds[sid]
        s, how = to_folio_str(g)
        if s:
            by_c[corp].append((sid, s))
    per = max(1, n // max(1, len(by_c)))
    pick = [x for c in sorted(by_c) for x in by_c[c][:per]][:n]
    items = []
    for sid, g in pick:
        F = fc.parse(g)
        for rw in mutants.make_rewrites(F, sid, k=2):
            items.append({"sid": sid, "gold": g, "kind": rw["kind"], "fol": rw["fol"], "map": rw["map"]})
    nl = {}
    for r in rows:
        if r["group"] == "heldout_confirm":
            nl.setdefault(r["metadata_sentence_id"], json.loads(r["input"])["sentence"])
    with open(common.DATA / "heldout_g2_items.jsonl", "w") as f:
        for sid, g in pick:
            f.write(json.dumps({"item_id": f"{sid}:gold", "kind": "gold", "sid": sid, "nl": nl[sid], "fol": g},
                               ensure_ascii=False) + "\n")
        for i, it in enumerate(items):
            f.write(json.dumps({"item_id": f"{it['sid']}:rw{i}:{it['kind']}", "kind": "rewrite", "rw_kind": it["kind"],
                                "gold_id": f"{it['sid']}:gold", "sid": it["sid"], "nl": nl[it["sid"]],
                                "fol": it["fol"]}, ensure_ascii=False) + "\n")
    res = WW.compute([g for _, g in pick] + [it["fol"] for it in items], workers=3)
    stat = C.defaultdict(C.Counter)
    for it in items:
        g, r = res.get(it["gold"]), res.get(it["fol"])
        k = it["kind"]
        stat[k]["n"] += 1
        if not g or not r or g.get("err") or r.get("err"):
            stat[k]["error"] += 1
            continue
        if k == "RENAME":
            same = sorted(w["key_norm"] for w in g["worlds"]) == sorted(w["key_norm"] for w in r["worlds"])
        else:
            same = sorted(w["key"] for w in g["worlds"]) == sorted(w["key"] for w in r["worlds"])
            stat[k]["canon_string_identical"] += int(g["canon"] == r["canon"])
            stat[k]["world_text_identical"] += int(sorted(w.get("text") or "" for w in g["worlds"]) ==
                                                   sorted(w.get("text") or "" for w in r["worlds"]))
        stat[k]["worldset_identical"] += int(same)
    out = {"n_golds": len(pick), "golds_by_corpus": {c: min(per, len(v)) for c, v in by_c.items()},
           "n_rewrites": len(items),
           "by_kind": {k: {**v, "rate": v["worldset_identical"] / max(1, v["n"])} for k, v in stat.items()},
           "note": "zero-cost invariance evidence; judged paired FA on these rewrites needs gemini (pending)"}
    (RESULTS / "heldout_g2_canon.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=1))
