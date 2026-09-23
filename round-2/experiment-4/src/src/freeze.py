"""FREEZE: frozen_config.json + prereg.json, hashed into freeze_receipt.json BEFORE any held-out label is read.

Plan freeze rule (section 4) needs C1/C2/C3 screen AUROC and paired G2 under the gemini judge. The OpenRouter key
was at its daily limit for the whole session (403 'Key limit exceeded (daily limit)'), so the rule could not be
evaluated; per fallback F4 the PRE-SELECTED default (C3, 3 order-permuted votes, canonical worlds) is frozen for
gemini with frozen_G2_pass = 'untested'. A separately labelled local-judge variant is frozen alongside it.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json

import common
from common import RESULTS


def file_sha1(p) -> str:
    return hashlib.sha1(open(p, "rb").read()).hexdigest()


def main() -> dict:
    import judge as J
    diag = json.loads((RESULTS / "canon_diagnostic.json").read_text())
    bc = json.loads((RESULTS / "bridge_coverage.json").read_text())
    src_hash = {p.name: file_sha1(p) for p in sorted((common.ROOT / "src").glob("*.py"))}
    frozen = {
        "frozen_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "TVJT_frozen(gemini)": {
            "config_id": "C3", "selection": "F4 default: freeze rule not evaluable (judge unavailable); C3 is the "
                                               "plan's PRE-SELECTED default", "frozen_G2_pass": "untested",
            "model": J.GEMINI, "temperature": 0.0, "reasoning": {"max_tokens": 0, "exclude": True},
            "prompt_version": J.PROMPT_VERSION, "prompt": J.TVJT_V2, "votes": 3,
            "vote_orders": ["canonical", "reversed", "rotated ceil(|U|/2)"],
            "score": "C3 = mean_w (p̄(w) if F(w) else 1-p̄(w)), p̄ = mean_k p_k(w), p_k = c/100 if v==1 else 1-c/100",
            "worlds": "canon_v1: canonical_worlds(F) — mutants of canon(F) with name-blind seed on a name-normalised "
                      "copy, prefer=0, n<=4, iso-dedup, cap 12, canonical key order; verbalisation = iter-1 "
                      "verbalize_world with predicates(F) ∪ predicates true in the world",
            "world_cache": "sha1(model|prompt_version|sentence|world_text|vote_idx)",
            "tau_frozen": 0.5, "tau_note": "Youden τ on screen needs judge scores; 0.5 pre-declared instead"},
        "TVJT_local(variant)": {
            "status": "DROPPED before any held-out label was read",
            "reason": "feasibility check on 8 panel items (39 worlds, labels not read): Qwen2.5-1.5B gave [0, 0.0] "
                      "for every world with the tvjt_v2_conf format and 0.538 world agreement with the iter-1 "
                      "TRUE/FALSE format; Qwen2.5-3B 0.436 — chance level, i.e. no usable judge signal, at "
                      "19-43 s/item on the contended 4-core CPU"},
        "B1": {"prompt": J.B1_PROMPT, "model": J.GEMINI, "max_tokens": 8, "fol_shown": "raw candidate string"},
        "canon_T1_gate": diag["T1_gate_pass(>=0.90 REORDER/DEMORGAN/CONTRAPOSITIVE)"],
        "canon_worldset_identity": {k: v.get("rate_canon") for k, v in diag["T1_worldset_identity"].items()},
        "src_sha1": src_hash,
    }
    prereg = {
        "labels": {"P": "heldout_confirm & label_source==panel3 (609); y = L3_majority, w = L3_sampling_weight",
                   "T": "heldout_confirm top tercile; y_hard = output∈{faithful,unfaithful}; y_soft = stratum p",
                   "Ccon": "contamination rows paired with originals"},
        "power_switch": {"n_panel_top_label_free": bc["n_panel_top_label_free"], "threshold": 150,
                         "decision": "H1 on P-top" if bc["n_panel_top_label_free"] >= 150 else "H1 on T (soft)"},
        "H1": "P-top: ΔAUROC_w(TVJT − B1) > 0 with paired sentence-cluster bootstrap (2000×, strata=corpus, seed 0) "
              "95% CI lower bound > 0",
        "H2": "Δ_top − Δ_bottom > 0 (paired bootstrap CI) and Δ per n_conditions bin {0-1,2-3,4+} non-decreasing",
        "H2b": "weighted GLM y ~ z(s) + c + z(s):c, cluster-robust by sentence; joint β(TVJT:c) − β(B1:c) > 0",
        "repeat_for": ["LC_onecoin", "A3", "B1x3", "TVJT_iter1", "TVJT_lite", "B3sc (2 systems)"],
        "error_types": "detection P(err < faithful same sentence), Wilson CIs; head-to-head scope∪cardinality vs A3",
        "stacking": "GroupKFold(5, sentence) weighted logistic C=1; S0=[B1,parse_ok], S1=S0+TVJT, S2=S1+LC+A3, "
                    "S0z=S0+LC+A3; placebo shuffled TVJT",
        "contamination": "AUROC orig vs paraphrase (paired over the 104 sentence pairs), mean shift per label class",
        "decision_table": {"CROSSOVER_CONFIRMED": "H1 LB>0 AND H2 LB>0", "CROSSOVER_PARTIAL": "H1 holds, H2 n.s.",
                           "NOT_REPLICATED": "H1 CI includes 0", "REVERSED": "H1 UB<0",
                           "REPAIR_OK": "frozen screen G2 passed and held-out G2 replication FA<=0.10",
                           "JUDGE_MATCHED": "TVJT − B1x3 top-tercile LB>0", "STACK_INCREMENT": "S2 − S0z LB>0",
                           "PENDING": "verdict for a judge whose scores do not exist yet (gemini key limit)"},
        "bins": {"tercile": ["bottom", "middle", "top"], "n_conditions": [[0, 1], [2, 3], [4, 99]]},
        "local_variant": "dropped (chance-level world agreement); no local-judge results are reported",
        "zero_llm_now": "H1/H2-style crossover tables (AUROC_w by tercile / n_conditions with paired bootstrap "
                        "growth CIs) are run NOW for the zero-LLM metrics LC_onecoin, A3, parse_ok (+B3sc on 2 "
                        "systems); TVJT*/B1/B1x3 rows are filled by the same code when gemini scores exist",
    }
    (RESULTS / "frozen_config.json").write_text(json.dumps(frozen, indent=1, ensure_ascii=False))
    (RESULTS / "prereg.json").write_text(json.dumps(prereg, indent=1, ensure_ascii=False))
    receipt = {"utc": dt.datetime.now(dt.timezone.utc).isoformat(),
               "frozen_config_sha1": file_sha1(RESULTS / "frozen_config.json"),
               "prereg_sha1": file_sha1(RESULTS / "prereg.json")}
    (RESULTS / "freeze_receipt.json").write_text(json.dumps(receipt, indent=1))
    return receipt


if __name__ == "__main__":
    print(main())
