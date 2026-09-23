"""Text side of the monotonicity signature.

extract(sentence) -> dict with
  concepts : [{cid, head_i, head_lemma, tokens(lemmas of head+compound/amod), span, pos, role, is_const}]
  anchors  : [{verb_cid, slot, arg_cid}]  (UD: nsubj->0, obj/dobj/pobj-of-verb-prep/attr->1, passive swapped)
  copies   : per non-constant concept, specialised copies m1/m2 (deterministic templates; LLM never rewrites)
  relpairs : up to 4 (c, q) pairs with relative-clause copies for A2 ('c that is q' / 'c that is not q')
  coord    : [(c, q, 'and'|'or'|'xor')] coordination pairs (for A3 relativized coordinates)
probe_questions(ex) -> list of (qid, premise, hypothesis) numbered substitution-entailment questions
labels_from_answers(ex, answers) -> T = {concept_labels, rel_labels, consistency}
rules_marker(ex) -> A3 zero-LLM polarity per concept (+ / − / ±) from a compact monotonicity calculus
"""
from __future__ import annotations

import re

import spacy

_NLP = None
MODS = {"NOUN": ("European", "young"), "VERB": ("on Mondays", "in Europe"), "ADJ": ("very", "European and")}
UNIV = {"every", "all", "each", "any"}
NEGDET = {"no", "none", "neither"}
EXCL_VERB_CHILD = {"advcl", "relcl", "conj", "ccomp", "cc", "punct", "mark", "xcomp", "parataxis"}


def nlp():
    global _NLP
    if _NLP is None:
        _NLP = spacy.load("en_core_web_sm", disable=["ner"])
    return _NLP


def _subtree_ids(tok, exclude_deps=()):
    out = {tok.i}
    for ch in tok.children:
        if ch.dep_ in exclude_deps:
            continue
        out |= {t.i for t in ch.subtree}
    return out


def extract(sent: str) -> dict:
    doc = nlp()(sent)
    concepts = []
    seen = set()

    def add(tok, pos, is_const=False):
        if tok.i in seen or not (tok.text.isalpha() or tok.pos_ == "NUM" or tok.like_num):
            return
        seen.add(tok.i)
        mods = [c for c in tok.children if c.dep_ in ("compound", "amod") and c.pos_ in ("NOUN", "PROPN", "ADJ", "VERB")]
        toks = [m.lemma_.lower() for m in mods] + [tok.lemma_.lower()]
        left = min([tok.i] + [m.i for m in mods if m.dep_ == "compound"])
        span = doc[left: tok.i + 1].text
        concepts.append({"cid": len(concepts), "head_i": tok.i, "head_lemma": tok.lemma_.lower(), "tokens": toks,
                         "span": span, "pos": pos, "role": tok.dep_, "is_const": is_const, "tag": tok.tag_,
                         "left_i": left})
        for m in mods:
            seen.add(m.i) if m.dep_ == "compound" else None

    for tok in doc:
        if tok.pos_ == "PROPN" and tok.dep_ != "compound":
            add(tok, "PROPN", is_const=True)
        elif tok.pos_ == "NOUN" and tok.dep_ != "compound":
            add(tok, "NOUN")
        elif tok.pos_ == "VERB" and tok.dep_ not in ("aux", "auxpass"):
            add(tok, "VERB")
        elif tok.pos_ == "ADJ" and tok.dep_ != "amod":
            add(tok, "ADJ")
        elif tok.pos_ == "ADJ" and tok.dep_ == "amod" and tok.head.pos_ in ("NOUN", "PROPN"):
            # attributive adjectives are part of the noun concept tokens but also their own concept
            add(tok, "ADJ")
    # numbers as constants
    for tok in doc:
        if tok.pos_ == "NUM" and tok.i not in seen:
            add(tok, "PROPN", is_const=True)
    # cap at 10 non-constant concepts, prioritise restrictor/scope content words (subject/object/root)
    nonc = [c for c in concepts if not c["is_const"]]
    if len(nonc) > 10:
        prio = {"nsubj": 0, "nsubjpass": 0, "ROOT": 0, "dobj": 1, "attr": 1, "acomp": 1, "relcl": 1, "pobj": 2}
        keep = sorted(nonc, key=lambda c: (prio.get(c["role"], 3), c["head_i"]))[:10]
        keepi = {c["head_i"] for c in keep}
        concepts = [c for c in concepts if c["is_const"] or c["head_i"] in keepi]
        for j, c in enumerate(concepts):
            c["cid"] = j
    by_i = {c["head_i"]: c["cid"] for c in concepts}

    # role anchors
    anchors = []
    for c in concepts:
        if c["pos"] != "VERB":
            continue
        v = doc[c["head_i"]]
        for ch in v.children:
            tgt = _content_head(ch)
            if tgt is None or tgt.i not in by_i:
                continue
            if ch.dep_ in ("nsubj",):
                slot = 0
            elif ch.dep_ in ("nsubjpass",):
                slot = 1
            elif ch.dep_ in ("dobj", "obj", "attr", "dative"):
                slot = 1
            elif ch.dep_ == "agent":
                pobj = [g for g in ch.children if g.dep_ == "pobj"]
                if not pobj or pobj[0].i not in by_i:
                    continue
                tgt, slot = pobj[0], 0
            elif ch.dep_ == "prep":
                pobj = [g for g in ch.children if g.dep_ == "pobj"]
                if not pobj or pobj[0].i not in by_i:
                    continue
                tgt, slot = pobj[0], 1
            else:
                continue
            anchors.append({"verb_cid": c["cid"], "slot": slot, "arg_cid": by_i[tgt.i]})
        # relcl: head noun is subject of the relative verb (who/that as nsubj)
        if v.dep_ == "relcl" and v.head.i in by_i:
            rel_subj = [g for g in v.children if g.dep_ in ("nsubj",) and g.tag_ in ("WP", "WDT")]
            rel_obj = [g for g in v.children if g.dep_ in ("dobj",) and g.tag_ in ("WP", "WDT")]
            if rel_subj:
                anchors.append({"verb_cid": c["cid"], "slot": 0, "arg_cid": by_i[v.head.i]})
            elif rel_obj:
                anchors.append({"verb_cid": c["cid"], "slot": 1, "arg_cid": by_i[v.head.i]})
    # dedupe
    seen_a = set()
    anchors = [a for a in anchors if not ((a["verb_cid"], a["slot"], a["arg_cid"]) in seen_a or
                                          seen_a.add((a["verb_cid"], a["slot"], a["arg_cid"])))]

    # coordination pairs
    coord = []
    for c in concepts:
        t = doc[c["head_i"]]
        if t.dep_ == "conj" and t.head.i in by_i:
            ccs = [g.lower_ for g in t.head.children if g.dep_ == "cc"] + [g.lower_ for g in t.children if g.dep_ == "cc"]
            pre = [g.lower_ for g in t.head.children if g.dep_ == "preconj"]
            kind = "xor" if "either" in pre else ("or" if any(x in ("or", "nor") for x in ccs) else "and")
            coord.append((by_i[t.head.i], c["cid"], kind))

    ex = {"sentence": sent, "tokens": [t.text for t in doc], "ws": [t.whitespace_ for t in doc],
          "concepts": concepts, "anchors": anchors, "coord": coord}
    ex["copies"] = _copies(doc, concepts)
    ex["relpairs"] = _relpairs(doc, concepts, coord)
    ex["marker"] = rules_marker(doc, concepts)
    return ex


def _content_head(tok):
    if tok.pos_ in ("NOUN", "PROPN", "VERB", "ADJ", "NUM"):
        return tok
    return None


def _render(doc, inserts: dict, replace: dict | None = None) -> str:
    """inserts: {token_index: (before_text, after_text)}; replace: {token_index: text}."""
    replace = replace or {}
    out = []
    for t in doc:
        b, a = inserts.get(t.i, ("", ""))
        word = replace.get(t.i, t.text)
        piece = (b + " " if b else "") + word + (" " + a if a else "")
        out.append(piece + t.whitespace_)
    s = "".join(out).strip()
    s = re.sub(r"\b([Aa]) ((?!Eu|eu|uni|Uni|use|one)[aeiouAEIOU])", r"\1n \2", s)
    s = re.sub(r"\b([Aa])n ([^aeiouAEIOU\W]|Eu|eu)", r"\1 \2", s)
    return re.sub(r"\s+", " ", s)


def _copies(doc, concepts) -> dict:
    out = {}
    low = doc.text.lower()
    for c in concepts:
        if c["is_const"]:
            continue
        pos = c["pos"]
        head = doc[c["head_i"]]
        copies = []
        for mi, m in enumerate(MODS[pos]):
            if pos == "NOUN":
                if m.lower() in low:
                    m = "Asian" if mi == 0 else "old"
                txt = _render(doc, {c["left_i"]: (m, "")})
            elif pos == "VERB":
                ids = _subtree_ids(head, EXCL_VERB_CHILD)
                ids = {i for i in ids if doc[i].dep_ != "punct"}
                right = max(ids)
                txt = _render(doc, {right: ("", m)})
            else:  # ADJ
                txt = _render(doc, {head.i: (m, "")})
            copies.append(txt)
        out[c["cid"]] = copies
    return out


def _relpairs(doc, concepts, coord, cap: int = 4) -> list:
    by_cid = {c["cid"]: c for c in concepts}
    pairs = []
    for a, b, kind in coord:
        if kind == "xor":
            continue
        pairs.append((a, b))
        pairs.append((b, a))
    uniq = []
    for p in pairs:
        if p not in uniq:
            uniq.append(p)
    out = []
    for ci, qi in uniq:
        c, q = by_cid[ci], by_cid[qi]
        if c["is_const"] or q["is_const"] or c["pos"] != "NOUN":
            continue
        plural = c["tag"] in ("NNS", "NNPS")
        be = "are" if plural else "is"
        qt = doc[q["head_i"]]
        if q["pos"] == "VERB":
            pos_phrase = f"that {qt.text}"
            neg_phrase = f"that {'do' if plural else 'does'} not {qt.lemma_}"
        elif q["pos"] == "ADJ":
            pos_phrase = f"that {be} {qt.text}"
            neg_phrase = f"that {be} not {qt.text}"
        else:
            art = "" if plural else ("an " if qt.text[:1].lower() in "aeiou" else "a ")
            pos_phrase = f"that {be} {art}{q['span']}"
            neg_phrase = f"that {be} not {art}{q['span']}"
        head = doc[c["head_i"]]
        ids = {i for i in _subtree_ids(head, ("conj", "cc", "punct", "relcl", "acl", "appos")) if doc[i].dep_ != "punct"}
        right = max(ids)
        s_out = _render(doc, {right: ("", pos_phrase)})   # P ∧ Q : P changes only OUTSIDE Q
        s_in = _render(doc, {right: ("", neg_phrase)})    # P ∧ ¬Q: P changes only INSIDE Q
        out.append({"c": ci, "q": qi, "copy_out": s_out, "copy_in": s_in})
        if len(out) >= cap:
            break
    return out


# ------------------------------------------------------------------ LLM probe
PROBE_INSTR = ("Treat each statement as a strict logical claim; ignore world knowledge beyond word meaning. "
               "For each numbered pair, answer whether statement A logically guarantees statement B (yes/no). "
               "Return JSON {\"1\":\"yes\",...}.")


def probe_questions(ex: dict, with_rel: bool = True) -> list:
    qs = []
    for cid, copies in ex["copies"].items():
        for mi, sp in enumerate(copies):
            qs.append({"key": ("c", int(cid), mi, "down"), "A": ex["sentence"], "B": sp})
            qs.append({"key": ("c", int(cid), mi, "up"), "A": sp, "B": ex["sentence"]})
    if with_rel:
        for rp in ex["relpairs"]:
            for side, sp in (("out", rp["copy_out"]), ("in", rp["copy_in"])):
                qs.append({"key": ("r", rp["c"], rp["q"], side, "down"), "A": ex["sentence"], "B": sp})
                qs.append({"key": ("r", rp["c"], rp["q"], side, "up"), "A": sp, "B": ex["sentence"]})
    return qs


def render_prompt(qs: list, offset: int = 0) -> str:
    lines = [PROBE_INSTR, ""]
    for j, q in enumerate(qs):
        lines.append(f"{j + 1 + offset}. A: {q['A']}\n   B: {q['B']}")
    return "\n".join(lines)


def parse_answers(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {}
    import json
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        d = dict(re.findall(r'"(\d+)"\s*:\s*"(yes|no)"', m.group(0), re.I))
    return {int(k): str(v).strip().lower().startswith("y") for k, v in d.items() if str(k).isdigit()}


def _lab(down: bool | None, up: bool | None) -> str:
    if down is None or up is None:
        return "?"
    return {(True, False): "-", (False, True): "+", (True, True): "0", (False, False): "±"}[(down, up)]


def labels_from_answers(ex: dict, qs: list, ans: dict) -> dict:
    by_key = {}
    for j, q in enumerate(qs):
        by_key[q["key"]] = ans.get(j + 1)
    concept_labels, per_mod = {}, {}
    n_cons = n_tot = 0
    for cid in ex["copies"]:
        cid = int(cid)
        labs = [_lab(by_key.get(("c", cid, mi, "down")), by_key.get(("c", cid, mi, "up"))) for mi in (0, 1)]
        per_mod[cid] = labs
        if "?" in labs:
            concept_labels[cid] = "?"
            continue
        n_tot += 1
        if labs[0] == labs[1]:
            n_cons += 1
            concept_labels[cid] = labs[0]
        else:
            concept_labels[cid] = "?"
    rel_labels = {}
    for rp in ex["relpairs"]:
        for side in ("out", "in"):
            rel_labels[(rp["c"], rp["q"], side)] = _lab(by_key.get(("r", rp["c"], rp["q"], side, "down")),
                                                        by_key.get(("r", rp["c"], rp["q"], side, "up")))
    return {"concept_labels": concept_labels, "per_mod": per_mod, "rel_labels": rel_labels,
            "consistency": (n_cons / n_tot) if n_tot else None}


# ------------------------------------------------------------------ A3 zero-LLM marker
def rules_marker(doc, concepts) -> dict:
    """Compact monotonicity calculus over the spaCy parse (A3-rules). Returns {cid: '+'|'-'|'±'}.
    Polarity of a token = parity of the downward-entailing contexts that contain it."""
    flips = [0] * len(doc)
    override = {}

    def flip(ids):
        for i in ids:
            flips[i] ^= 1

    def clause_of(tok):
        # the verb/aux head governing the noun (for nuclear scope)
        h = tok.head
        return h

    cond_ids = set()
    for t in doc:
        if t.dep_ == "mark" and t.lower_ in ("if", "when", "whenever"):
            cond_ids |= {x.i for x in t.head.subtree}
    for t in doc:
        low = t.lower_
        # quantified / generic noun phrases
        if t.pos_ in ("NOUN", "PROPN") and t.dep_ != "compound":
            dets = [d.lower_ for d in t.children if d.dep_ in ("det", "predet")]
            only = any(d.lower_ == "only" for d in t.children if d.dep_ == "advmod")
            restr = {x.i for x in t.subtree} - {d.i for d in t.children if d.dep_ in ("det", "predet")}
            is_subj = t.dep_ in ("nsubj", "nsubjpass")
            generic = is_subj and t.pos_ == "NOUN" and not dets and t.tag_ == "NNS" and t.i not in cond_ids
            generic_indef = False  # indefinite subjects inside if-clauses get their ↓ from the conditional
            if only:
                scope = {x.i for x in t.head.subtree} - restr
                flip(scope)
            elif any(d in NEGDET for d in dets):
                flip(restr)
                if is_subj:
                    flip({x.i for x in clause_of(t).subtree} - restr)
                else:
                    flip({t.head.i})
            elif any(d in UNIV for d in dets) or generic or generic_indef:
                flip(restr)
        if low in ("people", "those", "everyone", "everybody", "anyone", "anything", "everything") and \
                t.dep_ in ("nsubj", "nsubjpass"):
            pass  # handled as generic plural via NNS above for 'people'; pronouns carry no concept
        if low in ("nobody", "nothing", "noone"):
            flip({x.i for x in t.head.subtree})
        # sentential negation
        if t.dep_ == "neg" or low in ("never",):
            h = t.head
            subj = set()
            for ch in h.children:
                if ch.dep_ in ("nsubj", "nsubjpass", "advcl"):
                    subj |= {x.i for x in ch.subtree}
            flip({x.i for x in h.subtree} - subj - {t.i})
        # without
        if low == "without" and t.dep_ == "prep":
            flip({x.i for x in t.subtree} - {t.i})
        # conditionals
        if t.dep_ == "mark" and low in ("if", "when", "whenever"):
            flip({x.i for x in t.head.subtree} - {t.i})
        # either ... or  ->  ±
        if t.dep_ == "preconj" and low == "either":
            h = t.head
            members = [h] + [c for c in h.children if c.dep_ == "conj"]
            for m in members:
                for x in m.subtree:
                    override[x.i] = "±"
    out = {}
    for c in concepts:
        i = c["head_i"]
        out[c["cid"]] = override.get(i) or ("-" if flips[i] else "+")
    return out


if __name__ == "__main__":
    import json
    for s in ["All dogs that are not trained bark.", "No student who smokes is healthy.",
              "If people perform in school talent shows often, then they attend and are very engaged with school events.",
              "People either perform in school talent shows often or are inactive and disinterested members of their community.",
              "Every student reads some book.", "Tom is not a cat unless he meows.",
              "Vienna Music Society premiered Symphony No. 9."]:
        ex = extract(s)
        print("\n", s)
        for c in ex["concepts"]:
            print("   ", c["cid"], c["span"], c["pos"], c["role"], "marker:", ex["marker"][c["cid"]], ex["copies"].get(c["cid"]))
        print("   anchors", ex["anchors"], "coord", ex["coord"])
        for rp in ex["relpairs"]:
            print("   rel", rp)
