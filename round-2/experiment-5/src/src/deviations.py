#!/usr/bin/env python3
"""Writes results/deviations.json (plan departures D1-D8 plus the ones that arose while running) and
results/frozen_manifest.json (sha1 of every vendored file)."""
from __future__ import annotations

import time

from common import RES, ROOT, VENDOR, file_sha1, jdump, jload

DEV = [
    {"id": "D1", "what": "ONE label family (3-member no-gold panel). No audited-solver label exists for legal text; shared "
     "text-reading bias between the panel and the LLM judges (B1, B1plus) favours the judges over text-blind DC. Every "
     "number is labelled 'panel-only, secondary transfer'. Mitigation run: label robustness (each member alone, "
     "unanimous-only). The planned long-text exception-sensitivity check could NOT be run (see D-BUDGET)."},
    {"id": "D2", "what": "Calibration gate items are short ProverQA-style sentences (M1 0.875, M2 0.950, M3 0.850); the gate "
     "certifies members, not their accuracy on 60-170-word legal text."},
    {"id": "D3", "what": "Sample 680 drawn (480 system + 200 pilot) over 158 sentences; X3 per-bin and X4 per-type cells are "
     "descriptive and flagged underpowered when positives/unfaithful-of-type < 20."},
    {"id": "D4", "what": "max_tokens 1024 (gpt-oss-120b 4096) instead of 256 (2048); prompt and extractor v2 byte-identical "
     "(sha1 afabb41e...). Truncation at 1024: 9/1422 greedy outputs (0.6%); estimated truncation at the old 256 cap: 62/1422 "
     "(4.4%) outputs used >256 completion tokens (estimated from usage, instead of a separate 256-token probe)."},
    {"id": "D5", "what": "Contamination not tested (public statutes; could inflate B1/B1plus, not DC)."},
    {"id": "D6", "what": "Pilot formulas pooled across grounded/ungrounded conditions; condition kept as metadata, never analysed."},
    {"id": "D7", "what": "SARA clauses with cross-references kept, flagged has_cross_reference (21 sentences); DC AUROC split "
     "reported in analysis.json cross_reference_items."},
    {"id": "D8", "what": "DC defaults from short-sentence development used untouched on long text (the transfer test); DC_fp "
     "(structural-fingerprint map order) and DC_noL3 (L1/L2 only) are declared secondary variants frozen with the default."},
    {"id": "D-SET", "what": "Sentence set = 158 (68 AI-Act Art. 3 definitions - the Act has 68, the pilot covers 63 - plus 90 "
     "others). Marker bin B2 (>=4 of the 10 markers) is rare in statutory text: 16 sentences in total across ALL sources "
     "(public 4 + AI-Act non-Art.3 10 + Art.3 2). Per the selection rule the B2 deficit moved to B1. The public EUR-Lex/SARA "
     "pools (147 after filters) were topped up by the F1 fallback pool (AI-Act non-Art.3 sentences, 31 used, "
     "source=ai_act_other_articles) only where a bin ran out. SARA contributed 19 (<20 target: its eligible B1/B2 pool is 14)."},
    {"id": "D-L3", "what": "Before any label: the T0 toy tests showed L3 definitions with negated literals or with literals over "
     "still-mapped predicates manufacture agreement (Bird := Bird ∧ ¬Penguin absorbs a dropped exception). L3 was restricted "
     "to conjunctions of 2 POSITIVE literals over predicates unmatched by the rest of the map, each used once. Residual, "
     "documented identifiability limit: positive granularity (TallMan := Tall ∧ Man) is formula-only indistinguishable from "
     "a dropped/added positive conjunct (unit test 'drop_conjunct -> STRONGER/WEAKER' FAILS by design); DC_noL3 quantifies it."},
    {"id": "D-ORDER", "what": "Pre-registered best-map order EQUIV > STRONGER/WEAKER > INCOMPARABLE > CONTRADICTORY makes "
     "CONTRADICTORY rare (a partial L2 map is usually jointly satisfiable), so error type negation_polarity is almost never "
     "named; the DC score (EQUIV share) is unaffected."},
    {"id": "D-PEERS", "what": "T=0.8 samples are not DC peers (not independent systems); they are used only for DC_lone and B8. "
     "Pilot family = one rater whose weight is split equally over its parseable runs; pilot candidates' peers = the 9 systems."},
    {"id": "D-WEIGHTS", "what": "The pre-registered DS weights degenerate: every system's one-coin sensitivity p_w < 0.5 on "
     "long legal text (EQUIV agreement is rare), so every logit weight hits the 0.05 floor and DC equals its unweighted "
     "form (up to the pilot-family split)."},
    {"id": "D-KILL", "what": "One sentence (d6f53e1b30) hit the per-sentence watchdog; 71 of its pairs are UNKNOWN "
     "(coverage loss, counted). The runtime-only big-formula rule was NOT needed (DC wall 14 min << 2.5 h)."},
    {"id": "D-BUDGET", "what": "At 04:22 UTC the RUN-LEVEL OpenRouter budget shared by all sibling experiments ('Test idea' "
     "phase, $7.00; this artifact had spent $4.65) was exhausted (HTTP 403 aii_run_budget_exhausted; does not reset). "
     "Consequences: (a) panel: 655/680 sampled items labelled (645 with 3 votes, 10 with 2 votes; 25 unlabelled, weights "
     "post-stratified over labelled items); (b) B3 back-translation: only 40/680 flash calls done -> ALL 680 back-translated "
     "by local Qwen/Qwen3-8B (bf16, greedy, frozen B3 prompt) then vendor DeBERTa/MiniLM scoring (substitute, labelled "
     "b3_source=local_qwen3_8b); (c) the long-text exception-sensitivity check (30 mutants x 3 members) NOT run -> the "
     "panel's exception sensitivity is UNCERTIFIED; (d) DC+arb verdicts by local Qwen3-8B instead of flash (substitute); "
     "(e) F7 minority top-up (weighted faithful share 9.4% < 12%) impossible; (f) no sonnet 4th voter."},
    {"id": "D-SAMPLE", "what": "The adjudication sample was redrawn once BEFORE any label existed (boost for gpt-4.1-mini/llama "
     "1.25 -> 1.5) because the first draw gave llama 56 < the pre-set minimum 60."},
    {"id": "D-B7", "what": "B7 re-operationalised as in round 2 (no declared predicate lists): arity_self (a name used with two "
     "arities), arity_doc (cross-formula arity conflict within act x system), joint (unbounded z3 satisfiability of the "
     "candidate with the same system's formulas of the same act that share a predicate; 3 s; unknown -> ok); "
     "B7 = parse & arity_self & arity_doc & joint. B7_jacc = user's cross-run Jaccard (greedy vs own samples)."},
    {"id": "D-ARB", "what": "DC+arb verbaliser is a deterministic simplified re-implementation (predicate names split into "
     "words), not vendor verbalize.py (spaCy/WordNet)."},
    {"id": "D-INV", "what": "Invariance 'synonym rename' uses random predicate names (DC is name-blind, so any rename tests the "
     "same property); reorder = swap operands of every ∧/∨; contrapositive at the top-level implication."},
    {"id": "D-DCUNW", "what": "Bookkeeping: dc_score left DC_unw empty for unparseable candidates; analysis applies the "
     "contract's 0.5 rule. Post-hoc diagnostic DC_unparse0 (unparseable -> 0, the LC_maj/DS_bin convention) is reported "
     "separately and clearly labelled not pre-registered."},
]


def main() -> None:
    jdump({"deviations": DEV, "written_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}, RES / "deviations.json")
    files = {}
    for p in sorted(VENDOR.rglob("*")):
        if p.is_file():
            files[str(p.relative_to(ROOT))] = file_sha1(p)
    src = {
        "vendor/ds": "/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_dataset_1 (src/, prompts/, work/, label_report.json)",
        "vendor/armB": "/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_1/gen_art/gen_art_experiment_2 (src/, results/prompts_frozen.json)",
        "vendor/iter2": "/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/3_invention_loop/iter_2/gen_art/gen_art_experiment_3/src",
        "src/stats_ext.py": "byte-identical copy of vendor/iter2/stats.py"}
    jdump({"sha1": files, "sources": src, "stats_ext_identical": file_sha1(ROOT / "src" / "stats_ext.py") == files.get("vendor/iter2/stats.py"),
           "sibling_dc_implementation": "none found in run_ujABDGgoK_5Q iter_2 gen_art_experiment_3/4 (empty at start); "
                                        "contract v1 implemented from the plan defaults in dc/",
           "prompt_sha1": {"generation": "afabb41eedb31b3ee96e32419bd8e4abd727f758", "B1": "d7fe4b542820d08a2489de0c7fcf8b40baa5187d"}},
          RES / "frozen_manifest.json")


if __name__ == "__main__":
    main()
