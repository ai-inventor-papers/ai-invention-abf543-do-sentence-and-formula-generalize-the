"""R3: decoder from the signature mismatch vector to the panel's error taxonomy.

D_rule (PRIMARY, pre-registered): an evidence score per type from the mismatch records m of a scored item
  argument_swap              #swap coordinates
  dropped_condition          #dropped text concepts
  added_condition            #added formula predicates (unaligned or vacuous '0')
  conflation                 [dropped ∧ a label mismatch on a predicate that also covers another concept] (1.0)
                             or [dropped ∧ any label mismatch] (0.5)
  wrong_split                #concepts whose aligned predicates carry both + and −
  implication_direction_or_only  [∃ t=− → s=+  ∧  ∃ t=+ → s=−]
  quantifier_forall_exists   #(t=− and s ∈ {+, ±}) when there is no t=+ → s=− flip
  negation_polarity          [exactly one sign flip (+↔−)]
  connective_and_or          #relativized-coordinate mismatches
  wrong_constant             [a proper-noun text concept is unaligned ∧ the formula has an unaligned constant]
  unparseable -> syntax_unparseable; parse ok and no mismatch -> 'no_signature_change' (top-1), and for top-2
  the two BLIND types {quantifier_scope, cardinality_numeric, connective_and_or, wrong_constant} with the highest
  SCREEN-DEV prior. Ranking = evidence × per-type weight w_t (w_t ∈ {0.5, 1, 1.5, 2}, coordinate ascent on
  SCREEN-DEV mutant macro-F1); ties broken by a fixed prior order.
D_lr (SECONDARY): multinomial logistic regression on count features (core.features), trained on SCREEN-DEV
  mutants only, frozen.
"""
from __future__ import annotations

import numpy as np

OP2TYPE = {"NEG": "negation_polarity", "QUANT": "quantifier_forall_exists", "IMPL_REV": "implication_direction_or_only",
           "DROP": "dropped_condition", "ADD": "added_condition", "ARG_SWAP": "argument_swap", "MERGE": "conflation",
           "ANDOR": "connective_and_or", "SCOPE": "quantifier_scope", "CARD": "cardinality_numeric"}
RULE_TYPES = ["added_condition", "quantifier_forall_exists", "dropped_condition", "implication_direction_or_only",
              "negation_polarity", "argument_swap", "conflation", "wrong_split", "connective_and_or", "wrong_constant"]
BLIND = ["quantifier_scope", "cardinality_numeric", "connective_and_or", "wrong_constant"]
NO_CHANGE = "no_signature_change"
CALIB_OPS = ["NEG", "QUANT", "IMPL_REV", "DROP", "ADD", "ARG_SWAP", "MERGE", "ANDOR"]
LR_FEATS = ["n_dropped", "n_added_unaligned", "n_added_vacuous", "n_swap", "n_flip_pm", "n_flip_mp", "n_pm_nonmono",
            "n_rel", "n_split", "n_coords", "coverage"]


def evidence(res: dict, A: dict | None = None, concepts: list | None = None, consts: list | None = None) -> dict:
    ev = {t: 0.0 for t in RULE_TYPES}
    coords = res.get("coords") or []
    mism = [r for _, m, r in coords if m]
    lab = [r for r in mism if r["type"] == "label"]
    ev["argument_swap"] = float(sum(r["type"] == "swap" for r in mism))
    nd = sum(r["type"] == "dropped" for r in mism)
    ev["dropped_condition"] = float(nd)
    ev["added_condition"] = float(sum(r["type"] == "added" for r in mism))
    if nd and lab:
        spans2 = any(A and A["preds"].get(r.get("pred"), {}).get("covered") for r in lab)
        ev["conflation"] = 1.0 if spans2 else 0.5
    by_c: dict = {}
    for _, _, r in coords:
        if r["type"] == "label":
            by_c.setdefault(r["cid"], set()).add(r["s"])
    ev["wrong_split"] = float(sum(1 for v in by_c.values() if {"+", "-"} <= v))
    down_up = [r for r in lab if r["t"] == "-" and r["s"] == "+"]
    up_down = [r for r in lab if r["t"] == "+" and r["s"] == "-"]
    if down_up and up_down:
        ev["implication_direction_or_only"] = 1.0
    if not up_down:
        ev["quantifier_forall_exists"] = float(sum(1 for r in lab if r["t"] == "-" and r["s"] in ("+", "±")))
    flips = [r for r in lab if {r["t"], r["s"]} == {"+", "-"}]
    if len(flips) == 1:
        ev["negation_polarity"] = 1.0
    ev["connective_and_or"] = float(sum(r["type"] == "rel" for r in mism))
    if A is not None and concepts is not None and consts is not None:
        pn_unal = any(c["is_const"] and c["cid"] not in set(A["consts"].values()) and
                      not any(a["cid"] == c["cid"] for a in A["preds"].values()) for c in concepts)
        k_unal = any(k not in A["consts"] for k in consts)
        ev["wrong_constant"] = 1.0 if (pn_unal and k_unal) else 0.0
    return ev


def rank_rule(ev: dict, w: dict, parse_ok: bool, has_mismatch: bool, blind_prior: list) -> list[str]:
    if not parse_ok:
        return ["syntax_unparseable"]
    if not has_mismatch:
        return [NO_CHANGE] + list(blind_prior)
    sc = {t: ev[t] * w.get(t, 1.0) for t in RULE_TYPES if ev[t] > 0}
    if not sc:
        return ["other"] + list(blind_prior)
    order = sorted(sc, key=lambda t: (-sc[t], RULE_TYPES.index(t)))
    return order + [t for t in blind_prior if t not in order]


def top2_list(ranked: list[str]) -> list[str]:
    """Top-2 used for scoring: for no-change items the two blind types (no_signature_change is not a type)."""
    r = [t for t in ranked if t != NO_CHANGE]
    return r[:2]


def macro_f1(y_true: list, y_pred: list, labels: list) -> float:
    from sklearn.metrics import f1_score
    return float(f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0))


def calibrate_weights(items: list[dict], blind_prior: list, grid=(0.5, 1.0, 1.5, 2.0), rounds: int = 3) -> tuple:
    """items: [{ev, has_mismatch, y}] on SCREEN-DEV mutants of CALIB_OPS. Coordinate ascent on macro-F1."""
    labels = sorted({it["y"] for it in items})
    w = {t: 1.0 for t in RULE_TYPES}

    def f(wd):
        pred = [rank_rule(it["ev"], wd, True, it["has_mismatch"], blind_prior)[0] for it in items]
        return macro_f1([it["y"] for it in items], pred, labels)
    best = f(w)
    trace = [{"round": 0, "macro_f1": best, "w": dict(w)}]
    for rd in range(rounds):
        changed = False
        for t in RULE_TYPES:
            for v in grid:
                if v == w[t]:
                    continue
                w2 = {**w, t: v}
                s = f(w2)
                if s > best + 1e-12:
                    best, w, changed = s, w2, True
        trace.append({"round": rd + 1, "macro_f1": best, "w": dict(w)})
        if not changed:
            break
    return w, best, trace


def lr_matrix(feats: list[dict]) -> np.ndarray:
    return np.array([[float(f.get(k, 0.0)) for k in LR_FEATS] for f in feats])


def fit_lr(feats: list[dict], y: list[str]):
    from sklearn.linear_model import LogisticRegression
    X = lr_matrix(feats)
    m = LogisticRegression(max_iter=5000, C=1.0)
    m.fit(X, y)
    return {"classes": [str(c) for c in m.classes_], "coef": m.coef_.tolist(), "intercept": m.intercept_.tolist(),
            "feats": LR_FEATS}


def predict_lr(model: dict, feat: dict, parse_ok: bool, has_mismatch: bool, blind_prior: list) -> list[str]:
    if not parse_ok:
        return ["syntax_unparseable"]
    if not has_mismatch:
        return [NO_CHANGE] + list(blind_prior)
    x = lr_matrix([feat])[0]
    z = np.array(model["coef"]) @ x + np.array(model["intercept"])
    if len(model["classes"]) == 2:  # binary degenerate case
        z = np.array([-z[0], z[0]])
    order = np.argsort(-z)
    ranked = [model["classes"][i] for i in order]
    return ranked + [t for t in blind_prior if t not in ranked]
