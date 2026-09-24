#!/usr/bin/env python3
"""Collect every pre-registered prediction -> PASS / FAIL / UNDERPOWERED / NOT_RUN with numbers
(results/verdicts.json); write results/proposed_amendments.json and the T6 integrity check (results/integrity.json)."""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dc.common import RES, WORK, jdump, rj  # noqa: E402


def L(name):
    p = RES / name
    return json.loads(p.read_text()) if p.exists() else {}


def v(status, **kw):
    return {"verdict": status, **kw}


def main():
    pre = L("prereg.json")
    m0, m1, m2, m3, m4, m5, m6, m7 = (L("m0_anchor.json"), L("m1_confound.json"), L("m2_invariance.json"), L("m3_boundary.json"),
                                      L("m4_placebo.json"), L("m5_ladder_typing.json"), L("m6_within_sentence.json"), L("m7_goldflag.json"))
    arb_ran = bool(m3.get("n_calls_arbiter"))
    V = {}
    p = m1["predictions"]
    V["M1.P1_DC_arm_gap<0.02"] = v("PASS" if p["P1_DC_arm_gap"]["PASS"] else "FAIL", gaps=p["P1_DC_arm_gap"]["gaps"],
                                  equivalent_within_0_03=p["P1_DC_arm_gap"]["equivalent_within_0.03"])
    V["M1.P2_DC_crossed>=0.85"] = v("PASS" if p["P2_DC_crossed"]["PASS"] else "FAIL", auroc=p["P2_DC_crossed"]["auroc"],
                                   DC_L2w_crossed=m1["crossed"]["DC_L2w"]["auroc"],
                                   cause="L3 granularity/antonym definitions absorb NEG and DROP_CONJ mutants (see P6)")
    V["M1.P3_VC_gap>0.2"] = v("PASS" if p["P3_VC_gap"]["PASS"] else "FAIL", gap=p["P3_VC_gap"]["gap"],
                              note="within an arm F and M share vocabulary, so VC cannot separate them in ANY arm; the gap is ~0")
    V["M1.P4_VC_crossed<0.5"] = v("PASS" if p["P4_VC_crossed"]["PASS"] else "FAIL", auroc=p["P4_VC_crossed"]["auroc"])
    iso = p.get("P5_iso_blind_spot", {})
    V["M1.P5_iso_blind_spot~0.5"] = v(("PASS" if iso.get("PASS") else "FAIL") if iso.get("n", 0) >= 20 else "UNDERPOWERED",
                                      n=iso.get("n"), within_det=iso.get("within_det"))
    p6 = p["P6_L3_granularity_blind_spot"]
    V["M1.P6_L3_blind_spot(DROP_CONJ DC<DC_L2w)"] = v("PASS" if p6["PASS"] else "FAIL", DROP=p6["DROP_CONJ_det"],
                                                     ADD=p6["ADD_CONJ_det"], post_hoc_NEG=p6["post_hoc_NEG_absorption (not pre-registered)"])
    V["M1b.DC_adds_over_[B1,parse,VC]_panel"] = v("PASS" if p["M1b"]["PASS"] else "FAIL", delta=p["M1b"]["delta"], ci=p["M1b"]["ci"],
                                                  solver=m1["M1b_real_dev"]["stack_solver_base_B1+parse_ok+VC"])
    pk = m2["per_kind"]
    fa10 = {k: pk[k].get("FA_delta_0.10", {}).get("rate") for k in pk}
    V["M2.P1_FA(0.10)<=0.05_all_kinds"] = v("PASS" if all((x or 0) <= 0.05 for x in fa10.values()) else "FAIL", FA_0_10=fa10)
    fa0 = {k: pk[k].get("FA_delta_0.00", {}).get("rate") for k in ("syn_rename", "tok_rename", "var_rename")}
    V["M2.P2_FA(0)=0_renames"] = v("PASS" if all((x or 0) == 0 for x in fa0.values()) else "FAIL", FA_0=fa0,
                                   cause="role tie-break follows lexicographic pair order (name-dependent); see m2_rename_diagnosis.json")
    c = m2["contamination"]["all"]
    V["M2.P3_contamination_CI_includes_0_and_|Δ|<0.096"] = v(
        "PASS" if (c["delta_ci"][0] <= 0 <= c["delta_ci"][1] and abs(c["mean_delta_orig_minus_para"]) < 0.096) else "FAIL",
        delta=c["mean_delta_orig_minus_para"], ci=c["delta_ci"], share_exactly_equal=c["share_exactly_equal"],
        B1_delta=0.0965, note="|Δ| is 40x smaller than B1's; the CI excludes 0 by 0.0001 (renames that break ties)")
    P1 = m3["a_dose"]["P1"]
    V["M3.P1_dose_curve"] = v("PASS" if P1["PASS"] else "FAIL", det=P1["det"], parts=P1["parts"])
    V["M3.P2_DC+arb>DC_at_k>=4"] = v("NOT_RUN" if not arb_ran else ("PASS" if m3["b_arbiter"]["P2_PASS"] else "FAIL"),
                                     reason=None if arb_ran else "OpenRouter 403 aii_run_budget_exhausted (run-level cap; key polled 60 min)")
    cr = m3["c_real"]
    V["M3.P3_real_shared_bias_slope<0_top_bin<0.5"] = v("PASS" if cr["P3_PASS"] else "FAIL", slope=cr["logistic_slope_det_on_wrong_conc"],
                                                        slope_ci=cr["slope_ci"], bins={k: b["DC"]["mean"] for k, b in cr["bins"].items()})
    a = m4["a_cross_sentence"]
    V["M4.P1_spurious_EQUIV<=2%_non_iso"] = v("PASS" if a["TARGET_spurious_EQUIV_le_2pct"] else "FAIL",
                                              L2=a["all"].get("spurious_EQUIV_non_iso_L2"), L3=a["all"].get("spurious_EQUIV_non_iso_L3"),
                                              L3_flag=a["FLAG_L3_increment_gt_5pct"], shape_isomorphic_rate=a["all"]["shape_isomorphic_rate"])
    b = m4["b_within_sentence_shuffle"]
    V["M4.P2_shuffle~0.5"] = v("FAIL" if b["panel"]["mean_shuffled_auroc"] > 0.6 else "PASS", panel=b["panel"], solver=b["solver"],
                               reading="most of DC's AUROC is BETWEEN-sentence agreement structure")
    d = m4["d_lexical_anchor"]
    V["M4.P3_manufactured_agreement_enriched_in_unfaithful"] = v("PASS" if d["P3_enriched_among_unfaithful"] else "FAIL",
                                                                  panel_unf=d["panel_unfaithful_manufactured_share"]["mean"],
                                                                  panel_f=d["panel_faithful_manufactured_share"]["mean"],
                                                                  solver_unf=d["solver_unfaithful_manufactured_share"]["mean"],
                                                                  solver_f=d["solver_faithful_manufactured_share"]["mean"])
    V["M5.P1_largest_lift_added_condition"] = v("PASS" if m5["P1_PASS"] else "FAIL", largest=m5["P1_largest_step_lift_type"],
                                                lifts=m5["step_lifts"])
    t = m5["typing_real_panel_unfaithful"]
    V["M5.P2_typing>majority"] = v("PASS" if m5["P2_PASS"] else "FAIL", dc=t["weighted_top1_DC"], majority=t["majority_baseline"],
                                   TJ_same_items=t["weighted_top1_TJ_same_items"])
    V["M6.assert_n_dropped=36_n_impl=24"] = v("PASS" if (m6["assert_n_dropped_36"] and m6["assert_n_impl_24"]) else "FAIL",
                                              n=(m6["n_dropped"], m6["n_impl"]))
    V["M7.P1_goldflag_auroc>0.5"] = v("PASS" if m7["P1_PASS"] else "FAIL", auroc=m7["DC_gold_auroc_vs_L0"],
                                      stack_B1=m7.get("stack_B1_plus_DC"), stack_TJ=m7.get("stack_TJ_plus_DC"))
    jdump({"prereg_sha256_of_frozen_config": pre.get("frozen_dc_config_sha256"), "verdicts": V,
           "counts": {s: sum(1 for x in V.values() if x["verdict"] == s) for s in ("PASS", "FAIL", "UNDERPOWERED", "NOT_RUN")}},
          RES / "verdicts.json")
    am = {"status": "PROPOSED for the confirmation artifact; NOT applied here (frozen config unchanged)",
          "amendments": [
              {"id": "A1_drop_or_restrict_L3", "evidence": "M1 per-op: NEG det DC 0.52 vs DC_L2w 1.00; DROP_CONJ 0.68 vs 0.98; "
                                                         "crossed AUROC 0.805 vs 0.999; M4(a) L3 adds 11.9% spurious EQUIV on non-isomorphic "
                                                         "cross-sentence pairs; dev panel DC_L2w 0.774 >= DC 0.769",
               "proposal": "freeze DC_L2w (levels L1+L2, DS weights) as primary; if L3 is kept, forbid single negated-literal "
                           "definitions and require a lexical (WordNet lemma) cover for compound definitions (as the dataset's L2)"},
              {"id": "A2_name_free_role_tiebreak", "evidence": "M2: 1/999 DC changes and 0.4-0.5% relation-vector changes under renaming, "
                                                               "all traced to the source/target role tie-break following the lexicographic (lo, hi) pair order",
               "proposal": "break role ties with a name-free structural key (formula with symbols replaced by first-occurrence "
                           "indices), or search both directions and take the max rank"},
              {"id": "A3_typing_direct_relation", "evidence": "M5 typing top-1 0.213 < majority 0.257; clusters built by transitive "
                                                              "closure of (L3) EQUIV can place a mutant 'in' the mode",
               "proposal": "type against the mode representative by the DIRECT relation, store the best map per level, and fall "
                           "back to the repair variant"},
              {"id": "A4_report_within_sentence", "evidence": "M4(b): within-sentence label shuffle keeps panel AUROC at 0.73 (true 0.77)",
               "proposal": "make within-sentence AUROC / partnered detection co-primary in the confirmation artifact"}]}
    jdump(am, RES / "proposed_amendments.json")
    # T6 integrity
    man = json.loads((ROOT / "vendor" / "manifest.json").read_text())
    now = {k: hashlib.sha1(Path(ROOT / k).read_bytes()).hexdigest() for k in man}
    fz = ROOT / "frozen_dc_config.json"
    fzh = hashlib.sha256(fz.read_bytes()).hexdigest()
    cfg = json.loads(fz.read_text())
    code_now = {k: hashlib.sha256((ROOT / k).read_bytes()).hexdigest() for k in cfg["code_sha256"]}
    led = rj(ROOT / "cost_ledger.jsonl")
    integ = {"vendor_unchanged": now == man, "frozen_config_sha256": fzh,
             "frozen_config_unchanged_since_prereg": fzh == pre.get("frozen_dc_config_sha256"),
             "frozen_engine_code_unchanged": code_now == cfg["code_sha256"],
             "changed_engine_files": [k for k in code_now if code_now[k] != cfg["code_sha256"][k]],
             "ledger_sum_usd": sum(x["cost_usd"] for x in led), "ledger_n_calls": len(led),
             "ledger_by_phase": {ph: sum(x["cost_usd"] for x in led if x["phase"] == ph) for ph in sorted({x["phase"] for x in led})}}
    jdump(integ, RES / "integrity.json")
    print(json.dumps(V and {k: x["verdict"] for k, x in V.items()}, indent=0))
    print(json.dumps(integ))


if __name__ == "__main__":
    main()
