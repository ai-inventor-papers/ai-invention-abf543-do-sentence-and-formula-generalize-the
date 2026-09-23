"""R1: renaming-robust, polarity-blind aligner between formula symbols and text concepts.

sim(c, P) = max( lex(c,P), wn(c,P), emb(c,P), lexneg(c,P) ) + arity_term(c,P)
  lex     iter-1 lemma/camelCase overlap |pt ∩ ct| / |pt|           (pt = predicate tokens, ct = concept tokens)
  wn      max over (concept head lemma h, predicate token t) of WordNet similarity (wup or path) between
          same-POS synsets (noun/verb/adj), with derivationally related forms folded in (teach/teacher);
          capped at 0.95 for non-identical lemmas
  emb     cosine( SBERT(concept phrase), SBERT(' '.join(split_name(P))) )  (all-MiniLM-L6-v2 or all-mpnet-base-v2)
  lexneg  iter-1 lexical-negation morpheme test (un/non/in/im/dis/ir/il + X vs X). A LEXICAL test on the
          predicate NAME: if it is what aligns P, the alignment carries flip=True (Unfit vs 'fit').
  arity_term = +β if (concept is a verb with ≥2 role arguments AND arity(P) ≥ 2) or (concept is a
          noun/adjective AND arity(P) == 1); −β if mismatched (verb with ≥2 roles vs unary P, or noun/adj vs
          k≥2-ary P); else 0.  β ∈ {0, 0.1}.
NO polarity, negation-context or sign information of the SENTENCE enters sim: it depends only on the concept's
lemmas/span/POS/role count and the symbol's name/arity (tested in tests/test_align2.py).

Assignment
  (1) scipy.optimize.linear_sum_assignment on cost = 1 − sim over concepts × (predicates + constants), padded
      with one dummy column per concept at cost 1 − τ, so pairs with sim < τ stay unassigned;
  (2) second pass: each still-unassigned symbol joins its argmax concept if sim ≥ τ2 = τ + 0.1 (splits allowed:
      one concept, several predicates);
  (3) compound coverage as iter-1: other concepts that a predicate's tokens lexically overlap count as 'covered'.
Output format = legacy align.align, so score.signature_score runs unchanged.
"""
from __future__ import annotations

import re
from functools import lru_cache

import numpy as np
from scipy.optimize import linear_sum_assignment

from align import NEG_WORDS, STOP, _negmatch, concept_tokens, is_optional, lem, split_name  # legacy (iter-1)

DEFAULT_CFG = {"tau": 0.45, "wn": "wup", "emb": "sentence-transformers/all-MiniLM-L6-v2", "beta": 0.0}
_EMB: dict = {}
_ECACHE: dict = {}


# ---------------------------------------------------------------- embeddings
def _model(name: str):
    if name not in _EMB:
        from sentence_transformers import SentenceTransformer
        _EMB[name] = SentenceTransformer(name, device="cpu")
    return _EMB[name]


def embed(texts: list[str], model: str) -> np.ndarray:
    miss = sorted({t for t in texts if (model, t) not in _ECACHE})
    if miss:
        vecs = _model(model).encode(miss, batch_size=256, normalize_embeddings=True, show_progress_bar=False)
        for t, v in zip(miss, vecs):
            _ECACHE[(model, t)] = v
    return np.array([_ECACHE[(model, t)] for t in texts])


def prewarm(texts, model: str):
    t = [x for x in set(texts) if x]
    if t:
        embed(t, model)


# ---------------------------------------------------------------- WordNet
def _wn():
    from nltk.corpus import wordnet as wn
    return wn


@lru_cache(maxsize=200000)
def _synsets(word: str) -> tuple:
    wn = _wn()
    out = []
    for pos in (wn.NOUN, wn.VERB, wn.ADJ):
        out += wn.synsets(word, pos=pos)[:4]
    return tuple(out)


@lru_cache(maxsize=200000)
def _deriv(word: str) -> frozenset:
    """Lemma names derivationally related to `word` (teach <-> teacher), incl. adj satellites/pertainyms."""
    out = set()
    for s in _synsets(word):
        for l in s.lemmas():
            if l.name().lower() != word:
                continue
            for d in l.derivationally_related_forms():
                out.add(d.name().lower())
            for p in l.pertainyms():
                out.add(p.name().lower())
    return frozenset(out)


@lru_cache(maxsize=400000)
def wn_sim(a: str, b: str, measure: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if b in _deriv(a) or a in _deriv(b):
        return 0.95
    best = 0.0
    sa, sb = _synsets(a), _synsets(b)
    for x in sa:
        for y in sb:
            px, py = x.pos().replace("s", "a"), y.pos().replace("s", "a")
            if px != py:
                continue
            try:
                v = x.wup_similarity(y) if measure == "wup" else x.path_similarity(y)
            except Exception:  # noqa: BLE001  (nltk raises on some cross-hierarchy verb pairs)
                v = None
            if v and v > best:
                best = v
    return min(best, 0.95)


# ---------------------------------------------------------------- per-symbol features
def symbol_tokens(name: str) -> tuple[list[str], bool, list[str]]:
    """(tokens used for matching, name-level negation flag, raw split)."""
    raw = split_name(name)
    flip_name = bool(raw) and raw[0] in NEG_WORDS and len(raw) > 1
    pt = [lem(w) for w in (raw[1:] if flip_name else raw) if w not in STOP] or [lem(w) for w in raw]
    return pt, flip_name, raw


def concept_phrase(c: dict) -> str:
    toks = [t for t in c["tokens"] if t]
    return " ".join(toks) if toks else c["span"].lower()


def n_roles(concepts: list, anchors: list) -> dict:
    out: dict = {}
    for a in anchors or []:
        out.setdefault(a["verb_cid"], set()).add(a["slot"])
    return {k: len(v) for k, v in out.items()}


def arity_term(c: dict, arity: int | None, roles: int, beta: float) -> float:
    if beta == 0 or arity is None:
        return 0.0
    if c["pos"] == "VERB" and roles >= 2:
        return beta if arity >= 2 else -beta
    if c["pos"] in ("NOUN", "ADJ"):
        return beta if arity == 1 else (-beta if arity >= 2 else 0.0)
    return 0.0


def sim_matrix(syms: list[tuple[str, int | None]], concepts: list, anchors: list, cfg: dict) -> tuple:
    """Returns (S [n_concepts x n_syms], LEX, NEG matrices, flipname list, how matrix)."""
    nc, ns = len(concepts), len(syms)
    S = np.zeros((nc, ns))
    LEX = np.zeros((nc, ns))
    NEG = np.zeros((nc, ns))
    HOW = [[""] * ns for _ in range(nc)]
    if nc == 0 or ns == 0:
        return S, LEX, NEG, [], HOW
    ctoks = [concept_tokens(c) for c in concepts]
    heads = [c.get("head_lemma", "").lower() for c in concepts]
    phrases = [concept_phrase(c) for c in concepts]
    roles = n_roles(concepts, anchors)
    info = [symbol_tokens(n) for n, _ in syms]
    sym_txt = [" ".join(w for w in raw if w) or n.lower() for (n, _), (_, _, raw) in zip(syms, info)]
    E_c = embed(phrases, cfg["emb"])
    E_s = embed(sym_txt, cfg["emb"])
    EMB = E_c @ E_s.T
    for j, ((name, ar), (pt, flip_name, raw)) in enumerate(zip(syms, info)):
        for i, c in enumerate(concepts):
            ct = ctoks[i]
            lx = len(set(pt) & ct) / len(pt) if pt else 0.0
            ng = (sum(1 for t in pt if any(_negmatch(t, u) for u in ct)) / len(pt)) if pt else 0.0
            wv = max((wn_sim(heads[i], t, cfg["wn"]) for t in pt if len(t) > 2), default=0.0)
            ev = float(EMB[i, j])
            parts = {"lex": lx, "wn": wv, "emb": ev, "lexneg": ng}
            how = max(parts, key=parts.get)
            S[i, j] = parts[how] + (arity_term(c, ar, roles.get(c["cid"], 0), cfg["beta"]) if ar is not None else 0.0)
            LEX[i, j], NEG[i, j] = lx, ng
            HOW[i][j] = f"{how}:{parts[how]:.2f}"
    return S, LEX, NEG, [f for _, f, _ in info], HOW


def align2(pred_arity: dict, const_names: list, concepts: list, anchors: list | None = None,
           cfg: dict | None = None) -> dict:
    """Returns legacy-format {preds: {P: {cid, flip, covered[], how}}, consts: {c: cid}, coverage, n_concepts,
    covered_cids}."""
    cfg = {**DEFAULT_CFG, **(cfg or {})}
    tau = cfg["tau"]
    tau2 = tau + 0.1
    syms = [(P, k) for P, k in pred_arity.items()] + [(k, None) for k in const_names]
    npred = len(pred_arity)
    S, LEX, NEG, flipname, HOW = sim_matrix(syms, concepts, anchors or [], cfg)
    nc, ns = S.shape if len(concepts) and len(syms) else (len(concepts), len(syms))
    assign: dict[int, int] = {}  # sym index -> concept index
    if nc and ns:
        cost = np.hstack([1.0 - S, np.full((nc, nc), 1.0 - tau)])
        r, c = linear_sum_assignment(cost)
        for i, j in zip(r, c):
            if j < ns and S[i, j] >= tau:
                assign[j] = i
        for j in range(ns):
            if j in assign:
                continue
            i = int(np.argmax(S[:, j]))
            if S[i, j] >= tau2:
                assign[j] = i
    out_p, out_c = {}, {}
    for j, (name, ar) in enumerate(syms):
        is_pred = j < npred
        if j not in assign:
            if is_pred:
                out_p[name] = {"cid": None, "flip": False, "covered": [], "how": "unaligned"}
            continue
        i = assign[j]
        cid = concepts[i]["cid"]
        if not is_pred:
            out_c[name] = cid
            continue
        lexneg = NEG[i, j] >= 0.5 and LEX[i, j] < 0.5
        flip = (not flipname[j]) if lexneg else flipname[j]
        cov = [concepts[k]["cid"] for k in range(nc) if k != i and LEX[k, j] > 0]
        out_p[name] = {"cid": cid, "flip": bool(flip), "covered": cov, "how": HOW[i][j]}
    covered = set()
    for a in out_p.values():
        if a["cid"] is not None:
            covered.add(a["cid"])
            covered |= set(a["covered"])
    covered |= set(out_c.values())
    denom = [c["cid"] for c in concepts if not (is_optional(c) and c["cid"] not in covered)]
    n = len(denom)
    return {"preds": out_p, "consts": out_c, "coverage": (len(covered & set(denom)) / n) if n else 0.0,
            "n_concepts": n, "covered_cids": sorted(covered)}


def grid() -> list[dict]:
    out = []
    for tau in (0.35, 0.45, 0.55):
        for wn in ("wup", "path"):
            for emb in ("sentence-transformers/all-MiniLM-L6-v2", "sentence-transformers/all-mpnet-base-v2"):
                for beta in (0.0, 0.1):
                    out.append({"tau": tau, "wn": wn, "emb": emb, "beta": beta})
    return out


def cfg_name(cfg: dict) -> str:
    e = "L6" if "MiniLM" in cfg["emb"] else "mpnet"
    return f"t{cfg['tau']}_{cfg['wn']}_{e}_b{cfg['beta']}" + (f"_{cfg['tag']}" if cfg.get("tag") else "")


def simplicity(cfg: dict) -> tuple:
    """Lower = simpler (tie-break of the pre-registered selection rule)."""
    return (cfg["beta"] != 0.0, "mpnet" in cfg["emb"], cfg["wn"] != "wup", abs(cfg["tau"] - 0.45))


_ = re  # keep import (used by callers that patch split rules)
