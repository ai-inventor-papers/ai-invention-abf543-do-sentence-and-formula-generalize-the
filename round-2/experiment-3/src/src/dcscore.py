"""Batch DC scoring from the config-agnostic pair cache (shared by the dev freeze and the fresh confirmation)."""
from __future__ import annotations

import importlib.util
import itertools
from collections import defaultdict

from common import ROOT
from dc.align import derive
from dc.consensus import DCConfig, components, score_group
from dc.relation import converse
from dc.weights import fit_weights
from pairs import lookup

_spec = importlib.util.spec_from_file_location("r2stats", ROOT / "vendor" / "r2" / "src" / "stats.py")
r2stats = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(r2stats)


def rel_of(cache: dict, a: str, b: str, cfg: DCConfig) -> str:
    """Relation of canonical formula a to b under cfg (UNKNOWN if the pair is missing or errored)."""
    rec, flipped = lookup(cache, a, b)
    if rec is None or rec.get("error"):
        return "UNKNOWN"
    r = derive(rec, use_L3=cfg.use_L3, half_caps=cfg.half_caps)["rel"]
    return converse(r) if flipped else r


def group_relations(canons: dict[str, str | None], cache: dict, cfg: DCConfig) -> dict:
    rel = {}
    ok = [s for s, c in canons.items() if c is not None]
    for a, b in itertools.combinations(ok, 2):
        r = rel_of(cache, canons[a], canons[b], cfg)
        rel[(a, b)] = r
        rel[(b, a)] = converse(r)
    return rel


def score_all(groups: dict[str, dict[str, str | None]], cache: dict, cfg: DCConfig, systems: list[str],
              weights: dict | None = None) -> tuple[dict, dict, dict]:
    """groups: {sid: {system: canon or None}}. Fits label-free DS weights on the EQUIV clusters (unless weights are
    given), then scores every output. Returns ({(sid, system): result}, weights, weight_info)."""
    from dc.parse import parse_fol
    rels = {sid: group_relations(g, cache, cfg) for sid, g in groups.items()}
    if weights is None:
        sents = []
        for sid, g in groups.items():
            ok = [s for s, c in g.items() if c is not None]
            eq = {(a, b) for (a, b), r in rels[sid].items() if r == "EQUIV"}
            comp = components(ok, eq)
            sents.append({"cls": {s: (comp[s] if s in comp else None) for s in g}})
        weights, info = fit_weights(sents, systems, mode=cfg.weights)
    else:
        info = {"mode": "given"}
    out = {}
    for sid, g in groups.items():
        asts = {s: (parse_fol(c) if c is not None else None) for s, c in g.items()}
        res = score_group(asts, rels[sid], weights, cfg)
        for s, r in res.items():
            out[(sid, s)] = r
    return out, weights, info


def ladder_scores(groups: dict, cache: dict) -> dict:
    """Component ladder from the one cache: LC_maj-style L1-only uniform share (step 0) and +L2 / +L3 variants."""
    steps = {"L1_uniform": DCConfig(use_L3=False, weights="uniform"),
             "L12_uniform": DCConfig(use_L3=False, weights="uniform"),
             "L123_uniform": DCConfig(use_L3=True, weights="uniform")}
    out = defaultdict(dict)
    for name, cfg in steps.items():
        for sid, g in groups.items():
            ok = [s for s, c in g.items() if c is not None]
            for s in g:
                if g[s] is None:
                    out[name][(sid, s)] = (0.5, False)
                    continue
                num = den = 0
                for p in ok:
                    if p == s:
                        continue
                    rec, flipped = lookup(cache, g[s], g[p])
                    if rec is None or rec.get("error"):
                        continue
                    if name == "L1_uniform":
                        L1 = rec.get("L1")
                        r = "EQUIV" if (L1 and L1["rel"] == "EQUIV") else "NOT"
                    else:
                        r = derive(rec, use_L3=cfg.use_L3)["rel"]
                        if r == "UNKNOWN":
                            continue
                    den += 1
                    num += r == "EQUIV"
                out[name][(sid, s)] = (num / den, True) if den >= 2 else (0.5, False)
    return out
