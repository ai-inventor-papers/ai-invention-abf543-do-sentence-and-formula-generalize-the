"""Constructed-truth probe builders (M1-M4). Written AFTER the M0 freeze; contains no scoring logic.

tokmap/synmap renderers, rendering a formula into a peer's vocabulary through a DC alignment, ADD_CONJ that reuses an
existing predicate, bound-variable renaming, and verified meaning-preserving rewrites."""
from __future__ import annotations

import hashlib
import random
import string

from . import front  # noqa: F401
import fol_core as fc  # noqa: E402
import mutants as mu  # noqa: E402

OPS = ["DROP_CONJ", "ADD_CONJ", "QUANT", "IMPL_REV", "NEG", "ARG_SWAP"]
OP_TYPE = {"DROP_CONJ": "dropped_condition", "ADD_CONJ": "added_condition", "QUANT": "quantifier_forall_exists",
           "IMPL_REV": "implication_direction_or_only", "NEG": "negation_polarity", "ARG_SWAP": "argument_swap"}


def rng(key: str) -> random.Random:
    return random.Random(int(hashlib.sha1(key.encode()).hexdigest()[:12], 16))


def tokmap(F, key: str) -> tuple[dict, dict]:
    r = rng("tok|" + key)
    used = set()

    def tok(upper: bool) -> str:
        while True:
            s = "".join(r.choice(string.ascii_lowercase) for _ in range(3)) + str(r.randrange(10))
            s = (s[0].upper() + s[1:]) if upper else s
            s = ("P" if upper else "c") + s
            if s not in used:
                used.add(s)
                return s
    pm = {p: tok(True) for p in sorted(fc.predicates(F, strict=False) or {})}
    cm = {c: tok(False) for c in fc.constants(F)}
    return pm, cm


def synmap(F) -> tuple[dict, dict]:
    preds = fc.predicates(F, strict=False) or {}
    taken = set(preds)
    pm = {}
    for k, p in enumerate(sorted(preds)):
        new = mu.synonym_name(p, taken, k)
        taken.add(new)
        pm[p] = new
    cm = {}
    ctaken = set(fc.constants(F))
    for k, c in enumerate(fc.constants(F)):
        new = mu.synonym_name(c, ctaken, k)
        new = new[0].lower() + new[1:] if new else f"c{k}"
        if new in ctaken or new.startswith("Pred_") or new.startswith("pred_"):
            new = f"{c}_alt"
        ctaken.add(new)
        cm[c] = new
    return pm, cm


def map_to_peer(g: str, r: str, rec: dict) -> tuple[dict, dict] | None:
    """From a best_relation record between canonical strings g and r: rename maps g-symbols -> r-symbols.
    None if the record uses L3 definitions (not renderable by renaming) or leaves g symbols unmapped."""
    if rec.get("defs"):
        return None
    lo = rec.get("lo") or min(g, r)
    tgt_is_g = (rec.get("target") == "A") == (g == lo)
    pm, cm = {}, {}
    for kind, s, t in rec.get("map") or []:
        if t is None:
            return None
        if tgt_is_g:
            (pm if kind == "P" else cm)[t] = s
        else:
            (pm if kind == "P" else cm)[s] = t
    G = front.parse_canon(g)
    if set(fc.predicates(G, strict=False) or {}) - set(pm) or set(fc.constants(G)) - set(cm):
        return None
    return pm, cm


def add_conj_existing(F, seed_key: str, max_tries: int = 6):
    """ADD_CONJ reusing an EXISTING unary predicate of F at a restrictor site (antecedent of → under ∀, or ∃ body).
    Kept only if bounded-non-equivalent to F under the identity map. Returns (ast|None, reason)."""
    preds = fc.predicates(F, strict=False) or {}
    un = sorted(p for p, k in preds.items() if k == 1)
    sites = []
    for path, m in mu.preorder(F):
        if m[0] in ("forall", "exists"):
            v, b = m[1], m[2]
            for P in un:
                lit = ("atom", P, (("v", v),))
                if b[0] == "imp" and v in mu.free_vars(b[1]):
                    if lit in (b[1][1:] if b[1][0] == "and" else (b[1],)):
                        continue
                    sites.append(mu.replace(F, path + (0, 0), mu.mk_and([b[1], lit])))
                elif m[0] == "exists":
                    if lit in (b[1:] if b[0] == "and" else (b,)):
                        continue
                    sites.append(mu.replace(F, path + (0,), mu.mk_and([b, lit])))
    sites = [s for s in dict.fromkeys(sites) if s != F]
    if not sites:
        return None, "no_site"
    r = rng("addconj|" + seed_key)
    r.shuffle(sites)
    for s in sites[:max_tries]:
        if fc.bounded_equiv(s, F, nmax=4, timeout_ms=3000) == "nonequiv":
            return s, "ok"
    return None, "all_equivalent"


def mutant(F, op: str, seed_key: str) -> dict:
    if op == "ADD_CONJ":
        s, why = add_conj_existing(F, seed_key)
        if s is not None:
            return {"op": op, "kept": True, "ast": s, "fol": fc.to_str(s), "fresh_pred": False}
        m = mu.make_mutant(F, op, seed_key)
        if m.get("kept"):
            m["fresh_pred"] = True
        return m
    m = mu.make_mutant(F, op, seed_key)
    m["fresh_pred"] = False
    return m


def var_rename(F):
    """Alpha-rename every bound variable to fresh names (v1, v2, ...) - meaning preserving."""
    ctr = [0]

    def rec(n, env):
        k = n[0]
        if k == "atom":
            return ("atom", n[1], tuple(("v", env[t[1]]) if t[0] == "v" else t for t in n[2]))
        if k == "eq":
            return ("eq",) + tuple(("v", env[t[1]]) if t[0] == "v" else t for t in n[1:])
        if k in ("forall", "exists"):
            ctr[0] += 1
            nv = f"v{ctr[0]}"
            return (k, nv, rec(n[2], {**env, n[1]: nv}))
        return (k,) + tuple(rec(a, env) for a in n[1:])
    return rec(F, {})


def rewrites(F, key: str) -> list[dict]:
    """The 7 M2 rewrite kinds, each verified meaning-preserving (bounded n<=4 AND unbounded z3) under the identity or
    the rename map. Returns [{kind, fol, ok, reason}]."""
    out = []
    cands = []
    pm, cm = synmap(F)
    cands.append(("syn_rename", fc.rename(F, pm, cm), (pm, cm)))
    pm2, cm2 = tokmap(F, key)
    cands.append(("tok_rename", fc.rename(F, pm2, cm2), (pm2, cm2)))
    cands.append(("var_rename", var_rename(F), None))
    for kind, fn in (("reorder", mu._rw_reorder), ("contrapositive", mu._rw_contra), ("demorgan", mu._rw_demorgan),
                     ("prenex", mu._rw_prenex)):
        try:
            cs = [c for c in fn(F, rng(key + kind)) if c[0] != F]
        except (mu.NotPrenexable, ValueError, RecursionError):
            cs = []
        if not cs:
            out.append({"kind": kind, "ok": False, "reason": "inapplicable"})
            continue
        cands.append((kind, cs[rng(key + kind + "pick").randrange(len(cs))][0], None))
    for kind, new, m in cands:
        if new == F and kind != "var_rename":
            out.append({"kind": kind, "ok": False, "reason": "unchanged"})
            continue
        chk_new = new
        if m is not None:
            inv_p = {v: k for k, v in m[0].items()}
            inv_c = {v: k for k, v in m[1].items()}
            chk_new = fc.rename(new, inv_p, inv_c)
        try:
            b = fc.bounded_equiv(chk_new, F, nmax=4, timeout_ms=3000)
            u = fc.unbounded_equiv(chk_new, F, timeout_ms=5000) if b == "equiv" else "skip"
        except Exception as e:  # noqa: BLE001 - verification failure is counted per kind
            b, u = "error", repr(e)[:60]
        ok = b == "equiv" and u in ("equiv", "unknown")
        out.append({"kind": kind, "ok": ok, "fol": fc.to_str(new), "bounded": b, "unbounded": u,
                    "reason": "verified" if ok else "not_verified"})
    return out
