"""L2: granularity-aware equivalence (LEXICAL — flagged L2_lexical=true).

Run only when L1 is not equivalent. Predicate names are split on camelCase / snake_case and
lemmatized with WordNet; negation markers (not, non, un-, never, no) set a polarity. Then:
  (a) a candidate predicate with no same-arity lexical partner is DEFINED as a conjunction of at
      most 2 gold literals (possibly negated) of the same arity and argument list whose lemma set
      covers its lemmas (e.g. UntrainedDog(x) := ¬Trained(x) ∧ Dog(x)); symmetrically, a gold
      compound is defined by candidate literals;
  (b) definitions are substituted and the lexical-free L1 check is rerun with the substituted
      names pinned (identity) and the remaining predicates matched by arity-preserving bijection.
Status: equiv_granular | non_equiv | not_applicable.
"""
from __future__ import annotations

import itertools
import os
import re
from functools import lru_cache
from pathlib import Path

from fol_equiv import equivalence
from fol_parse import SYM, normalize_arity_overloads, signature

os.environ.setdefault("NLTK_DATA", str(Path(__file__).resolve().parents[1] / "nltk_data"))
try:
    from nltk.stem import WordNetLemmatizer
    _LEM = WordNetLemmatizer()
    _LEM.lemmatize("dogs")
except Exception:  # noqa: BLE001 - fall back to a suffix stripper if WordNet is unavailable
    _LEM = None

NEG_WORDS = {"not", "non", "never", "no", "un", "none"}
STOP = {"is", "are", "be", "has", "have", "a", "an", "the", "of", "to", "in", "on", "at", "by", "for", "with", "can",
        "does", "do", "that", "who", "which", "x", "y", "z", "prop"}


@lru_cache(maxsize=100000)
def lemmas(name: str) -> tuple[frozenset, bool]:
    s = re.sub(r"__\d+$", "", name)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)
    words = [w.lower() for w in re.split(r"[\s_\-]+", s) if w]
    neg = False
    out = set()
    for w in words:
        if w in NEG_WORDS:
            neg = not neg
            continue
        if w.startswith("un") and len(w) > 4 and w not in ("under", "unit", "united", "universe", "university", "uniform", "unique"):
            neg = not neg
            w = w[2:]
        elif w.startswith("non") and len(w) > 5:
            neg = not neg
            w = w[3:]
        if w in STOP:
            continue
        if _LEM is not None:
            l1 = _LEM.lemmatize(w, "v")
            w = _LEM.lemmatize(l1, "n")
        else:
            w = re.sub(r"(ing|ed|es|s)$", "", w)
        out.add(w)
    return frozenset(out), neg


def _substitute(ast: tuple, defs: dict) -> tuple:
    """defs: name -> list[(neg, other_name)] (conjunction over the same args)."""
    op = ast[0]
    if op in ("forall", "exists"):
        return (op, ast[1], _substitute(ast[2], defs))
    if op == "not":
        return ("not", _substitute(ast[1], defs))
    if op in SYM:
        return (op, _substitute(ast[1], defs), _substitute(ast[2], defs))
    if op == "atom" and ast[1] in defs:
        lits = []
        for neg, nm in defs[ast[1]]:
            a = ("atom", nm, ast[2])
            lits.append(("not", a) if neg else a)
        out = lits[0]
        for l in lits[1:]:
            out = ("and", out, l)
        return out
    return ast


def _definitions(src_preds: dict, tgt_preds: dict, matched_src: set) -> dict:
    """Define unmatched source predicates by <=2 target literals covering their lemmas."""
    defs = {}
    for p, a in src_preds.items():
        if p in matched_src:
            continue
        lp, negp = lemmas(p)
        if not lp:
            continue
        cands = [q for q, b in tgt_preds.items() if b == a and lemmas(q)[0] and lemmas(q)[0] <= lp]
        found = None
        for k in (1, 2):
            for combo in itertools.combinations(cands, k):
                cov = frozenset().union(*[lemmas(q)[0] for q in combo])
                if cov >= lp and (k == 2 or cov == lp):
                    found = combo
                    break
            if found:
                break
        if found:
            lits = []
            for q in found:
                lq, negq = lemmas(q)
                owner = True if len(found) == 1 else _neg_owner(p, q)
                lits.append(((negp and owner) != negq, q))
            defs[p] = lits
    return defs


def _neg_owner(p: str, q: str) -> bool:
    """For 2-literal definitions, the negation of p attaches to the literal whose lemmas follow the marker."""
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", p).lower().replace("_", " ")
    m = re.search(r"\b(not|non|never|no|un|none)\s*([a-z]+)", s) or re.search(r"\b(un|non)([a-z]+)", s)
    if not m:
        return False
    word = m.group(2)
    lq, _ = lemmas(q)
    if _LEM is not None:
        word = _LEM.lemmatize(_LEM.lemmatize(word, "v"), "n")
    return word in lq


def granular_equivalence(cand_ast: tuple, gold_ast: tuple, time_limit: float = 20.0) -> dict:
    C = normalize_arity_overloads(cand_ast)
    G = normalize_arity_overloads(gold_ast)
    cp, _ = signature(C)
    gp, _ = signature(G)
    # 1:1 lexical partners (same arity, same lemma set) are left to the bijection
    same = lambda p, q: cp[p] == gp[q] and lemmas(p)[0] and lemmas(p) == lemmas(q)  # noqa: E731 (lemmas AND polarity)
    matched_c = {p for p in cp if any(same(p, q) for q in gp)}
    matched_g = {q for q in gp if any(same(p, q) for p in cp)}
    defs_c = _definitions(cp, gp, matched_c)      # candidate compounds defined by gold literals
    used_g = {q for lits in defs_c.values() for _, q in lits}
    defs_g = _definitions(gp, {p: a for p, a in cp.items() if p not in defs_c},
                          matched_g | used_g)      # gold compounds defined by candidate literals
    if not defs_c and not defs_g:
        return {"status": "not_applicable", "definitions": {}}
    C2 = _substitute(C, defs_c)
    G2 = _substitute(G, defs_g)
    # pinned names: gold names introduced into the candidate, candidate names introduced into the gold
    fixed = {}
    for lits in defs_c.values():
        for _, q in lits:
            fixed[q] = q
    for lits in defs_g.values():
        for _, p in lits:
            fixed[p] = p
    # a pinned name must exist on both sides after substitution
    cp2, _ = signature(C2)
    gp2, _ = signature(G2)
    fixed = {k: v for k, v in fixed.items() if k in gp2 and v in cp2}
    r = equivalence(C2, G2, time_limit=time_limit, fixed=fixed, want_entailment=False)
    defs_txt = {**{f"cand:{p}": " ∧ ".join(("¬" if n else "") + q for n, q in l) for p, l in defs_c.items()},
                **{f"gold:{q}": " ∧ ".join(("¬" if n else "") + p for n, p in l) for q, l in defs_g.items()}}
    st = "equiv_granular" if r["status"] in ("equiv_proved", "equiv_bounded") else "non_equiv"
    return {"status": st, "definitions": defs_txt, "inner_status": r["status"]}
