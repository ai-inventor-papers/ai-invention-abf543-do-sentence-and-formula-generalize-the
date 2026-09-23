#!/usr/bin/env python3
"""PHASE 1 / STEP 4 (R3): error-type decoder calibration on SCREEN_DEV mutants; evaluation on SCREEN_TEST mutants +
the Arm-B SCOPE_SWAP supplement (n=37, FOLIO-train / MALLS sentences; never used for tuning).

Uses the chosen R1 aligner (results/r1_grid.json) and R2 text side (results/r2_select.json).
D_rule weights: coordinate ascent over w_t ∈ {0.5,1,1.5,2} maximising macro-F1 over NEG, QUANT, IMPL_REV, DROP, ADD,
ARG_SWAP, MERGE, ANDOR mutants of SCREEN_DEV. D_lr: multinomial LR on count features, SCREEN_DEV mutants (all ops).
Blind prior (top-2 for no-change items): the blind types ranked by their frequency among SCREEN_DEV mutants whose
signature did not change. Writes results/r3_decoder.json.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import screen_common as sc  # noqa: E402
import core  # noqa: E402
import decoder as D  # noqa: E402
import phase1_r1  # noqa: E402

logger.remove()
logger.add(sys.stdout, level="INFO", format="{time:HH:mm:ss}|{level:<7}|{message}")
logger.add(ROOT / "logs" / "phase1_r3.log", rotation="30 MB", level="DEBUG")
RES = ROOT / "results"


def frozen_aligner():
    r1 = json.loads((RES / "r1_grid.json").read_text())
    cfg = r1["chosen_cfg"]
    return (phase1_r1.fallback_aligner(cfg) if cfg.get("fallback_mpnet_0.4") else phase1_r1.make_aligner(cfg)), cfg


def text_side() -> str:
    p = RES / "r2_select.json"
    return json.loads(p.read_text())["chosen"] if p.exists() else "T0"


def score_units(units, aligner, side):
    out = []
    for u in units:
        r = sc.score_item(u, aligner, side=side, variant="A3", T=u.get("T"))
        ev = D.evidence(r, r.get("A"), u.get("concepts") or sc.ex_of(u["sid"])["concepts"], r.get("consts"))
        has_m = bool([1 for _, m, _ in r.get("coords", []) if m])
        out.append({**{k: u[k] for k in ("item_id", "sid", "operator") if k in u}, "ev": ev, "has_mismatch": has_m,
                    "feat": core.features(r), "parse_ok": r.get("parse_ok", False),
                    "y": D.OP2TYPE.get(u.get("operator"), "other"), "score": r["score"]})
    return out


def supplement_units(side: str):
    import textside
    rows = [json.loads(l) for l in (ROOT / "data" / "blindspot_supplement.jsonl").read_text().splitlines()]
    rows = [r for r in rows if r["op"] == "SCOPE_SWAP"]
    exs = textside.extract_many([r["nl"] for r in rows])
    probes = textside.probe_many([r["nl"] for r in rows], exs) if side != "T0" else {}
    units = []
    for r in rows:
        ex = exs[r["nl"]]
        lab = textside.labels_for(ex, side, probes.get(r["nl"]))
        T = core.make_T(ex, lab)
        units.append({"item_id": r["item_id"], "sid": r["sid"], "operator": "SCOPE", "fol": r["fol"],
                      "gold_fol": r["gold_fol"], "parse_ok": True, "T": T, "concepts": ex["concepts"], "ex": ex})
    return units


def eval_block(scored, w, lr, blind_prior, labels):
    y = [s["y"] for s in scored]
    pr = [D.rank_rule(s["ev"], w, s["parse_ok"], s["has_mismatch"], blind_prior) for s in scored]
    pl = [D.predict_lr(lr, s["feat"], s["parse_ok"], s["has_mismatch"], blind_prior) for s in scored]
    out = {}
    for name, preds in (("D_rule", pr), ("D_lr", pl), ("legacy_iter1", None)):
        if preds is None:
            continue
        top1 = [p[0] for p in preds]
        top2 = [D.top2_list(p) for p in preds]
        per_op = defaultdict(lambda: [0, 0, 0])
        conf = defaultdict(Counter)
        for s, t1, t2 in zip(scored, top1, top2):
            per_op[s["y"]][0] += t1 == s["y"]
            per_op[s["y"]][1] += s["y"] in t2
            per_op[s["y"]][2] += 1
            conf[s["y"]][t1] += 1
        out[name] = {"macro_f1": D.macro_f1(y, top1, labels), "top1": sum(a == b for a, b in zip(top1, y)) / len(y),
                     "top2": sum(b in t for t, b in zip(top2, y)) / len(y),
                     "per_type": {k: {"top1": v[0] / v[2], "top2": v[1] / v[2], "n": v[2]} for k, v in per_op.items()},
                     "confusion": {k: dict(v) for k, v in conf.items()}, "n": len(y)}
    return out


@logger.catch(reraise=True)
def main():
    aligner, cfg = frozen_aligner()
    side = text_side()
    dev, test = sc.splits()
    dev_units = [u for u in sc.items(set(dev), kinds=("mutant",))]
    test_units = [u for u in sc.items(set(test), kinds=("mutant",))]
    if side != "T0":
        for u in dev_units + test_units:
            u["T"] = sc.T_of(u["sid"], side)
    sd = score_units(dev_units, aligner, side)
    st = score_units(test_units, aligner, side)
    nochg = Counter(s["y"] for s in sd if s["parse_ok"] and not s["has_mismatch"])
    blind_prior = sorted(D.BLIND, key=lambda t: (-nochg.get(t, 0), D.BLIND.index(t)))[:2]
    calib = [s for s in sd if s["operator"] in D.CALIB_OPS and s["parse_ok"]]
    w, f1_dev, trace = D.calibrate_weights(calib, blind_prior)
    lr = D.fit_lr([s["feat"] for s in sd if s["parse_ok"] and s["has_mismatch"]],
                  [s["y"] for s in sd if s["parse_ok"] and s["has_mismatch"]])
    labels_calib = sorted({D.OP2TYPE[o] for o in D.CALIB_OPS})
    dev_eval = eval_block([s for s in sd if s["operator"] in D.CALIB_OPS], w, lr, blind_prior, labels_calib)
    test_eval = eval_block([s for s in st if s["operator"] in D.CALIB_OPS], w, lr, blind_prior, labels_calib)
    test_all = eval_block(st, w, lr, blind_prior, sorted({s["y"] for s in st}))
    sup = supplement_units(side)
    ss = score_units(sup, aligner, side)
    # blind-spot detection on supplement: mutant score < its own gold score
    gold_sc = {}
    for u in sup:
        gu = {**u, "fol": u["gold_fol"], "item_id": u["item_id"] + ":gold"}
        gold_sc[u["item_id"]] = score_units([gu], aligner, side)[0]["score"]
    det_scope = [1.0 if s["score"] < gold_sc[s["item_id"]] else (0.5 if s["score"] == gold_sc[s["item_id"]] else 0.0)
                 for s in ss]
    sup_eval = eval_block(ss, w, lr, blind_prior, ["quantifier_scope"])
    lr_better = test_eval["D_lr"]["macro_f1"] - test_eval["D_rule"]["macro_f1"] >= 0.05
    out = {"aligner_cfg": cfg, "text_side": side, "weights": w, "dev_macro_f1_calib": f1_dev, "trace": trace,
           "blind_prior": blind_prior, "dev_nochange_ops": dict(nochg), "lr_model": lr,
           "dev_eval": dev_eval, "test_eval": test_eval, "test_eval_all_ops": test_all,
           "scope_supplement": {"n": len(ss), "eval": sup_eval,
                                "DET_scope": sum(det_scope) / len(det_scope) if det_scope else None,
                                "share_no_signature_change": sum(not s["has_mismatch"] for s in ss) / max(1, len(ss))},
           "carry_D_lr_to_heldout": bool(lr_better),
           "rule": "PRIMARY = D_rule; D_lr carried too iff it beats D_rule on SCREEN_TEST macro-F1 by >= 0.05"}
    (RES / "r3_decoder.json").write_text(json.dumps(out, indent=1))
    logger.info(f"R3: w={w} dev macroF1={f1_dev:.3f}; TEST D_rule macroF1={test_eval['D_rule']['macro_f1']:.3f} "
                f"top1={test_eval['D_rule']['top1']:.3f} top2={test_eval['D_rule']['top2']:.3f}; D_lr "
                f"{test_eval['D_lr']['macro_f1']:.3f}; blind_prior={blind_prior}; scope DET={out['scope_supplement']['DET_scope']}")


if __name__ == "__main__":
    main()
