"""Analysis frame for the fresh confirmation: one row per fresh greedy output with scores and both label types."""
from __future__ import annotations

import json
from collections import defaultdict

import numpy as np

from common import RES, WORK, read_jsonl
from dcscore import r2stats

FAITH = {"equiv_proved", "equiv_bounded"}
UNF = {"non_equiv", "non_equiv_no_bijection"}
NBOOT = 2000


def raked_weights(l3: dict, cap_ratio: float = 6.0, n_iter: int = 50) -> tuple[dict, dict]:
    """Post-stratification RAKED over two margins of the L3 frame: design stratum (L1 status x LC_maj position x
    tercile | unparseable) and generating system (the sampler preferred the two T4 systems). IPF, then the
    max/min weight ratio is capped at cap_ratio (plan), then renormalised to the frame size."""
    import s06_labels as s6
    frame = s6.build_l3_frame()
    Nst = defaultdict(float)
    Nsy = defaultdict(float)
    for r in frame:
        Nst[r["stratum"]] += 1
        Nsy[r["system"]] += 1
    items = {k: v for k, v in l3.items() if v["L3_majority"] is not None}
    w = {k: 1.0 for k in items}
    for _ in range(n_iter):
        for key, N in (("stratum", Nst), ("system", Nsy)):
            tot = defaultdict(float)
            for k, v in items.items():
                tot[v[key]] += w[k]
            for k, v in items.items():
                if tot[v[key]] > 0:
                    w[k] *= N[v[key]] / tot[v[key]]
    lo = max(w.values()) / cap_ratio
    capped = sum(1 for x in w.values() if x < lo)
    w = {k: max(x, lo) for k, x in w.items()}
    s = sum(w.values())
    w = {k: x * len(frame) / s for k, x in w.items()}
    info = {"frame_n": len(frame), "n_items": len(items), "n_floor_capped": capped,
            "kish_n_eff": float(sum(w.values()) ** 2 / sum(x * x for x in w.values())),
            "max_min_ratio": max(w.values()) / min(w.values())}
    return w, info


def load_frame() -> tuple[list[dict], dict]:
    rows = [r for r in read_jsonl(WORK / "fresh_frame.jsonl") if r["fold"] == "fresh_greedy"]
    wide = defaultdict(dict)
    extra = defaultdict(dict)
    for x in read_jsonl(RES / "scores.jsonl"):
        wide[x["item_id"]][x["metric"]] = x["score"]
        wide[x["item_id"]][x["metric"] + "__cov"] = x["covered"]
        if x["metric"] == "DC":
            extra[x["item_id"]] = x["extra"]
    l1 = {x["key"]: x for x in read_jsonl(WORK / "l1_fresh.jsonl")}
    l3 = json.loads((WORK / "l3_fresh.json").read_text())["results"] if (WORK / "l3_fresh.json").exists() else {}
    l0 = json.loads((WORK / "l0_results.json").read_text())
    wr, winfo = raked_weights(l3) if l3 else ({}, {})
    out = []
    for r in rows:
        iid = r["item_id"]
        st = l1.get(iid, {}).get("status")
        p = l3.get(iid)
        y_p = None if (p is None or p["L3_majority"] is None) else int(p["L3_majority"])
        g = l0.get(r["sid"], {})
        out.append({**r, "S_status": st, "y_solver": 1 if st in FAITH else (0 if st in UNF else None),
                    "y_panel": y_p, "w_panel": wr.get(iid) if p else None, "w_design": p["w_design"] if p else None,
                    "panel_primary": p["L3_primary_error"] if p else None, "panel_item": p is not None,
                    "panel_pair_kind": p["pair_kind"] if p else None, "lc_pos": p["lc_pos"] if p else None,
                    "sentence_ambiguous": p.get("sentence_ambiguous") if p else None,
                    "gold_faithful_final": g.get("gold_faithful_final"), "gold_source": g.get("gold_source"),
                    "S": wide.get(iid, {}), "dc_extra": extra.get(iid, {})})
    return out, {"l0": l0, "l3": l3, "weights": winfo}


def strata_of(rows) -> dict:
    return {r["sid"]: f"{r['corpus']}|{r['tercile']}" for r in rows}


def boot(rows, n=NBOOT, seed=0):
    return r2stats.StratBoot([r["sid"] for r in rows], strata_of(rows), n=n, seed=seed)


def sc(r, m, default=0.5):
    v = r["S"].get(m)
    return default if v is None else v


def wauc(y, s, w=None):
    return r2stats.wauc(y, s, w)


def auc_rows(rows, metric, label="panel", getter=None):
    y = np.array([r["y_panel"] if label == "panel" else r["y_solver"] for r in rows], dtype=float)
    s = np.array([getter(r) if getter else sc(r, metric) for r in rows], dtype=float)
    w = np.array([r["w_panel"] for r in rows], dtype=float) if label == "panel" else None
    return y, s, w


def ci_diff(rows, s1, s2, y, w, B) -> dict:
    """Paired bootstrap of AUROC(s1) - AUROC(s2): point, 95% CI, one-sided 5th percentile (LB)."""
    d0 = wauc(y, s1, w) - wauc(y, s2, w)
    ds = []
    for idx in B:
        ww = None if w is None else w[idx]
        a = wauc(y[idx], s1[idx], ww)
        b = wauc(y[idx], s2[idx], ww)
        if not (np.isnan(a) or np.isnan(b)):
            ds.append(a - b)
    ds = np.array(ds)
    return {"point": float(d0), "ci95": [float(np.percentile(ds, 2.5)), float(np.percentile(ds, 97.5))],
            "lb_one_sided_5": float(np.percentile(ds, 5)), "n_boot": len(ds)}


def ci_auc(y, s, w, B) -> dict:
    a0 = wauc(y, s, w)
    vals = [wauc(y[idx], s[idx], None if w is None else w[idx]) for idx in B]
    vals = np.array([v for v in vals if not np.isnan(v)])
    return {"auc": float(a0), "ci95": [float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))]}
