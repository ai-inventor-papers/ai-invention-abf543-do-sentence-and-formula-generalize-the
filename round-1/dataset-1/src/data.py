# /// script
# requires-python = ">=3.12"
# dependencies = ["loguru"]
# ///
"""Build full_data_out.json (exp_sel_data_out) for the held-out NL->FOL faithfulness dataset.

Inputs
- work/assembled_data_out.json.gz : the 5 labelled groups produced by the pipeline in src/
  (prep_sources -> generate -> label_l1 -> calibrate -> audit -> l3_adjudicate/l3_extra -> e1 -> e2 -> assemble).
- temp/datasets/ : the source datasets. EVERY row is re-verified against them here:
    heldout_confirm / heldout_samples : sentence + original gold == the MALLS-v0.1-test / FOLIO-v2-train /
                                        ProverQA-dev source record named by metadata_source_id; paper-corrected
                                        gold == DSAVlab-UNIUD curated record
    screen_gold_audit                 : sentence + gold in FOLIO v0.0 validation; the Logic-LM line exists in
                                        FOLIO_dev_<system>.json
    contamination                     : original sentence == the held-out sentence it was derived from
    transfer_unlabeled                : candidate formula == the pilot 04_fol.json it came from
  Result stored per row as metadata_source_verified (+ metadata_source_file). Rows are never dropped.

One example per data row (candidate formalization); grouped by dataset (= split).
Run: uv run data.py
"""
from __future__ import annotations

import ast
import gzip
import json
import re
import sys
from collections import Counter
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).resolve().parent
TD = ROOT / "temp" / "datasets"
(ROOT / "logs").mkdir(exist_ok=True)
logger.remove()
logger.add(sys.stdout, level="INFO", format="{time:HH:mm:ss}|{level:<7}|{message}")
logger.add(ROOT / "logs" / "data_py.log", rotation="30 MB", level="DEBUG")

GROUP_ORDER = ["heldout_confirm", "heldout_samples", "screen_gold_audit", "contamination", "transfer_unlabeled"]
FORBIDDEN = {"split", "dataset", "context"}


def norm(s: str) -> str:
    s = re.sub(r"\s+", " ", s.strip().lower())
    return s[:-1].strip() if s.endswith(".") else s


def ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def read_jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def load_sources() -> dict:
    src = {}
    src["malls"] = json.loads((TD / "yuan-yang__MALLS-v0" / "MALLS-v0.1-test.json").read_text())
    src["malls_cur"] = {c["id"] - 1: c for c in read_jsonl(TD / "DSAVlab-UNIUD__MALLS_test_subset-CURATED" / "MALLS_instances.jsonl")}
    src["folio_train"] = {str(r["example_id"]): r for r in read_jsonl(TD / "tasksource__folio" / "folio_v2_train.jsonl")}
    src["proverqa"] = {}
    for lvl in ("medium", "hard"):
        for it in json.loads((TD / "opendatalab__ProverQA" / "dev" / f"{lvl}.json").read_text()):
            d = it["nl2fol"]
            d = ast.literal_eval(d) if isinstance(d, str) else d
            src["proverqa"][(lvl, str(it["id"]))] = list(d.items())
    gh = TD / "github_FOLIO_v0.0_and_LogicLM_outputs"
    val = {}
    for s in read_jsonl(gh / "folio-validation_v0.0.jsonl"):
        p = s["premises"]
        p = ast.literal_eval(p) if isinstance(p, str) and p.startswith("[") else p
        pf = s["premises-FOL"]
        pf = ast.literal_eval(pf) if isinstance(pf, str) and pf.startswith("[") else pf
        for nl, f in list(zip(p, pf)) + [(s["conclusion"], s["conclusion-FOL"])]:
            val.setdefault(norm(nl), set()).add(ws(f))
    src["folio_v1_val"] = val
    src["logiclm"] = {}
    for sysname in ("gpt-3.5-turbo", "gpt-4", "text-davinci-003"):
        txt = "\n".join(ex["raw_logic_programs"][0] for ex in json.loads((gh / f"FOLIO_dev_{sysname}.json").read_text())
                        if ex.get("raw_logic_programs"))
        src["logiclm"][f"logiclm_{sysname}"] = {ws(l) for l in txt.split("\n") if ":::" in l}
    return src


def verify_heldout(ex: dict, src: dict) -> tuple[bool, str]:
    inp = json.loads(ex["input"])
    sent, gold, sid = inp["sentence"], ex["metadata_gold_fol_original"], ex["metadata_source_id"]
    m = re.match(r"malls_test_(\d+)$", sid)
    if m:
        i = int(m.group(1))
        rec = src["malls"][i]
        ok = ws(rec["NL"]) == ws(sent) and ws(rec["FOL"]) == ws(gold)
        if ex.get("metadata_gold_fol_paper"):
            ok = ok and ws(src["malls_cur"][i]["FOL_sentence_new"]) == ws(ex["metadata_gold_fol_paper"])
        return ok, f"yuan-yang__MALLS-v0/MALLS-v0.1-test.json[{i}]"
    m = re.match(r"folio_train_story(\w+)_ex(\w+)_(p\d+|c)$", sid)
    if m:
        rec = src["folio_train"].get(m.group(2))
        if rec is None:
            return False, "tasksource__folio/folio_v2_train.jsonl (example missing)"
        pos = m.group(3)
        if pos == "c":
            nl, fol = rec["conclusion"], rec["conclusion-FOL"]
        else:
            j = int(pos[1:])
            nl = [l for l in rec["premises"].split("\n") if l.strip()][j]
            fol = [l for l in rec["premises-FOL"].split("\n") if l.strip()][j]
        return ws(nl) == ws(sent) and ws(fol) == ws(gold), f"tasksource__folio/folio_v2_train.jsonl[example_id={m.group(2)},{pos}]"
    m = re.match(r"proverqa_dev_(medium|hard)_(\w+)_(\d+)$", sid)
    if m:
        items = src["proverqa"].get((m.group(1), m.group(2)))
        if items is None:
            return False, "opendatalab__ProverQA (item missing)"
        nl, fol = items[int(m.group(3))]
        return ws(nl) == ws(sent) and ws(fol) == ws(gold), f"opendatalab__ProverQA/dev/{m.group(1)}.json[id={m.group(2)}][{m.group(3)}]"
    return False, "unknown source_id pattern"


def verify_screen(ex: dict, src: dict) -> tuple[bool, str]:
    inp = json.loads(ex["input"])
    golds = src["folio_v1_val"].get(norm(inp["sentence"]), set())
    ok_gold = ws(ex["metadata_gold_fol_original"]) in golds
    ok_line = ws(ex["metadata_raw_output"]) in src["logiclm"].get(ex["metadata_system"], set())
    return ok_gold and ok_line, f"github FOLIO v0.0 validation + Logic-LLM FOLIO_dev_{ex['metadata_system'].replace('logiclm_', '')}.json"


def verify_transfer(ex: dict) -> tuple[bool, str]:
    rel = ex["metadata_source_path"].replace("raw/pilot/", "", 1)
    p = TD / "user_dpv_pilot" / rel
    if not p.exists():
        return False, str(p.relative_to(ROOT))
    try:
        fol = json.loads(p.read_text()).get("fol", "")
    except json.JSONDecodeError:
        fol = p.read_text()
    return ws(fol) == ws(json.loads(ex["input"])["candidate_fol"]), f"temp/datasets/user_dpv_pilot/{rel}"


@logger.catch(reraise=True)
def main() -> None:
    with gzip.open(ROOT / "work" / "assembled_data_out.json.gz", "rt", encoding="utf-8") as fh:
        data = json.load(fh)
    src = load_sources()
    logger.info(f"sources loaded: malls={len(src['malls'])} folio_train={len(src['folio_train'])} proverqa_items={len(src['proverqa'])}")
    groups = {d["dataset"]: d["examples"] for d in data["datasets"]}
    held_sent = {}
    for ex in groups.get("heldout_confirm", []):
        held_sent[ex["metadata_sentence_id"]] = json.loads(ex["input"])["sentence"]
    stats = {}
    out = []
    for g in GROUP_ORDER:
        rows = groups.get(g, [])
        c = Counter()
        for ex in rows:
            assert isinstance(ex["input"], str) and isinstance(ex["output"], str), ex.get("metadata_item_id")
            bad = FORBIDDEN & set(ex)
            assert not bad, bad
            assert all(k in ("input", "output") or k.startswith("metadata_") for k in ex), ex.keys()
            if g in ("heldout_confirm", "heldout_samples"):
                ok, f = verify_heldout(ex, src)
            elif g == "screen_gold_audit":
                ok, f = verify_screen(ex, src)
            elif g == "contamination":
                ok = held_sent.get(ex["metadata_sentence_id"]) == ex["metadata_original_sentence"]
                f = "derived from heldout_confirm sentence " + ex["metadata_sentence_id"]
            else:
                ok, f = verify_transfer(ex)
            ex["metadata_source_verified"] = bool(ok)
            ex["metadata_source_file"] = f
            c[ok] += 1
        stats[g] = {"rows": len(rows), "source_verified": c[True], "not_verified": c[False],
                    "labels": dict(Counter(ex["output"] for ex in rows))}
        logger.info(f"{g}: {stats[g]}")
        out.append({"dataset": g, "examples": rows})
    meta = dict(data["metadata"])
    meta["source_verification"] = stats
    meta["groups"] = GROUP_ORDER
    (ROOT / "full_data_out.json").write_text(json.dumps({"metadata": meta, "datasets": out}, ensure_ascii=False))
    logger.info(f"wrote full_data_out.json: {sum(len(d['examples']) for d in out)} examples in {len(out)} datasets")


if __name__ == "__main__":
    main()
