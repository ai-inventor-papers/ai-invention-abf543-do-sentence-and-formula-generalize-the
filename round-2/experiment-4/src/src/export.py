"""method_out.json (exp_gen_sol_out): one dataset per item group, identical items across metrics.

Groups: screen_real, screen_rewrites, heldout_panel, heldout_top, contamination. Predictions are strings;
a metric that was not computed for an item is simply absent (e.g. every gemini TVJT/B1 prediction on held-out
items is absent: the judge was unavailable all session). metadata_tvjt_status records this per item.
"""
from __future__ import annotations

import json

import common
import worlds as WW
from common import DATA, RESULTS, read_jsonl
from labels import load_labels


def _f(x) -> str:
    return f"{x:.6f}" if isinstance(x, (int, float)) else str(x)


def main() -> dict:
    by_key, by_src = WW.load_cache()

    def nworlds(fol):
        r = by_key.get(by_src.get(fol)) if fol else None
        return (len(r["worlds"]), r.get("canon")) if r else (None, None)

    # ---------------- screen (Phase 1; labels = iter-1 L_bij; predictions from iter-1 cache + zero-cost replay)
    ss = json.loads((common.ARMB / "data" / "screen_set.json").read_text())
    sent = {s["sid"]: s for s in ss["sentences"]}
    i1 = {}
    for r in read_jsonl(common.ARMB / "results" / "screen_scores.jsonl"):
        i1[(r["item_id"], r["metric"])] = r
    rep = {r["item_id"]: r for r in read_jsonl(RESULTS / "screen_replay_scores.jsonl")}
    screen_real = []
    for it in ss["real_items"]:
        n, cf = nworlds(it["fol"]) if it.get("parse_ok") else (None, None)
        ex = {"input": json.dumps({"sentence": sent[it["sid"]]["nl"], "candidate_fol": it["fol"]}, ensure_ascii=False),
              "output": it["L_bij"],
              "metadata_item_id": it["item_id"], "metadata_sentence_id": it["sid"], "metadata_system": it["system"],
              "metadata_parse_ok": bool(it.get("parse_ok")), "metadata_tercile": sent[it["sid"]].get("tercile"),
              "metadata_canon_fol": cf, "metadata_n_canonical_worlds": n}
        for m, key in (("TVJT_iter1", "TVJT"), ("B1", "B1"), ("LC_onecoin", "LC_onecoin"), ("B3sc", "B3sc")):
            r = i1.get((it["item_id"], key))
            if r:
                ex[f"predict_{m}"] = _f(r["score"])
        r = rep.get(it["item_id"])
        if r and r.get("C1_replay") is not None:
            ex["predict_TVJT_C1_replay"] = _f(r["C1_replay"])
            ex["metadata_replay_world_coverage"] = round(r["cov"], 4)
        screen_real.append(ex)
    screen_rw = []
    for rw in ss["rewrites"]:
        g = sent[rw["sid"]]
        rn, rc = nworlds(rw["fol"])
        gn, gc = nworlds(g["gold_fol"])
        ex = {"input": json.dumps({"sentence": g["nl"], "candidate_fol": rw["fol"]}, ensure_ascii=False),
              "output": "meaning_preserving_rewrite_of_gold",
              "metadata_item_id": rw["item_id"], "metadata_rewrite_kind": rw["kind"], "metadata_gold_fol": g["gold_fol"],
              "metadata_canon_fol": rc, "metadata_gold_canon_fol": gc,
              "metadata_canon_identical_to_gold": (rc == gc) if rc and gc else None}
        for m, key in (("TVJT_iter1", "TVJT"), ("B1", "B1")):
            r = i1.get((rw["item_id"], key))
            if r:
                ex[f"predict_{m}"] = _f(r["score"])
            r0 = i1.get((f"{rw['sid']}:gold", key))
            if r0:
                ex[f"metadata_gold_score_{m}"] = r0["score"]
        screen_rw.append(ex)

    # ---------------- held-out (labels read only through the freeze-guarded loader)
    lab = load_labels()
    tg = [json.loads(l) for l in (DATA / "heldout_targets.jsonl").read_text().splitlines()]
    sc = {}
    for p in ("zero_llm_scores.jsonl", "a3_scores.jsonl", "heldout_llm_scores.jsonl"):
        for r in read_jsonl(RESULTS / p):
            sc.setdefault(r["item_id"], {})[r["metric"]] = r
    groups = {"heldout_panel": [], "heldout_top": [], "contamination": []}
    for t in tg:
        L = lab.get(t["item_id"], {})
        n, cf = nworlds(t["fol_folio"])
        ex = {"input": json.dumps({"sentence": t["nl"], "candidate_fol": t["fol_raw"]}, ensure_ascii=False),
              "output": ("faithful" if L.get("y_panel") == 1 else "unfaithful") if L.get("panel") else
                        ({1: "faithful", 0: "unfaithful"}.get(L.get("y_hard"), "unknown")),
              "metadata_item_id": t["item_id"], "metadata_sentence_id": t["sid"], "metadata_system": t["system"],
              "metadata_corpus": t["corpus"], "metadata_complexity_tercile": t["tercile"],
              "metadata_complexity_composite": t["composite"], "metadata_n_conditions": t["n_conditions"],
              "metadata_bridge": t["bridge"], "metadata_fol_folio": t["fol_folio"], "metadata_canon_fol": cf,
              "metadata_n_canonical_worlds": n, "metadata_panel_weight": L.get("w"),
              "metadata_label_source": "panel3" if L.get("panel") else "hard/solver",
              "metadata_y_soft": L.get("y_soft"), "metadata_L3_primary_error": L.get("primary_error"),
              "metadata_tvjt_status": "pending: gemini-2.5-flash unavailable (OpenRouter daily key limit)"}
        for m, r in sc.get(t["item_id"], {}).items():
            ex[f"predict_{m}"] = _f(r["score"])
            if m == "A3" and r.get("error_type_pred"):
                ex["metadata_A3_error_type_pred"] = r["error_type_pred"]
        ex["predict_parse_ok"] = "1" if t["parse_ok_meta"] else "0"
        if t["group"] == "contamination":
            ex["metadata_original_item_id"] = t["original_item_id"]
            ex["metadata_rename_incomplete"] = t["rename_incomplete"]
            groups["contamination"].append(ex)
        else:
            if t["panel"]:
                groups["heldout_panel"].append(ex)
            if t["tercile"] == "top":
                groups["heldout_top"].append(dict(ex))
    out = {"metadata": {
        "method_name": "TVJT crossover deep test (iter 2): canonical-form repair R1 + frozen judge protocol R2/R3; "
                       "zero-LLM held-out baselines LC_onecoin / A3 / B3sc / parse_ok",
        "judge_status": "gemini-2.5-flash unavailable for the whole session (OpenRouter key daily limit, HTTP 403); "
                        "all TVJT*/B1/B1x3/TVJT_lite held-out predictions pending; screen predictions TVJT_iter1/B1 "
                        "are iter-1 cached gemini outputs",
        "labels": {"screen_real": "iter-1 L_bij (blind bijection equivalence to FOLIO v1 gold)",
                   "screen_rewrites": "solver-verified meaning-preserving rewrites (should score like their gold)",
                   "heldout_panel": "panel3 L3 majority (post-stratified weight in metadata_panel_weight)",
                   "heldout_top": "top-tercile rows; panel label when available else hard solver label",
                   "contamination": "entity-renamed paraphrase rows; label transferred from the original"},
        "analysis": "results/analysis.json", "verdict": "results/verdict.json"},
        "datasets": [{"dataset": "screen_real", "examples": screen_real},
                     {"dataset": "screen_rewrites", "examples": screen_rw}] +
                    [{"dataset": k, "examples": v} for k, v in groups.items()]}
    (common.ROOT / "method_out.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    return {d["dataset"]: len(d["examples"]) for d in out["datasets"]}


if __name__ == "__main__":
    print(main())
