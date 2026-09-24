#!/usr/bin/env python3
"""STEP 9 (plan numbering): SECONDARY analyses -> results/analysis.json.

circularity | component ladder | system level | complexity | invariance (solver-verified rewrites) | shared bias |
wrong-gold flag (gold as a 10th peer) | contamination (dev, $0) | coverage / timeouts / UNKNOWN / non-transitivity |
cost | label quality (kappa, wrong-gold, correct-but-inequivalent) | frontier gap (dev anchor).
"""
from __future__ import annotations

import itertools
import json
import random
from collections import Counter, defaultdict

import numpy as np
from loguru import logger

from aframe import boot, ci_auc, ci_diff, load_frame, sc, wauc
from common import RES, SYSTEMS, WORK, assert_frozen, read_jsonl, setup_logging
from dc.align import derive
from dc.consensus import DCConfig, score_group
from dc.parse import n_atoms, parse_fol
from dcscore import group_relations, ladder_scores, r2stats, score_all
from pairs import load_cache, lookup, run as run_pairs


def auc_block(rows, metrics, label):
    out = {}
    for m in metrics:
        rr = [r for r in rows if m in r["S"]]
        if len(rr) < 20:
            continue
        y = np.array([r["y_panel"] if label == "panel" else r["y_solver"] for r in rr], float)
        if len(set(y)) < 2:
            continue
        s = np.array([sc(r, m) for r in rr], float)
        w = np.array([r["w_panel"] for r in rr], float) if label == "panel" else None
        out[m] = {**ci_auc(y, s, w, boot(rr, n=1000, seed=5)), "n": len(rr), "n_pos": int(y.sum())}
    return out


def fleiss(votes_list):
    """Fleiss kappa for binary ratings; votes_list = list of lists of booleans (3 raters)."""
    N = len(votes_list)
    if N == 0:
        return None
    n = 3
    p1 = sum(sum(v) for v in votes_list) / (N * n)
    Pbar = np.mean([(sum(v) * (sum(v) - 1) + (n - sum(v)) * (n - sum(v) - 1)) / (n * (n - 1)) for v in votes_list])
    Pe = p1 ** 2 + (1 - p1) ** 2
    return float((Pbar - Pe) / (1 - Pe)) if Pe < 1 else None


@logger.catch(reraise=True)
def main() -> None:
    setup_logging("s12_secondary")
    fz = assert_frozen()
    c = fz["config"]
    cfg = DCConfig(use_L3=c["use_L3"], unalign_in_denominator=c["unalign_in_denominator"], weights=c["weights"],
                   half_caps=c["half_caps"], rule_1b=c["rule_1b"])
    rows, meta = load_frame()
    P = [r for r in rows if r["y_panel"] is not None]
    S = [r for r in rows if r["y_solver"] is not None]
    A = {}
    cache = load_cache()
    groups = defaultdict(dict)
    for r in rows:
        groups[r["sid"]][r["system"]] = r["canon"]
    W = json.loads((WORK / "fresh_dc_weights.json").read_text())["weights"]
    mets = ["DC", "LC_maj", "LC_ds_binary", "B1", "B3nliL", "VC", "TJ_L"]
    # ---------------- label quality
    l3 = meta["l3"]
    full = [v for v in l3.values() if v["full_panel_subset"]]
    kv = [[v["L3_votes"][m]["cand_faithful"] for m in ("M1", "M2", "M3")] for v in full
          if all(v["L3_votes"].get(m) and v["L3_votes"][m]["cand_faithful"] is not None for m in ("M1", "M2", "M3"))]
    l0 = meta["l0"]
    kv0 = [[l0[s]["votes"][m]["faithful"] for m in ("M1", "M2", "M3")] for s in l0 if l0[s]["full_panel_subset"]
           and all(l0[s]["votes"].get(m) and l0[s]["votes"][m]["faithful"] is not None for m in ("M1", "M2", "M3"))]
    wrong = defaultdict(list)
    sents = {s["sid"]: s for s in json.loads((RES / "fresh_sentences.json").read_text())}
    for s, v in l0.items():
        if v["gold_faithful_final"] is not None:
            wrong[sents[s]["corpus"]].append(1 - int(v["gold_faithful_final"]))

    def pci(x):
        x = np.array(x, float)
        rng = np.random.default_rng(0)
        bs = [rng.choice(x, len(x)).mean() for _ in range(2000)]
        return {"rate": float(x.mean()), "ci95": [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))], "n": len(x)}
    # correct-but-inequivalent: panel-faithful share among solver-NON-equivalent panel items (weighted)
    ne = [r for r in P if r["S_status"] in ("non_equiv", "non_equiv_no_bijection")]
    eq = [r for r in P if r["S_status"] in ("equiv_proved", "equiv_bounded")]
    cbi = (sum(r["w_panel"] * r["y_panel"] for r in ne) / sum(r["w_panel"] for r in ne)) if ne else None
    eq_unf = (sum(r["w_panel"] * (1 - r["y_panel"]) for r in eq) / sum(r["w_panel"] for r in eq)) if eq else None
    agree_ps = [r for r in P if r["y_solver"] is not None]
    A["label_quality"] = {
        "fleiss_kappa_L3_full_subset": fleiss(kv), "n_L3_full_subset": len(kv),
        "fleiss_kappa_L0_full_subset": fleiss(kv0), "n_L0_full_subset": len(kv0),
        "wrong_gold_rate_by_corpus": {k: pci(v) for k, v in wrong.items()},
        "wrong_gold_rate_all": pci([x for v in wrong.values() for x in v]),
        "correct_but_inequivalent_rate_weighted": cbi, "n_solver_nonequiv_panel": len(ne),
        "panel_unfaithful_among_solver_equiv_weighted": eq_unf, "n_solver_equiv_panel": len(eq),
        "solver_panel_agreement_weighted": (sum(r["w_panel"] * (r["y_panel"] == r["y_solver"]) for r in agree_ps) /
                                            sum(r["w_panel"] for r in agree_ps)) if agree_ps else None,
        "gold_sources": dict(Counter(v["gold_source"] for v in l0.values())),
        "L0_cascade_rules": dict(Counter(v["cascade_rule"] for v in l0.values())),
        "L0_full_subset_cascade_equals_majority": f"{sum(v['gold_faithful_final'] == v['full_majority'] for v in l0.values() if v['full_panel_subset'] and v['full_majority'] is not None)}/"
                                                  f"{sum(1 for v in l0.values() if v['full_panel_subset'] and v['full_majority'] is not None)}",
        "L3_no_majority": sum(1 for v in l3.values() if v["L3_majority"] is None),
        "panel_type_mix_weighted": {k: v / sum(r["w_panel"] for r in P if r["y_panel"] == 0) for k, v in Counter(
            {t: sum(r["w_panel"] for r in P if r["y_panel"] == 0 and r["panel_primary"] == t) for t in
             {r["panel_primary"] for r in P if r["y_panel"] == 0}}).items()},
        "weights": meta["weights"]}
    logger.info(f"label quality: {json.dumps(A['label_quality'], default=str)[:800]}")
    # ---------------- circularity (panel items whose candidate is solver-NON-equivalent to the audited gold)
    circ = {}
    for name, R in (("solver_nonequiv", ne), ("no_bijection", [r for r in P if r["S_status"] == "non_equiv_no_bijection"])):
        circ[name] = auc_block(R, mets, "panel")
    same = [r for r in P if r["y_solver"] is not None]
    if same:
        B = boot(same, n=1000, seed=6)
        y_p = np.array([r["y_panel"] for r in same], float)
        y_s = np.array([r["y_solver"] for r in same], float)
        w = np.array([r["w_panel"] for r in same], float)
        gap = {}
        for m in ("DC", "LC_maj", "B1"):
            s = np.array([sc(r, m) for r in same], float)
            vals = [wauc(y_p[i], s[i], w[i]) - wauc(y_s[i], s[i], w[i]) for i in B]
            vals = [v for v in vals if not np.isnan(v)]
            gap[m] = {"panel_minus_solver": wauc(y_p, s, w) - wauc(y_s, s, w),
                      "ci95": [float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))]}
        circ["panel_minus_solver_same_items"] = gap
    A["circularity"] = circ
    # ---------------- component ladder on fresh
    lad = ladder_scores(groups, cache)
    ladder = {}
    for lab, R in (("panel", P), ("solver", S)):
        d = {}
        for name in ("L1_uniform", "L12_uniform", "L123_uniform"):
            y = np.array([r["y_panel"] if lab == "panel" else r["y_solver"] for r in R], float)
            w = np.array([r["w_panel"] for r in R], float) if lab == "panel" else None
            d[name] = wauc(y, np.array([lad[name][(r["sid"], r["system"])][0] for r in R], float), w)
        for m in ("LC_maj", "LC_ds_binary", "LC_onecoin", "DC"):
            y = np.array([r["y_panel"] if lab == "panel" else r["y_solver"] for r in R], float)
            w = np.array([r["w_panel"] for r in R], float) if lab == "panel" else None
            d[m] = wauc(y, np.array([sc(r, m) for r in R], float), w)
        for alt in (DCConfig(use_L3=cfg.use_L3, unalign_in_denominator=cfg.unalign_in_denominator, weights="uniform"),
                    DCConfig(use_L3=True, unalign_in_denominator=cfg.unalign_in_denominator, weights=cfg.weights)):
            sc2, _, _ = score_all(groups, cache, alt, SYSTEMS)
            y = np.array([r["y_panel"] if lab == "panel" else r["y_solver"] for r in R], float)
            w = np.array([r["w_panel"] for r in R], float) if lab == "panel" else None
            d["DC:" + alt.name()] = wauc(y, np.array([sc2[(r["sid"], r["system"])]["score"] for r in R], float), w)
        # DC+SP: oof stack of DC with the strength profile
        X = np.array([[sc(r, "DC"), sc(r, "sp_net", 0.0), sc(r, "sp_incomparable", 0.0), sc(r, "sp_contradictory", 0.0)]
                      for r in R], float)
        y = np.array([r["y_panel"] if lab == "panel" else r["y_solver"] for r in R], int)
        w = np.array([r["w_panel"] for r in R], float) if lab == "panel" else None
        oof = r2stats.oof_stack(X, y, np.array([r["sid"] for r in R]), w)
        d["DC+SP(oof)"] = wauc(y, oof, w)
        ladder[lab] = d
    A["ladder_fresh"] = ladder
    logger.info(f"ladder {ladder}")
    # ---------------- system level
    sys_level = {}
    for lab, R in (("panel", P), ("solver", S)):
        truth = {}
        for s in SYSTEMS:
            rr = [r for r in R if r["system"] == s]
            if not rr:
                continue
            ww = [r["w_panel"] if lab == "panel" else 1.0 for r in rr]
            truth[s] = sum(w * (r["y_panel"] if lab == "panel" else r["y_solver"]) for w, r in zip(ww, rr)) / sum(ww)
        res = {"truth_accuracy": truth}
        for m in ("DC", "LC_maj", "LC_ds_binary", "B1", "VC", "B2", "B7"):
            ms = {s: float(np.mean([sc(r, m) for r in rows if r["system"] == s])) for s in SYSTEMS}
            kp = r2stats.kendall_pairwise(ms, truth)
            # bootstrap over sentences
            sids = sorted({r["sid"] for r in rows})
            rng = np.random.default_rng(0)
            taus = []
            byss = defaultdict(list)
            for r in rows:
                byss[r["sid"]].append(r)
            for _ in range(500):
                pick = [sids[i] for i in rng.integers(0, len(sids), len(sids))]
                rr = [x for sd in pick for x in byss[sd]]
                ms_b = {s: np.mean([sc(r, m) for r in rr if r["system"] == s]) for s in SYSTEMS}
                lr = [x for x in rr if (x["y_panel"] if lab == "panel" else x["y_solver"]) is not None]
                tr = {}
                for s in SYSTEMS:
                    q = [x for x in lr if x["system"] == s]
                    if q:
                        ww = [x["w_panel"] if lab == "panel" else 1.0 for x in q]
                        tr[s] = sum(w * (x["y_panel"] if lab == "panel" else x["y_solver"]) for w, x in zip(ww, q)) / sum(ww)
                t = r2stats.kendall_pairwise(ms_b, tr)["tau_b"]
                if t is not None:
                    taus.append(t)
            res[m] = {**kp, "tau_ci95": [float(np.percentile(taus, 2.5)), float(np.percentile(taus, 97.5))] if taus else None,
                      "metric_means": ms}
        sys_level[lab] = res
    A["system_level"] = sys_level
    # ---------------- complexity
    comp = {}
    for lab, R in (("panel", P), ("solver", S)):
        d = {}
        for t in ("bottom", "middle", "top"):
            d[f"tercile={t}"] = auc_block([r for r in R if r["tercile"] == t], ["DC", "B1", "LC_maj", "VC"], lab)
        for lo, hi, nm in ((0, 0, "0"), (1, 1, "1"), (2, 2, "2"), (3, 99, "3+")):
            d[f"n_conditions={nm}"] = auc_block([r for r in R if lo <= (r["n_conditions"] or 0) <= hi],
                                                ["DC", "B1", "LC_maj"], lab)
        # slope of (DC - B1) vs tercile
        tv = {"bottom": 0, "middle": 1, "top": 2}
        gaps = []
        for t in ("bottom", "middle", "top"):
            x = d[f"tercile={t}"]
            gaps.append((x.get("DC", {}).get("auc", np.nan) - x.get("B1", {}).get("auc", np.nan)))
        B = boot(R, n=500, seed=8)
        slopes = []
        y_all = np.array([r["y_panel"] if lab == "panel" else r["y_solver"] for r in R], float)
        w_all = np.array([r["w_panel"] for r in R], float) if lab == "panel" else None
        terc = np.array([tv[r["tercile"]] for r in R])
        sdc = np.array([sc(r, "DC") for r in R], float)
        sb1 = np.array([sc(r, "B1") for r in R], float)
        for idx in B:
            g = []
            for t in (0, 1, 2):
                j = idx[terc[idx] == t]
                ww = None if w_all is None else w_all[j]
                g.append(wauc(y_all[j], sdc[j], ww) - wauc(y_all[j], sb1[j], ww))
            if not any(np.isnan(g)):
                slopes.append(np.polyfit([0, 1, 2], g, 1)[0])
        d["gap_DC_minus_B1_by_tercile"] = gaps
        d["slope"] = {"point": float(np.polyfit([0, 1, 2], gaps, 1)[0]) if not any(np.isnan(gaps)) else None,
                      "ci95": [float(np.percentile(slopes, 2.5)), float(np.percentile(slopes, 97.5))] if slopes else None}
        comp[lab] = d
    A["complexity"] = comp
    # ---------------- shared bias: mode-wrong strata (solver label of the modal representative, panel if adjudicated)
    mode_rep_ok = {}
    by_sid = defaultdict(list)
    for r in rows:
        by_sid[r["sid"]].append(r)
    for sid, L in by_sid.items():
        mode_members = [r for r in L if r["dc_extra"].get("in_mode")]
        lab_p = [r["y_panel"] for r in mode_members if r["y_panel"] is not None]
        lab_s = [r["y_solver"] for r in mode_members if r["y_solver"] is not None]
        if lab_p:
            mode_rep_ok[sid] = float(np.mean(lab_p)) >= 0.5
        elif lab_s:
            mode_rep_ok[sid] = float(np.mean(lab_s)) >= 0.5
    sb = {}
    for lab, R in (("panel", P), ("solver", S)):
        sb[lab] = {"mode_right": auc_block([r for r in R if mode_rep_ok.get(r["sid"]) is True], ["DC", "B1", "LC_maj"], lab),
                   "mode_wrong": auc_block([r for r in R if mode_rep_ok.get(r["sid"]) is False], ["DC", "B1", "LC_maj"], lab),
                   "n_sent_mode_wrong": sum(1 for v in mode_rep_ok.values() if v is False),
                   "n_sent_mode_right": sum(1 for v in mode_rep_ok.values() if v is True)}
        for corp in ("proverqa", "malls", "folio"):
            sb[lab][f"corpus={corp}"] = auc_block([r for r in R if r["corpus"] == corp], ["DC", "B1"], lab)
    sb["panel"]["ambiguous_sentence"] = auc_block([r for r in P if r["sentence_ambiguous"]], ["DC", "B1"], "panel")
    sb["panel"]["unambiguous_sentence"] = auc_block([r for r in P if r["sentence_ambiguous"] is False], ["DC", "B1"], "panel")
    A["shared_bias"] = sb
    # ---------------- wrong-gold flag: gold (original) as a 10th peer
    from dc import canon as dcanon
    gold_c = {}
    for sid in groups:
        g = parse_fol(sents[sid]["gold_fol_original"])
        gold_c[sid] = dcanon(g) if g is not None else None
    jobs = [(gold_c[sid], c) for sid, g in groups.items() if gold_c[sid] for c in g.values() if c]
    run_pairs(jobs, workers=12, log=logger.info)
    cache = load_cache()
    gold_scores = {}
    for sid, g in groups.items():
        if not gold_c[sid]:
            continue
        g2 = {**g, "GOLD": gold_c[sid]}
        rel = group_relations(g2, cache, cfg)
        res = score_group({k: parse_fol(v) if v else None for k, v in g2.items()}, rel, {**W, "GOLD": 1.0}, cfg)
        gold_scores[sid] = res["GOLD"]["score"]
    yg, sg = [], []
    for sid, s in gold_scores.items():
        v = l0.get(sid, {}).get("gold_faithful_final")
        if v is not None:
            yg.append(1 - int(v))
            sg.append(1 - s)
    order = np.argsort(-np.array(sg), kind="mergesort")
    A["wrong_gold_flag"] = {"n": len(yg), "base_rate": float(np.mean(yg)), "AUROC_1_minus_DC_gold": wauc(yg, sg),
                            "precision_at_50": float(np.mean(np.array(yg)[order[:50]]))}
    logger.info(f"wrong-gold flag {A['wrong_gold_flag']}")
    # ---------------- coverage / timeouts / relation shares on fresh
    rels = Counter()
    ntri = nbad = 0
    size_bins = defaultdict(lambda: [0, 0])
    for sid, g in groups.items():
        rel = group_relations(g, cache, cfg)
        ok = [s for s, v in g.items() if v]
        for a, b in itertools.combinations(ok, 2):
            rels[rel[(a, b)]] += 1
            rec, _ = lookup(cache, g[a], g[b])
            na = n_atoms(parse_fol(g[a])) + n_atoms(parse_fol(g[b]))
            bn = "<=6" if na <= 6 else ("7-12" if na <= 12 else ("13-20" if na <= 20 else ">20"))
            size_bins[bn][0] += 1
            size_bins[bn][1] += bool(rec and rec.get("timed_out"))
        for a, b, c_ in itertools.permutations(ok, 3):
            if a < c_ and rel[(a, b)] == "EQUIV" and rel[(b, c_)] == "EQUIV":
                ntri += 1
                nbad += rel[(a, c_)] != "EQUIV"
    tot = sum(rels.values())
    A["coverage"] = {"relation_shares": {k: v / tot for k, v in rels.items()}, "n_pairs": tot,
                     "equiv_nontransitivity": nbad / max(1, ntri),
                     "timeouts_by_pair_size_atoms": {k: {"n": v[0], "timeout_share": v[1] / max(1, v[0])} for k, v in size_bins.items()},
                     "DC_coverage": float(np.mean([r["S"].get("DC__cov", False) for r in rows])),
                     "unparseable_greedy": sum(1 for r in rows if not r["parse_ok"]),
                     "unparseable_by_system": dict(Counter(r["system"] for r in rows if not r["parse_ok"])),
                     "coverage_by_metric": {m: float(np.mean([r["S"].get(m + "__cov", False) for r in rows]))
                                            for m in ("DC", "LC_maj", "LC_ds_binary", "VC", "B1", "B7")}}
    # ---------------- cost
    gen = read_jsonl(WORK / "fresh_frame.jsonl")
    per_out = float(np.mean([r["gen_usd"] or 0 for r in gen if r["fold"] == "fresh_greedy"]))
    dcsec = [x for r in rows for x in [r["S"].get("DC")] if x is not None]
    secs = [x["seconds"] for x in read_jsonl(RES / "scores.jsonl") if x["metric"] == "DC" and x["seconds"] is not None]
    b1 = read_jsonl(WORK / "b1_fresh.jsonl")
    A["cost"] = {"DC": {"usd_per_item_peers_exist": 0.0, "solver_seconds_per_item_mean": float(np.mean(secs)) if secs else None,
                        "solver_seconds_per_item_p95": float(np.percentile(secs, 95)) if secs else None,
                        "usd_per_item_peers_generated": per_out * 8,
                        "note": "peers generated = 8 extra greedy outputs at the measured mean generation cost"},
                 "B1": {"usd_per_item": float(np.mean([x["usd"] or 0 for x in b1]))},
                 "panel_label_usd_per_item": 0.8056 / 272, "gold_audit_usd_per_gold": 0.8761 / 450}
    # ---------------- invariance (solver-verified rewrites of 400 fresh parseable candidates)
    A["invariance"] = invariance(rows, groups, W, cfg)
    # ---------------- contamination (dev, $0)
    A["contamination_dev"] = contamination(cfg)
    # ---------------- frontier gap (dev anchor: B1plus scored on the 609 dev panel items in round 2)
    A["frontier_gap_dev"] = frontier_dev(cfg)
    (RES / "analysis.json").write_text(json.dumps(A, indent=1, default=str))
    logger.info("analysis written")


def invariance(rows, groups, W, cfg, n=400):
    import nltk
    from common import ROOT
    nltk.data.path.insert(0, str(ROOT / ".nltk_data"))
    from nltk.corpus import wordnet as wn
    from dc import canon as dcanon
    from rewrites import KINDS, rewrite
    from dc.relation import pair_relation
    from dc.align import align_pair
    from typing_jobs import run_typing
    rng = random.Random(20260924)
    cand = [r for r in rows if r["parse_ok"]]
    by_sys = defaultdict(list)
    for r in cand:
        by_sys[r["system"]].append(r)
    pick = []
    for s in SYSTEMS:
        rng.shuffle(by_sys[s])
        pick += by_sys[s][: n // len(SYSTEMS) + 1]
    pick = pick[:n]
    variants = []
    for r in pick:
        A0 = parse_fol(r["canon"])
        for k in KINDS:
            try:
                X = rewrite(A0, k, rng, wn)
            except (ValueError, KeyError, IndexError):
                X = None
            if X is None:
                continue
            xc = dcanon(X)
            if xc == r["canon"]:
                continue
            # verify meaning preservation: identity vocabulary for structural rewrites, L1 alignment for renames
            if k in ("SYN_RENAME", "RAND_RENAME"):
                ok = derive(align_pair(parse_fol(xc), A0), use_L3=False)["rel"] == "EQUIV"
            else:
                ok = pair_relation(parse_fol(xc), A0)["rel"] == "EQUIV"
            variants.append({"item_id": r["item_id"], "sid": r["sid"], "system": r["system"], "kind": k, "canon": xc,
                             "verified": ok, "orig_canon": r["canon"]})
    ver = [v for v in variants if v["verified"]]
    jobs = [(v["canon"], c) for v in ver for s, c in groups[v["sid"]].items() if c and s != v["system"]]
    run_pairs(jobs, workers=12, log=logger.info)
    cache = load_cache()
    base = {}
    for sid in {v["sid"] for v in ver}:
        g = groups[sid]
        rel = group_relations(g, cache, cfg)
        base[sid] = score_group({k: parse_fol(v) if v else None for k, v in g.items()}, rel, W, cfg)
    newres = []
    typing_jobs = []
    for i, v in enumerate(ver):
        g = dict(groups[v["sid"]])
        g[v["system"]] = v["canon"]
        rel = group_relations(g, cache, cfg)
        res = score_group({k: parse_fol(x) if x else None for k, x in g.items()}, rel, W, cfg)[v["system"]]
        old = base[v["sid"]][v["system"]]
        newres.append((v, old, res))
        if res.get("mode_rep") and not res.get("in_mode"):
            typing_jobs.append((f"new{i}", v["canon"], g[res["mode_rep"]]))
        if old.get("mode_rep") and not old.get("in_mode"):
            typing_jobs.append((f"old{i}", v["orig_canon"], groups[v["sid"]][old["mode_rep"]]))
    typ = run_typing(typing_jobs, use_L3=cfg.use_L3)
    key = "type_1b_on" if cfg.rule_1b else "type_1b_off"
    by_kind = defaultdict(lambda: {"n": 0, "false_alarm": 0, "score_change": 0, "mode_flip": 0, "type_change": 0})
    for i, (v, old, res) in enumerate(newres):
        t_old = "none" if old.get("in_mode") else typ.get(f"old{i}", {}).get(key)
        t_new = "none" if res.get("in_mode") else typ.get(f"new{i}", {}).get(key)
        dsc = abs(res["score"] - old["score"]) > 0.05
        flip = bool(res.get("in_mode")) != bool(old.get("in_mode"))
        tch = t_old != t_new
        b = by_kind[v["kind"]]
        b["n"] += 1
        b["score_change"] += dsc
        b["mode_flip"] += flip
        b["type_change"] += tch
        b["false_alarm"] += (dsc or flip or tch)
    for b in by_kind.values():
        for k2 in ("false_alarm", "score_change", "mode_flip", "type_change"):
            b[k2 + "_rate"] = b[k2] / max(1, b["n"])
    # VC contrast on the synonym-renamed subset
    from s05_fresh import vc_scores
    syn = [v for v in ver if v["kind"] == "SYN_RENAME"]
    vc_d = []
    for v in syn:
        g = {f"{v['sid']}:{s}": (c if c else None) for s, c in groups[v["sid"]].items()}
        k0 = f"{v['sid']}:{v['system']}"
        a = vc_scores({v["sid"]: g}).get(k0, (0.5, False))[0]
        g[k0] = v["canon"]
        b2 = vc_scores({v["sid"]: g}).get(k0, (0.5, False))[0]
        vc_d.append(abs(a - b2))
    return {"n_candidates": len(pick), "n_variants": len(variants), "n_verified": len(ver),
            "verified_share_by_kind": {k: sum(1 for v in variants if v["kind"] == k and v["verified"]) /
                                       max(1, sum(1 for v in variants if v["kind"] == k)) for k in KINDS},
            "DC_by_kind": dict(by_kind),
            "VC_synonym_rename": {"n": len(vc_d), "false_alarm_rate(|dVC|>0.05)": float(np.mean([d > 0.05 for d in vc_d])) if vc_d else None,
                                  "mean_abs_change": float(np.mean(vc_d)) if vc_d else None},
            "B1_synonym_rename": "not run (OpenRouter key exhausted)"}


def contamination(cfg):
    """DC on the 104 x 9 entity-renamed paraphrase candidates vs their originals (dev data, frozen config)."""
    rows = read_jsonl(WORK / "dev_frame.jsonl")
    cont = [r for r in rows if r["fold"] == "contamination"]
    orig = {r["item_id"]: r for r in rows if r["fold"] == "heldout_confirm"}
    groups_c = defaultdict(dict)
    for r in cont:
        groups_c[r["sid"]][r["system"]] = r["canon"]
    jobs = [(a, b) for g in groups_c.values() for a, b in itertools.combinations([c for c in g.values() if c], 2)]
    run_pairs(jobs, workers=12, log=logger.info)
    cache = load_cache()
    sc_c, _, _ = score_all(groups_c, cache, cfg, SYSTEMS)
    groups_o = defaultdict(dict)
    for r in cont:
        o = orig.get(r["original_item_id"])
        if o:
            groups_o[o["sid"]][o["system"]] = o["canon"]
    # score originals within their FULL dev group (as in the dev freeze)
    full = defaultdict(dict)
    for r in orig.values():
        if r["sid"] in groups_o:
            full[r["sid"]][r["system"]] = r["canon"]
    sc_o, _, _ = score_all(full, cache, cfg, SYSTEMS)
    d, yo, so, yp, sp_ = [], [], [], [], []
    for r in cont:
        o = orig.get(r["original_item_id"])
        if not o:
            continue
        a = sc_o[(o["sid"], o["system"])]["score"]
        b = sc_c[(r["sid"], r["system"])]["score"]
        d.append(a - b)
        lab = {"faithful": 1, "unfaithful": 0}.get(r["output"])
        if lab is not None:
            yo.append(lab); so.append(a); yp.append(lab); sp_.append(b)
    rng = np.random.default_rng(0)
    bs = [np.mean(rng.choice(d, len(d))) for _ in range(2000)]
    return {"n": len(d), "mean_delta_orig_minus_para": float(np.mean(d)),
            "ci95": [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))],
            "AUROC_orig": wauc(yo, so), "AUROC_para": wauc(yp, sp_), "judge_B1_delta_round2": 0.096}


def frontier_dev(cfg):
    rows = read_jsonl(WORK / "dev_frame.jsonl")
    G = [r for r in rows if r["fold"] == "heldout_confirm"]
    base = json.loads((WORK / "dev_baselines.json").read_text())
    groups = defaultdict(dict)
    for r in G:
        groups[r["sid"]][r["system"]] = r["canon"]
    sc_, _, _ = score_all(groups, load_cache(), cfg, SYSTEMS)
    P = [r for r in G if r["y_panel"] is not None and "B1plus" in base.get(r["item_id"], {})]
    y = np.array([r["y_panel"] for r in P], int)
    w = np.array([r["w_panel"] for r in P], float)
    X = np.array([[base[r["item_id"]].get("B1", [0.5])[0], base[r["item_id"]].get("B2", [0.5])[0],
                   sc_[(r["sid"], r["system"])]["score"]] for r in P], float)
    oof = r2stats.oof_stack(X, y, np.array([r["sid"] for r in P]), w)
    return {"n": len(P), "stack_B1_B2_DC_oof": wauc(y, oof, w),
            "B1plus": wauc(y, [base[r["item_id"]]["B1plus"][0] for r in P], w),
            "B1": wauc(y, [base[r["item_id"]]["B1"][0] for r in P], w),
            "note": "dev anchor only (B1plus not run on fresh: key exhausted); the dev set also fixed DC's config"}


if __name__ == "__main__":
    main()
