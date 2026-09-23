#!/usr/bin/env python3
"""STEP 10: E1 contamination set — entity-renamed paraphrases with renamed gold and candidates.

150 held-out sentences (75 FOLIO-train, 75 MALLS; back-filled from the other corpus if short) whose
audited gold contains a constant or whose sentence names an entity, preferring panel-faithful gold
and the top tercile. gpt-4.1-mini (T=0.7) rewords the sentence AND renames every named entity to a
fresh name from a seeded list, returning {paraphrase, rename_map}. rename_map is applied to the gold
constants and to entity substrings inside predicate names; M2 then verifies (i) same meaning up to
renaming and (ii) the renamed gold faithfully formalizes the paraphrase. Only pairs passing both
are kept. The 9 greedy candidates are renamed the same way (unmatched -> rename_incomplete flag).
Writes work/e1_results.json.
"""
from __future__ import annotations

import argparse
import hashlib
import asyncio
import json
import random
import re
import sys
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from fol_parse import SYM, parse, signature, to_str  # noqa: E402
from label_l1 import audited_gold_map, load_generations  # noqa: E402
from or_client import BudgetExceeded, Client  # noqa: E402
from panel import cached_call, load_cache, parse_json, yn  # noqa: E402

logger.remove()
logger.add(sys.stdout, level="INFO", format="{time:HH:mm:ss}|{level:<7}|{message}")
logger.add(ROOT / "logs" / "e1.log", rotation="30 MB", level="DEBUG")
CFG = json.loads((ROOT / "work" / "panel_config.json").read_text())["members"]
PARA_CFG = {"model": "openai/gpt-4.1-mini", "params": {"temperature": 0.7, "max_tokens": 400}}

FRESH = ["Oriel", "Tamsin", "Kestrel", "Brannock", "Velden", "Quillon", "Marisol", "Dunmore", "Halvard", "Ysolde",
         "Corvina", "Pellham", "Ashgrove", "Thessaly", "Nerida", "Barnaby", "Eskarth", "Lucerna", "Wystan", "Fenwick",
         "Galloway", "Isolde", "Rookwood", "Saffira", "Tobiah", "Umbria", "Valtor", "Wrenna", "Zephyrine", "Calder"]

PARA_TMPL = (
    "Reword the English sentence below so that it keeps EXACTLY the same meaning but uses different wording, and "
    "rename EVERY named entity in it (people, places, organizations, products, named things) to a new name taken "
    "from this list: {names}. Do not rename common nouns. Keep all conditions, quantities and negations.\n"
    "Sentence: {sentence}\n"
    'Return ONLY JSON: {{"paraphrase": "<reworded sentence>", "rename_map": {{"<old name as written>": "<new name>"}}}}')

VERIFY_TMPL = (
    "Original sentence: {orig}\nParaphrased sentence (entities renamed as {rmap}): {para}\n"
    "First-order logic formula (for the paraphrase): {fol}\n"
    "Notation: ∀ ∃ ¬ ∧ ∨ → ↔ ⊕(exclusive or).\n"
    "Q1: Does the paraphrase mean exactly the same as the original sentence, up to the entity renaming?\n"
    "Q2: Does the formula faithfully formalize the paraphrased sentence (same truth conditions; predicate names "
    "may be chosen freely)?\n"
    'Return ONLY JSON: {{"same_meaning": "yes" or "no", "formula_faithful": "yes" or "no", "note": "<at most 25 words>"}}')


def variants(name: str) -> dict[str, str]:
    words = re.findall(r"[A-Za-z0-9]+", name)
    if not words:
        return {}
    return {"lower": "".join(w.lower() for w in words), "camel": words[0].lower() + "".join(w.capitalize() for w in words[1:]),
            "pascal": "".join(w.capitalize() for w in words), "snake": "_".join(w.lower() for w in words)}


def rename_ast(ast: tuple, rmap: dict) -> tuple[tuple, set]:
    """Rename constants (case/sep-insensitive whole match) and entity substrings in predicate names."""
    pairs = [(variants(o), variants(n)) for o, n in rmap.items() if variants(o) and variants(n)]
    hit = set()

    def rc(c: str) -> str:
        key = re.sub(r"[^a-z0-9]", "", c.lower())
        for (vo, vn), o in zip(pairs, rmap):
            if key == vo["lower"]:
                hit.add(o)
                if "_" in c:
                    return vn["snake"]
                return vn["camel"] if c[:1].islower() else vn["pascal"]
        return c

    def rp(p: str) -> str:
        for (vo, vn), o in zip(pairs, rmap):
            for form in ("pascal", "snake", "camel"):
                if vo[form] and len(vo[form]) >= 3 and vo[form] in p:
                    hit.add(o)
                    p = p.replace(vo[form], vn[form])
        return p

    def rw(n):
        if n[0] in ("forall", "exists"):
            return (n[0], n[1], rw(n[2]))
        if n[0] == "not":
            return ("not", rw(n[1]))
        if n[0] in SYM:
            return (n[0], rw(n[1]), rw(n[2]))
        if n[0] == "atom":
            return ("atom", rp(n[1]), tuple((t[0], rc(t[1])) if t[0] == "const" else t for t in n[2]))
        if n[0] == "eq":
            return ("eq",) + tuple((t[0], rc(t[1])) if t[0] == "const" else t for t in n[1:])
        return n
    return rw(ast), hit


def has_entity(sentence: str, gold: str) -> bool:
    p = parse(gold)
    if p.ok and signature(p.ast)[1]:
        return True
    return bool(re.search(r"(?<!^)(?<![.!?]\s)\b[A-Z][a-z]+", sentence.strip()))


@logger.catch(reraise=True)
async def amain(args) -> None:
    held = json.loads((ROOT / "work" / "heldout_sentences.json").read_text())
    aud = json.loads((ROOT / "work" / "audit_results.json").read_text())["results"]
    gmap = audited_gold_map()
    rng = random.Random(0)
    pools = {}
    for corpus in ("folio", "malls"):
        cands = []
        for s in held:
            if s["corpus"] != corpus:
                continue
            gold, src = gmap[f"heldout:{s['sentence_id']}"]
            if not gold or not has_entity(s["sentence"], gold):
                continue
            a = aud.get(f"heldout:{s['sentence_id']}") or {}
            pref = 0 if (src in ("original", "paper_corrected") and a.get("gold_faithful_final") is not False) else 1
            cands.append((pref, {"top": 0, "middle": 1, "bottom": 2}[s["complexity_tercile"]], s["sentence_id"], s, gold, src))
        cands.sort(key=lambda t: t[:3])
        pools[corpus] = cands
    take = {"folio": args.n // 2, "malls": args.n - args.n // 2}
    for c, o in (("folio", "malls"), ("malls", "folio")):
        short = take[c] - len(pools[c])
        if short > 0:
            take[c] -= short
            take[o] += short
    chosen = pools["folio"][: take["folio"]] + pools["malls"][: take["malls"]]
    names_for = {t[2]: rng.sample(FRESH, 6) for t in chosen}  # drawn up front: deterministic
    logger.info(f"E1 selected {len(chosen)} (folio {take['folio']}, malls {take['malls']}; pools {[len(v) for v in pools.values()]})")
    gens = {}
    for r in load_generations():
        if r["sample_idx"] == 0:
            gens.setdefault(r["sentence_id"], []).append(r)
    cache = load_cache()
    out = {}
    async with Client("e1_contamination", phase_cap=args.cap, concurrency=16) as client:
        async def one(t):
            _, _, sid, s, gold, src = t
            names = names_for[sid]
            rec = await cached_call(client, cache, f"e1para|{sid}", PARA_CFG,
                                    PARA_TMPL.format(names=", ".join(names), sentence=s["sentence"]), "PARA")
            p = rec.get("parsed") or {}
            para = str(p.get("paraphrase") or "").strip()
            rmap = p.get("rename_map") if isinstance(p.get("rename_map"), dict) else {}
            rmap = {str(k): str(v) for k, v in rmap.items() if str(k).strip() and str(v).strip() and str(k) != str(v)}
            row = {"sentence_id": sid, "orig_sentence": s["sentence"], "paraphrase": para, "rename_map": rmap,
                   "gold_fol_audited": gold, "gold_source": src, "corpus": s["corpus"], "kept": False}
            if not para:
                row["drop_reason"] = "no_paraphrase"
                out[sid] = row
                return
            g_ast = parse(gold).ast
            g2, ghit = rename_ast(g_ast, rmap)
            row["gold_fol_renamed"] = to_str(g2)
            row["gold_rename_hits"] = sorted(ghit)
            vkey = hashlib.sha1((para + "\x00" + row["gold_fol_renamed"]).encode()).hexdigest()[:12]
            vrec = await cached_call(client, cache, f"e1verify|{sid}|{vkey}", CFG["M2"],
                                     VERIFY_TMPL.format(orig=s["sentence"], rmap=json.dumps(rmap, ensure_ascii=False),
                                                        para=para, fol=row["gold_fol_renamed"]), "M2")
            v = vrec.get("parsed") or {}
            row["verify_same_meaning"] = yn(v.get("same_meaning"))
            row["verify_formula_faithful"] = yn(v.get("formula_faithful"))
            row["verify_note"] = str(v.get("note", ""))[:300]
            row["kept"] = bool(row["verify_same_meaning"] and row["verify_formula_faithful"] and parse(row["gold_fol_renamed"]).ok)
            if not row["kept"]:
                row["drop_reason"] = "verification_failed"
            cands = []
            for g in gens.get(sid, []):
                c = {"system": g["system"], "candidate_fol_original": g["candidate_fol"], "parse_ok": g["parse_ok"]}
                if g["parse_ok"]:
                    ca = parse(g["candidate_fol"]).ast
                    c2, chit = rename_ast(ca, rmap)
                    c["candidate_fol_renamed"] = to_str(c2)
                    _, consts = signature(ca)
                    c["rename_incomplete"] = bool(rmap) and bool(consts) and not chit
                else:
                    c["candidate_fol_renamed"] = g["candidate_fol"]
                    c["rename_incomplete"] = True
                cands.append(c)
            row["candidates"] = cands
            out[sid] = row
        try:
            await asyncio.gather(*[one(t) for t in chosen])
        except BudgetExceeded as e:
            logger.error(f"budget stop: {e}")
        logger.info(f"E1 spend ${client.spent_phase:.3f}; total ${client.spent_total:.3f}")
    kept = sum(r["kept"] for r in out.values())
    logger.info(f"E1 kept {kept}/{len(out)}")
    (ROOT / "work" / "e1_results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=150)
    ap.add_argument("--cap", type=float, default=0.6)
    asyncio.run(amain(ap.parse_args()))
