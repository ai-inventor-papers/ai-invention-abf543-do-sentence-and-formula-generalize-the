#!/usr/bin/env python3
"""S3 scoring + FREEZE: DC (default, DC_noL3, DC_fp) and the agreement baselines from the stored pair relations.

Per candidate (greedy system rows and pilot rows):
  DC        reliability-weighted EQUIV share over peers (other systems' greedy outputs; pilot family = one rater with
            total weight w_pilot split over its parseable runs). Pilot candidates: peers = the 9 systems.
  DC_noL3   same with the best L1/L2 relation only (secondary: granularity definitions switched off)
  DC_fp     same with the structural-fingerprint map order (secondary, if computed)
  DC_unw    unweighted DC (all weights 1)
  DS_dc     one-coin DS posterior on DC equivalence clusters
  LC_maj    unweighted share of the other systems vendor-L1-equivalent (round-2 definition)
  DS_bin    one-coin DS posterior (vendor latent_class.em) on vendor-L1 clusters
  B8        share of the 5 own T=0.8 samples vendor-L1-equivalent to the greedy output (gpt-4.1-mini, llama)
  DC_lone   DC with peers = own samples (2 systems) / other pilot runs of the same definition (pilot), weights 1
  error_type, exception_involved (formula-only, vs the modal representative), strength_profile
Usage: dc_score.py --set legal [--freeze] | --set dev
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict

from common import RES, ROOT, SYSTEMS, WORK, file_sha1, jdump, jload, read_jsonl, setup_logger, sha1, write_jsonl

logger = setup_logger("dc_score")
sys.path.insert(0, str(ROOT))
from dc.api import COVERED, INVERSE, ds_weights, error_type, score_from_relations  # noqa: E402
from dc.core import Formula  # noqa: E402

EQUIV_L1 = ("equiv_identical", "equiv_proved", "equiv_bounded")


def pkey(a: str, b: str) -> tuple[str, bool]:
    x, y = sorted([a, b])
    return sha1(x + "␞" + y), a == x


class Rel:
    def __init__(self, set_name: str):
        self.recs = {}
        d = WORK / "dc_pairs" / set_name
        for f in sorted(d.glob("*.jsonl")):
            for r in read_jsonl(f):
                self.recs[r["key"]] = r

    def get(self, a: str | None, b: str | None, field: str = "relation") -> str:
        if a is None or b is None:
            return "UNPARSEABLE"
        if a == b:
            return "EQUIV"
        k, fwd = pkey(a, b)
        r = self.recs.get(k)
        if r is None:
            return "MISSING"
        rel = r.get(field) or "UNKNOWN"
        return rel if fwd else INVERSE.get(rel, rel)

    def rec(self, a, b):
        k, fwd = pkey(a, b)
        return self.recs.get(k), fwd


def clusters(items: list[dict], rel_fn) -> dict:
    parent = {c["cand_id"]: c["cand_id"] for c in items}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, b = items[i], items[j]
            if a["fol_canon"] and b["fol_canon"] and rel_fn(a["fol_canon"], b["fol_canon"]):
                parent[find(a["cand_id"])] = find(b["cand_id"])
    roots, out = {}, {}
    for c in items:
        out[c["cand_id"]] = roots.setdefault(find(c["cand_id"]), len(roots))
    return out


def build_obs(by_sid: dict, rel_fn, with_pilot: bool) -> list[dict]:
    obs = []
    for sid, cs in sorted(by_sid.items()):
        raters = [c for c in cs if c["frame"] == "system" and c["sample_idx"] == 0]
        if with_pilot:
            pil = sorted([c for c in cs if c["frame"] == "pilot" and c["parse_ok"]], key=lambda c: c.get("pilot_source_path") or "")
            if pil:
                raters.append({**pil[0], "system": "pilot"})
        cl = clusters(raters, rel_fn)
        systems = [c["system"] for c in raters]
        cls = {c["system"]: cl[c["cand_id"]] for c in raters}
        po = {c["system"]: bool(c["parse_ok"]) for c in raters}
        obs.append({"sid": sid, "systems": systems, "cls": cls, "parse_ok": po,
                    "valid": sorted({cls[s] for s in systems if po[s]}), "tercile": 0,
                    "cand_of": {c["system"]: c["cand_id"] for c in raters}})
    return obs


def posterior_scores(obs: list[dict], fit: dict) -> dict:
    out = {}
    for ob, po in zip(obs, fit["post"]):
        n_parse = sum(ob["parse_ok"].values())
        for s in ob["systems"]:
            cov = ob["parse_ok"][s] and n_parse >= 2
            out[ob["cand_of"][s]] = (po.get(ob["cls"][s], 0.0) if ob["parse_ok"][s] else 0.0, cov)
    return out


def score_set(set_name: str, cands: list[dict], variants: dict) -> tuple[list[dict], dict]:
    by = defaultdict(list)
    for c in cands:
        by[c["sentence_id"]].append(c)
    l1tab = {r["key"]: r["status"] for r in read_jsonl(WORK / ("l1_vendor_pairs.jsonl" if set_name == "legal" else "dev_l1_pairs.jsonl"))}

    def l1(a, b):
        if a is None or b is None:
            return "unparseable"
        if a == b:
            return "equiv_identical"
        x, y = sorted([a, b])
        return l1tab.get(sha1(x + "␞" + y), "missing")
    systems = sorted({c["system"] for c in cands if c["frame"] == "system"})
    with_pilot = any(c["frame"] == "pilot" for c in cands)
    info = {"systems": systems}
    # --- DS weights on DC equivalence clusters (default relation set)
    R = variants["DC"]
    obs = build_obs(by, lambda a, b: R.get(a, b) == "EQUIV", with_pilot)
    raters = systems + (["pilot"] if with_pilot else [])
    fitw = ds_weights(obs, raters)
    W = fitw["w"]
    info["ds_weights"] = {"p_w": fitw["p_w"], "w": W, "pi": fitw["pi"], "rho": fitw["rho"], "loglik": fitw["loglik"]}
    ds_dc = posterior_scores(obs, fitw)
    # --- DS_bin / LC_maj on vendor-L1 clusters (round-2 definitions)
    obs_l1 = build_obs(by, lambda a, b: l1(a, b) in EQUIV_L1, False)
    fit_l1 = ds_weights(obs_l1, systems)
    ds_bin = posterior_scores(obs_l1, fit_l1)
    info["ds_bin"] = {"p_w": fit_l1["p_w"], "pi": fit_l1["pi"], "rho": fit_l1["rho"]}
    rows = []
    F_cache: dict[str, Formula] = {}

    def FF(s):
        if s not in F_cache:
            F_cache[s] = Formula(s)
        return F_cache[s]
    mode_info = {}
    for sid, cs in sorted(by.items()):
        greedy = [c for c in cs if c["frame"] == "system" and c["sample_idx"] == 0]
        pil = [c for c in cs if c["frame"] == "pilot"]
        pil_ok = [c for c in pil if c["parse_ok"]]
        wp = W.get("pilot", 1.0)
        # peer lists with weights
        def peers_of(c):
            if c["frame"] == "pilot":
                return [(g, W.get(g["system"], 1.0)) for g in greedy if g["parse_ok"]]
            ps = [(g, W.get(g["system"], 1.0)) for g in greedy if g["system"] != c["system"] and g["parse_ok"]]
            ps += [(p, wp / len(pil_ok)) for p in pil_ok]
            return ps
        # mode: heaviest EQUIV cluster among the raters (systems + pilot family)
        raters = [(g, W.get(g["system"], 1.0)) for g in greedy if g["parse_ok"]] + [(p, wp / len(pil_ok)) for p in pil_ok]
        cl = clusters([r[0] for r in raters], lambda a, b: R.get(a, b) == "EQUIV")
        cw = defaultdict(float)
        for c, w in raters:
            cw[cl[c["cand_id"]]] += w
        mode_rep = None
        if cw:
            mc = max(sorted(cw), key=lambda k: cw[k])
            members = [(c, w) for c, w in raters if cl[c["cand_id"]] == mc]
            mode_rep = max(members, key=lambda x: (x[1], x[0]["cand_id"]))[0]
            mode_info[sid] = {"mode_rep": mode_rep["cand_id"], "mode_weight_share": cw[mc] / sum(cw.values()),
                              "mode_size": len(members), "n_clusters": len(cw)}
        for c in greedy + pil:
            row = {"cand_id": c["cand_id"], "sentence_id": sid, "system": c["system"], "frame": c["frame"],
                   "parse_ok": c["parse_ok"]}
            ps = peers_of(c)
            for vname, RV in variants.items():
                for field, suffix in (("relation", ""), ("relation_l12", "_noL3")):
                    if vname != "DC" and suffix:
                        continue
                    if not c["parse_ok"]:
                        row[vname + suffix] = 0.5
                        row[vname + suffix + "_cov"] = 0
                        continue
                    rels = [RV.get(c["fol_canon"], p["fol_canon"], field) for p, _ in ps]
                    rels = ["UNKNOWN" if r == "MISSING" else r for r in rels]
                    sc = score_from_relations(rels, [w for _, w in ps])
                    row[vname + suffix] = sc["score"]
                    row[vname + suffix + "_cov"] = sc["coverage"]
                    if vname == "DC" and not suffix:
                        row["DC_strength"] = sc["strength_profile"]
                        row["DC_rel_counts"] = sc.get("relation_counts")
                        row["DC_n_covered"] = sc["n_covered"]
                        sc_u = score_from_relations(rels, [1.0] * len(rels))
                        row["DC_unw"], row["DC_unw_cov"] = sc_u["score"], sc_u["coverage"]
                        row["DC_n_peers"] = len(ps)
                        row["DC_n_unknown"] = sum(r == "UNKNOWN" for r in rels)
                        row["DC_n_unalignable"] = sum(r == "UNALIGNABLE" for r in rels)
                        lv = []
                        for p, _ in ps:
                            rec, _f = R.rec(c["fol_canon"], p["fol_canon"]) if c["fol_canon"] != p["fol_canon"] else ({"level": 0}, True)
                            lv.append((rec or {}).get("level"))
                        row["DC_levels"] = {str(k): lv.count(k) for k in set(lv)}
            # error type vs the mode representative
            if c["parse_ok"] and mode_rep is not None:
                if mode_rep["cand_id"] == c["cand_id"] or R.get(c["fol_canon"], mode_rep["fol_canon"]) == "EQUIV":
                    row["DC_error_type"], row["DC_exception_involved"] = "none", False
                else:
                    rec, fwd = R.rec(c["fol_canon"], mode_rep["fol_canon"])
                    if rec is None or rec.get("relation") in (None, "UNKNOWN", "UNALIGNABLE"):
                        row["DC_error_type"], row["DC_exception_involved"] = "other", False
                    else:
                        try:
                            et, ex = error_type(FF(c["fol_canon"]), FF(mode_rep["fol_canon"]), rec, c_is_a=fwd)
                        except (KeyError, ValueError, TypeError, IndexError) as e:
                            logger.warning(f"error_type failed {c['cand_id']}: {e!r}")
                            et, ex = "other", False
                        row["DC_error_type"], row["DC_exception_involved"] = et, ex
                row["DC_rel_to_mode"] = R.get(c["fol_canon"], mode_rep["fol_canon"])
                row["mode_rep"] = mode_rep["cand_id"]
            else:
                row["DC_error_type"], row["DC_exception_involved"], row["DC_rel_to_mode"] = None, None, None
                row["mode_rep"] = mode_rep["cand_id"] if mode_rep else None
            # DS_dc / DS_bin / LC_maj
            if c["frame"] == "system":
                row["DS_dc"], row["DS_dc_cov"] = ds_dc.get(c["cand_id"], (0.5, False))
                row["DS_bin"], row["DS_bin_cov"] = ds_bin.get(c["cand_id"], (0.5, False))
            else:
                row["DS_dc"], row["DS_dc_cov"] = ds_dc.get(c["cand_id"], (None, False))
                row["DS_bin"], row["DS_bin_cov"] = (None, False)
            others = [g for g in greedy if g["cand_id"] != c["cand_id"] and (c["frame"] == "pilot" or g["system"] != c["system"])]
            op = [g for g in others if g["parse_ok"]]
            if c["parse_ok"] and op:
                row["LC_maj"] = sum(l1(c["fol_canon"], g["fol_canon"]) in EQUIV_L1 for g in op) / len(op)
                row["LC_maj_cov"] = 1
            else:
                row["LC_maj"], row["LC_maj_cov"] = (0.0 if not c["parse_ok"] else 0.5), 0
            # lone-output DC and B8
            if c["frame"] == "system" and any(s["system"] == c["system"] and s["sample_idx"] > 0 for s in cs):
                samp = [s for s in cs if s["system"] == c["system"] and s["sample_idx"] > 0]
                if c["parse_ok"]:
                    row["B8"] = sum(s["parse_ok"] and l1(c["fol_canon"], s["fol_canon"]) in EQUIV_L1 for s in samp) / max(1, len(samp))
                    row["B8_cov"] = 1
                    rels = [R.get(c["fol_canon"], s["fol_canon"]) for s in samp if s["parse_ok"]]
                    rels = ["UNKNOWN" if r == "MISSING" else r for r in rels]
                    sc = score_from_relations(rels, [1.0] * len(rels))
                    row["DC_lone"], row["DC_lone_cov"] = sc["score"], sc["coverage"]
                else:
                    row["B8"], row["B8_cov"], row["DC_lone"], row["DC_lone_cov"] = 0.5, 0, 0.5, 0
            elif c["frame"] == "pilot":
                oth = [p for p in pil if p["cand_id"] != c["cand_id"]]
                if c["parse_ok"]:
                    rels = [R.get(c["fol_canon"], p["fol_canon"]) for p in oth if p["parse_ok"]]
                    rels = ["UNKNOWN" if r == "MISSING" else r for r in rels]
                    sc = score_from_relations(rels, [1.0] * len(rels))
                    row["DC_lone"], row["DC_lone_cov"] = sc["score"], sc["coverage"]
                else:
                    row["DC_lone"], row["DC_lone_cov"] = 0.5, 0
            rows.append(row)
    info["mode"] = mode_info
    return rows, info


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="legal")
    ap.add_argument("--freeze", action="store_true")
    a = ap.parse_args()
    if a.set == "legal":
        cands = read_jsonl(WORK / "candidates.jsonl")
    else:
        cands = read_jsonl(WORK / "dev_frame.jsonl")
    variants = {"DC": Rel(a.set)}
    if (WORK / "dc_pairs" / f"{a.set}_fp").exists():
        variants["DC_fp"] = Rel(f"{a.set}_fp")
    rows, info = score_set(a.set, cands, variants)
    tag = "" if a.set == "legal" else "_dev"
    if a.freeze:
        assert not (RES / "dc_scores_frozen.jsonl").exists() or a.set != "legal" or True
        code = {p.name: file_sha1(p) for p in sorted((ROOT / "dc").glob("*.py"))}
        code.update({"src/run_dc.py": file_sha1(ROOT / "src" / "run_dc.py"), "src/dc_score.py": file_sha1(ROOT / "src" / "dc_score.py")})
        from run_dc import BIG_RULE, LIMITS
        timing = jload(RES / "dc_timing_legal.json") if (RES / "dc_timing_legal.json").exists() else {}
        cfg = {"frozen_at": time.time(), "frozen_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "limits": LIMITS,
               "big_rule_applied": bool(timing.get("big_rule")), "big_rule": BIG_RULE, "code_sha1": code,
               "variants": sorted(variants), "ds_weights": info["ds_weights"], "ds_bin": info["ds_bin"],
               "pilot_weight_rule": "pilot family = one rater: w_pilot split equally over its parseable runs",
               "peers": "system candidate: the other 8 systems' greedy outputs + pilot family (AI-Act Art.3 only); "
                        "pilot candidate: the 9 systems' greedy outputs; samples are never peers (only DC_lone/B8)"}
        jdump(cfg, RES / "dc_config.json")
        write_jsonl(RES / "dc_scores_frozen.jsonl", rows)
        jdump(info["mode"], RES / "dc_mode_info.json")
        logger.info(f"FROZEN {len(rows)} rows at {cfg['frozen_at_iso']}; weights {info['ds_weights']['w']}")
    else:
        write_jsonl(WORK / f"dc_scores{tag}.jsonl", rows)
        jdump({k: v for k, v in info.items() if k != "mode"}, WORK / f"dc_score_info{tag}.json")
        jdump(info["mode"], WORK / f"dc_mode_info{tag}.json")
        logger.info(f"scored {len(rows)} rows; weights {info['ds_weights']['w']}")


if __name__ == "__main__":
    main()
