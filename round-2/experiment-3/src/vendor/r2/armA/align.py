"""Lexical aligner between formula predicates/constants and text concepts (shared by A1/A2/A3/B4/B5).

pred_tokens(P)   camelCase/underscore split -> lowercase -> WordNet lemma -> drop stopwords
concept tokens   spaCy lemmas of head + compound/amod modifiers (+ WordNet lemmas of the same words)
overlap(P, c)    |pt ∩ ct| / |pt|;  P -> argmax_c overlap if >= 0.5, else MiniLM cosine >= 0.5, else unaligned
COMPOUND rule    (pre-registered) if pt overlaps >= 2 concepts, P is compared ONLY with the concept that
                 contains its LAST token (the head); the other overlapped concepts count as covered.
LEX-NEG rule     (pre-registered) un/non/in/im/dis/ir/il + X  vs  X  (either direction) or predicate name
                 starting with Not/Non/No/Un where the concept lacks the prefix -> aligned with sign_flip.
Thresholds (0.5 / 0.5) fixed a priori, never tuned on labels.
"""
from __future__ import annotations

import re

from nltk.stem import WordNetLemmatizer

_WNL = WordNetLemmatizer()
STOP = {"a", "an", "the", "of", "in", "on", "at", "to", "for", "with", "by", "from", "is", "are", "be", "and",
        "or", "has", "have", "do", "does", "can", "will", "was", "were", "as", "into", "that", "who", "which",
        "x", "y", "z", "it", "its", "their", "his", "her"}
NEG_PREFIX = ("un", "non", "in", "im", "dis", "ir", "il")
NEG_WORDS = {"not", "non", "no", "un"}
_EMB = {"model": None, "cache": {}}
# generic domain nouns / quantity adjectives: FOL may leave them implicit (the quantifier domain), so they are
# OPTIONAL concepts: compared if aligned, never counted as 'dropped', excluded from the coverage denominator if unaligned
OPTIONAL_LEMMAS = {"person", "people", "thing", "something", "someone", "somebody", "anyone", "anything", "everyone",
                   "everybody", "everything", "individual", "one", "entity", "least", "most", "many", "much", "more",
                   "few", "other", "same", "such", "own", "able", "certain", "number", "have", "take", "get", "make",
                   "do", "become", "lot", "part", "kind", "type"}


def is_optional(c: dict) -> bool:
    return c.get("head_lemma", "").lower() in OPTIONAL_LEMMAS


def split_name(name: str) -> list[str]:
    s = re.sub(r"[_#\-]", " ", name)
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)
    s = re.sub(r"([a-zA-Z])(\d)", r"\1 \2", s)
    return [w.lower() for w in s.split() if w]


def lem(w: str) -> str:
    n = _WNL.lemmatize(w, "n")
    if n != w:
        return n
    v = _WNL.lemmatize(w, "v")
    if v != w:
        return v
    return _WNL.lemmatize(w, "a")


def pred_tokens(name: str) -> list[str]:
    return [lem(w) for w in split_name(name) if w not in STOP]


def concept_tokens(c: dict) -> set:
    out = set()
    for t in c["tokens"]:
        out.add(t.lower())
        out.add(lem(t.lower()))
    for w in re.findall(r"[A-Za-z0-9]+", c["span"]):
        out.add(lem(w.lower()))
        out.add(w.lower())
    return out - STOP


def _embed(texts: list[str]):
    import numpy as np
    if _EMB["model"] is None:
        from sentence_transformers import SentenceTransformer
        import torch
        _EMB["model"] = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2",
                                            device="cuda" if torch.cuda.is_available() else "cpu")
    miss = [t for t in set(texts) if t not in _EMB["cache"]]
    if miss:
        vecs = _EMB["model"].encode(miss, batch_size=256, normalize_embeddings=True, show_progress_bar=False)
        for t, v in zip(miss, vecs):
            _EMB["cache"][t] = v
    return np.array([_EMB["cache"][t] for t in texts])


def prewarm(texts: list[str]):
    if texts:
        _embed(list(texts))


def cosine(a: str, b: str) -> float:
    v = _embed([a, b])
    return float(v[0] @ v[1])


def _negmatch(t: str, u: str) -> bool:
    for p in NEG_PREFIX:
        if (t == p + u and len(u) > 2) or (u == p + t and len(t) > 2):
            return True
    return False


def align(pred_arity: dict, const_names: list, concepts: list, use_emb: bool = True) -> dict:
    """Returns {preds: {P: {cid, flip, covered[], how}}, consts: {c: cid}, coverage, n_concepts}."""
    ncs = [c for c in concepts if not c["is_const"]]
    cons = [c for c in concepts if c["is_const"]]
    ctoks = {c["cid"]: concept_tokens(c) for c in concepts}
    out_p = {}
    for P in pred_arity:
        raw = split_name(P)
        flip_name = bool(raw) and raw[0] in NEG_WORDS and len(raw) > 1
        pt = [lem(w) for w in (raw[1:] if flip_name else raw) if w not in STOP] or [lem(w) for w in raw]
        if not pt:
            out_p[P] = {"cid": None, "flip": False, "covered": [], "how": "empty"}
            continue
        ov, negov = {}, {}
        for c in ncs + cons:
            ct = ctoks[c["cid"]]
            ov[c["cid"]] = len(set(pt) & ct) / len(pt) - (0.001 if c["is_const"] else 0.0)
            negov[c["cid"]] = sum(1 for t in pt if any(_negmatch(t, u) for u in ct)) / len(pt)
        hits = [cid for cid, v in ov.items() if v > 0]
        best = max(ov, key=lambda k: (ov[k], -k)) if ov else None
        if best is not None and ov[best] >= 0.5:
            if len(hits) >= 2:
                head = pt[-1]
                hc = [cid for cid in hits if head in ctoks[cid]]
                main = hc[0] if hc else best
                out_p[P] = {"cid": main, "flip": flip_name, "covered": [h for h in hits if h != main], "how": "compound"}
            else:
                out_p[P] = {"cid": best, "flip": flip_name, "covered": [], "how": "lexical"}
            continue
        nbest = max(negov, key=lambda k: (negov[k], -k)) if negov else None
        if nbest is not None and negov[nbest] >= 0.5:
            out_p[P] = {"cid": nbest, "flip": not flip_name, "covered": [], "how": "lexneg"}
            continue
        if use_emb and ncs:
            txt = " ".join(pt)
            sims = {c["cid"]: cosine(txt, c["span"]) for c in ncs}
            sb = max(sims, key=lambda k: (sims[k], -k))
            if sims[sb] >= 0.5:
                out_p[P] = {"cid": sb, "flip": flip_name, "covered": [], "how": f"minilm:{sims[sb]:.2f}"}
                continue
        out_p[P] = {"cid": None, "flip": False, "covered": [], "how": "unaligned"}
    out_c = {}
    for k in const_names:
        kt = [lem(w) for w in split_name(k) if w not in STOP] or split_name(k)
        best, bv = None, 0.0
        for c in cons + ncs:
            v = len(set(kt) & ctoks[c["cid"]]) / max(1, len(kt)) - (0.0 if c["is_const"] else 0.001)
            if v > bv:
                best, bv = c["cid"], v
        if best is not None and bv >= 0.5:
            out_c[k] = best
        elif use_emb and cons:
            sims = {c["cid"]: cosine(" ".join(kt), c["span"]) for c in cons}
            sb = max(sims, key=lambda q: sims[q])
            if sims[sb] >= 0.5:
                out_c[k] = sb
    covered = set()
    for a in out_p.values():
        if a["cid"] is not None:
            covered.add(a["cid"])
            covered |= set(a["covered"])
    covered |= set(out_c.values())
    denom = [c["cid"] for c in concepts if not (is_optional(c) and c["cid"] not in covered)]
    n = len(denom)
    return {"preds": out_p, "consts": out_c, "coverage": (len(covered & set(denom)) / n) if n else 0.0, "n_concepts": n,
            "covered_cids": sorted(covered)}
