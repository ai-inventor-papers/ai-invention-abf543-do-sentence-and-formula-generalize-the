"""T1 (blind-spot probe mini-check) and T2 (dev-slice prompt check on 20 FOLIO-dev gold sentences that are
NOT among the 300 screen sentences). Writes results/dev_checks.json and results/prompts_frozen.json."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("NLTK_DATA", str(ROOT / "nltk_data"))

import fol_core as fc  # noqa: E402
import llm  # noqa: E402
from build_screen import load_gold, norm  # noqa: E402
from tvjt import TVJT_PROMPT, build_prompt, find_world, parse_answer, score_answers, worlds_for  # noqa: E402

llm.LEDGER = ROOT / "results" / "cost_ledger_devtests.jsonl"

PROBES = {  # (gold sentence, gold FOL, wrong FOL)
    "and/or restrictor": ("Dogs and cats are pets.", "∀x ((Dog(x) ∨ Cat(x)) → Pet(x))", "∀x ((Dog(x) ∧ Cat(x)) → Pet(x))"),
    "and/or scope": ("Dogs bark and bite.", "∀x (Dog(x) → (Bark(x) ∧ Bite(x)))", "∀x (Dog(x) → (Bark(x) ∨ Bite(x)))"),
    "exception consequent swap": ("Untrained dogs bark, and trained dogs sit.",
                                  "∀x ((Dog(x) ∧ ¬Trained(x)) → Bark(x)) ∧ ∀x ((Dog(x) ∧ Trained(x)) → Sit(x))",
                                  "∀x ((Dog(x) ∧ Trained(x)) → Bark(x)) ∧ ∀x ((Dog(x) ∧ ¬Trained(x)) → Sit(x))"),
    "wrong constant": ("Tom is a cat and Ann does not meow.", "Cat(tom) ∧ ¬Meows(ann)", "Cat(ann) ∧ ¬Meows(tom)"),
    "scope 1": ("Every student reads some book.", "∀x (Student(x) → ∃y (Book(y) ∧ Reads(x, y)))",
                "∃y (Book(y) ∧ ∀x (Student(x) → Reads(x, y)))"),
    "scope 2": ("There is a teacher whom every student admires.", "∃y (Teacher(y) ∧ ∀x (Student(x) → Admires(x, y)))",
                "∀x (Student(x) → ∃y (Teacher(y) ∧ Admires(x, y)))"),
    "cardinality 1": ("At least two dogs bark.", "∃x ∃y (Dog(x) ∧ Dog(y) ∧ x ≠ y ∧ Bark(x) ∧ Bark(y))",
                      "∃x (Dog(x) ∧ Bark(x))"),
    "cardinality 2": ("Exactly one student passed.", "∃x (Student(x) ∧ Passed(x) ∧ ∀y ((Student(y) ∧ Passed(y)) → y = x))",
                      "∃x (Student(x) ∧ Passed(x))"),
}


async def main() -> None:
    from instance_nli import A1, build_items, label_pairs, select_pairs, verbalize_pair  # noqa: F401
    out = {"prompt_version": "tvjt_v1", "T1": {}, "T2": {}}
    async with llm.LLM() as L:
        # ---- T1: pairwise judge on the world separating gold from wrong
        t1 = []
        for name, (s, g, w) in PROBES.items():
            G, W = fc.parse(g), fc.parse(w)
            world = find_world(G, W, prefer=0)
            world.update({"op": "PROBE", "variant": None})
            prompt = build_prompt(s, G, [world])
            r = await L.call([{"role": "user", "content": prompt}], stage="dev_T1", item_id=name, max_tokens=60)
            ans = parse_answer(r["text"], 1)
            sided = None if ans is None else (0.5 if ans[1] == "UNCLEAR" else float((ans[1] == "TRUE") == world["F_value"]))
            t1.append({"probe": name, "judge_sided_with_gold": sided, "answer": ans, "world_prompt": prompt})
        out["T1"] = {"pairs": t1, "n_sided_with_gold": sum(1 for x in t1 if x["judge_sided_with_gold"] == 1.0),
                     "n": len(t1), "expectation": ">= 6 of 8 (signal, not a gate)"}
        # ---- T2: 20 FOLIO-dev golds outside the 300 screen sentences
        ss = json.loads((ROOT / "data" / "screen_set.json").read_text())
        screen = {s["nl"].lower().strip() for s in ss["sentences"]}
        gold, _ = load_gold()
        sup_sids = {x["sid"] for x in map(json.loads, (ROOT / "data" / "blindspot_supplement.jsonl").read_text().splitlines())
                    if x["split"] == "supplement"}
        cand = sorted([(hashlib.sha1(k.encode()).hexdigest(), v) for k, v in gold.items()
                       if v["nl"].lower().strip() not in screen], key=lambda x: x[0])
        dev = []
        for h, v in cand:
            a, _ = fc.try_parse(v["fol"])
            if a is None or fc.satisfiable(a) != "sat":
                continue
            # only sentences that are not among the 300 (they are the remaining FOLIO-dev golds)
            dev.append((h[:10], v["nl"], a))
            if len(dev) >= 20:
                break
        agrees, malformed, recs = [], 0, []
        for sid, nl, a in dev:
            worlds = worlds_for(a, f"dev:{sid}")
            if not worlds:
                continue
            prompt = build_prompt(nl, a, worlds)
            r = await L.call([{"role": "user", "content": prompt}], stage="dev_T2", item_id=sid, max_tokens=300)
            ans = parse_answer(r["text"], len(worlds))
            if ans is None:
                malformed += 1
                continue
            sc, ag, _ = score_answers(worlds, ans)
            agrees += ag
            recs.append({"sid": sid, "nl": nl, "fol": fc.to_str(a), "score": sc, "agrees": ag,
                         "ops": [w["op"] for w in worlds]})
        acc = sum(agrees) / max(1, len(agrees))
        out["T2"] = {"n_sentences": len(dev), "n_worlds": len(agrees), "judge_oracle_accuracy_on_gold_worlds": acc,
                     "malformed_rate": malformed / max(1, len(dev)), "pass": acc >= 0.70 and malformed / max(1, len(dev)) < 0.05,
                     "items": recs, "dev_sids_disjoint_from_screen": True}
        out["cost_usd"] = L.cum
    (ROOT / "results" / "dev_checks.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    frozen = {"TVJT_PROMPT": TVJT_PROMPT, "sha1": hashlib.sha1(TVJT_PROMPT.encode()).hexdigest(),
              "version": "tvjt_v1", "frozen_after": "T2 dev-slice check (non-screen FOLIO-dev sentences)"}
    from stages import B1_PROMPT, NLI_GEMINI_PROMPT
    frozen["B1_PROMPT"] = B1_PROMPT
    frozen["NLI_GEMINI_PROMPT"] = NLI_GEMINI_PROMPT
    frozen["NLI_GEMINI_sha1"] = hashlib.sha1(NLI_GEMINI_PROMPT.encode()).hexdigest()
    (ROOT / "results" / "prompts_frozen.json").write_text(json.dumps(frozen, indent=1, ensure_ascii=False))
    print(json.dumps({"T1": {k: v for k, v in out["T1"].items() if k != "pairs"},
                      "T1_pairs": [(x["probe"], x["judge_sided_with_gold"]) for x in t1],
                      "T2": {k: v for k, v in out["T2"].items() if k != "items"}, "cost": out["cost_usd"]}, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
