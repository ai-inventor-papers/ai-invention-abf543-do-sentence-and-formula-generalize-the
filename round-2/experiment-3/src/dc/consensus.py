"""Directional Consensus (DC): a gold-free, text-blind faithfulness score for an NL->FOL output.

DC(C) = sum_{covered peers p} w_p * 1[align(C, p) == EQUIV] / sum_{covered peers p} w_p
where a peer is covered when its relation is not UNKNOWN (and, if cfg.unalign_in_denominator is False, not
UNALIGNABLE). Fewer than 2 covered peers -> score 0.5, covered=False. Unparseable C -> 0.5 (DC) / 0.0 (DC0).
Also returned: the strength profile of C against the modal EQUIV cluster (net STRONGER-minus-WEAKER mass,
INCOMPARABLE / CONTRADICTORY / UNALIGNABLE shares) and an error type (errtype.type_error vs the mode).
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass

from .align import CAPS, Caps, align_pair, derive
from .errtype import type_error
from .parse import parse_fol
from .relation import converse


@dataclass(frozen=True)
class DCConfig:
    use_L3: bool = True
    unalign_in_denominator: bool = True
    weights: str = "DS"  # 'DS' | 'uniform'
    half_caps: bool = False
    rule_1b: bool = True

    def name(self) -> str:
        return (f"L3{'on' if self.use_L3 else 'off'}_UA{'in' if self.unalign_in_denominator else 'out'}_"
                f"{self.weights}_caps{'0.5' if self.half_caps else '1'}")

    def as_dict(self) -> dict:
        return asdict(self)


DEFAULT = DCConfig()


def components(nodes: list[str], eq_edges: set[tuple[str, str]]) -> dict[str, int]:
    parent = {n: n for n in nodes}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for a, b in eq_edges:
        if a in parent and b in parent:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)
    roots = sorted({find(n) for n in nodes})
    idx = {r: i for i, r in enumerate(roots)}
    return {n: idx[find(n)] for n in nodes}


def score_group(outputs: dict[str, object], rel: dict, weights: dict[str, float], cfg: DCConfig = DEFAULT) -> dict:
    """Score every output of one sentence.
    outputs: {system: parsed AST or None}; rel: {(a, b): relation of a to b under cfg} for parseable a != b
    (both orders present). Returns {system: result dict}."""
    parse_ok = [s for s, a in outputs.items() if a is not None]
    eq = {(a, b) for (a, b), r in rel.items() if r == "EQUIV"}
    comp = components(parse_ok, eq)
    cw = {}
    for s in parse_ok:
        cw[comp[s]] = cw.get(comp[s], 0.0) + weights.get(s, 1.0)
    mode = max(cw, key=lambda c: (cw[c], -c)) if cw else None
    mode_members = [s for s in parse_ok if comp[s] == mode]
    out = {}
    for s, ast in outputs.items():
        res = {"system": s, "unparseable": ast is None, "n_peers": len(outputs) - 1,
               "n_peers_unparseable": sum(1 for p, a in outputs.items() if p != s and a is None)}
        if ast is None:
            res.update({"score": 0.5, "score_DC0": 0.0, "covered": False})
            out[s] = res
            continue
        num = den = 0.0
        counts = {}
        covered = []
        for p in parse_ok:
            if p == s:
                continue
            r = rel.get((s, p), "UNKNOWN")
            counts[r] = counts.get(r, 0) + 1
            if r == "UNKNOWN" or (r == "UNALIGNABLE" and not cfg.unalign_in_denominator):
                continue
            covered.append(p)
            w = weights.get(p, 1.0)
            den += w
            num += w * (r == "EQUIV")
        if len(covered) < 2 or den <= 0:
            res.update({"score": 0.5, "score_DC0": 0.5, "covered": False})
        else:
            res.update({"score": num / den, "score_DC0": num / den, "covered": True})
        # strength profile against the mode (excluding s itself)
        mm = [p for p in mode_members if p != s]
        W = sum(weights.get(p, 1.0) for p in mm)
        net = sum(weights.get(p, 1.0) * ((rel.get((s, p)) == "STRONGER") - (rel.get((s, p)) == "WEAKER"))
                  for p in mm) / W if W > 0 else 0.0
        nc = max(1, len(covered))
        res.update({"relations": counts, "n_peers_covered": len(covered), "in_mode": s in mode_members,
                    "mode_size": len(mode_members), "mode_weight_share": (cw[mode] / sum(cw.values())) if cw else None,
                    "n_clusters": len(cw), "cluster": comp[s],
                    "sp_net": net,
                    "sp_incomparable": sum(rel.get((s, p)) == "INCOMPARABLE" for p in covered) / nc,
                    "sp_contradictory": sum(rel.get((s, p)) == "CONTRADICTORY" for p in covered) / nc,
                    "sp_unalignable": sum(rel.get((s, p)) == "UNALIGNABLE" for p in parse_ok if p != s) /
                    max(1, len(parse_ok) - 1)})
        # heaviest mode member other than s = the representative for typing
        res["mode_rep"] = (max(mm, key=lambda p: (weights.get(p, 1.0), p)) if mm and s not in mode_members else None)
        out[s] = res
    return out


def directional_consensus(text: str | None, fol: str, peers: list[str], weights: list[float] | None = None,
                          cfg: DCConfig = DEFAULT, caps: Caps = CAPS, with_type: bool = True) -> dict:
    """Reliability-weighted share of peer formalizations that are solver-equivalent to this one under
    lexical-free alignment (text is not read). peers: other systems' formulas for the same sentence;
    weights: optional per-peer reliability weights (default 1)."""
    t0 = time.time()
    names = ["_cand"] + [f"p{i}" for i in range(len(peers))]
    asts = {"_cand": parse_fol(fol), **{f"p{i}": parse_fol(p) for i, p in enumerate(peers)}}
    w = {"_cand": 1.0, **{f"p{i}": (weights[i] if weights else 1.0) for i in range(len(peers))}}
    rel, recs = {}, {}
    ok = [n for n in names if asts[n] is not None]
    for i, a in enumerate(ok):
        for b in ok[i + 1:]:
            rec = align_pair(asts[a], asts[b], caps=caps, use_L3=cfg.use_L3)
            r = derive(rec, use_L3=cfg.use_L3, half_caps=cfg.half_caps)["rel"]
            rel[(a, b)], rel[(b, a)] = r, converse(r)
            recs[(a, b)] = rec
    res = score_group(asts, rel, w, cfg)["_cand"]
    if with_type and res.get("mode_rep") and asts["_cand"] is not None:
        M = asts[res["mode_rep"]]
        rec = recs.get(("_cand", res["mode_rep"]))
        res["error_type"] = type_error(asts["_cand"], M, rec, use_L3=cfg.use_L3, rule_1b=cfg.rule_1b)["type"]
    elif res.get("in_mode"):
        res["error_type"] = "none"
    else:
        res["error_type"] = None
    res["cost"] = {"usd": 0.0, "seconds": round(time.time() - t0, 3)}
    return res


__all__ = ["directional_consensus", "score_group", "DCConfig", "DEFAULT", "components"]
