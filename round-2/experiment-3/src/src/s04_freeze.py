#!/usr/bin/env python3
"""STEP 4: DEV grid (12 configs) -> select -> FREEZE with a sha256 receipt. Uses dev labels ONLY.

Grid: caps x1: L3 {on, off} x UNALIGNABLE {in, out of denominator} x weights {DS, uniform} (8)
      caps x0.5: L3 on x UNALIGN {in, out} x weights {DS, uniform} (4)
Selection: argmax mean(AUROC_P, AUROC_S) over the 700 dev sentences (609 panel items, weighted; audited-solver
rows unweighted). Ties within 0.005 -> the simpler config (L3 off > on, uniform > DS, caps x0.5 > x1, UA in > out).
Also fixed here (and only here): typing rule 1b on/off by dev weighted top-1 on panel-unfaithful items.
Diagnostics: default-config anchor, component ladder, L1 reproduction of round-2 pairs_cache 'equiv', EQUIV
non-transitivity, EQUIV-only-by-L2/L3 share, 20 L3-EQUIV pairs for inspection, T4 dev anchor (DC_self vs B8).
"""
from __future__ import annotations

import datetime
import hashlib
import itertools
import json
from collections import Counter, defaultdict

import numpy as np
from loguru import logger

from common import R2, RES, ROOT, SAMPLE_SYSTEMS, SYSTEMS, WORK, read_jsonl, setup_logging, sha1
from dc.align import derive
from dc.consensus import DCConfig
from dcscore import group_relations, ladder_scores, r2stats, score_all
from pairs import load_cache, lookup
from typing_jobs import run_typing

wauc = r2stats.wauc


def grid() -> list[DCConfig]:
    out = []
    for L3, ua, w in itertools.product((True, False), (True, False), ("DS", "uniform")):
        out.append(DCConfig(use_L3=L3, unalign_in_denominator=ua, weights=w, half_caps=False))
    for ua, w in itertools.product((True, False), ("DS", "uniform")):
        out.append(DCConfig(use_L3=True, unalign_in_denominator=ua, weights=w, half_caps=True))
    return out


def simplicity(c: DCConfig) -> tuple:
    return (int(not c.use_L3), int(c.weights == "uniform"), int(c.half_caps), int(c.unalign_in_denominator))


def dc_tree_hash() -> str:
    h = hashlib.sha256()
    for p in sorted((ROOT / "dc").glob("*.py")):
        h.update(p.name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def evaluate(G, sc) -> dict:
    P = [r for r in G if r["y_panel"] is not None]
    S = [r for r in G if r["y_solver"] is not None]
    ap = wauc([r["y_panel"] for r in P], [sc[(r["sid"], r["system"])]["score"] for r in P], [r["w_panel"] for r in P])
    as_ = wauc([r["y_solver"] for r in S], [sc[(r["sid"], r["system"])]["score"] for r in S])
    cov = float(np.mean([sc[(r["sid"], r["system"])]["covered"] for r in G]))
    return {"AUROC_P": ap, "AUROC_S": as_, "mean": (ap + as_) / 2, "coverage": cov, "n_P": len(P), "n_S": len(S)}


@logger.catch(reraise=True)
def main() -> None:
    setup_logging("s04_freeze")
    if (RES / "frozen_config.json").exists():
        raise SystemExit("already frozen: refusing to re-freeze (delete results/frozen_config.* only to restart dev)")
    rows = read_jsonl(WORK / "dev_frame.jsonl")
    G = [r for r in rows if r["fold"] == "heldout_confirm"]
    groups = defaultdict(dict)
    for r in G:
        groups[r["sid"]][r["system"]] = r["canon"]
    cache = load_cache()
    logger.info(f"dev greedy {len(G)} sentences {len(groups)} cache {len(cache)}")
    table = []
    scores_by_cfg = {}
    for cfg in grid():
        sc, w, info = score_all(groups, cache, cfg, SYSTEMS)
        ev = evaluate(G, sc)
        table.append({"config": cfg.name(), **cfg.as_dict(), **ev, "weights": w,
                      "weight_p": info.get("p")})
        scores_by_cfg[cfg.name()] = (cfg, sc, w)
        logger.info(f"{cfg.name():32s} P {ev['AUROC_P']:.4f} S {ev['AUROC_S']:.4f} mean {ev['mean']:.4f} cov {ev['coverage']:.3f}")
    best_mean = max(t["mean"] for t in table)
    tied = [t for t in table if t["mean"] >= best_mean - 0.005]
    cfgs = {c.name(): c for c in grid()}
    sel = max(tied, key=lambda t: (simplicity(cfgs[t["config"]]), t["mean"]))
    cfg = cfgs[sel["config"]]
    logger.info(f"SELECTED {cfg.name()} (best mean {best_mean:.4f}; tied {[t['config'] for t in tied]})")
    _, sc_sel, w_sel = scores_by_cfg[cfg.name()]
    # ---------------- typing rule 1b decision on dev panel-unfaithful items
    P_unf = [r for r in G if r["y_panel"] == 0 and r["parse_ok"]]
    jobs = []
    for r in P_unf:
        res = sc_sel[(r["sid"], r["system"])]
        rep = res.get("mode_rep")
        if rep and not res.get("in_mode"):
            jobs.append((r["item_id"], r["canon"], groups[r["sid"]][rep]))
    typ = run_typing(jobs, use_L3=cfg.use_L3)

    def top1(key):
        num = den = 0.0
        for r in P_unf:
            res = sc_sel[(r["sid"], r["system"])]
            t = "none" if res.get("in_mode") else typ.get(r["item_id"], {}).get(key, "other")
            num += r["w_panel"] * (t == r["L3_primary_error"])
            den += r["w_panel"]
        return num / den if den else None
    t_on, t_off = top1("type_1b_on"), top1("type_1b_off")
    rule_1b = bool(t_on is not None and t_off is not None and t_on > t_off)
    type_dist = Counter(v["type_1b_on" if rule_1b else "type_1b_off"] for v in typ.values())
    share_other = type_dist.get("other", 0) / max(1, sum(type_dist.values()))
    logger.info(f"typing dev top1: 1b on {t_on}, off {t_off} -> rule_1b={rule_1b}; dist {dict(type_dist)}; other {share_other:.2f}")
    cfg = DCConfig(use_L3=cfg.use_L3, unalign_in_denominator=cfg.unalign_in_denominator, weights=cfg.weights,
                   half_caps=cfg.half_caps, rule_1b=rule_1b)
    # ---------------- diagnostics
    diag = {}
    default = DCConfig()
    diag["default_config_anchor"] = next(t for t in table if t["config"] == default.name())
    # ladder
    lad = ladder_scores(groups, cache)
    base = json.loads((WORK / "dev_baselines.json").read_text())
    P = [r for r in G if r["y_panel"] is not None]
    S = [r for r in G if r["y_solver"] is not None]

    def auc_pair(getter):
        return {"AUROC_P": wauc([r["y_panel"] for r in P], [getter(r) for r in P], [r["w_panel"] for r in P]),
                "AUROC_S": wauc([r["y_solver"] for r in S], [getter(r) for r in S])}
    ladder = {"LC_maj(round2)": auc_pair(lambda r: base.get(r["item_id"], {}).get("LC_maj", [0.5])[0]),
              "LC_ds_binary(round2)": auc_pair(lambda r: base.get(r["item_id"], {}).get("LC_ds_binary", [0.5])[0])}
    for name in ("L1_uniform", "L12_uniform", "L123_uniform"):
        ladder[name] = auc_pair(lambda r, name=name: lad[name][(r["sid"], r["system"])][0])
    for nm in (DCConfig(use_L3=False, weights="DS").name(), DCConfig(use_L3=True, weights="DS").name(), cfg.name()):
        c2, sc2, _ = scores_by_cfg[nm]
        ladder["DC:" + nm] = auc_pair(lambda r, sc2=sc2: sc2[(r["sid"], r["system"])]["score"])
    # DC+SP (oof stack on dev, secondary)
    X = np.array([[sc_sel[(r["sid"], r["system"])][k] if sc_sel[(r["sid"], r["system"])].get(k) is not None else 0.0
                   for k in ("score", "sp_net", "sp_incomparable", "sp_contradictory")] for r in P])
    yP = np.array([r["y_panel"] for r in P])
    oof = r2stats.oof_stack(X, yP, np.array([r["sid"] for r in P]), np.array([r["w_panel"] for r in P]))
    ladder["DC+SP(oof,panel)"] = {"AUROC_P": wauc(yP, oof, [r["w_panel"] for r in P])}
    # cross-implementation: L1_uniform vs round-2 LC_maj
    a = [lad["L1_uniform"][(r["sid"], r["system"])][0] for r in G if "LC_maj" in base.get(r["item_id"], {})]
    b = [base[r["item_id"]]["LC_maj"][0] for r in G if "LC_maj" in base.get(r["item_id"], {})]
    diag["L1_uniform_vs_round2_LC_maj"] = {"pearson": float(np.corrcoef(a, b)[0, 1]),
                                           "share_abs_diff_lt_0.01": float(np.mean(np.abs(np.array(a) - np.array(b)) < 0.01))}
    # L1 reproduction of round-2 pairs_cache 'equiv' verdicts
    from fol_parse import parse as vparse, to_str
    r2c = {}
    with open(R2 / "work" / "pairs_cache.jsonl", encoding="utf-8") as f:
        for line in f:
            x = json.loads(line)
            r2c[x["k"]] = x.get("bij")
    n_eq = n_rep = 0
    by_sid = defaultdict(dict)
    for r in G:
        by_sid[r["sid"]][r["system"]] = r
    for sid, d in by_sid.items():
        systems = sorted(d)
        for i, j in itertools.combinations(range(len(systems)), 2):
            ra, rb = d[systems[i]], d[systems[j]]
            if not (ra["parse_ok"] and rb["parse_ok"]):
                continue
            pa, pb = vparse(ra["cand"]), vparse(rb["cand"])
            sa = to_str(pa.ast) if pa.ok else ra["cand"]
            sb = to_str(pb.ast) if pb.ok else rb["cand"]
            k = hashlib.sha1((sa + "||" + sb).encode("utf-8")).hexdigest()
            if r2c.get(k) == "equiv":
                n_eq += 1
                rec, fl = lookup(cache, ra["canon"], rb["canon"])
                n_rep += bool(rec and rec.get("L1") and rec["L1"]["rel"] == "EQUIV")
    diag["L1_reproduces_round2_equiv"] = {"n_round2_equiv": n_eq, "n_reproduced": n_rep, "share": n_rep / max(1, n_eq)}
    # non-transitivity + EQUIV-only-by-L2/L3 per config
    for t in table:
        c2 = cfgs[t["config"]]
        n_tri = n_bad = 0
        n_pairs = n_eq_l23 = n_eq_all = 0
        for sid, g in groups.items():
            rel = group_relations(g, cache, c2)
            ok = [s for s, c in g.items() if c is not None]
            for a_, b_, c_ in itertools.permutations(ok, 3):
                if a_ < c_ and rel.get((a_, b_)) == "EQUIV" and rel.get((b_, c_)) == "EQUIV":
                    n_tri += 1
                    n_bad += rel.get((a_, c_)) != "EQUIV"
            for a_, b_ in itertools.combinations(ok, 2):
                rec, fl = lookup(cache, g[a_], g[b_])
                if rec is None or rec.get("error"):
                    continue
                n_pairs += 1
                d_ = derive(rec, use_L3=c2.use_L3, half_caps=c2.half_caps)
                if d_["rel"] == "EQUIV":
                    n_eq_all += 1
                    n_eq_l23 += (d_["lvl"] or 1) > 1
        t["nontransitivity"] = n_bad / max(1, n_tri)
        t["share_pairs_equiv_only_L2L3"] = n_eq_l23 / max(1, n_pairs)
        t["share_equiv_from_L2L3"] = n_eq_l23 / max(1, n_eq_all)
    # 20 L3-EQUIV samples for hand inspection
    l3 = [(k, r) for k, r in cache.items() if r.get("L3") and r["L3"].get("rel") == "EQUIV"]
    strings = {}
    for r in G:
        if r["canon"]:
            strings.setdefault(r["canon"], r["sentence"])
    inv = {}
    for sid, g in groups.items():
        for a_, b_ in itertools.combinations([c for c in g.values() if c], 2):
            k, x, y = __import__("pairs").pkey(a_, b_)
            inv[k] = (x, y, next(iter([r["sentence"] for r in G if r["sid"] == sid])))
    samp = []
    for k, r in l3[:400]:
        if k in inv:
            x, y, s = inv[k]
            samp.append({"sentence": s, "a": x, "b": y, "via_def": r["L3"].get("via_def"),
                         "L1": (r.get("L1") or {}).get("rel"), "L2": (r.get("L2") or {}).get("rel")})
        if len(samp) >= 20:
            break
    (RES / "dev_L3_equiv_samples.json").write_text(json.dumps(samp, ensure_ascii=False, indent=1))
    # T4 dev anchor: DC_self (peers = own 5 samples, uniform) vs B8, both labels
    t4 = {}
    within = read_jsonl(WORK / "dev_frame.jsonl")
    samples = defaultdict(dict)
    for r in within:
        if r["fold"] == "heldout_samples":
            samples[(r["sid"], r["system"])][f"s{r['sample_idx']}"] = r["canon"]
    for sysn in SAMPLE_SYSTEMS:
        gself = {}
        for r in G:
            if r["system"] == sysn:
                gself[r["sid"]] = {"greedy": r["canon"], **samples.get((r["sid"], sysn), {})}
        sc_self, _, _ = score_all(gself, cache, DCConfig(use_L3=cfg.use_L3, unalign_in_denominator=cfg.unalign_in_denominator,
                                                          weights="uniform", half_caps=cfg.half_caps),
                                  ["greedy", "s1", "s2", "s3", "s4", "s5"])
        rows_s = [r for r in G if r["system"] == sysn]
        Ps = [r for r in rows_s if r["y_panel"] is not None]
        Ss = [r for r in rows_s if r["y_solver"] is not None]
        get = lambda r: sc_self[(r["sid"], "greedy")]["score"]  # noqa: E731
        getb8 = lambda r: base.get(r["item_id"], {}).get("B8", [0.5])[0]  # noqa: E731
        t4[sysn] = {"n_P": len(Ps), "n_S": len(Ss),
                    "DC_self_P": wauc([r["y_panel"] for r in Ps], [get(r) for r in Ps], [r["w_panel"] for r in Ps]),
                    "B8_P": wauc([r["y_panel"] for r in Ps], [getb8(r) for r in Ps], [r["w_panel"] for r in Ps]),
                    "DC_self_S": wauc([r["y_solver"] for r in Ss], [get(r) for r in Ss]),
                    "B8_S": wauc([r["y_solver"] for r in Ss], [getb8(r) for r in Ss])}
    diag["T4_dev_anchor"] = t4
    # ---------------- freeze
    frozen = {"config": cfg.as_dict(), "config_name": cfg.name(),
              "typing_rules": {"rule_1b": rule_1b, "dev_top1_1b_on": t_on, "dev_top1_1b_off": t_off,
                               "dev_type_distribution": dict(type_dist), "dev_share_other": share_other,
                               "n_typed_dev": len(typ), "order": "1,1b,2,3,4,5,6,7 (see dc/errtype.py)"},
              "dc_code_sha256": dc_tree_hash(),
              "selection_rule": "argmax mean(AUROC_P, AUROC_S); ties within 0.005 -> simpler (L3 off > on, uniform > DS, caps x0.5 > x1, UA in > out)",
              "grid": [{k: v for k, v in t.items() if k not in ("weights", "weight_p")} | {"weights": t["weights"]} for t in table],
              "dev_weights_selected": w_sel,
              "arbiter": {"mixing_weight": 0.5, "status": "pre-registered; see README (DC+arb)"},
              "ladder_dev": ladder, "diagnostics": diag,
              "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    txt = json.dumps(frozen, indent=1, default=str).encode()
    (RES / "frozen_config.json").write_bytes(txt)
    (RES / "frozen_config.sha256").write_text(hashlib.sha256(txt).hexdigest() + "  frozen_config.json\n")
    logger.info(f"FROZEN {cfg.name()} rule_1b={rule_1b} sha256={hashlib.sha256(txt).hexdigest()}")
    logger.info(json.dumps({"ladder": ladder, "diag": diag}, default=str)[:3000])


if __name__ == "__main__":
    main()
