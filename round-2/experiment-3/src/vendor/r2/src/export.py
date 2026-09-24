"""S8 export: method_out.json (exp_gen_sol_out schema) + deviations + integrity checks.

One example per held-out greedy candidate (heldout_confirm, 6,300 rows) and per contamination / transfer row, with
every metric score as predict_<metric> (string, 4 decimals; uncovered -> '0.5' and metadata_uncovered lists them).
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict

from loguru import logger

from common import RES, ROOT, WORK, jdump, load_frame, read_jsonl
from or_client import ledger_total

DEVIATIONS = [
    {"id": "D-LLM", "what": "The OpenRouter key hit its shared $50 DAILY limit at the start of the LLM stage (14:22 UTC; "
     "limit_remaining 0). The key was later replaced by the platform (~17:20 UTC, $7.02 left for all runs today). The frozen "
     "gemini metrics were then run with the exact frozen requests, prioritised for the shared budget: B1 on all 6,300 "
     "held-out + 936 contamination rows (+300-call sequential retest); B3 back-translation on the 609 panel items + the "
     "3-system contamination slice; B1plus = google/gemini-2.5-pro on the 609 panel items only (contamination slice "
     "dropped, plan fallback 5); A1 probe on the 530 panel + contamination sentences only (plan fallback 5: 562 calls, "
     "$1.65). B3c and the gold-recall probe were NOT re-run on gemini (first items of the plan's sacrifice order); their "
     "local Qwen3-8B substitutes (B3cL, RECALL_L) are reported instead. Total OpenRouter spend: see results/integrity.json.",
     "impact": "Frozen metrics are primary. The local Qwen3-8B substitutes computed while the key was down (suffix L: B1L, "
               "B1plusL thinking judge, A1L, B3cosL/B3nliL, B3cL, RECALL_L; same prompts) are kept as secondary rows. "
               "A1 and B1plus are panel-restricted, so their C3 coverage is computed over the rows they ran on."},
    {"id": "D-B1plusL", "what": "The reasoning substitute judge B1plusL (Qwen3-8B thinking mode, SAME B1 prompt, greedy) "
     "ran at ~10 s/item; to fit the session it was restricted to the 609 panel items (no contamination slice, so no "
     "contamination delta for it) and capped at 1024 new tokens (batch 16). An unfinished reasoning trace has no final "
     "answer and is uncovered (score 0.5, counted)."},
    {"id": "D-B3c-parse", "what": "B3c/B3cL JSON reader is tolerant: a scalar a_covered/b_covered boolean is applied to "
     "every listed clause (Qwen3 answered that way for most items; the strict list-only reader gave 0% coverage)."},
    {"id": "D-14B", "what": "The planned stronger local judge Qwen3-14B could not be used (its shared-cache blobs were "
     "deleted; 4-bit loading would need the memory-mapped path, which ran at ~20 s per tensor on this network "
     "filesystem). B1plusL = Qwen3-8B in thinking mode (<= 1024 new tokens, greedy; see D-B1plusL)."},
    {"id": "D-B1-maxtokens", "what": "B1 request uses max_tokens 16 with a 48-token retry (Arm A run_baselines, and the "
     "plan); Arm B's b1_request_example.json used 8. All other fields identical (checked in results/frozen_manifest.json)."},
    {"id": "D-LC-uncovered", "what": "The plan text says LC gives 0.0 to its own unparseable candidates; iter-1 Arm B "
     "stored 0.5 for every uncovered item (stages.row: score if covered else 0.5). The iter-1 pipeline behaviour is kept "
     "(score 0.5, covered=False); the raw 0.0 is kept in extra.raw_score."},
    {"id": "D-A0-textside", "what": "Held-out A0 uses the reusable zero-LLM function method.signature_faithfulness('A0') "
     "(rules text side). The iter-1 SCREEN A0 rows were produced by run_metrics.py with the A1 LLM text side, so the "
     "pre-flight reproduces A0 exactly on 76% of 50 screen items (A3: 100%)."},
    {"id": "D-A1-rewire", "what": "A1/A1L: method._text_side is wrapped so that the cached probe answers are used (the "
     "probe prompts are the iter-1 screen probe: probe_questions(with_rel=True), >40 questions split in two chunks); "
     "solver_sig.signature is memoised per AST. The vendored code path is otherwise unchanged."},
    {"id": "D-adapter", "what": "Iter-1 parsers accept only the FOLIO unicode dialect; every metric input is the dataset "
     "parser's canonical print (to_str(parse(x))) when it parses, else the raw string. Coverage with/without the adapter "
     "is in results/coverage_adapter.json."},
    {"id": "D-B7-port", "what": "B7 re-operationalised (no declared predicate lists in held-out outputs): within-formula "
     "arity overloads, within-story cross-formula arity conflicts (story_id; MALLS singletons), story-level joint "
     "satisfiability (Arm B fol_core.satisfiable nmax 3, 5 s; unknown -> 1), and greedy-vs-sample predicate Jaccard "
     "(2 systems). B7 = parse_ok & arity_self & arity_story & joint."},
    {"id": "D-B3c", "what": "B3c Monty-style clause conformance is a RE-IMPLEMENTATION (labelled), prompt in src/llm_stages.py."},
    {"id": "D-strata", "what": "Bootstrap resamples sentences within sentence-level strata corpus x complexity tercile: the "
     "L3 design strata are item-level (a sentence's candidates fall in several strata), so their sentence-level "
     "projection is used."},
    {"id": "D-rerank-story", "what": "Screen re-rank story exclusion (87/105/106/173) matched on Arm A's FOLIO story_id "
     "for Arm A items and on Arm B's Logic-LM example index for Arm B items."},
    {"id": "D-panel-slice", "what": "B3L / B3cL / RECALL_L substitutes run on the 609 panel items + the 3-system "
     "contamination slice (as planned for the frozen versions)."},
]


def fmt(x) -> str:
    return "NA" if x is None else f"{float(x):.4f}"


def run(limit=None) -> dict:
    rows = load_frame()
    long = read_jsonl(RES / "heldout_scores.jsonl")
    W = defaultdict(dict)
    for r in long:
        W[r["item_id"]][r["metric"]] = r
    metrics = sorted({r["metric"] for r in long})
    datasets = []
    for fold in ("heldout_confirm", "contamination", "transfer_unlabeled"):
        exs = []
        for r in rows:
            if r["fold"] != fold:
                continue
            ex = {"input": json.dumps({"sentence": r["sentence"], "candidate_fol": r["candidate_fol"]}, ensure_ascii=False),
                  "output": r["output"]}
            unc = []
            for m in metrics:
                x = W.get(r["item_id"], {}).get(m)
                if x is None:
                    continue
                ex[f"predict_{m}"] = fmt(x["score"])
                if not x["covered"]:
                    unc.append(m)
            a3 = W.get(r["item_id"], {}).get("A3")
            ex.update({"metadata_item_id": r["item_id"], "metadata_fold": fold, "metadata_sentence_id": r["sentence_id"],
                       "metadata_system": r["system"], "metadata_corpus": r["corpus"],
                       "metadata_complexity_tercile": r["complexity_tercile"], "metadata_n_conditions": r["n_conditions"],
                       "metadata_parse_ok": r["parse_ok"], "metadata_label_source": r["label_source"],
                       "metadata_L1_audited_status": r["L1_audited_status"],
                       "metadata_L3_sampling_weight": r["L3_sampling_weight"],
                       "metadata_L3_primary_error": r["L3_primary_error"],
                       "metadata_uncovered_metrics": unc,
                       "metadata_A3_error_type_pred": (a3 or {}).get("extra", {}).get("error_type_pred")})
            if fold == "contamination":
                ex["metadata_original_item_id"] = r["original_item_id"]
            if fold == "transfer_unlabeled":
                ex["metadata_condition"] = r.get("condition")
            exs.append(ex)
        datasets.append({"dataset": fold, "examples": exs})
    ana = json.loads((RES / "analysis.json").read_text()) if (RES / "analysis.json").exists() else {}
    ct = json.loads((RES / "confirmation_table.json").read_text()) if (RES / "confirmation_table.json").exists() else {}
    meta = {"method_name": "Frozen held-out confirmation of gold-free NL->FOL faithfulness metrics (iter 2)",
            "description": "LC latent-class agreement (Arm B), A3/A0/Ccov monotonicity signature (Arm A) and baselines "
                           "re-run with frozen iter-1 code on 700 sentences x 9 systems; primary labels = 609 panel3 items "
                           "(post-stratified weights).",
            "metrics": metrics, "confirmation_table": ct,
            "circularity_b": {k: v for k, v in (ana.get("circularity", {}).get("b_nonequiv") or {}).items()
                              if k in ("n", "LC_onecoin", "LC_maj", "A3", "B1", "B1L", "faithful_share_weighted")},
            "openrouter_spend_usd": ledger_total(), "deviations": [d["id"] for d in DEVIATIONS]}
    out = {"metadata": meta, "datasets": datasets}
    (ROOT / "method_out.json").write_text(json.dumps(out, ensure_ascii=False))
    # deviations + integrity
    jdump(DEVIATIONS, RES / "deviations.json")
    import preflight
    ver = preflight.verify()
    ledger = read_jsonl(WORK / "cost_ledger.jsonl")
    integ = {"frozen_manifest_reverified": ver, "ledger_sum_usd": sum(r.get("cost_usd", 0) for r in ledger),
             "ledger_n_calls": len(ledger), "reported_spend_usd": ledger_total(),
             "ledger_equals_reported": abs(sum(r.get("cost_usd", 0) for r in ledger) - ledger_total()) < 1e-9,
             "n_examples": {d["dataset"]: len(d["examples"]) for d in datasets}}
    jdump(integ, RES / "integrity.json")
    logger.info(f"export: {integ}")
    return integ
