"""sigfaith — gold-free NL→FOL faithfulness signature, error-type namer and wrong-gold flagger (iter-2 repair of Arm A).

All tuned parameters (aligner config, text side, decoder weights, blind prior) are read from
results/frozen_config.json, written once by freeze.py after the screen-only repair (R1-R3).

signature_faithfulness(text, fol, zero_llm=True) -> dict
    WHAT IT MEASURES: agreement between (a) the monotonicity profile of the SENTENCE — for each content concept, whether
    it sits in an upward (+) or downward (−) entailing position (restrictor / antecedent / negated scope vs nuclear
    scope / consequent), which argument slot each role word fills, and which concepts are expressed at all — and (b)
    the same properties computed EXACTLY from the FORMULA by SAT over all finite models of size 1..3 (per predicate P:
    is F upward/downward monotone in P; anchors of relation slots; relativized coordination coordinates). The two are
    linked by a polarity-blind, renaming-robust aligner (Hungarian assignment on max(lemma overlap, WordNet, SBERT)).
    score = 1 − weighted fraction of mismatching coordinates (dropped concepts, added/vacuous predicates, polarity
    mismatches, swapped slots, relativized mismatches); 0.5 if the item is not covered (unparseable, coverage < 0.5,
    > 20% solver-unknown coordinates, or no labelled concept).
    Returns {score, raw_score, P (polarity-only subscore), A0 (alignment-only score), coverage, covered, error_types
    (ranked D_rule types), error_type_top1, per_concept_signs, formula_signs, alignment, mismatches, cost_usd, seconds}.
    BLIND SPOTS (by construction): quantifier-scope swaps (∀∃ vs ∃∀), cardinality / numerics (monotone profile does
    not change), and many and/or swaps when coordination is not detected in the text; errors that keep every
    concept's polarity (e.g. a wrong constant with the same predicate profile). NOT invariant to renamings the aligner
    cannot match (predicate names unrelated to any sentence word) — those surface as dropped+added coordinates.
    zero_llm=True uses the rule-based text polarity (T0). If the frozen text side is an LLM probe and zero_llm=False,
    one gemini-2.5-flash probe call per sentence is made (OPENROUTER_API_KEY).

gold_audit(text, gold_fol) -> dict
    The same measurement applied to a GOLD formula: flag_score = 1 − score (higher = more likely a wrong gold), plus the
    ranked error types. MEASURES whether the gold's monotonicity profile disagrees with the sentence's; it cannot flag
    gold errors in its blind spots (scope, cardinality) nor wrong golds whose profile happens to agree.

document_signature(sentences, fols) -> dict
    Cross-sentence vocabulary consistency of a document's formalizations under the same aligner: (a) CONFLATION flag —
    one predicate name aligned to ≥ 2 concept heads that are themselves dissimilar (sim < τ); (b) SPLIT/INCONSISTENCY
    flag — one concept head aligned to ≥ 2 different predicate names across sentences; (c) ARITY conflict — the same
    predicate name used with different arities (the user's pilot structural metric). Exploratory (V5).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import core  # noqa: F401  (sets sys.path: sigfaith/ + legacy_armA/src)
from . import align2, decoder, textside  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FROZEN = ROOT / "results" / "frozen_config.json"
_STATE: dict = {}


def _cfg() -> dict:
    if "cfg" not in _STATE:
        _STATE["cfg"] = json.loads(FROZEN.read_text()) if FROZEN.exists() else None
    return _STATE["cfg"]


def aligner_from(cfg: dict):
    acfg = {k: v for k, v in cfg.items() if k in ("tau", "wn", "emb", "beta")}

    def f(preds, consts, concepts, anchors):
        A = align2.align2(preds, consts, concepts, anchors, acfg)
        if cfg.get("fallback_mpnet_0.4"):
            left = [P for P, a in A["preds"].items() if a["cid"] is None]
            if left and concepts:
                m = "sentence-transformers/all-mpnet-base-v2"
                Ec = align2.embed([align2.concept_phrase(c) for c in concepts], m)
                Es = align2.embed([" ".join(align2.split_name(P)) or P.lower() for P in left], m)
                sim = Ec @ Es.T
                for j, P in enumerate(left):
                    i = int(sim[:, j].argmax())
                    if sim[i, j] >= 0.4:
                        A["preds"][P] = {"cid": concepts[i]["cid"], "flip": A["preds"][P]["flip"], "covered": [],
                                         "how": f"fallback_mpnet:{sim[i, j]:.2f}"}
                covered = set()
                for a in A["preds"].values():
                    if a["cid"] is not None:
                        covered.add(a["cid"])
                        covered |= set(a["covered"])
                covered |= set(A["consts"].values())
                denom = [c["cid"] for c in concepts if not (align2.is_optional(c) and c["cid"] not in covered)]
                A["coverage"] = (len(covered & set(denom)) / len(denom)) if denom else 0.0
                A["covered_cids"] = sorted(covered)
        return A
    return f


def score_parsed(ex: dict, labels: dict, p, S: dict | None, fz: dict, aligner=None) -> dict:
    """Score one parsed formula (p = legacy Parsed or None) against one extracted sentence `ex` with text labels."""
    from align import is_optional  # legacy
    T = core.make_T(ex, labels)
    optional = {c["cid"] for c in ex["concepts"] if is_optional(c)}
    if p is None or S is None or "error" in (S or {}):
        r = core.signature_score_full(T, None, None, variant="A3", parse_ok=False)
        ranked = decoder.rank_rule({t: 0.0 for t in decoder.RULE_TYPES}, fz["decoder"]["weights"], False, False,
                                   fz["decoder"]["blind_prior"]) if p is None else \
            ["other"] + list(fz["decoder"]["blind_prior"])
        return {"score": 0.5, "raw_score": None, "covered": False, "coverage": 0.0, "P": 0.5, "A0": 0.5,
                "error_types": ranked, "error_type_top1": ranked[0], "mismatches": [], "alignment": None,
                "why_uncovered": "unparseable" if p is None else "no_signature", "features": core.features(r),
                "lr_types": ranked}
    aligner = aligner or aligner_from(fz["aligner"])
    A = aligner(p.preds, p.consts, ex["concepts"], ex["anchors"])
    r = core.signature_score_full(T, S, A, variant="A3", parse_ok=True, optional=optional)
    r0 = core.signature_score_full(T, S, A, variant="A0", parse_ok=True, optional=optional)
    ev = decoder.evidence(r, A, ex["concepts"], p.consts)
    has_m = any(m for _, m, _ in r["coords"])
    ranked = decoder.rank_rule(ev, fz["decoder"]["weights"], True, has_m, fz["decoder"]["blind_prior"])
    feat = core.features(r)
    lr_types = decoder.predict_lr(fz["decoder"]["lr_model"], feat, True, has_m, fz["decoder"]["blind_prior"])
    return {"score": r["score"], "raw_score": r["raw_score"], "covered": r["covered"], "coverage": r["coverage"],
            "P": r["P"], "P_raw": r["P_raw"], "A0": r0["score"], "A0_raw": r0["raw_score"],
            "error_types": ranked, "error_type_top1": ranked[0], "lr_types": lr_types, "evidence": ev,
            "legacy_type_panel": r.get("legacy_type_panel"), "why_uncovered": r["why_uncovered"],
            "mismatches": [x for _, m, x in r["coords"] if m][:12], "n_coords": r["n_coords"], "features": feat,
            "alignment": {k: v["cid"] for k, v in A["preds"].items()},
            "per_concept_signs": {c["span"]: T["labels"].get(c["cid"]) for c in ex["concepts"]},
            "formula_signs": S["labels"]}


def signature_faithfulness(text: str, fol: str, zero_llm: bool = True) -> dict:
    t0 = time.time()
    fz = _cfg()
    if fz is None:
        raise RuntimeError("results/frozen_config.json missing: run freeze.py first")
    from solver_sig import signature
    ex = textside.extract_many([text])[text]
    side = "T0" if zero_llm else fz["text_side"]
    probe = None
    cost = 0.0
    if side != "T0":
        probe = textside.probe_many([text], {text: ex})[text]
        cost = probe.get("usd", 0.0)
    labels = textside.labels_for(ex, side if side in ("T0", "T1a", "T1b", "T1c") else "T1b", probe)
    p, err = core.parse_front(fol)
    S = None
    if p is not None:
        try:
            S = signature(p.ast, N=3, timeout_ms=5000, with_rel=True, rel_max_unary=8)
        except Exception as e:  # noqa: BLE001
            S = {"error": repr(e)}
    out = score_parsed(ex, labels, p, S, fz)
    out.update(cost_usd=cost, seconds=round(time.time() - t0, 3), text_side=side, parse_error=err or None)
    return out


def gold_audit(text: str, gold_fol: str, zero_llm: bool = True) -> dict:
    r = signature_faithfulness(text, gold_fol, zero_llm=zero_llm)
    r["flag_score"] = 1.0 - r["score"]
    return r


def document_signature(sentences: list[str], fols: list[str], aligned: list[dict] | None = None,
                       tau: float | None = None) -> dict:
    """aligned: optional precomputed [{ex, alignment{P: cid}, arity{P: k}}] per sentence (else computed here)."""
    fz = _cfg()
    tau = tau if tau is not None else (fz["aligner"]["tau"] if fz else 0.45)
    if aligned is None:
        aligned = []
        exs = textside.extract_many(sentences)
        aligner = aligner_from(fz["aligner"]) if fz else None
        for s, f in zip(sentences, fols):
            p, _ = core.parse_front(f)
            if p is None or aligner is None:
                aligned.append({"ex": exs[s], "alignment": {}, "arity": {}})
                continue
            A = aligner(p.preds, p.consts, exs[s]["concepts"], exs[s]["anchors"])
            aligned.append({"ex": exs[s], "alignment": {k: v["cid"] for k, v in A["preds"].items()},
                            "arity": dict(p.preds)})
    emb = (fz or {}).get("aligner", {}).get("emb", "sentence-transformers/all-MiniLM-L6-v2")
    pred_heads: dict = {}
    head_preds: dict = {}
    arities: dict = {}
    for i, a in enumerate(aligned):
        cmap = {c["cid"]: c for c in a["ex"]["concepts"]}
        for P, cid in a["alignment"].items():
            arities.setdefault(P, set()).add(a["arity"].get(P))
            if cid is None or cid not in cmap:
                continue
            c = cmap[cid]
            pred_heads.setdefault(P, {}).setdefault(c["head_lemma"], set()).add(i)
            head_preds.setdefault(c["head_lemma"], {}).setdefault(P.split("#")[0], set()).add(i)
    conflation, split, arity_conf = [], [], []
    for P, heads in pred_heads.items():
        hs = sorted(heads)
        if len(hs) < 2:
            continue
        E = align2.embed(hs, emb)
        wn_m = (fz or {}).get("aligner", {}).get("wn", "wup")
        bad = [(a, b) for x, a in enumerate(hs) for y, b in enumerate(hs) if x < y and
               max(float(E[x] @ E[y]), align2.wn_sim(a, b, wn_m)) < tau]
        if bad:
            conflation.append({"pred": P, "heads": hs, "sentences": sorted({i for v in heads.values() for i in v}),
                               "dissimilar_pairs": bad[:5]})
    for h, ps in head_preds.items():
        if len(ps) >= 2:
            split.append({"head": h, "preds": sorted(ps), "sentences": sorted({i for v in ps.values() for i in v})})
    for P, ks in arities.items():
        ks = {k for k in ks if k is not None}
        if len(ks) > 1:
            arity_conf.append({"pred": P, "arities": sorted(ks)})
    flagged = {"conflation": sorted({i for c in conflation for i in c["sentences"]}),
               "split": sorted({i for c in split for i in c["sentences"]})}
    return {"conflation": conflation, "split": split, "arity_conflicts": arity_conf, "flagged_sentences": flagged,
            "n_sentences": len(sentences)}


__all__ = ["signature_faithfulness", "gold_audit", "document_signature", "score_parsed", "aligner_from"]
