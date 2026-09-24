"""DC contract v1 public API.

    from dc.api import align_pair, pair_relation, directional_consensus, ds_weights

directional_consensus(text, fol, peers, weights=None, pair_results=None) -> dict
    MEASURES: the reliability-weighted share of peers (other systems' formalizations of the SAME text) that are
    logically equivalent to the candidate under lexical-free alignment. `text` is carried for provenance only and is
    never read. score = Σ_{EQUIV} w / Σ_{covered ∪ UNALIGNABLE} w, where covered = {EQUIV, STRONGER, WEAKER,
    COMPATIBLE-INCOMPARABLE, CONTRADICTORY}; UNKNOWN peers are excluded (coverage loss). Unparseable candidate or
    < 2 covered peers -> score 0.5, coverage 0. Also returns the strength profile (Σw STRONGER − Σw WEAKER over the
    covered weight), the modal cluster, and a rule-based error type relative to the modal representative.
"""
from __future__ import annotations

import math
from collections import defaultdict

from .core import INVERSE, Formula, align_pair, pair_relation, walk_atoms  # noqa: F401

COVERED = {"EQUIV", "STRONGER", "WEAKER", "COMPATIBLE-INCOMPARABLE", "CONTRADICTORY"}


def invert(res: dict) -> dict:
    """relation of (B, A) from the stored relation of (A, B)."""
    r = dict(res)
    r["relation"] = INVERSE.get(res["relation"], res["relation"])
    r["inverted"] = not res.get("inverted", False)
    return r


def logit_weight(p: float, lo: float = 0.05, hi: float = 3.0) -> float:
    p = min(0.999, max(0.001, p))
    return float(min(hi, max(lo, math.log(p / (1 - p)))))


def _mapped_sets(C: Formula, M: Formula, rel: dict, c_is_a: bool):
    """predicate sets of C and of the mode M expressed in a common vocabulary through the chosen map.
    rel was computed with A=(C if c_is_a else M), B read in A's vocabulary via rel['map'] (B->A)."""
    m = rel.get("map") or {}
    defs = rel.get("defs") or {}
    if rel.get("direction") == "A_in_B":  # the L3 reverse search stored a map A->B: flip roles
        c_is_a = not c_is_a
    if c_is_a:
        a_set = set(C.preds)
        b_set = set()
        for b in M.preds:
            if b in defs:
                b_set |= {x[0] for x in defs[b]}
            else:
                b_set.add(m.get(b, "~" + b))
        return a_set, b_set  # (C, mode)
    a_set = set(M.preds)
    c_set = set()
    for b in C.preds:
        if b in defs:
            c_set |= {x[0] for x in defs[b]}
        else:
            c_set.add(m.get(b, "~" + b))
    return c_set, a_set


def _strip_quants(ast):
    while ast[0] in ("forall", "exists"):
        ast = ast[2]
    return ast


def _ante_cons(F: Formula, rename: dict | None = None):
    core = _strip_quants(F.ast)
    if core[0] != "imp":
        return None
    rn = rename or {}
    ante = {rn.get(o["name"], o["name"]) for o in walk_atoms(core[1])}
    cons = {rn.get(o["name"], o["name"]) for o in walk_atoms(core[2])}
    return ante, cons


def _neg_in_antecedent(F: Formula, names: set, rename: dict | None = None) -> bool:
    rn = rename or {}
    for o in F.occ:
        if o["ante"] and o["negated"] and rn.get(o["name"], o["name"]) in names:
            return True
    return False


def error_type(C: Formula, M: Formula, rel: dict, c_is_a: bool) -> tuple[str, bool]:
    """Rule-based error type of candidate C relative to the modal representative M (formula-only), plus the
    exception_involved flag (the diffed literal is negated inside an antecedent: the shape of 'unless/except')."""
    r = rel["relation"]
    if not c_is_a:
        r = INVERSE.get(r, r)  # relation of C to M
    if r == "EQUIV":
        return "none", False
    c_set, m_set = _mapped_sets(C, M, rel, c_is_a)
    # rename maps into the common vocabulary for antecedent / negation checks
    m = rel.get("map") or {}
    flipped = rel.get("direction") == "A_in_B"
    a_is_c = c_is_a != flipped
    ren_c = {} if a_is_c else {b: m.get(b, "~" + b) for b in C.preds}
    ren_m = {b: m.get(b, "~" + b) for b in M.preds} if a_is_c else {}
    added, dropped = c_set - m_set, m_set - c_set
    exc = False
    if r in ("STRONGER", "WEAKER"):
        if added:
            exc = _neg_in_antecedent(C, added, ren_c)
            return "added_condition", exc
        if dropped:
            exc = _neg_in_antecedent(M, dropped, ren_m)
            return "dropped_condition", exc
    if c_set == m_set:
        if C.quant_profile() != M.quant_profile():
            return "quantifier_forall_exists", False
        if r == "COMPATIBLE-INCOMPARABLE":
            ac, am = _ante_cons(C, ren_c), _ante_cons(M, ren_m)
            if ac and am and ac[0] == am[1] and ac[1] == am[0]:
                return "implication_direction_or_only", False
        if r == "CONTRADICTORY":
            return "negation_polarity", _neg_in_antecedent(C, c_set, ren_c)
        pc = sorted((ren_c.get(o["name"], o["name"]), tuple(sorted(t[1] for t in o["args"]))) for o in C.occ if len(o["args"]) >= 2)
        pm = sorted((ren_m.get(o["name"], o["name"]), tuple(sorted(t[1] for t in o["args"]))) for o in M.occ if len(o["args"]) >= 2)
        if pc and [p for p, _ in pc] == [p for p, _ in pm]:
            return "argument_swap", False
    elif r in ("COMPATIBLE-INCOMPARABLE", "CONTRADICTORY") and (added or dropped):
        exc = _neg_in_antecedent(C, added, ren_c) or _neg_in_antecedent(M, dropped, ren_m)
    return "other", exc


def equivalence_clusters(ids: list[str], rel_of) -> dict[str, int]:
    """union-find over EQUIV relations; rel_of(i, j) -> relation string."""
    parent = {i: i for i in ids}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for x in range(len(ids)):
        for y in range(x + 1, len(ids)):
            if rel_of(ids[x], ids[y]) == "EQUIV":
                parent[find(ids[x])] = find(ids[y])
    roots, out = {}, {}
    for i in ids:
        out[i] = roots.setdefault(find(i), len(roots))
    return out


def directional_consensus(text: str, fol: str, peers: list, weights: list | None = None,
                          pair_results: list | None = None, limits: dict | None = None) -> dict:
    """text: provenance only (never read). peers: list of FOL strings (other systems, same text).
    weights: per-peer reliability weights (default 1). pair_results: optional precomputed pair_relation(fol, peer)
    dicts (A = candidate). Returns {score, coverage, n_covered, strength_profile, relations, cost_seconds}."""
    C = Formula(fol)
    w = list(weights) if weights is not None else [1.0] * len(peers)
    if not C.ok:
        return {"score": 0.5, "coverage": 0, "reason": "unparseable_candidate", "n_covered": 0,
                "strength_profile": 0.0, "relations": [], "cost_seconds": 0.0}
    rels, secs = [], 0.0
    for k, p in enumerate(peers):
        r = pair_results[k] if pair_results is not None else pair_relation(C, Formula(p), limits)
        rels.append(r)
        secs += r.get("seconds", 0.0) or 0.0
    return score_from_relations([r["relation"] for r in rels], w, secs)


def score_from_relations(relations: list[str], w: list[float], seconds: float = 0.0) -> dict:
    cov_w = sum(wi for r, wi in zip(relations, w) if r in COVERED)
    den = cov_w + sum(wi for r, wi in zip(relations, w) if r == "UNALIGNABLE")
    n_cov = sum(1 for r in relations if r in COVERED)
    eq = sum(wi for r, wi in zip(relations, w) if r == "EQUIV")
    st = sum(wi for r, wi in zip(relations, w) if r == "STRONGER") - sum(wi for r, wi in zip(relations, w) if r == "WEAKER")
    counts = defaultdict(int)
    for r in relations:
        counts[r] += 1
    if n_cov < 2 or den <= 0:
        return {"score": 0.5, "coverage": 0, "reason": "fewer_than_2_covered_peers", "n_covered": n_cov,
                "strength_profile": 0.0, "relation_counts": dict(counts), "cost_seconds": seconds}
    return {"score": eq / den, "coverage": 1, "reason": "", "n_covered": n_cov,
            "strength_profile": st / cov_w if cov_w > 0 else 0.0, "relation_counts": dict(counts),
            "cost_seconds": seconds}


def ds_weights(obs: list[dict], systems: list[str]) -> dict:
    """one-coin Dawid-Skene (vendor Arm B latent_class.em) on 'in the equivalence cluster' observations ->
    per-system weight logit(sensitivity) clipped to [0.05, 3]."""
    import sys
    from pathlib import Path
    vb = Path(__file__).resolve().parents[1] / "vendor" / "armB"
    if str(vb) not in sys.path:
        sys.path.insert(0, str(vb))
    from latent_class import em
    fit = em(obs, systems)
    p = {s: fit["p"][(0, s)] for s in systems}
    return {"p_w": p, "w": {s: logit_weight(v) for s, v in p.items()}, "pi": fit["pi"][0], "rho": fit["rho"],
            "loglik": fit["ll"], "post": fit["post"]}
