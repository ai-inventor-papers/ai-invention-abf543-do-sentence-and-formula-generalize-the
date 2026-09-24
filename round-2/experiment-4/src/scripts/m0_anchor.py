#!/usr/bin/env python3
"""M0 dev anchor + freeze. Weighted AUROC on the 609 panel items (L3_sampling_weight) and unweighted AUROC on all
solver/final-labelled rows, 2,000-draw sentence bootstrap stratified by corpus x tercile, for DC, its ladder variants,
DC_lex, LC_maj*, VC and the frozen exp3 baselines (LC_maj, LC_onecoin, LC_ds_binary, B1, B3nli, B3cos, B7, B8) on
the SAME items. Writes results/m0_anchor.json and (once) frozen_dc_config.json + its sha256."""
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from loguru import logger  # noqa: E402

from dc.common import EXP3, RES, WORK, LOGS, jdump, load_frame, rj  # noqa: E402
from dc import stats as ST  # noqa: E402

logger.remove()
logger.add(sys.stdout, level="INFO", format="{time:HH:mm:ss}|{level:<7}|{message}")
logger.add(str(LOGS / "m0_anchor.log"), level="DEBUG")

OURS = ["DC", "S0_L1", "S1_L2", "S2_L3", "DC_L2w", "DC_lex", "LC_maj_star", "VC"]
EXP3_M = ["LC_maj", "LC_onecoin", "LC_ds_binary", "B1", "B3nli", "B3cos", "B7", "B8"]


def load_all(tag: str = ""):
    G = [r for r in load_frame() if r["fold"] == "heldout_confirm"]
    sc = {r["item_id"]: r for r in rj(WORK / f"dc_scores{tag}.jsonl")}
    ex = defaultdict(dict)
    for r in rj(EXP3 / "results" / "heldout_scores.jsonl"):
        if r["fold"] == "heldout_confirm":
            ex[r["item_id"]][r["metric"]] = (r["score"], r["covered"])
    for r in G:
        s = sc.get(r["item_id"], {})
        r["m"] = {}
        for m in OURS:
            if m in s:
                r["m"][m] = s[m]
        for m in EXP3_M:
            v = ex[r["item_id"]].get(m)
            r["m"][m] = None if v is None else v[0]
        r["y_panel"] = (1 if r["output"] == "faithful" else 0) if (
            r["label_source"] == "panel3" and r["output"] in ("faithful", "unfaithful")) else None
        r["y_solver"] = {"faithful": 1, "unfaithful": 0}.get(r["output"])
        r["w"] = float(r["L3_sampling_weight"] or 1.0) if r["y_panel"] is not None else None
    return G, sc


def strata(rows):
    return {r["sentence_id"]: f"{r['corpus']}|{r['complexity_tercile']}" for r in rows}


def auc_table(rows, metrics, ykey, wkey, nboot=ST.NBOOT):
    R = [r for r in rows if r[ykey] is not None]
    out = {}
    stt = strata(R)
    for m in metrics:
        Rm = [r for r in R if r["m"].get(m) is not None]
        if len(Rm) < 10:
            out[m] = {"auroc": None, "n": len(Rm)}
            continue
        y = [r[ykey] for r in Rm]
        s = [r["m"][m] for r in Rm]
        w = [r[wkey] for r in Rm] if wkey else None
        out[m] = ST.auc_ci(y, s, w, [r["sentence_id"] for r in Rm], stt, n=nboot)
        out[m]["n_missing"] = len(R) - len(Rm)
    return out


def code_sha() -> dict:
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT / "dc").glob("*.py"))}


@logger.catch(reraise=True)
def main():
    tag = sys.argv[1] if len(sys.argv) > 1 else ""
    G, sc = load_all(tag)
    info = json.loads((WORK / f"m0_info{tag}.json").read_text())
    Gs = [r for r in G if r["item_id"] in sc]
    P = [r for r in Gs if r["y_panel"] is not None]
    logger.info(f"items {len(Gs)}; panel {len(P)} (Kish n_eff {ST.kish([r['w'] for r in P]):.0f})")
    res = {"label_note": "DEV: the dev set was seen by LC in round 2; nothing here is confirmatory",
           "panel_weighted": auc_table(Gs, OURS + EXP3_M, "y_panel", "w"),
           "solver_unweighted": auc_table(Gs, OURS + EXP3_M, "y_solver", None),
           "n_items": len(Gs), "n_panel": len(P), "kish_panel": ST.kish([r["w"] for r in P]),
           "coverage": {m: float(np.mean([bool(sc[r['item_id']].get(m + "_cov")) for r in Gs]))
                        for m in ["DC", "S0_L1", "S1_L2", "S2_L3", "DC_L2w", "DC_lex", "LC_maj_star", "VC"]},
           "n_unparseable_items": sum(1 for r in Gs if not sc[r["item_id"]]["coverage"]["self_parseable"]),
           "cost_seconds_per_item_mean": float(np.mean([sc[r["item_id"]].get("seconds") or 0 for r in Gs])),
           "l1_crosscheck": {k: v for k, v in info["l1_crosscheck"].items() if k != "disagreements"},
           "l1_crosscheck_disagreements_sample": info["l1_crosscheck"]["disagreements"][:20],
           "ds": info["ds"]}
    # T2: LC_maj* reproduction of exp3 LC_maj (0.765 panel) and DS weight sanity (Spearman with panel accuracy)
    pa = res["panel_weighted"]
    res["T2_lcmaj_reproduction"] = {"LC_maj_star": pa["LC_maj_star"]["auroc"], "exp3_LC_maj": pa["LC_maj"]["auroc"],
                                    "abs_diff": abs(pa["LC_maj_star"]["auroc"] - pa["LC_maj"]["auroc"]),
                                    "within_0.02": abs(pa["LC_maj_star"]["auroc"] - pa["LC_maj"]["auroc"]) <= 0.02}
    from scipy.stats import spearmanr
    acc = defaultdict(list)
    for r in P:
        acc[r["system"]].append((r["y_panel"], r["w"]))
    sys_acc = {s: sum(y * w for y, w in v) / sum(w for _, w in v) for s, v in acc.items()}
    ks = sorted(sys_acc)
    rho = spearmanr([info["ds"]["p"][k] for k in ks], [sys_acc[k] for k in ks]).statistic
    res["T2_ds_sanity"] = {"system_panel_accuracy": sys_acc, "p_s": info["ds"]["p"], "spearman": float(rho)}
    for m in ("DC", "S0_L1", "LC_maj", "LC_ds_binary", "B1"):
        logger.info(f"  {m}: panel {pa[m]['auroc']:.3f} {pa[m].get('ci')}  solver "
                    f"{res['solver_unweighted'][m]['auroc']:.3f}")
    jdump(res, RES / f"m0_anchor{tag}.json")
    if not tag:
        fz = ROOT / "frozen_dc_config.json"
        if fz.exists():
            logger.warning("frozen_dc_config.json already exists: NOT overwritten (config is frozen)")
        else:
            from dc import align, pairs, relation, fp
            cfg = {"contract": "DC v1 (this artifact; no external contract file was found)",
                   "limits": {"L1_cap": align.L1_CAP, "L2_cap": align.L2_CAP, "L2_min_occurrence_cover": align.L2_MIN_COVER,
                              "L3_cap_defsets": align.L3_CAP, "L3_max_defs": 2, "L3_base_maps": pairs.N_L3_BASE,
                              "wall_s_per_pair": pairs.WALL_S, "z3_timeout_ms": relation.Z3_MS,
                              "bounded_fallback_nmax": relation.BOUND_N, "max_z3_equiv_tries": pairs.MAX_Z3_EQ,
                              "max_z3_entail_tries": pairs.MAX_Z3_ENT, "fingerprint_structures": fp.N,
                              "fingerprint_domains": [2, 3], "worker_rlimit_as_gb": 3.0},
                   "ordering_rule": "maps sorted by (-fingerprint agreement, -occurrence match, -polarity match, "
                                    "-n mapped, first-occurrence structure); names never used",
                   "selection_rule": "max rank EQUIV > STRONGER=WEAKER over all levels (lower level wins ties); "
                                     "else the relation under the top map of the lowest level with any map "
                                     "(COMPATIBLE/CONTRADICTORY/UNKNOWN); none -> UNALIGNABLE",
                   "score_rule": "sum w*[EQUIV] / sum w over peers with rel != UNKNOWN (UNALIGNABLE in the "
                                 "denominator); unparseable or < 2 covered peers -> 0.5",
                   "weights": info["weights_used"], "ds_fit": info["ds"],
                   "code_sha256": code_sha(), "dev_anchor": {m: pa[m] for m in ("DC", "S0_L1", "S2_L3", "DC_L2w")}}
            jdump(cfg, fz)
            h = hashlib.sha256(fz.read_bytes()).hexdigest()
            (ROOT / "frozen_dc_config.sha256").write_text(h + "\n")
            logger.info(f"FROZEN config sha256 {h}")


if __name__ == "__main__":
    main()
