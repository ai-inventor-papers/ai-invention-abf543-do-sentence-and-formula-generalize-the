"""best_relation: the best logical relation between two formalisations over all admissible lexical-free alignments.

Selection rule (frozen in frozen_dc_config.json):
  maximise rank EQUIV(4) > STRONGER = WEAKER(3) among maps whose fingerprints permit it (solver-confirmed);
  if no map yields EQUIV/STRONGER/WEAKER, report the relation (COMPATIBLE / CONTRADICTORY / UNKNOWN) under the TOP
  map of the name-independent ordering. Tie-break: lower level, then ordering key.
Per level: rel_L1 (bijections), rel_L2 (<= L2), rel_L3 (<= L3). Also rel_lex = relation under the lexically anchored
fol_core.trigram_map (for the M4(d) contrast). UNALIGNABLE = no admissible map at any level.
Cache key sha1(min(sa,sb)+'||'+max(sa,sb)); records stored in (min,max) orientation, STRONGER<->WEAKER flipped on read.
"""
from __future__ import annotations

import hashlib
import time

import numpy as np

from . import front
from .align import (L1_CAP, L2_CAP, apply_defs, apply_map, definition_sets, enumerate_maps, map_key, profiles, roles,
                    score_maps)
from .fp import slotmap, truth_vector
from .relation import RANK, flip, pair_relation, possible
import fol_core as fc  # noqa: E402

WALL_S = 12.0
MAX_Z3_EQ = 6
MAX_Z3_ENT = 6
N_L3_BASE = 3


def pkey(a: str, b: str) -> str:
    lo, hi = (a, b) if a <= b else (b, a)
    return hashlib.sha1((lo + "||" + hi).encode("utf-8")).hexdigest()


def _search(T, cands: list[dict], deadline: float) -> dict | None:
    """cands: [{'RS'/'T2', 'vT', 'vS', ...}] sorted best-first. Returns best {rel (T to S), cand, pr} or None."""
    if not cands:
        return None
    n_calls = 0
    eq = [c for c in cands if np.array_equal(c["vT"], c["vS"])]
    unknown_seen = False
    for c in eq[:MAX_Z3_EQ]:
        if time.time() > deadline:
            break
        pr = pair_relation(c.get("T2", T), c["RS"], c["vT"], c["vS"], deadline=deadline)
        n_calls += pr["n_solver_calls"]
        if pr["rel"] == "EQUIV":
            return {"rel": "EQUIV", "cand": c, "pr": pr, "n_calls": n_calls}
        unknown_seen |= pr["had_unknown"]
    ent = []
    for c in cands:
        p = possible(c["vT"], c["vS"])
        if (p["ab"] or p["ba"]) and not np.array_equal(c["vT"], c["vS"]):
            ent.append(c)
    for c in ent[:MAX_Z3_ENT]:
        if time.time() > deadline:
            break
        pr = pair_relation(c.get("T2", T), c["RS"], c["vT"], c["vS"], deadline=deadline)
        n_calls += pr["n_solver_calls"]
        if pr["rel"] in ("STRONGER", "WEAKER", "EQUIV"):
            return {"rel": pr["rel"], "cand": c, "pr": pr, "n_calls": n_calls}
        unknown_seen |= pr["had_unknown"]
    top = cands[0]
    if time.time() > deadline:
        return {"rel": "UNKNOWN", "cand": top, "pr": None, "n_calls": n_calls, "timeout": True}
    pr = pair_relation(top.get("T2", T), top["RS"], top["vT"], top["vS"], deadline=deadline)
    n_calls += pr["n_solver_calls"]
    rel = pr["rel"]
    return {"rel": rel, "cand": top, "pr": pr, "n_calls": n_calls, "unknown_seen": unknown_seen}


def _better(a: dict | None, b: dict | None) -> dict | None:
    """Keep a (lower level) unless b is an entailment-type relation (EQUIV/STRONGER/WEAKER) of strictly higher rank.
    COMPATIBLE / CONTRADICTORY / UNKNOWN are decided at the lowest level that has any admissible map."""
    if a is None:
        return b
    if b is None:
        return a
    return b if (RANK[b["rel"]] >= 3 and RANK[b["rel"]] > RANK[a["rel"]]) else a


def _ser_map(m: dict) -> list:
    return [[k[0], k[1], v] for k, v in sorted(m.items(), key=lambda kv: (kv[0][0], kv[0][1]))]


def best_relation_ast(A, B, deadline: float | None = None, want_lex: bool = True) -> dict:
    """Relation of A to B (A STRONGER = A |= B strictly). See module docstring."""
    t0 = time.time()
    deadline = deadline or (t0 + WALL_S)
    if A == B:
        return {"rel": "EQUIV", "rel_L1": "EQUIV", "rel_L2": "EQUIV", "rel_L3": "EQUIV", "level": 1,
                "method": "identical", "target": "A", "map": [], "defs": None, "rel_lex": "EQUIV",
                "n_maps_L1": 1, "n_maps_L2": 0, "n_defsets": 0, "n_solver_calls": 0, "timeout": False,
                "seconds": round(time.time() - t0, 4)}
    tgt, _ = roles(A, B)
    T, S = (A, B) if tgt == "A" else (B, A)
    profT, profS = profiles(T), profiles(S)
    Tn = (set(profT["P"]), set(profT["C"]))
    n_calls = 0
    # ---- L1
    maps1 = enumerate_maps(profS, profT, 1, L1_CAP, deadline)
    sc1 = score_maps(T, S, maps1, profS, profT, deadline)
    r1 = _search(T, sc1, deadline)
    if r1:
        r1["level"] = 1
        n_calls += r1["n_calls"]
    best = r1
    rel_L1 = r1["rel"] if r1 else "UNALIGNABLE"
    # ---- L2
    sc2 = []
    if (best is None or best["rel"] != "EQUIV") and time.time() < deadline:
        seen = {map_key(m) for m in maps1}
        maps2 = [m for m in enumerate_maps(profS, profT, 2, L2_CAP, deadline) if map_key(m) not in seen]
        sc2 = score_maps(T, S, maps2, profS, profT, deadline)
        r2 = _search(T, sc2, deadline)
        if r2:
            r2["level"] = 2
            n_calls += r2["n_calls"]
        best = _better(best, r2)
    rel_L2 = best["rel"] if best else "UNALIGNABLE"
    # ---- L3 (definitions on top of the best L2 maps; if no L2 map exists, on the best L1 maps)
    n_def = 0
    if (best is None or best["rel"] != "EQUIV") and time.time() < deadline:
        from .align import unmapped
        base = []
        for c in sc2:
            uT, uS = unmapped(T, c["RS"])
            if uT and uS and len(uS) <= 2 and len(uT) <= 4:
                base.append(c)
            if len(base) >= N_L3_BASE:
                break
        c3 = []
        for bmap in base:
            for sd in definition_sets(T, bmap["RS"]):
                if time.time() > deadline:
                    break
                T2, RS2 = apply_defs(T, bmap["RS"], sd)
                try:
                    ps, cs = slotmap(T2, RS2)
                    vT, vS = truth_vector(T2, ps, cs), truth_vector(RS2, ps, cs)
                except (KeyError, IndexError, ValueError):
                    continue
                n_def += 1
                c3.append({"map": bmap["map"], "RS": RS2, "T2": T2, "vT": vT, "vS": vS, "defs": sd,
                           "agree": float(np.mean(vT == vS)), "key": (bmap["key"], n_def)})
        # only definition sets that can raise the rank are worth solver time
        c3 = [c for c in c3 if (possible(c["vT"], c["vS"])["ab"] or possible(c["vT"], c["vS"])["ba"])]
        c3.sort(key=lambda c: (0 if np.array_equal(c["vT"], c["vS"]) else 1, -c["agree"], c["key"]))
        if c3:
            r3 = _search(T, c3, deadline)
            if r3 and r3["rel"] in ("EQUIV", "STRONGER", "WEAKER"):
                r3["level"] = 3
                n_calls += r3["n_calls"]
                best = _better(best, r3)
    rel_L3 = best["rel"] if best else "UNALIGNABLE"
    timeout = time.time() > deadline

    def orient(rel: str) -> str:
        return rel if tgt == "A" else flip(rel)
    out = {"rel": orient(rel_L3), "rel_L1": orient(rel_L1), "rel_L2": orient(rel_L2), "rel_L3": orient(rel_L3),
           "level": best["level"] if best else None, "target": tgt,
           "method": (best["pr"] or {}).get("method") if best and best.get("pr") else None,
           "map": _ser_map(best["cand"]["map"]) if best else [],
           "defs": ({"side": best["cand"]["defs"][0], "defs": {q: [list(l) for l in b] for q, b in
                                                               best["cand"]["defs"][1].items()}}
                    if best and best["cand"].get("defs") else None),
           "n_maps_L1": len(maps1), "n_maps_L2": len(sc2), "n_defsets": n_def, "n_solver_calls": n_calls,
           "timeout": timeout}
    # ---- lexically anchored relation (M4 d)
    if want_lex:
        try:
            m = fc.trigram_map(A, B)
        except (ValueError, ImportError):
            m = None
        if m is None:
            out["rel_lex"] = "NOMAP"
        else:
            RA = fc.rename(A, m[0], m[1])
            pr = pair_relation(RA, B, deadline=max(deadline, time.time() + 3))
            out["rel_lex"] = pr["rel"]
            out["lex_map"] = {"P": m[0], "C": m[1]}
    out["seconds"] = round(time.time() - t0, 4)
    return out


def best_relation(sa: str, sb: str, want_lex: bool = True) -> dict:
    """String interface (canonical strings). Unparseable -> rel 'UNPARSEABLE'."""
    A, B = front.parse_canon(sa), front.parse_canon(sb)
    if A is None or B is None:
        return {"rel": "UNPARSEABLE", "rel_L1": "UNPARSEABLE", "rel_L2": "UNPARSEABLE", "rel_L3": "UNPARSEABLE",
                "rel_lex": "UNPARSEABLE", "seconds": 0.0}
    return best_relation_ast(A, B, want_lex=want_lex)


def oriented(rec: dict, a_is_lo: bool) -> dict:
    """Cached record is stored for (lo, hi). Return it oriented for the requested (a, b)."""
    if a_is_lo:
        return rec
    out = dict(rec)
    for k in ("rel", "rel_L1", "rel_L2", "rel_L3", "rel_lex"):
        if k in out and isinstance(out[k], str):
            out[k] = flip(out[k])
    out["flipped"] = True
    return out


def compute_record(sa: str, sb: str, want_lex: bool = True) -> dict:
    lo, hi = (sa, sb) if sa <= sb else (sb, sa)
    try:
        r = best_relation(lo, hi, want_lex=want_lex)
    except (RecursionError, MemoryError, ValueError, KeyError, IndexError) as e:
        r = {"rel": "UNKNOWN", "rel_L1": "UNKNOWN", "rel_L2": "UNKNOWN", "rel_L3": "UNKNOWN", "rel_lex": "UNKNOWN",
             "error": f"{type(e).__name__}: {str(e)[:120]}", "seconds": None}
    r["k"] = pkey(sa, sb)
    r["lo"], r["hi"] = lo, hi
    return r
