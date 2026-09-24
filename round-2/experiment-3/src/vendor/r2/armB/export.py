"""Export method_out.json (exp_gen_sol_out schema): one example per scored item (real candidates, golds, controlled
mutants, rewrites) with the label as `output`, every metric's score as predict_<metric>, and the full summary
(gates, verdict, counts, costs, kept-file workspace paths) in top-level metadata."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def run_export(limit) -> None:
    d = ROOT / ("data" if limit is None else f"runs/mini_{limit}/data")
    r = ROOT / ("results" if limit is None else f"runs/mini_{limit}/results")
    ss = json.loads((d / "screen_set.json").read_text())
    an = json.loads((r / "analysis.json").read_text())
    S = pd.DataFrame([json.loads(x) for x in (r / "screen_scores.jsonl").read_text().splitlines() if x.strip()])
    sc = {}
    for rr in S.itertuples():
        sc.setdefault(rr.item_id, {})[rr.metric] = (rr.score, rr.covered, rr.error_type_pred)
    sent = {s["sid"]: s for s in ss["sentences"]}

    def preds(iid):
        out = {}
        for m, (v, c, et) in sorted(sc.get(iid, {}).items()):
            out[f"predict_{m}"] = f"{v:.4f}"
            if et not in (None, "") and not (isinstance(et, float)):
                out[f"predict_{m}_error_type"] = str(et)
        return out

    ex_real, ex_ctrl = [], []
    for it in ss["real_items"]:
        s = sent[it["sid"]]
        ex_real.append({"input": f"Sentence: {s['nl']}\nCandidate FOL: {it['fol']}", "output": it["L_bij"],
                        "metadata_item_id": it["item_id"], "metadata_sid": it["sid"], "metadata_system": it["system"],
                        "metadata_parse_ok": it["parse_ok"], "metadata_parse_err": it.get("parse_err"),
                        "metadata_gold_fol": s["gold_fol"], "metadata_gold_source": s["gold_source"],
                        "metadata_recipe_gold_source": s["recipe_gold_source"], "metadata_curated_fol": s.get("curated_fol"),
                        "metadata_L_bij_orig": it["L_bij_orig"], "metadata_L_str": it["L_str"],
                        "metadata_L_bij_cur": it.get("L_bij_cur"), "metadata_L_any": it.get("L_any"),
                        "metadata_n_equiv_maps": it.get("n_equiv_maps"), "metadata_label_reason": it.get("label_reason"),
                        "metadata_tercile": s["tercile"], "metadata_composite": s["composite"],
                        "metadata_features": {k: s[k] for k in ("n_tokens", "n_quant", "depth", "n_cond")},
                        **preds(it["item_id"])})
    for s in ss["sentences"]:
        ex_ctrl.append({"input": f"Sentence: {s['nl']}\nCandidate FOL: {s['gold_fol']}", "output": "correct",
                        "metadata_item_id": f"{s['sid']}:gold", "metadata_kind": "gold", "metadata_operator": None,
                        **preds(f"{s['sid']}:gold")})
    for m in ss["mutants"]:
        ex_ctrl.append({"input": f"Sentence: {sent[m['sid']]['nl']}\nCandidate FOL: {m['fol']}", "output": "incorrect",
                        "metadata_item_id": m["item_id"], "metadata_kind": "mutant", "metadata_operator": m["op"],
                        **preds(m["item_id"])})
    for m in ss["rewrites"]:
        ex_ctrl.append({"input": f"Sentence: {sent[m['sid']]['nl']}\nCandidate FOL: {m['fol']}", "output": "correct",
                        "metadata_item_id": m["item_id"], "metadata_kind": "rewrite", "metadata_operator": m["kind"],
                        **preds(m["item_id"])})
    base = "" if limit is None else f"runs/mini_{limit}/"
    kept = {k: str(ROOT / (base + v)) for k, v in {
        "screen_set": "data/screen_set.json", "alt_candidates": "data/alt_candidates.jsonl",
        "worlds_cache": "data/worlds_cache.jsonl", "consequences_cache": "data/consequences_cache.jsonl",
        "blindspot_supplement": "data/blindspot_supplement.jsonl", "screen_scores": "results/screen_scores.jsonl",
        "cost_ledger": "results/cost_ledger.jsonl", "analysis": "results/analysis.json", "verdict": "results/verdict.json",
        "blindspot_headtohead": "results/blindspot_headtohead.json", "prompts_frozen": "results/prompts_frozen.json",
        "dev_checks": "results/dev_checks.json", "b1_request_example": "results/b1_request_example.json",
        "llm_cache": "cache/llm/"}.items()}
    an_small = {k: v for k, v in an.items() if k not in ("metrics",)}
    an_small["metrics"] = {m: {k: v for k, v in res.items()} for m, res in an["metrics"].items()}
    meta = {"method_name": "Screen Arm B: TVJT worlds / instance-consequence NLI / latent-class vs B1 judge + B2 parse rate",
            "fingerprint": ss["fingerprint"], "recipe_version": ss["recipe_version"], "counts": ss["counts"],
            "feature_spec": ss["feature_spec"], "gold_policy": GOLD_POLICY, "deviations": DEVIATIONS,
            "analysis": an_small, "kept_files_workspace_paths": kept,
            "llm_model": "google/gemini-2.5-flash (T=0, reasoning disabled)",
            "nli_model": "MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli (fp16, cuda)"}
    out = {"metadata": meta, "datasets": [
        {"dataset": "folio_dev_logiclm_screen_real_candidates", "examples": ex_real},
        {"dataset": "folio_dev_screen_controlled_gold_mutants_rewrites", "examples": ex_ctrl}]}
    (ROOT / ("method_out.json" if limit is None else f"runs/mini_{limit}/method_out.json")).write_text(
        json.dumps(out, ensure_ascii=False, indent=1, default=str))


GOLD_POLICY = (
    "Screen item set follows the recipe exactly (gold = curated if NL-matched else FOLIO v1; dropped if unparseable/"
    "unsatisfiable). PRIMARY labels (L_bij) are computed against FOLIO v1 gold whenever it is usable, NOT against the "
    "DSAVlab-UNIUD curated gold: the curated release re-annotates FOLIO v2 (reworded story sentences, FOLIO-v2 "
    "vocabulary with binary predicates/constants, 'some'=at-least-two conventions), so blind bijection equivalence "
    "against it mostly measures vocabulary/granularity mismatch. Labels vs curated gold (L_bij_cur), vs v1 (L_bij_orig), "
    "trigram-anchored (L_str) and union (L_any) are all reported; AUROC is reported under each.")
DEVIATIONS = [
    "Primary label gold = FOLIO v1 (see gold_policy); curated gold used as secondary label L_bij_cur.",
    "Blind-spot supplement extended beyond FOLIO-dev with FOLIO-train (∃ formulas), curated MALLS subset and MALLS-v0.1 "
    "test mixed-quantifier formulas, because FOLIO-dev gold has 0 mixed ∀/∃ formulas (SCOPE_SWAP inapplicable on the screen).",
    "One-coin latent-class likelihood includes (1-rho) for non-coinciding wrong pairs (proper Bernoulli coincidence model).",
    "Dawid-Skene sanity row: task = candidate, worker = each OTHER system, label = agrees with it (the plan's "
    "one-worker-per-task reformulation is degenerate).",
    "Free-variable formulas (implicit universal closure, e.g. 'P(x) → Q(x)') are parse failures per plan (parse_ok=0, label incorrect).",
    "Added secondary TVJT_nv (non-vacuous worlds) and robustness analyses (within-sentence discrimination, "
    "vocabulary-compatible subset AUROC, paired clustered-bootstrap AUROC deltas); none of them enters the selection rule.",
    "FOLIO-v1 examples whose premise and premise-FOL counts differ are not zipped (misaligned gold); Arm A zips them, so "
    "the screens differ on ~11 sentences (803 shared items identical) — see results/integrity_checks.json.",
]
