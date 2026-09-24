"""Deterministic verbalizer for ground facts over FOL predicate names (shared by TVJT and instance-NLI).

Head-word category: WordNet sense-count vote (noun / verb / adjective, participles -> adjective), spaCy
tag as tie-breaker. Templates: VERB '{a} barks', ADJ '{a} is trained', NOUN '{a} is a dog'; binary
'{a} schedules {b}', trailing preposition '{a} is located in {b}', NOUN '{a} is the parent of {b}'.
GLOSS variant substitutes individuals into Logic-LM predicate glosses ('x is a composer').
"""
from __future__ import annotations

import os as _os
from pathlib import Path as _Path

_os.environ.setdefault("NLTK_DATA", str(_Path(__file__).resolve().parents[1] / "nltk_data"))

import re
from functools import lru_cache

FRESH = ["Alex", "Blair", "Casey", "Drew", "Emery", "Frankie", "Gale", "Harper"]
PREPS = {"of", "in", "at", "to", "on", "with", "from", "by", "for", "as", "about", "into", "under", "than", "over"}
AUXES = {"is", "are", "was", "has", "have", "can", "does", "do", "will", "had", "were", "be"}
IRREG_3SG = {"have": "has", "be": "is", "do": "does", "go": "goes"}
IRREG_NEG_BASE = {"has": "have", "is": "be", "does": "do", "was": "be"}


def split_name(n: str) -> list[str]:
    s = n.replace("_", " ").replace("-", " ")
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)
    s = re.sub(r"([A-Za-z])([0-9])", r"\1 \2", s)
    s = re.sub(r"([0-9])([A-Za-z])", r"\1 \2", s)
    return [w.lower() for w in s.split() if w]


def const_name(c: str) -> str:
    ws = split_name(c)
    return " ".join(w.capitalize() for w in ws) if ws else c


@lru_cache(maxsize=1)
def _nlp():
    import spacy
    return spacy.load("en_core_web_sm", disable=["ner", "parser", "lemmatizer"])


@lru_cache(maxsize=1)
def _wn():
    try:
        from nltk.corpus import wordnet as wn
        wn.synsets("dog")
        return wn
    except LookupError:
        return None


@lru_cache(maxsize=20000)
def head_category(words: tuple[str, ...], arity: int = 1) -> tuple[str, bool]:
    """Returns (category in {VERB, VERB3, VERBPAST, ADJ, NOUN, AUX}, x_or_punct_flag).
    WordNet sense-frequency vote: adjective if it dominates; verb if verb counts exceed half the noun
    counts (unary) or any verb sense exists (binary); inflected verbs (reads / wrote) detected via morphy."""
    w = words[0]
    if w in AUXES:
        return "AUX", False
    doc = _nlp()(" ".join(words))
    tag, pos = doc[0].tag_, doc[0].pos_
    bad = pos in ("X", "PUNCT", "SYM", "NUM")
    wn = _wn()
    if w.endswith("ed") and len(w) > 4 and (wn is None or wn.morphy(w, "v") not in (None, w)):
        return "ADJ", bad
    if wn is not None:
        cnt = {"n": 0, "v": 0, "a": 0}
        for pos_key, cat in (("n", "n"), ("v", "v"), ("a", "a"), ("s", "a")):
            for syn in wn.synsets(w, pos=pos_key):
                for lem in syn.lemmas():
                    if lem.name().lower() == w:
                        cnt[cat] += lem.count() + 1
        if max(cnt.values()) == 0:
            base = wn.morphy(w, "v")
            if base and base != w:
                return ("VERB3" if w.endswith("s") else "VERBPAST"), bad
        else:
            if cnt["a"] >= max(cnt["n"], cnt["v"]):
                cat1 = "ADJ"
            elif (arity == 1 and cnt["v"] > 0.5 * cnt["n"]) or (arity >= 2 and cnt["v"] > 0):
                cat1 = "VERB"
            else:
                cat1 = "NOUN"
            last = words[-1]
            if (len(words) > 1 and arity == 1 and cat1 in ("ADJ", "NOUN") and last not in PREPS
                    and (wn.synsets(last, pos="n") or wn.morphy(last, "n"))):
                return "NOUN", bad  # compound noun phrase 'wild turkey', 'talent shows'
            return cat1, bad
    if pos in ("VERB", "AUX"):
        return "VERB", bad
    if pos == "ADJ" or tag in ("VBN", "VBG", "JJ"):
        return "ADJ", bad
    return "NOUN", bad


def verb_base(w: str) -> str:
    wn = _wn()
    b = wn.morphy(w, "v") if wn is not None else None
    return IRREG_NEG_BASE.get(w, b or w)


def singular(ws: list[str]) -> list[str]:
    wn = _wn()
    last = ws[-1]
    if wn is not None and last.endswith("s") and not last.endswith("ss"):
        b = wn.morphy(last, "n")
        if b and b != last:
            return ws[:-1] + [b]
    return ws


def third_sg(v: str) -> str:
    if v in IRREG_3SG:
        return IRREG_3SG[v]
    if v.endswith("ed") or v.endswith("s") and not v.endswith("ss"):
        return v
    if re.search(r"(s|sh|ch|x|z|o)$", v):
        return v + "es"
    if re.search(r"[^aeiou]y$", v):
        return v[:-1] + "ies"
    return v + "s"


def article(w: str) -> str:
    return "an" if w[:1] in "aeiou" else "a"


def pred_fail(name: str) -> bool:
    ws = split_name(name)
    if not ws or len(ws) > 6 or any(not w.isalpha() for w in ws):
        return True
    return head_category(tuple(ws))[1]


def fact(pred: str, args: list[str], positive: bool = True, glosses: dict | None = None) -> str:
    """One ground literal as an English sentence (no trailing period)."""
    if glosses and pred in glosses:
        g = gloss_fact(glosses[pred], args)
        if g is not None:
            if positive:
                return g
            first = g.split()[0] if g.split() else ""
            keep = any(first == a.split()[0] for a in args)
            return f"It is not the case that {g if keep else g[:1].lower() + g[1:]}"
    ws = split_name(pred) or [pred.lower()]
    if len(args) == 0:
        s = " ".join(ws)
        return f"It is the case that {s}" if positive else f"It is not the case that {s}"
    cat, _ = head_category(tuple(ws), min(len(args), 2))
    a = args[0]
    rest = " ".join(ws[1:])
    if len(args) == 1:
        if cat == "AUX":
            if positive:
                return f"{a} {' '.join(ws)}"
            return f"{a} {ws[0]} not {rest}".rstrip()
        if cat in ("VERB", "VERB3"):
            if positive:
                return f"{a} {third_sg(ws[0]) if cat == 'VERB' else ws[0]} {rest}".rstrip()
            return f"{a} does not {verb_base(ws[0])} {rest}".rstrip()
        if cat == "VERBPAST":
            s = f"{a} {' '.join(ws)}"
            return s if positive else f"It is not the case that {s}"
        if cat == "ADJ":
            return f"{a} is {'' if positive else 'not '}{' '.join(ws)}"
        ws2 = singular(ws)
        return f"{a} is {'' if positive else 'not '}{article(ws2[0])} {' '.join(ws2)}"
    if len(args) == 2:
        b = args[1]
        if ws[-1] in PREPS and len(ws) >= 2:
            cat = head_category(tuple(ws), 1)[0]  # 'ParentOf' -> noun reading, 'BelongTo' -> verb reading
            if cat in ("VERB", "VERB3"):
                s = f"{a} {third_sg(ws[0]) if cat == 'VERB' else ws[0]} {rest} {b}"
            elif cat == "VERBPAST":
                s = f"{a} {' '.join(ws)} {b}"
            else:
                s = f"{a} is {' '.join(ws)} {b}"
        elif cat in ("VERB", "VERB3"):
            s = f"{a} {third_sg(ws[0]) if cat == 'VERB' else ws[0]} {rest + ' ' if rest else ''}{b}"
        elif cat in ("VERBPAST", "AUX"):
            s = f"{a} {' '.join(ws)} {b}"
        elif cat == "ADJ":
            s = f"{a} is {' '.join(ws)} {b}"
        else:
            s = f"{a} is the {' '.join(ws)} of {b}"
        return s if positive else f"It is not the case that {s}"
    s = f"{', '.join(args[:-1])} and {args[-1]} are in the '{' '.join(ws)}' relation"
    return s if positive else f"It is not the case that {s}"


def parse_gloss_head(head: str) -> tuple[str, list[str]] | None:
    m = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)\s*$", head)
    if not m:
        return None
    return m.group(1), [x.strip() for x in m.group(2).split(",") if x.strip()]


def gloss_fact(gloss: dict, args: list[str]) -> str | None:
    params, text = gloss["params"], gloss["text"].strip().rstrip(".")
    if len(params) != len(args):
        return None
    out = text
    for p, a in zip(params, args):
        if not re.search(rf"\b{re.escape(p)}\b", out):
            return None
        out = re.sub(rf"\b{re.escape(p)}\b", f"\x00{a}\x00", out)
    out = out.replace("\x00", "")
    return out[0].upper() + out[1:] if out and out[0].islower() and out.split()[0] not in args else out


def individual_names(consts: list[str], n_extra: int) -> tuple[dict, list[str]]:
    names = {c: const_name(c) for c in consts}
    taken = {v.lower() for v in names.values()}
    fresh = [f for f in FRESH if f.lower() not in taken][:n_extra]
    return names, fresh
