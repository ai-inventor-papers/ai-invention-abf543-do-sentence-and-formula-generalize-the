#!/usr/bin/env python3
"""M4 search placebos -> results/m4_placebo.json.
(a) cross-sentence peers: 1,000 dev candidates x (3 same-corpus + 1 other-corpus) parseable outputs of OTHER sentences
    with an identical arity profile; EQUIV/STRONGER/WEAKER rates by the level first found, by atom count and by
    shape-isomorphism (EQUIV at L1). (b) within-sentence label shuffle (200 permutations). (c) within-sentence AUROC
    (all faithful x unfaithful pairs in a sentence). (d) lexical-anchor contrast: within-sentence EQUIVs that are
    non-EQUIV under the trigram map although one exists; enrichment among panel-unfaithful items."""
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from loguru import logger  # noqa: E402

from dc.common import LOGS, RES, WORK, PairStore, detect_cpus, jdump, rj  # noqa: E402
from dc import stats as ST  # noqa: E402
from m0_anchor import load_all  # noqa: E402

logger.remove()
logger.add(sys.stdout, level="INFO", format="{time:HH:mm:ss}|{level:<7}|{message}")
logger.add(str(LOGS / "m4.log"), level="DEBUG")


def n_atoms(s):
    from dc import front
    import mutants as mu
    A = front.parse_canon(s)
    return sum(1 for _, m in mu.preorder(A) if m[0] == "atom")


def arity_profile(s):
    from dc import front
    import fol_core as fc
    A = front.parse_canon(s)
    return (tuple(sorted((fc.predicates(A, strict=False) or {}).values())), len(fc.constants(A)))


def pairs_within(G):
    by = defaultdict(list)
    for r in G:
        by[r["sentence_id"]].append(r)
    return by


def wsauc(G, by, metric, ykey, weighted):
    """Within-sentence AUROC: over all (faithful, unfaithful) pairs in the same sentence."""
    vals, wts, grp = [], [], []
    for sid, rs in by.items():
        R = [r for r in rs if r[ykey] is not None and r["m"].get(metric) is not None]
        pos = [r for r in R if r[ykey] == 1]
        neg = [r for r in R if r[ykey] == 0]
        for a in pos:
            for b in neg:
                vals.append(ST.det(a["m"][metric], b["m"][metric]))
                wts.append((a["w"] * b["w"]) if weighted else 1.0)
                grp.append(sid)
    return ST.cluster_boot_mean(vals, wts, grp)


@logger.catch(reraise=True)
def main():
    workers = max(1, detect_cpus() - 1)
    G, sc = load_all()
    cm = {c["raw"]: (c["canon"] if c["ok"] else None) for c in rj(WORK / "canon.jsonl")}
    out = {}
    # ---------------- (a)
    rng = random.Random(4)
    parse = [r for r in G if cm.get(r["candidate_fol"] or "")]
    prof = {}
    for r in parse:
        c = cm[r["candidate_fol"]]
        if c not in prof:
            prof[c] = arity_profile(c)
    idx = defaultdict(list)
    for r in parse:
        idx[(r["corpus"], prof[cm[r["candidate_fol"]]])].append(r)
        idx[("*", prof[cm[r["candidate_fol"]]])].append(r)
    cands = list(parse)
    rng.shuffle(cands)
    jobs, meta = [], []
    for r in cands:
        if len(meta) >= 1000:
            break
        c = cm[r["candidate_fol"]]
        pf = prof[c]
        same = [x for x in idx[(r["corpus"], pf)] if x["sentence_id"] != r["sentence_id"] and cm[x["candidate_fol"]] != c]
        other = [x for x in idx[("*", pf)] if x["corpus"] != r["corpus"] and cm[x["candidate_fol"]] != c]
        if len(same) < 3:
            continue
        picks = rng.sample(same, 3) + ([rng.choice(other)] if other else [])
        meta.append({"item_id": r["item_id"], "c": c, "picks": [(cm[x["candidate_fol"]], x["corpus"] == r["corpus"]) for x in picks],
                     "atoms": n_atoms(c)})
        jobs += [(c, cm[x["candidate_fol"]]) for x in picks]
    st = PairStore()
    st.compute(jobs, workers=workers, want_lex=True, log=logger.info)
    recs = []
    for m in meta:
        for p, same in m["picks"]:
            x = st.get(m["c"], p)
            recs.append({"L1": x.get("rel_L1"), "L2": x.get("rel_L2"), "L3": x.get("rel_L3"), "lex": x.get("rel_lex"),
                         "same_corpus": same, "atoms": m["atoms"], "timeout": x.get("timeout")})

    def rates(R):
        n = len(R)
        if not n:
            return {"n": 0}
        iso = [r for r in R if r["L1"] == "EQUIV"]
        non = [r for r in R if r["L1"] != "EQUIV"]
        o = {"n": n, "shape_isomorphic_rate": len(iso) / n, "n_non_iso": len(non)}
        for lv in ("L1", "L2", "L3"):
            o[f"EQUIV_{lv}"] = sum(r[lv] == "EQUIV" for r in R) / n
            o[f"ENTAIL_{lv}"] = sum(r[lv] in ("STRONGER", "WEAKER") for r in R) / n
        if non:
            o["spurious_EQUIV_non_iso_L2"] = sum(r["L2"] == "EQUIV" for r in non) / len(non)
            o["spurious_EQUIV_non_iso_L3"] = sum(r["L3"] == "EQUIV" for r in non) / len(non)
            o["L3_increment_EQUIV_non_iso"] = o["spurious_EQUIV_non_iso_L3"] - o["spurious_EQUIV_non_iso_L2"]
            o["spurious_ENTAIL_non_iso_L3"] = sum(r["L3"] in ("STRONGER", "WEAKER") for r in non) / len(non)
        o["lexical_EQUIV_rate"] = sum(r["lex"] == "EQUIV" for r in R) / n
        return o
    A = {"all": rates(recs), "same_corpus": rates([r for r in recs if r["same_corpus"]]),
         "other_corpus": rates([r for r in recs if not r["same_corpus"]])}
    for lab, f in (("atoms<=3", lambda a: a <= 3), ("atoms4-6", lambda a: 4 <= a <= 6), ("atoms>=7", lambda a: a >= 7)):
        A[lab] = rates([r for r in recs if f(r["atoms"])])
    a = A["all"]
    A["TARGET_spurious_EQUIV_le_2pct"] = (a.get("spurious_EQUIV_non_iso_L3") or 0) <= 0.02
    A["FLAG_L3_increment_gt_5pct"] = (a.get("L3_increment_EQUIV_non_iso") or 0) > 0.05
    A["n_candidates"] = len(meta)
    out["a_cross_sentence"] = A
    logger.info(f"(a) {json.dumps(a)}")
    # ---------------- (b) within-sentence label shuffle
    by = pairs_within(G)
    rng2 = np.random.default_rng(9)
    res_b = {}
    for lab, yk, wk in (("solver", "y_solver", None), ("panel", "y_panel", "w")):
        R = [r for r in G if r[yk] is not None]
        s = np.array([r["m"]["DC"] for r in R])
        w = np.array([r[wk] for r in R], float) if wk else np.ones(len(R))
        y = np.array([r[yk] for r in R], float)
        grp = defaultdict(list)
        for i, r in enumerate(R):
            grp[r["sentence_id"]].append(i)
        vals = []
        for _ in range(200):
            yp = y.copy()
            for ix in grp.values():
                ix = np.array(ix)
                yp[ix] = y[rng2.permutation(ix)]
            vals.append(ST.wauc(yp, s, w))
        res_b[lab] = {"mean_shuffled_auroc": float(np.mean(vals)), "p2.5_97.5": ST.ci(vals),
                      "true_auroc": ST.wauc(y, s, w), "signature_reference": 0.648}
    out["b_within_sentence_shuffle"] = res_b
    # ---------------- (c) within-sentence AUROC
    res_c = {}
    for lab, yk, weighted in (("panel", "y_panel", True), ("solver", "y_solver", False)):
        res_c[lab] = {m: wsauc(G, by, m, yk, weighted) for m in
                      ("DC", "DC_L2w", "S0_L1", "DC_lex", "LC_maj", "LC_ds_binary", "LC_onecoin", "B1", "VC")}
    out["c_within_sentence_auroc"] = res_c
    # ---------------- (d) lexical-anchor contrast
    rows = []
    for r in G:
        s = sc[r["item_id"]]
        c = cm.get(r["candidate_fol"] or "")
        if c is None:
            continue
        n_eq = n_manuf = n_eq_lexmap = 0
        for pp in s["per_peer"]:
            if pp["rel"] != "EQUIV":
                continue
            n_eq += 1
            peer = next((x for x in by[r["sentence_id"]] if x["system"] == pp["peer"]), None)
            pc = cm.get(peer["candidate_fol"] or "") if peer else None
            if pc is None:
                continue
            x = st.get(c, pc) if pc != c else {"rel_lex": "EQUIV"}
            if x is None:
                continue
            if x.get("rel_lex") != "NOMAP":
                n_eq_lexmap += 1
                n_manuf += x.get("rel_lex") != "EQUIV"
        rows.append({"item_id": r["item_id"], "y_panel": r["y_panel"], "y_solver": r["y_solver"], "w": r["w"],
                     "n_eq": n_eq, "n_eq_lexmap": n_eq_lexmap, "n_manuf": n_manuf, "sid": r["sentence_id"]})
    tot_eq = sum(x["n_eq_lexmap"] for x in rows)
    D = {"share_of_EQUIVs_with_trigram_map_that_are_nonEQUIV_under_it": (sum(x["n_manuf"] for x in rows) / tot_eq) if tot_eq else None,
         "n_EQUIV_with_trigram_map": tot_eq, "n_EQUIV_total": sum(x["n_eq"] for x in rows)}
    for lab, yk in (("panel", "y_panel"), ("solver", "y_solver")):
        for yv, nm in ((1, "faithful"), (0, "unfaithful")):
            R = [x for x in rows if x[yk] == yv and x["n_eq_lexmap"] > 0]
            v = [x["n_manuf"] / x["n_eq_lexmap"] for x in R]
            w = [x["w"] if lab == "panel" else 1.0 for x in R]
            D[f"{lab}_{nm}_manufactured_share"] = ST.cluster_boot_mean(v, w, [x["sid"] for x in R])
    pa = json.loads((RES / "m0_anchor.json").read_text())
    D["DC_lex_vs_DC_auroc"] = {lab: {m: pa[lab][m]["auroc"] for m in ("DC", "DC_lex")} for lab in ("panel_weighted", "solver_unweighted")}
    fu, ff = D.get("panel_unfaithful_manufactured_share", {}).get("mean"), D.get("panel_faithful_manufactured_share", {}).get("mean")
    D["P3_enriched_among_unfaithful"] = bool(fu is not None and ff is not None and fu > ff)
    out["d_lexical_anchor"] = D
    jdump(out, RES / "m4_placebo.json")
    logger.info("M4 done")


if __name__ == "__main__":
    main()
