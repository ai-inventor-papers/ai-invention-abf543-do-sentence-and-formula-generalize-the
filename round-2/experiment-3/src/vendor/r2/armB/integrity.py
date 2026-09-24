"""T6 post-hoc integrity checks -> results/integrity_checks.json."""
from __future__ import annotations

import glob
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    ss = json.loads((ROOT / "data" / "screen_set.json").read_text())
    scores = [json.loads(x) for x in (ROOT / "results" / "screen_scores.jsonl").read_text().splitlines() if x.strip()]
    an = json.loads((ROOT / "results" / "analysis.json").read_text())
    real_ids = sorted(r["item_id"] for r in ss["real_items"])
    chk = {}
    chk["fingerprint_recomputed_matches"] = hashlib.sha1("\n".join(real_ids).encode()).hexdigest() == ss["fingerprint"]
    chk["fingerprint"] = ss["fingerprint"]
    per_sys = Counter(r["system"] for r in ss["real_items"])
    chk["real_items_equals_sum_of_system_primaries"] = sum(per_sys.values()) == len(ss["real_items"]) == ss["counts"]["real_items"]
    chk["real_items_unique"] = len(set(real_ids)) == len(real_ids)
    chk["n_sentences"] = len(ss["sentences"])
    chk["label_counts_sum"] = {k: sum(v.values()) for k, v in ss["counts"]["label_distribution"].items()}
    chk["unlabeled_L_bij"] = ss["counts"]["label_distribution"]["L_bij"].get("unlabeled", 0)
    by_metric = Counter((s["metric"], s["item_kind"]) for s in scores)
    chk["every_real_item_scored_by_every_metric"] = {m: by_metric[(m, "real")] == len(real_ids) for m in
                                                     sorted({s["metric"] for s in scores})}
    unc = Counter(s["metric"] for s in scores if s["item_kind"] == "real" and not s["covered"])
    chk["uncovered_real_items_kept_with_0.5"] = {m: {"uncovered": unc[m],
                                                     "all_uncovered_scored_0.5": all(s["score"] == 0.5 for s in scores
                                                                                     if s["metric"] == m and not s["covered"])}
                                                 for m in sorted(unc)}
    chk["noise_metric_G3_ci_contains_0"] = an["controls"]["noise_metric_G3"]["ci"][0] <= 0 <= an["controls"]["noise_metric_G3"]["ci"][1]
    chk["shuffled_label_auroc_mean"] = an["controls"]["shuffled_label_auroc_mean_TVJT"]
    chk["bootstrap_seed"] = 0
    # cross-arm item-set comparison (never imported, only diffed)
    others = [p for p in glob.glob(str(ROOT.parent / "*" / "**" / "screen_set.json"), recursive=True)
              if not p.startswith(str(ROOT))]
    diffs = {}
    for p in others:
        try:
            o = json.loads(Path(p).read_text())
            oids = sorted(r["item_id"] for r in (o.get("real_items") or o.get("real") or []))
            osids = sorted({r["item_id"].split(":")[0] for r in (o.get("real_items") or o.get("real") or [])})
            diffs[p] = {"their_fingerprint": o.get("fingerprint"), "n_theirs": len(oids), "n_ours": len(real_ids),
                        "only_ours": len(set(real_ids) - set(oids)), "only_theirs": len(set(oids) - set(real_ids)),
                        "identical": oids == real_ids, "only_ours_ids": sorted(set(real_ids) - set(oids))[:20],
                        "only_theirs_ids": sorted(set(oids) - set(real_ids))[:20],
                        "same_sentence_ids": osids == sorted({r.split(":")[0] for r in real_ids})}
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            diffs[p] = {"error": repr(e)}
    chk["cross_arm_screen_diff"] = diffs or "no other arm's screen_set.json found at run time"
    chk["cross_arm_diff_explanation"] = (
        "10 FOLIO-v1 validation examples have len(premises) != len(premises-FOL). Arm B skips zipping those examples' "
        "premises (their sentences still enter via other examples of the same story when aligned); zipping by index "
        "there misaligns gold (e.g. 'Tom lives in a single-parent family.' -> '∀x (SingleParent(x) ∨ FewResources(x) → "
        "Hardship(x))'). Arm A (gen_art_experiment_1) zips them, which admits ~11 extra sentences (stories 87/105/106/173) "
        "with misaligned gold and shifts the sha1-first-300 boundary; the 803 shared items have identical primary candidates.")
    (ROOT / "results" / "integrity_checks.json").write_text(json.dumps(chk, indent=1))
    print(json.dumps(chk, indent=1))


if __name__ == "__main__":
    main()
