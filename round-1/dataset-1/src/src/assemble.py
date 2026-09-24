#!/usr/bin/env python3
"""STEP 9 + 12: final labels, data_out assembly (exp_sel_data_out) and label_report.json.

Final label precedence (output field):
  (1) L3 panel majority if adjudicated                          -> label_source=panel3
  (2) ProverQA with synthetic gold: L1_orig                      -> equiv_synthetic_gold
  (3) otherwise L1_audited vs audited gold                       -> equiv_audited_gold
      equiv_proved / equiv_bounded -> faithful; non_equiv / non_equiv_no_bijection -> unfaithful
  (4) else unknown (kept, counted; e.g. unparseable candidate, timeouts, no audited gold)
"""
from __future__ import annotations

import json
import math
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from fol_equiv import bounded_check  # noqa: E402
from fol_parse import parse, signature  # noqa: E402
from generate import PROMPT_SHA1, SYSTEMS  # noqa: E402
from label_l1 import audited_gold_map, load_cache as load_l1, load_generations, pair_key  # noqa: E402
from prep_sources import norm  # noqa: E402

logger.remove()
logger.add(sys.stdout, level="INFO", format="{time:HH:mm:ss}|{level:<7}|{message}")
logger.add(ROOT / "logs" / "assemble.log", rotation="30 MB", level="DEBUG")

W = ROOT / "work"
EQ = ("equiv_proved", "equiv_bounded")
NEQ = ("non_equiv", "non_equiv_no_bijection")


def lab_from_l1(st: str | None) -> str:
    if st in EQ:
        return "faithful"
    if st in NEQ:
        return "unfaithful"
    return "unknown"


def wilson(k: int, n: int, z: float = 1.96) -> dict:
    if n == 0:
        return {"k": 0, "n": 0, "p": None, "lo": None, "hi": None}
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return {"k": k, "n": n, "p": round(p, 4), "lo": round(c - h, 4), "hi": round(c + h, 4)}


def cohen_kappa(a: list, b: list) -> dict:
    n = len(a)
    if n == 0:
        return {"n": 0, "kappa": None}
    po = sum(x == y for x, y in zip(a, b)) / n
    cats = set(a) | set(b)
    pe = sum((a.count(c) / n) * (b.count(c) / n) for c in cats)
    return {"n": n, "agreement": round(po, 4), "kappa": round((po - pe) / (1 - pe), 4) if pe < 1 else None}


def fleiss_kappa(rows: list[list]) -> dict:
    """rows: list of rating lists (same number of raters, categorical)."""
    rows = [r for r in rows if len(r) >= 2 and all(x is not None for x in r)]
    if not rows:
        return {"n_items": 0, "kappa": None}
    m = len(rows[0])
    rows = [r for r in rows if len(r) == m]
    cats = sorted({x for r in rows for x in r}, key=str)
    N = len(rows)
    P_i = []
    pj = Counter()
    for r in rows:
        c = Counter(r)
        pj.update(c)
        P_i.append((sum(v * v for v in c.values()) - m) / (m * (m - 1)))
    Pbar = sum(P_i) / N
    pe = sum((pj[c] / (N * m)) ** 2 for c in cats)
    return {"n_items": N, "n_raters": m, "kappa": round((Pbar - pe) / (1 - pe), 4) if pe < 1 else None,
            "observed_agreement": round(Pbar, 4)}


def weighted_prop(items: list[dict], pred, weight_key="w", strata_key="stratum", B: int = 2000, seed: int = 0) -> dict:
    """Weighted (ratio) proportion with a stratified bootstrap 95% CI."""
    items = [x for x in items if pred(x) is not None]
    if not items:
        return {"n": 0, "p": None}
    num = sum(x[weight_key] * pred(x) for x in items)
    den = sum(x[weight_key] for x in items)
    p = num / den
    by = defaultdict(list)
    for x in items:
        by[x[strata_key]].append(x)
    rng = random.Random(seed)
    boots = []
    for _ in range(B):
        nn = dd = 0.0
        for v in by.values():
            for _ in range(len(v)):
                x = v[rng.randrange(len(v))]
                nn += x[weight_key] * pred(x)
                dd += x[weight_key]
        boots.append(nn / dd if dd else 0)
    boots.sort()
    return {"n": len(items), "weighted_p": round(p, 4), "boot_lo": round(boots[int(0.025 * B)], 4),
            "boot_hi": round(boots[int(0.975 * B) - 1], 4), "unweighted_k": sum(pred(x) for x in items)}


def identity_nonequiv(a: str, b: str) -> bool | None:
    pa, pb = parse(a), parse(b)
    if not (pa.ok and pb.ok):
        return None
    _, c1 = signature(pa.ast)
    _, c2 = signature(pb.ast)
    r, _ = bounded_check(pa.ast, pb.ast, sorted(c1 | c2), {}, "equiv")
    return {"countermodel": True, "none": False}.get(r)


def l3_stratum(corpus: str, tier: str, tercile: str, l1: str, l2: str | None) -> str:
    if l1 in EQ:
        return f"equiv|{corpus}"
    if l2 == "equiv_granular":
        return "nonequiv|l2_granular"
    return f"nonequiv|{corpus}|{tier}|{tercile}"


def poststratified_weights(gens, held, gmap, l1, l3r) -> tuple[dict, dict]:
    """Post-stratified L3 weights on the CURRENT frame (L1 statuses after the parser fix):
    w = N_h / n_h with n_h = adjudicated items (with a majority) falling in stratum h."""
    N = Counter()
    cur = {}
    for r in gens:
        if r["sample_idx"] != 0 or not r["parse_ok"]:
            continue
        s = held[r["sentence_id"]]
        gold, _ = gmap[f"heldout:{s['sentence_id']}"]
        if not gold:
            continue
        res = l1.get(pair_key(r["candidate_fol"], gold))
        if res is None or res["status"] in ("gold_unparseable", "unparseable"):
            continue
        h = l3_stratum(s["corpus"], r["tier"], s["complexity_tercile"], res["status"], res.get("L2_status"))
        N[h] += 1
        cur[f"{s['sentence_id']}:{r['system']}:0"] = (h, res["status"], res.get("L2_status"))
    n = Counter()
    for iid, x in l3r.items():
        if x.get("L3_majority") is not None and iid in cur:
            n[cur[iid][0]] += 1
    w = {iid: (cur[iid][0], N[cur[iid][0]] / n[cur[iid][0]], cur[iid][1], cur[iid][2]) for iid in l3r if iid in cur and n[cur[iid][0]]}
    info = {"frame_N": dict(N), "adjudicated_n": dict(n),
            "strata_without_adjudicated_items": {h: N[h] for h in N if n[h] == 0},
            "frame_items_in_uncovered_strata": sum(N[h] for h in N if n[h] == 0)}
    return w, info


@logger.catch(reraise=True)
def main() -> None:
    held = {s["sentence_id"]: s for s in json.loads((W / "heldout_sentences.json").read_text())}
    screen = json.loads((W / "screen_sentences.json").read_text())
    prep = json.loads((W / "prep_report.json").read_text())
    audit = json.loads((W / "audit_results.json").read_text())
    aud = audit["results"]
    l3 = json.loads((W / "l3_results.json").read_text())
    l3r = l3["results"]
    e1 = json.loads((W / "e1_results.json").read_text()) if (W / "e1_results.json").exists() else {}
    e2 = json.loads((W / "e2_rows.json").read_text())
    cal = json.loads((W / "calibration_results.json").read_text())
    calv = json.loads((W / "calibration_variants.json").read_text()) if (W / "calibration_variants.json").exists() else {}
    panel_cfg = json.loads((W / "panel_config.json").read_text())
    gmap = audited_gold_map()
    l1 = load_l1()
    gens = load_generations()
    zpar = prep["complexity"]
    PSW, ps_info = poststratified_weights(gens, held, gmap, l1, l3r)
    # per post-stratum panel-faithful share (equal weights within a stratum) -> label-noise prior for
    # non-adjudicated items whose label comes from L1 alone
    _num, _den = Counter(), Counter()
    for iid, (h, _w, _s, _l2) in PSW.items():
        if l3r[iid].get("L3_majority") is not None:
            _den[h] += 1
            _num[h] += int(l3r[iid]["L3_majority"])
    P_STRATUM = {h: round(_num[h] / _den[h], 4) for h in _den}

    def l0_fields(key: str) -> dict:
        a = aud.get(key)
        if not a:
            return {"metadata_gold_audit_votes": None, "metadata_gold_faithful_final": None,
                    "metadata_sentence_ambiguous": None, "metadata_gold_audit_primary_error": None,
                    "metadata_gold_audit_cascade_rule": None, "metadata_gold_audit_full_panel_subset": None,
                    "metadata_gold_correction_status": None}
        votes = {m: ({k: v[k] for k in ("faithful", "sentence_ambiguous", "error_types", "primary_error", "explanation", "model")} if v else None)
                 for m, v in a["votes"].items()}
        return {"metadata_gold_audit_votes": votes, "metadata_gold_faithful_final": a["gold_faithful_final"],
                "metadata_sentence_ambiguous": a["sentence_ambiguous"], "metadata_gold_audit_primary_error": a.get("primary_error"),
                "metadata_gold_audit_cascade_rule": a["cascade_rule"], "metadata_gold_audit_full_panel_subset": a["full_panel_subset"],
                "metadata_gold_correction_status": a.get("correction_status")}

    def l1_fields(prefix: str, res: dict | None) -> dict:
        res = res or {}
        d = {f"metadata_{prefix}_status": res.get("status")}
        if True:
            d.update({f"metadata_{prefix}_mapping": res.get("mapping"),
                      f"metadata_{prefix}_entail_cand_to_gold": res.get("entail_cand_to_gold"),
                      f"metadata_{prefix}_entail_gold_to_cand": res.get("entail_gold_to_cand"),
                      f"metadata_{prefix}_method": res.get("method"), f"metadata_{prefix}_max_domain": res.get("max_domain"),
                      f"metadata_{prefix}_seconds": res.get("seconds")})
        return d

    groups = {"heldout_confirm": [], "heldout_samples": [], "screen_gold_audit": [], "contamination": [], "transfer_unlabeled": []}
    greedy_index = {}
    for r in sorted(gens, key=lambda r: (r["sentence_id"], r["system"], r["sample_idx"])):
        s = held.get(r["sentence_id"])
        if s is None:
            continue
        key = f"heldout:{s['sentence_id']}"
        gold_a, gsrc = gmap[key]
        cand = r["candidate_fol"] or ""
        res_o = l1.get(pair_key(cand, s["gold_fol_original"])) if r["parse_ok"] else None
        res_a = l1.get(pair_key(cand, gold_a)) if (r["parse_ok"] and gold_a) else None
        st_o = res_o["status"] if res_o else ("unparseable" if not r["parse_ok"] else None)
        st_a = res_a["status"] if res_a else ("unparseable" if not r["parse_ok"] else ("no_audited_gold" if not gold_a else None))
        item_id = f"{s['sentence_id']}:{r['system']}:{r['sample_idx']}"
        l3x = l3r.get(item_id) if r["sample_idx"] == 0 else None
        if l3x is not None and l3x.get("L3_majority") is not None:
            final, src = ("faithful" if l3x["L3_majority"] else "unfaithful"), "panel3"
        elif s["corpus"] == "proverqa" and gsrc in ("synthetic_clean", "original"):
            final, src = lab_from_l1(st_o), "equiv_synthetic_gold"
        else:
            final, src = lab_from_l1(st_a), "equiv_audited_gold"
        if final == "unknown":
            src = "unknown"
        row = {
            "input": json.dumps({"sentence": s["sentence"], "candidate_fol": cand}, ensure_ascii=False),
            "output": final,
            "metadata_fold": "heldout_confirm" if r["sample_idx"] == 0 else "heldout_samples",
            "metadata_item_id": item_id, "metadata_sentence_id": s["sentence_id"], "metadata_corpus": s["corpus"],
            "metadata_corpus_subset": s["corpus_subset"], "metadata_source_id": s["source_id"],
            "metadata_story_id": s.get("story_id"), "metadata_licence": s["licence"],
            "metadata_system": r["system"], "metadata_model": r["model"], "metadata_system_tier": r["tier"],
            "metadata_provider": r["provider"], "metadata_sample_idx": r["sample_idx"], "metadata_temperature": r["temperature"],
            "metadata_raw_output": r["raw_output"], "metadata_parse_ok": r["parse_ok"], "metadata_parse_error": r["parse_error"] or "",
            "metadata_parse_notes": r.get("parse_notes", []), "metadata_finish_reason": r.get("finish_reason"),
            "metadata_prompt_sha1": PROMPT_SHA1, "metadata_extractor_version": r.get("extractor_version", 1),
            "metadata_gold_fol_original": s["gold_fol_original"], "metadata_gold_fol_audited": gold_a,
            "metadata_gold_source": gsrc, "metadata_gold_parse_ok": True,
            "metadata_gold_fol_paper": s.get("gold_fol_paper"), "metadata_paper_corrected_flag": s.get("paper_corrected_flag"),
            "metadata_gold_fol_refined": s.get("gold_fol_refined"),
            **l0_fields(key),
            **l1_fields("L1_orig", res_o), **l1_fields("L1_audited", res_a),
            "metadata_L1_orig_status": st_o, "metadata_L1_audited_status": st_a,
            "metadata_L2_status": (res_a or {}).get("L2_status") if st_a not in EQ else "not_run_equivalent",
            "metadata_L2_definitions": (res_a or {}).get("L2_definitions"), "metadata_L2_lexical": True,
            "metadata_L2_orig_status": (res_o or {}).get("L2_status") if st_o not in EQ else "not_run_equivalent",
            "metadata_L3_selected": l3x is not None,
            "metadata_L3_sampling_weight": (PSW.get(item_id, (None, None))[1] if l3x else None),
            "metadata_L3_design_weight": (l3x or {}).get("weight"), "metadata_L3_design_stratum": (l3x or {}).get("stratum"),
            "metadata_L3_poststratum": (PSW.get(item_id, (None,))[0] if l3x else None), "metadata_L3_votes": (l3x or {}).get("L3_votes"),
            "metadata_L3_majority": (l3x or {}).get("L3_majority"), "metadata_L3_primary_error": (l3x or {}).get("L3_primary_error"),
            "metadata_L3_dissent": (l3x or {}).get("L3_dissent"), "metadata_L3_gold_shown_as": (("A" if l3x["gold_is_A"] else "B") if l3x else None),
            "metadata_label_source": src,
            "metadata_L3_stratum_p_faithful": P_STRATUM.get(l3_stratum(s["corpus"], r["tier"], s["complexity_tercile"], st_a,
                                                                      (res_a or {}).get("L2_status"))) if (res_a and st_a not in ("unparseable", "gold_unparseable")) else None,
            "metadata_n_tokens": s["n_tokens"], "metadata_n_quantifiers": s["n_quantifiers"], "metadata_nesting_depth": s["nesting_depth"],
            "metadata_n_conditions": s["n_conditions"], "metadata_complexity_composite": round(s["complexity_composite"], 4),
            "metadata_complexity_tercile": s["complexity_tercile"], "metadata_complexity_gold_used": s.get("complexity_gold_used"),
            "metadata_gen_usd": r["gen_usd"], "metadata_gen_seconds": r["gen_seconds"],
        }
        groups[row["metadata_fold"]].append(row)
        if r["sample_idx"] == 0:
            greedy_index[(s["sentence_id"], r["system"])] = row

    # ---- screen gold audit (L4)
    for s in screen:
        key = f"screen:{s['sentence_id']}"
        gold_a, gsrc = gmap[key]
        for sysname, c in sorted(s["candidates"].items()):
            cand = c["candidate_fol"]
            pc = parse(cand)
            res_o = l1.get(pair_key(cand, s["gold_fol_original"]))
            res_a = l1.get(pair_key(cand, gold_a)) if gold_a else None
            st_o = res_o["status"] if res_o else None
            st_a = res_a["status"] if res_a else ("no_audited_gold" if not gold_a else None)
            final = lab_from_l1(st_a)
            groups["screen_gold_audit"].append({
                "input": json.dumps({"sentence": s["sentence"], "candidate_fol": cand}, ensure_ascii=False),
                "output": final, "metadata_fold": "screen_gold_audit",
                "metadata_item_id": f"{s['sentence_id']}:{sysname}", "metadata_sentence_id": s["sentence_id"],
                "metadata_screen_rank": s["screen_rank"], "metadata_in_screen_first300": s["in_screen_first300"],
                "metadata_corpus": "folio", "metadata_corpus_subset": s["corpus_subset"], "metadata_source_id": s["source_id"],
                "metadata_logiclm_id": c.get("logiclm_id"), "metadata_licence": "MIT (FOLIO); Logic-LM outputs MIT",
                "metadata_system": sysname, "metadata_sample_idx": 0, "metadata_raw_output": c["raw_output"],
                "metadata_parse_ok": pc.ok, "metadata_parse_error": pc.error,
                "metadata_gold_fol_original": s["gold_fol_original"], "metadata_gold_fol_audited": gold_a, "metadata_gold_source": gsrc,
                "metadata_gold_fol_v2": s.get("gold_fol_v2"), "metadata_gold_fol_refined": s.get("gold_fol_refined"),
                "metadata_gold_fol_paper": s.get("gold_fol_paper"), "metadata_paper_corrected_flag": s.get("paper_corrected_flag"),
                **l0_fields(key), **l1_fields("L1_orig", res_o), **l1_fields("L1_audited", res_a),
                "metadata_L1_orig_status": st_o, "metadata_L1_audited_status": st_a,
                "metadata_L2_status": (res_a or {}).get("L2_status") if st_a not in EQ else "not_run_equivalent",
                "metadata_L2_definitions": (res_a or {}).get("L2_definitions"), "metadata_L2_lexical": True,
                "metadata_label_source": "equiv_audited_gold" if final != "unknown" else "unknown",
                "metadata_label_orig": lab_from_l1(st_o),
            })

    # ---- E1 contamination
    for sid, e in sorted(e1.items()):
        if not e.get("kept"):
            continue
        s = held[sid]
        for c in e.get("candidates", []):
            base = greedy_index.get((sid, c["system"]))
            groups["contamination"].append({
                "input": json.dumps({"sentence": e["paraphrase"], "candidate_fol": c["candidate_fol_renamed"]}, ensure_ascii=False),
                "output": base["output"] if base else "unknown", "metadata_fold": "contamination",
                "metadata_item_id": f"{sid}:{c['system']}:0:renamed", "metadata_sentence_id": sid,
                "metadata_original_item_id": f"{sid}:{c['system']}:0", "metadata_original_sentence": e["orig_sentence"],
                "metadata_rename_map": e["rename_map"], "metadata_corpus": s["corpus"], "metadata_system": c["system"],
                "metadata_candidate_fol_original": c["candidate_fol_original"], "metadata_parse_ok": c["parse_ok"],
                "metadata_contamination_rename_incomplete": c["rename_incomplete"],
                "metadata_gold_fol_audited": e["gold_fol_audited"], "metadata_gold_fol_renamed": e["gold_fol_renamed"],
                "metadata_gold_source": e["gold_source"], "metadata_gold_rename_hits": e.get("gold_rename_hits"),
                "metadata_verify_same_meaning": e.get("verify_same_meaning"), "metadata_verify_formula_faithful": e.get("verify_formula_faithful"),
                "metadata_verify_note": e.get("verify_note"),
                "metadata_label_source": ("transfer:" + base["metadata_label_source"]) if base else "unknown",
                "metadata_complexity_tercile": s["complexity_tercile"],
            })

    # ---- E2 transfer
    for r in e2:
        groups["transfer_unlabeled"].append({
            "input": json.dumps({"sentence": r["sentence"], "candidate_fol": r["candidate_fol"]}, ensure_ascii=False),
            "output": "unlabeled", "metadata_fold": "transfer_unlabeled",
            "metadata_item_id": f"{r['definition_id']}:{r['condition']}:{r['run']}",
            **{f"metadata_{k}": v for k, v in r.items() if k not in ("sentence", "candidate_fol")},
            "metadata_corpus": "eu_ai_act_art3_pilot", "metadata_label_source": "none",
        })

    data = {"metadata": {
        "description": "Held-out NL->FOL faithfulness meta-evaluation dataset (run_qY2a2IS-WLIs iter 1): real candidates from 9 "
                       "current systems on MALLS-test / FOLIO-v2-train / ProverQA-dev sentences, audited gold, layered labels "
                       "(L0 gold audit, L1 lexical-free solver equivalence, L2 granular, L3 blinded 3-model adjudication), plus "
                       "screen gold audit (L4), contamination paraphrases (E1) and the user's EU-AI-Act pilot (E2).",
        "generation_prompt_sha1": PROMPT_SHA1, "systems": {k: v[0] for k, v in SYSTEMS.items()},
        "panel": {m: c["model"] for m, c in panel_cfg["members"].items()},
        "complexity_params": zpar, "label_precedence": ["panel3", "equiv_synthetic_gold", "equiv_audited_gold", "unknown"],
    }, "datasets": [{"dataset": k, "examples": v} for k, v in groups.items() if v]}
    out_path = W / "assembled_data_out.json.gz"  # consumed by data.py (source verification) -> full_data_out.json
    import gzip
    with gzip.open(out_path, "wt", encoding="utf-8") as fh:
        fh.write(json.dumps(data, ensure_ascii=False))
    logger.info(f"wrote {out_path} groups={ {k: len(v) for k, v in groups.items()} }")

    # =====================================================================  label report
    rep: dict = {"generated_by": "src/assemble.py"}
    G = groups["heldout_confirm"]
    S = groups["heldout_samples"]
    rep["counts"] = {k: len(v) for k, v in groups.items()}
    rep["prep_exclusions"] = prep["exclusions"]
    rep["prep_eligible_counts"] = prep["eligible_counts"]
    rep["sample_design"] = {"counts": prep["sample_counts"], "terciles": prep["sample_terciles"], "top_share": prep["sample_top_share"],
                            "folio_disjointness": prep["folio_disjointness"], "complexity": zpar}
    cnt = defaultdict(Counter)
    for x in G:
        cnt[f"{x['metadata_corpus']}|{x['metadata_system']}|{x['metadata_complexity_tercile']}"][x["output"]] += 1
    rep["final_label_counts_corpus_system_tercile"] = {k: dict(v) for k, v in sorted(cnt.items())}
    by = defaultdict(Counter)
    for x in G:
        by[x["metadata_corpus"]][x["output"]] += 1
        by["ALL"][x["output"]] += 1
        by["sys:" + x["metadata_system"]][x["output"]] += 1
        by["tercile:" + x["metadata_complexity_tercile"]][x["output"]] += 1
    rep["final_label_balance_greedy"] = {k: {**dict(v), "unfaithful_share_of_labelled": round(v["unfaithful"] / max(1, v["unfaithful"] + v["faithful"]), 4)}
                                         for k, v in by.items()}
    rep["label_source_counts_greedy"] = dict(Counter(x["metadata_label_source"] for x in G))
    rep["parse_rate_greedy"] = {sname: wilson(sum(x["metadata_parse_ok"] for x in G if x["metadata_system"] == sname),
                                             sum(1 for x in G if x["metadata_system"] == sname)) for sname in SYSTEMS}
    rep["parse_rate_samples"] = {sname: wilson(sum(x["metadata_parse_ok"] for x in S if x["metadata_system"] == sname),
                                              sum(1 for x in S if x["metadata_system"] == sname)) for sname in ("gpt-4.1-mini", "llama-3.1-8b")}
    rep["unparseable_counted_greedy"] = sum(not x["metadata_parse_ok"] for x in G)
    rep["L1_status_distribution"] = {
        "greedy_orig": dict(Counter(x["metadata_L1_orig_status"] for x in G)),
        "greedy_audited": dict(Counter(x["metadata_L1_audited_status"] for x in G)),
        "samples_audited": dict(Counter(x["metadata_L1_audited_status"] for x in S)),
        "screen_orig": dict(Counter(x["metadata_L1_orig_status"] for x in groups["screen_gold_audit"])),
        "screen_audited": dict(Counter(x["metadata_L1_audited_status"] for x in groups["screen_gold_audit"])),
    }
    rep["L2_status_distribution_greedy"] = dict(Counter(x["metadata_L2_status"] for x in G))
    # label bias: orig-gold labels vs audited-gold labels
    flips = Counter((lab_from_l1(x["metadata_L1_orig_status"]), lab_from_l1(x["metadata_L1_audited_status"]))
                    for x in G if x["metadata_corpus"] in ("malls", "folio"))
    rep["label_bias_orig_vs_audited_greedy_malls_folio"] = {f"{a}->{b}": v for (a, b), v in flips.items()}

    # ---- L0 wrong-gold rates
    l0 = {}
    for grp in ("malls", "folio", "proverqa_spot", "proverqa_escalated", "screen"):
        rs = [r for r in aud.values() if r["group"] == grp and r["gold_faithful_final"] is not None]
        l0[grp] = wilson(sum(r["gold_faithful_final"] is False for r in rs), len(rs))
        l0[grp]["ambiguous_share"] = round(sum(bool(r["sentence_ambiguous"]) for r in rs) / max(1, len(rs)), 4)
        l0[grp]["correction_valid"] = sum(bool(r.get("correction")) for r in rs if r["gold_faithful_final"] is False)
        l0[grp]["primary_error_counts"] = dict(Counter(r.get("primary_error") for r in rs if r["gold_faithful_final"] is False))
    pq_all = [r for r in aud.values() if r["group"].startswith("proverqa") and r["gold_faithful_final"] is not None]
    l0["proverqa_all_audited"] = wilson(sum(r["gold_faithful_final"] is False for r in pq_all), len(pq_all))
    rep["L0_wrong_gold_rate"] = l0
    rep["L0_meta"] = audit["meta"]
    # panel vs human (2606.02837) on MALLS first-100 (panel judged the ORIGINAL gold; paper corrected flag)
    ph_a, ph_b, conf = [], [], Counter()
    for s in held.values():
        if s.get("gold_fol_paper") is None:
            continue
        a = aud.get(f"heldout:{s['sentence_id']}")
        if not a or a["gold_faithful_final"] is None:
            continue
        human_wrong = bool(s.get("paper_corrected_flag"))
        panel_wrong = a["gold_faithful_final"] is False
        ph_a.append(human_wrong)
        ph_b.append(panel_wrong)
        conf[f"human_{'wrong' if human_wrong else 'ok'}|panel_{'wrong' if panel_wrong else 'ok'}"] += 1
    rep["L0_panel_vs_human_MALLS_paper_subset"] = {**cohen_kappa(ph_a, ph_b), "confusion": dict(conf),
                                                    "human_wrong_rate": wilson(sum(ph_a), len(ph_a)),
                                                    "panel_wrong_rate": wilson(sum(ph_b), len(ph_b))}
    # panel vs human on screen conclusions where the v1 gold equals the v2 gold the paper judged
    sa, sb, sconf = [], [], Counter()
    for s in screen:
        if s.get("gold_fol_paper_old_v2") is None:
            continue
        if norm(s["gold_fol_paper_old_v2"]).replace(" ", "") != norm(s["gold_fol_original"]).replace(" ", ""):
            continue
        a = aud.get(f"screen:{s['sentence_id']}")
        if not a or a["gold_faithful_final"] is None:
            continue
        sa.append(bool(s["paper_corrected_flag"]))
        sb.append(a["gold_faithful_final"] is False)
        sconf[f"human_{'wrong' if sa[-1] else 'ok'}|panel_{'wrong' if sb[-1] else 'ok'}"] += 1
    rep["L4_panel_vs_human_screen_conclusions_same_formula"] = {**cohen_kappa(sa, sb), "confusion": dict(sconf)}
    # folio-refined diff vs panel (independent non-panel wrong-gold signal)
    ra, rb = [], []
    rs_rows = []
    for key, s in [(f"heldout:{s['sentence_id']}", s) for s in held.values() if s["corpus"] == "folio"] + \
                  [(f"screen:{s['sentence_id']}", s) for s in screen]:
        ref = s.get("gold_fol_refined")
        a = aud.get(key)
        if not ref or not a or a["gold_faithful_final"] is None:
            continue
        d = identity_nonequiv(ref, s["gold_fol_original"])
        if d is None:
            continue
        ra.append(d)
        rb.append(a["gold_faithful_final"] is False)
        rs_rows.append(key)
    rep["L0_panel_vs_folio_refined_diff"] = {**cohen_kappa(ra, rb), "refined_differs_rate": wilson(sum(ra), len(ra)),
                                            "panel_wrong_rate_same_items": wilson(sum(rb), len(rb)),
                                            "note": "refined_differs = bounded countermodel between yfxiao/folio-refined FOL and original FOL (identity naming)"}
    # Fleiss kappa L0 on full-panel subset
    fp = [r for r in aud.values() if r["full_panel_subset"] and all(r["votes"].get(m) for m in ("M1", "M2", "M3"))]
    rep["L0_fleiss_kappa_full_panel_subset"] = fleiss_kappa([[r["votes"][m]["faithful"] for m in ("M1", "M2", "M3")] for r in fp])
    pair_agree = {}
    for m1, m2 in (("M1", "M2"), ("M1", "M3"), ("M2", "M3")):
        rr = [r for r in aud.values() if r["votes"].get(m1) and r["votes"].get(m2)]
        pair_agree[f"{m1}-{m2}"] = cohen_kappa([r["votes"][m1]["faithful"] for r in rr], [r["votes"][m2]["faithful"] for r in rr])
    rep["L0_pairwise_member_agreement"] = pair_agree

    # ---- L3
    L3 = []
    for iid, x in l3r.items():
        if x.get("L3_majority") is None or iid not in PSW:
            continue
        h, wt, l1cur, l2cur = PSW[iid]
        L3.append({**x, "w": wt, "stratum": h, "l1": l1cur, "l2": l2cur, "l1_design": x["l1"], "l1_orig": None})
    for x in L3:
        row = greedy_index.get((x["sentence_id"], x["system"]))
        x["l1_orig"] = row["metadata_L1_orig_status"] if row else None
    non = [x for x in L3 if x["l1"] not in EQ]
    eqs = [x for x in L3 if x["l1"] in EQ]
    rep["L3_frame_design"] = l3["frame_counts"]
    rep["L3_poststratification"] = ps_info
    rep["L3_stratum_p_faithful"] = P_STRATUM
    rep["L3_extra_top"] = l3.get("extra_top")
    rep["L3_design_vs_current_L1_status_changes"] = sum(1 for x in L3 if x["l1"] != x["l1_design"])
    rep["L3_n_adjudicated"] = {"total": len(l3r), "with_majority": len(L3), "nonequiv": len(non), "equiv": len(eqs)}
    rep["L3_correct_but_gold_inequivalent_rate"] = {
        "among_L1_audited_nonequiv": weighted_prop(non, lambda x: int(x["L3_majority"] is True)),
        "among_L1_audited_nonequiv_no_bijection": weighted_prop([x for x in non if x["l1"] == "non_equiv_no_bijection"], lambda x: int(x["L3_majority"] is True)),
        "among_L1_audited_nonequiv_with_bijection": weighted_prop([x for x in non if x["l1"] == "non_equiv"], lambda x: int(x["L3_majority"] is True)),
        "among_L1_orig_nonequiv": weighted_prop([x for x in L3 if x["l1_orig"] in NEQ], lambda x: int(x["L3_majority"] is True)),
        "among_L2_equiv_granular": weighted_prop([x for x in non if x.get("l2") == "equiv_granular"], lambda x: int(x["L3_majority"] is True)),
        "by_corpus": {c: weighted_prop([x for x in non if x["corpus"] == c], lambda x: int(x["L3_majority"] is True)) for c in ("malls", "folio", "proverqa")},
        "by_tercile": {t: weighted_prop([x for x in non if x["tercile"] == t], lambda x: int(x["L3_majority"] is True)) for t in ("bottom", "middle", "top")},
    }
    rep["L3_equivalent_items_panel_unfaithful_rate"] = weighted_prop(eqs, lambda x: int(x["L3_majority"] is False))
    rep["L3_gold_judged_unfaithful_by_panel_majority"] = weighted_prop(
        L3, lambda x: (lambda v: None if not v else int(sum(v) < len(v) / 2))([vv["gold_faithful"] for vv in x["L3_votes"].values() if vv and vv["gold_faithful"] is not None]))
    # solver vs panel same_meaning
    sm = []
    for x in L3:
        v = [vv["same_meaning"] for vv in x["L3_votes"].values() if vv and vv["same_meaning"] is not None]
        if v:
            sm.append((x["l1"] in EQ, sum(v) > len(v) / 2))
    rep["L3_solver_vs_panel_same_meaning"] = {**cohen_kappa([a for a, _ in sm], [b for _, b in sm]),
                                              "confusion": dict(Counter(f"solver_{'eq' if a else 'neq'}|panel_{'same' if b else 'diff'}" for a, b in sm))}
    unf = [x for x in L3 if x["L3_majority"] is False]
    et = defaultdict(float)
    for x in unf:
        et[x["L3_primary_error"] or "other"] += x["w"]
    tot = sum(et.values()) or 1
    rep["L3_error_type_distribution_weighted"] = {k: round(v / tot, 4) for k, v in sorted(et.items(), key=lambda t: -t[1])}
    rep["L3_error_type_counts_unweighted"] = dict(Counter(x["L3_primary_error"] for x in unf))
    rep["L3_scope_plus_cardinality_share_weighted"] = round((et.get("quantifier_scope", 0) + et.get("cardinality_numeric", 0)) / tot, 4)
    allv = [x for x in l3r.values() if all(x["L3_votes"].get(m) and x["L3_votes"][m]["cand_faithful"] is not None for m in ("M1", "M2", "M3"))]
    rep["L3_fleiss_kappa_candidate"] = fleiss_kappa([[x["L3_votes"][m]["cand_faithful"] for m in ("M1", "M2", "M3")] for x in allv])
    rep["L3_fleiss_kappa_gold"] = fleiss_kappa([[x["L3_votes"][m]["gold_faithful"] for m in ("M1", "M2", "M3")] for x in allv
                                                if all(x["L3_votes"][m]["gold_faithful"] is not None for m in ("M1", "M2", "M3"))])
    rep["L3_dissent_pattern"] = dict(Counter(",".join(x["L3_dissent"]) or "unanimous" for x in l3r.values()))
    rep["L3_family_disjointness"] = ("Panel families (Anthropic, xAI, Zhipu) share no family with any generator (Meta, Qwen, Mistral, "
                                     "OpenAI, Google, DeepSeek, Microsoft) -> no leave-one-out correction needed.")
    # accuracy of L1-based labels against L3 (the residual label-noise rate of non-adjudicated items)
    rep["L1_label_vs_L3_weighted_agreement"] = weighted_prop(
        L3, lambda x: int((x["l1"] in EQ) == bool(x["L3_majority"])))

    # ---- calibration
    rep["panel_calibration"] = {m: [{k: o[k] for k in ("model", "audit_accuracy", "adj_accuracy", "same_meaning_accuracy", "n_audit")} for o in v]
                                for m, v in cal.items()}
    rep["panel_calibration_variants"] = {k: {kk: v[kk] for kk in ("model", "audit_accuracy", "adj_accuracy", "same_meaning_accuracy")}
                                         for k, v in calv.items()}
    rep["panel_config"] = panel_cfg
    rep["calibration_note"] = ("3 of the 15 'faithful-by-construction' ProverQA-easy golds drop a restrictor stated in the "
                               "sentence ('For all fish', 'For every human', 'For all humans'); all members flagged them. "
                               "Gate accuracies are computed against the ORIGINAL pre-registered labels.")
    # ---- E1
    if e1:
        kept = [e for e in e1.values() if e.get("kept")]
        rep["E1_contamination"] = {"selected": len(e1), "kept": len(kept), "by_corpus": dict(Counter(e["corpus"] for e in kept)),
                                   "drop_reasons": dict(Counter(e.get("drop_reason") for e in e1.values() if not e.get("kept"))),
                                   "rename_incomplete_candidates": sum(c["rename_incomplete"] for e in kept for c in e.get("candidates", []))}
    rep["E2_transfer"] = {"rows": len(e2), "parse_ok": sum(r["parse_ok"] for r in e2),
                          "definitions": len({r["definition_id"] for r in e2}),
                          "parse_errors": dict(Counter(r["parse_error"][:40] for r in e2 if not r["parse_ok"]))}
    # ---- cost
    led = [json.loads(l) for l in (ROOT / "cost_ledger.jsonl").read_text().splitlines() if l.strip()]
    ph = defaultdict(float)
    pm = defaultdict(float)
    for r in led:
        ph[r["phase"]] += r["cost_usd"]
        pm[r["model"]] += r["cost_usd"]
    rep["cost_usd_by_phase"] = {k: round(v, 4) for k, v in ph.items()}
    rep["cost_usd_by_model"] = {k: round(v, 4) for k, v in sorted(pm.items(), key=lambda t: -t[1])}
    rep["cost_usd_total"] = round(sum(ph.values()), 4)
    rep["n_api_calls"] = len(led)
    (ROOT / "label_report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=str))
    logger.info(f"label_report written; total ${rep['cost_usd_total']}")


if __name__ == "__main__":
    main()
