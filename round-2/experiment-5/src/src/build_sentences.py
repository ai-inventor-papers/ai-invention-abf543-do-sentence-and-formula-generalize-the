#!/usr/bin/env python3
"""S1: build the ~150-sentence long-legal-text set (63 AI-Act Art. 3 definitions + ~90 public statutory items).

Sources: raw/pilot (AI Act enacting terms, local), raw/eurlex/<CELEX>.html (GDPR Art. 4, DSA Art. 3, DMA Art. 2,
Data Act Art. 2), raw/sara/sara/statutes/source/section* (SARA, Holzenberger et al. 2020).
Writes work/sentences.json and results/sentence_set_report.json.
"""
from __future__ import annotations

import html as htmlmod
import random
import re
from collections import Counter, defaultdict

from common import PIPE, RAW, RES, SEED, WORK, jdump, jload, setup_logger, sha1

logger = setup_logger("build_sentences")

EU = {  # celex -> (act, article id, article label, url)
    "32016R0679": ("GDPR", "art_4", "Article 4"),
    "32022R2065": ("DSA", "art_3", "Article 3"),
    "32022R1925": ("DMA", "art_2", "Article 2"),
    "32023R2854": ("DataAct", "art_2", "Article 2"),
}
EU_LICENCE = "EUR-Lex, reuse under Commission Decision 2011/833/EU, source acknowledged"
SARA_LICENCE = "US Code text, public domain; SARA edits Holzenberger et al. 2020, research use"
AIACT_LICENCE = "EUR-Lex (Regulation (EU) 2024/1689) via the user's pilot upload; reuse under Commission Decision 2011/833/EU"

MARKERS = {"unless": r"\bunless\b", "except": r"\bexcept\b", "other than": r"\bother than\b",
           "provided that": r"\bprovided that\b", "only": r"\bonly\b", "where": r"\bwhere\b",
           "not": r"\bnot\b|n't\b", "excluding": r"\bexcluding\b", "including": r"\bincluding\b",
           "without prejudice": r"\bwithout prejudice\b"}
EXC = ["unless", "except", "other than", "provided that", "excluding", "without prejudice"]
COND = [r"\bif\b", r"\bwhere\b", r"\bwhen\b", r"\bprovided\b", r"\bunless\b", r"\bexcept\b", r"\band that\b",
        r"\bwhich\b", r"\bwho\b"]
XREF = re.compile(r"section \d+|subsection \(|paragraph \(", re.I)
DEF_RE = re.compile(r"\((\d{1,2}|[a-z]{1,2})\)\s*[‘'\"]([^’'\"]{1,140})[’'\"]\s*(?=means|shall mean|refers|is|are)")


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def features(text: str) -> dict:
    t = text.lower()
    mc = {k: len(re.findall(p, t)) for k, p in MARKERS.items()}
    markers = sum(mc.values())
    exc = sum(mc[k] for k in EXC)
    ncond = sum(len(re.findall(p, t)) for p in COND)
    depth = cur = 0
    for ch in text:
        if ch == "(":
            cur += 1
            depth = max(depth, cur)
        elif ch == ")":
            cur = max(0, cur - 1)
    limbs = len(re.findall(r"(?:^|\s)\((?:[a-z]|[ivx]+|[A-Z]|[IVX]+)\)\s", text))
    return {"n_tokens": len(text.split()), "marker_counts": mc, "n_markers": markers, "exception_markers": exc,
            "n_conditions": ncond, "paren_depth": depth, "n_limbs": limbs, "nesting": depth + limbs,
            "marker_bin": "B0" if markers <= 1 else ("B1" if markers <= 3 else "B2"),
            "has_cross_reference": bool(XREF.search(text))}


def is_pointer(text: str) -> bool:
    body = re.sub(r"^\(\w+\)\s*[‘'\"][^’'\"]+[’'\"]\s*", "", text)
    return bool(re.search(r"means .{0,120}(as defined in|within the meaning of)", body)) and \
        len(body.split()) < 35 and not re.search(r"\b(unless|except|other than|provided|where|if|not)\b", body)


# ------------------------------------------------------------------ AI Act
def ai_act() -> list[dict]:
    terms = jload(PIPE / "euaiact_enacting_terms.json")["enacting_terms"]
    art3 = next(a for c in terms["chapters"] for a in c["articles"] if a["id"] == "Article 3")
    out = []
    for par in art3["paragraphs"][1:]:
        m = re.match(r"\((\d+)\)\s*[‘']([^’']+)[’']\s*(.*)", par)  # SAME regex as vendor/ds/e2_transfer.py
        if m:
            out.append({"source": "ai_act_art3", "act": "AIAct", "article": "Article 3",
                        "item": int(m.group(1)), "term": m.group(2), "sentence": par, "licence": AIACT_LICENCE,
                        "url": "https://eur-lex.europa.eu/eli/reg/2024/1689/oj/eng"})
    return out


def ai_act_other() -> list[dict]:
    """F1 fallback pool: non-Art.-3 AI-Act paragraphs (only used if a public source fails)."""
    terms = jload(PIPE / "euaiact_enacting_terms.json")["enacting_terms"]
    out = []
    for c in terms["chapters"]:
        for a in c["articles"]:
            if a["id"] != "Article 3":
                for i, par in enumerate(a["paragraphs"]):
                    for s in re.split(r"(?<=[.;])\s+(?=[A-Z(])", par):
                        s = norm(re.sub(r"^\d+\.\s+", "", s))
                        if 12 <= len(s.split()) <= 170:
                            out.append({"source": "ai_act_other_articles", "act": "AIAct", "article": a["id"],
                                        "item": i + 1, "term": None, "sentence": s, "licence": AIACT_LICENCE,
                                        "url": "https://eur-lex.europa.eu/eli/reg/2024/1689/oj/eng"})
    return out


# ------------------------------------------------------------------ EUR-Lex
def eurlex(celex: str) -> list[dict]:
    act, art, label = EU[celex]
    p = RAW / "eurlex" / f"{celex}.html"
    h = p.read_text(encoding="utf-8")
    i = h.find(f'id="{art}"')
    if i < 0:
        raise ValueError(f"{celex}: {art} not found")
    n = int(art.split("_")[1])
    j = h.find(f'id="art_{n + 1}"', i)
    seg = h[i:j if j > 0 else i + 200000]
    seg = re.sub(r"<(/?)(p|tr|div|table)[^>]*>", "\n", seg)
    txt = htmlmod.unescape(re.sub(r"<[^>]+>", " ", seg))
    txt = norm(txt)
    ms = list(DEF_RE.finditer(txt))
    out = []
    for k, m in enumerate(ms):
        end = ms[k + 1].start() if k + 1 < len(ms) else len(txt)
        s = norm(txt[m.start():end]).rstrip(" ;")
        s = re.sub(r"\s+([,;:.)])", r"\1", s).replace("( ", "(")
        out.append({"source": "eurlex", "act": act, "article": label, "item": m.group(1), "term": m.group(2),
                    "sentence": s, "licence": EU_LICENCE,
                    "url": f"https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:{celex}"})
    return out


# ------------------------------------------------------------------ SARA
HEADING = re.compile(r"^\(([0-9a-zA-Z]{1,4})\)\s+([A-Z][^.;:]*)$")
LIMB = re.compile(r"^\(([0-9a-zA-Z]{1,4})\)\s+")


def sara() -> list[dict]:
    base = RAW / "sara" / "sara" / "statutes" / "source"
    out = []
    for f in sorted(base.glob("section*")):
        sec = f.name.replace("section", "")
        blocks = []
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.startswith("§"):
                continue
            ind = len(line) - len(line.lstrip(" "))
            t = line.strip()
            hd = HEADING.match(t)
            if hd and len(t.split()) <= 12 and not t.endswith(("-", "—", ":")):
                blocks.append({"ind": ind, "text": t, "kind": "heading"})
            else:
                blocks.append({"ind": ind, "text": t, "kind": "limb" if LIMB.match(t) else "free"})
        used = set()
        for k, b in enumerate(blocks):
            if b["kind"] == "heading" or k in used:
                continue
            if b["text"].endswith(("-", "—", ":")):  # chapeau: join with its limbs
                parts = [b["text"]]
                used.add(k)
                for k2 in range(k + 1, len(blocks)):
                    b2 = blocks[k2]
                    if b2["kind"] == "heading" or b2["ind"] < b["ind"] or (b2["ind"] == b["ind"] and b2["kind"] == "free" and not b2["text"][0].islower()):
                        break
                    parts.append(b2["text"])
                    used.add(k2)
                units = [" ".join(parts)]
            elif b["kind"] == "limb":
                continue  # a limb outside a chapeau is not self-contained
            else:
                used.add(k)
                units = [s for s in re.split(r"(?<=\.)\s+(?=[A-Z])", b["text"])]
            for u in units:
                u = norm(u.replace("- (", "— (").replace("—", "-"))
                u = re.sub(r"-\s+\(", " (", u)
                if 10 <= len(u.split()):
                    out.append({"source": "sara", "act": "SARA-IRC", "article": f"section {sec}", "item": k,
                                "term": None, "sentence": u, "licence": SARA_LICENCE,
                                "url": "https://nlp.jhu.edu/law/sara/sara.tar.gz"})
    return out


# ------------------------------------------------------------------ selection
def select_public(pool: list[dict], rng: random.Random, n_target: int = 90) -> list[dict]:
    per_bin_target = {"B2": 30, "B1": 30, "B0": 30}
    by_bin = defaultdict(list)
    for s in pool:
        by_bin[s["marker_bin"]].append(s)
    quotas = {"SARA-IRC": 20, "GDPR": 10, "DSA": 10, "DMA": 10, "DataAct": 10}
    chosen, chosen_ids = [], set()
    remaining = dict(per_bin_target)
    for act in sorted(quotas):  # per-source minimums, scarce bins first
        cand = [s for s in pool if s["act"] == act]
        rng.shuffle(cand)
        cand.sort(key=lambda s: {"B2": 0, "B1": 1, "B0": 2}[s["marker_bin"]])
        k = 0
        for s in cand:
            if k >= quotas[act]:
                break
            if remaining[s["marker_bin"]] <= 0 or s["sentence_id"] in chosen_ids:
                continue
            chosen.append(s)
            chosen_ids.add(s["sentence_id"])
            remaining[s["marker_bin"]] -= 1
            k += 1
    for b in ("B2", "B1", "B0"):  # fill bins: public sources first, then the local AI-Act fallback pool
        cand = [s for s in by_bin[b] if s["sentence_id"] not in chosen_ids]
        rng.shuffle(cand)
        cand.sort(key=lambda s: s["source"] == "ai_act_other_articles")
        take = cand[:max(0, remaining[b])]
        for s in take:
            chosen.append(s)
            chosen_ids.add(s["sentence_id"])
        remaining[b] -= len(take)
        if b == "B2" and remaining[b] > 0:  # B2 short even with the fallback: move the deficit to B1
            remaining["B1"] += remaining[b]
            remaining[b] = 0
    return chosen


@logger.catch(reraise=True)
def main() -> None:
    rng = random.Random(SEED)
    report = {"sources": {}, "fallback_used": False}
    ai = ai_act()
    report["sources"]["ai_act_art3"] = len(ai)
    pub = []
    for celex in EU:
        try:
            rows = eurlex(celex)
            report["sources"][EU[celex][0]] = len(rows)
            pub += rows
        except (OSError, ValueError) as e:
            logger.error(f"EUR-Lex {celex} failed: {e}")
            report["sources"][EU[celex][0]] = f"failed: {e}"
            report["fallback_used"] = True
    try:
        sr = sara()
        report["sources"]["SARA-IRC"] = len(sr)
        pub += sr
    except OSError as e:
        logger.error(f"SARA failed: {e}")
        report["fallback_used"] = True
    fb = ai_act_other()  # F1 fallback / bin top-up pool (used only where the public pools run out, B2 first)
    report["sources"]["ai_act_other_articles"] = len(fb)
    pub += fb
    seen = set()
    for s in ai + pub:
        s["sentence"] = norm(s["sentence"]) if s["source"] != "ai_act_art3" else s["sentence"]
        s["sentence_id"] = sha1(norm(s["sentence"]).lower())[:10]
        s.update(features(s["sentence"]))
    ai_ids = {s["sentence_id"] for s in ai}
    filt = Counter()
    pool = []
    for s in pub:
        if s["sentence_id"] in ai_ids or s["sentence_id"] in seen:
            filt["duplicate"] += 1
            continue
        seen.add(s["sentence_id"])
        if s["n_tokens"] > 170:
            filt["over_170_words"] += 1
            continue
        if s["n_tokens"] < 10:
            filt["under_10_words"] += 1
            continue
        if is_pointer(s["sentence"]):
            filt["pointer_definition"] += 1
            continue
        pool.append(s)
    report["pool_after_filters"] = len(pool)
    report["filtered"] = dict(filt)
    report["pool_by_act_bin"] = {f"{a}|{b}": n for (a, b), n in sorted(Counter((s["act"], s["marker_bin"]) for s in pool).items())}
    chosen = select_public(pool, rng)
    sents = ai + chosen
    for s in sents:
        s["in_ai_act"] = s["source"] == "ai_act_art3"
    jdump(sents, WORK / "sentences.json")
    report["n_sentences"] = len(sents)
    report["by_source"] = dict(Counter(s["act"] for s in sents))
    report["by_bin"] = dict(Counter(s["marker_bin"] for s in sents))
    report["ai_act_bins"] = dict(Counter(s["marker_bin"] for s in ai))
    report["public_bins"] = dict(Counter(s["marker_bin"] for s in chosen))
    report["public_by_act_bin"] = {f"{a}|{b}": n for (a, b), n in sorted(Counter((s["act"], s["marker_bin"]) for s in chosen).items())}
    report["n_tokens_mean_by_bin"] = {b: sum(s["n_tokens"] for s in sents if s["marker_bin"] == b) / max(1, sum(1 for s in sents if s["marker_bin"] == b)) for b in ("B0", "B1", "B2")}
    report["has_cross_reference"] = sum(s["has_cross_reference"] for s in sents)
    jdump(report, RES / "sentence_set_report.json")
    logger.info(f"sentences: {report}")


if __name__ == "__main__":
    main()
