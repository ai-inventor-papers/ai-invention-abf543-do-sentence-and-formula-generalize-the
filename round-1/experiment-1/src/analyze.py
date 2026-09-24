#!/usr/bin/env python3
"""STEPS 7-9: meta-evaluation analysis, pre-registered selection rule, diagnosis, method_out.json, figures.

Primary label: blind bijection equivalence to the primary gold (curated 2606.02837 gold where its NL matches,
else FOLIO v0.0), 'unlabeled' excluded. Secondary labels: vs original v0.0 gold, and lexical-bijection labels.
All CIs: 1000x bootstrap resampling SENTENCES (sid) with replacement.
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger
from scipy.stats import kendalltau, spearmanr
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
logger.remove()
logger.add(sys.stdout, level="INFO", format="{time:HH:mm:ss}|{level:<7}|{message}")
logger.add(ROOT / "logs" / "analyze.log", rotation="30 MB", level="DEBUG")

RES = ROOT / "results"
NBOOT = 1000
CANDIDATES = ["A1", "A2", "A3"]
ALL_METRICS = ["A1", "A2", "A3", "B1", "B1plus", "B2", "B2sat", "B3cos", "B3nli", "B4", "B5", "B5A2", "B7", "B8", "A0", "Ccov"]
SIGNATURE_LIKE = {"A1", "A2", "A3", "B4", "B5", "B5A2", "A0", "Ccov"}
OP_TYPE = {"NEG": "negation_polarity", "QUANT": "quantifier", "IMPL_REV": "reversed_implication",
           "DROP": "dropped_condition", "ADD": "added_condition", "ARG_SWAP": "swapped_args",
           "MERGE": "conflation", "ANDOR": "connective_andor", "SCOPE": "scope", "CARD": "cardinality"}
PRED_TYPES = ["swapped_args", "conflation", "dropped_condition", "added_condition", "wrong_split",
              "reversed_implication", "quantifier", "negation_polarity", "connective_andor", "other", "none"]
SELECTION_RULE = ("Primary measure: AUROC_real, item-level AUROC of the metric score on the screen's real candidates "
                  "against equivalence-up-to-renaming labels, with a 1000x bootstrap clustered by sentence. A candidate "
                  "SURVIVES iff all four gates hold: (G1) Coverage: at least 70% of real candidates are scored. Unscored "
                  "items get 0.5 and stay in. (G2) False alarms: at most 10% on solver-verified meaning-preserving "
                  "rewrites. (G3) Increment: ΔAUROC of logistic(cheap_judge + parse_ok + metric) over "
                  "logistic(cheap_judge + parse_ok) has a clustered-bootstrap 95% lower bound above 0. (G4) AUROC_real "
                  "is at least 0.65. Ranking: survivors are ranked by AUROC_real in the TOP complexity tercile. A winner "
                  "is declared only if it leads the next survivor there by at least 0.03. Otherwise the top two advance "
                  "as a pre-specified combined score (logistic stack), provided their per-item score correlation is "
                  "below 0.5; if it is not, the top one advances alone. If no candidate survives, the one with the "
                  "largest ΔAUROC point estimate advances only if ΔAUROC ≥ 0.03. Otherwise the screen is reported as "
                  "null, and iter 2 tests the full stack of all four against baselines on held-out. In iter 2 the rule "
                  "is re-applied with the DATASET's audited screen labels; if the ranking changes, the audited ranking "
                  "governs.")


def jl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def auc(y, s):
    y = np.asarray(y)
    if len(set(y.tolist())) < 2:
        return float("nan")
    return float(roc_auc_score(y, s))


class Boot:
    """Pre-drawn sentence-clustered bootstrap resamples shared across metrics (paired comparisons)."""

    def __init__(self, sids: np.ndarray, n: int = NBOOT, seed: int = 0):
        rng = np.random.default_rng(seed)
        self.uniq = np.unique(sids)
        idx_by = defaultdict(list)
        for i, s in enumerate(sids):
            idx_by[s].append(i)
        self.idx_by = {k: np.array(v) for k, v in idx_by.items()}
        self.draws = [rng.choice(self.uniq, size=len(self.uniq), replace=True) for _ in range(n)]

    def indices(self, mask: np.ndarray | None = None):
        for d in self.draws:
            idx = np.concatenate([self.idx_by[s] for s in d])
            if mask is not None:
                idx = idx[mask[idx]]
            yield idx


def ci(vals):
    v = np.array([x for x in vals if not (x is None or (isinstance(x, float) and math.isnan(x)))])
    if len(v) == 0:
        return [None, None]
    return [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]


def boot_auc(boot: Boot, y, s, mask=None):
    y, s = np.asarray(y), np.asarray(s)
    return ci(auc(y[i], s[i]) for i in boot.indices(mask))


def wilson(k, n, z=1.96):
    if n == 0:
        return [None, None]
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [max(0.0, c - h), min(1.0, c + h)]


def oof_logit(X: np.ndarray, y: np.ndarray, sids: np.ndarray, n_rep: int = 5, k: int = 5) -> np.ndarray:
    preds = np.zeros(len(y))
    uniq = np.unique(sids)
    for r in range(n_rep):
        rng = np.random.default_rng(100 + r)
        perm = rng.permutation(uniq)
        fold_of = {s: i % k for i, s in enumerate(perm)}
        f = np.array([fold_of[s] for s in sids])
        p = np.zeros(len(y))
        for j in range(k):
            tr, te = f != j, f == j
            if len(set(y[tr].tolist())) < 2:
                p[te] = y[tr].mean()
                continue
            sc = StandardScaler().fit(X[tr])
            m = LogisticRegression(C=1.0, max_iter=2000).fit(sc.transform(X[tr]), y[tr])
            p[te] = m.predict_proba(sc.transform(X[te]))[:, 1]
        preds += p / n_rep
    return preds


def increment(df: pd.DataFrame, base_cols: list[str], metric: str, boot: Boot) -> dict:
    y = df["y"].values.astype(int)
    sids = df["sid"].values
    X0 = df[base_cols].values.astype(float)
    X1 = df[base_cols + [metric]].values.astype(float)
    p0, p1 = oof_logit(X0, y, sids), oof_logit(X1, y, sids)
    d = auc(y, p1) - auc(y, p0)
    bs = [auc(y[i], p1[i]) - auc(y[i], p0[i]) for i in boot.indices()]
    lo, hi = ci(bs)
    return {"base": base_cols, "auc_base_oof": auc(y, p0), "auc_with_metric_oof": auc(y, p1), "delta_auroc": d,
            "ci95": [lo, hi], "passes": bool(lo is not None and lo > 0)}


@logger.catch(reraise=True)
def main():
    d = json.loads((ROOT / "data" / "screen_set.json").read_text())
    sents = {s["sid"]: s for s in d["sentences"]}
    real = pd.DataFrame(d["real"])
    real["tercile"] = real["sid"].map(lambda s: sents[s]["tercile"])
    real["gold_source"] = real["sid"].map(lambda s: sents[s]["gold_source"])

    # ---------------- collect scores
    rows = jl(RES / "screen_scores_signature.jsonl")
    for name in ("b1", "b1_mutants", "b3", "b1plus", "b8"):
        rows += jl(RES / f"baseline_{name}.jsonl")
    sc = pd.DataFrame(rows)
    b7 = json.loads((RES / "b7_structural.json").read_text())["items"]
    # candidate satisfiability for B2sat
    from fol_parse import parse
    from labeler import satisfiable
    satc = {}
    for r in d["real"]:
        if r["parse_ok"]:
            try:
                satc[r["item_id"]] = satisfiable(parse(r["cand_fol"]).ast, N=3) == "sat"
            except Exception:  # noqa: BLE001
                satc[r["item_id"]] = False
        else:
            satc[r["item_id"]] = False
    extra = []
    for r in d["real"]:
        extra.append({"item_id": r["item_id"], "set": "real", "sid": r["sid"], "metric": "B2",
                      "score": float(r["parse_ok"]), "covered": True, "usd": 0.0})
        extra.append({"item_id": r["item_id"], "set": "real", "sid": r["sid"], "metric": "B2sat",
                      "score": float(r["parse_ok"] and satc[r["item_id"]]), "covered": True, "usd": 0.0})
        extra.append({"item_id": r["item_id"], "set": "real", "sid": r["sid"], "metric": "B7",
                      "score": float(b7[r["item_id"]]["b7"]), "covered": True, "usd": 0.0})
    sc = pd.concat([sc, pd.DataFrame(extra)], ignore_index=True)
    # write the unified per-item score file
    with (RES / "screen_scores.jsonl").open("w") as f:
        for r in sc.to_dict("records"):
            f.write(json.dumps({k: (None if (isinstance(v, float) and math.isnan(v)) else v) for k, v in r.items()},
                               ensure_ascii=False, default=str) + "\n")
    metrics_present = [m for m in ALL_METRICS if m in set(sc["metric"])]
    logger.info(f"metrics present: {metrics_present}")

    realsc = sc[sc["set"] == "real"].pivot_table(index="item_id", columns="metric", values="score", aggfunc="first")
    realcov = sc[sc["set"] == "real"].pivot_table(index="item_id", columns="metric", values="covered", aggfunc="first")
    df = real.set_index("item_id").join(realsc, how="left")
    L = df[df["correct"].notna()].copy()
    L["y"] = L["correct"].astype(int)
    L = L.reset_index()
    boot = Boot(L["sid"].values)
    out: dict = {"config": {
        "workspace": str(ROOT),
        "candidates": CANDIDATES,
        "text_probe_model": "google/gemini-2.5-flash", "text_probe_reasoning": {"max_tokens": 1024},
        "text_probe_config_choice": "thinking_1024 (pre-registered MED pilot rule); fallback-11 switch to gpt-4.1-mini "
                                    "NOT applied because gpt-4.1-mini piloted worse (down 0.32 vs 0.64) - see probe_config",
        "B1_model": "google/gemini-2.5-flash", "B1_reasoning": {"max_tokens": 0}, "B1_temperature": 0,
        "B1_prompt": "Sentence: {s}\\nFOL: {f}\\nGive the probability (0-100) that this FOL is a faithful formalization "
                     "of the sentence. Reply with a number only.",
        "B3_backtranslation_model": "google/gemini-2.5-flash (thinking off)",
        "B3_nli_model": "MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli (GPU)",
        "B3_cos_model": "sentence-transformers/all-MiniLM-L6-v2",
        "B4_model": "google/gemini-2.5-flash thinking 1024 (same as probe)",
        "B4_samples": "all parseable real (810) + gold (300) + 20 mutants/operator (180) + 120 rewrites "
                      "(budget rule 13: 40/op and 150 rewrites shrunk)",
        "B1plus": "SKIPPED: optional tier runs only if cumulative spend < $4.30; spend was $4.51 before it (budget rule 12/13)",
        "B8_self_consistency": "added (not in plan): agreement with the same system's re-translations of the same "
                               "sentence in other FOLIO stories (Logic-LM translated each story independently)",
        "A0_Ccov_controls": "added (not in plan): A0 = signature score with polarity/anchor coordinates disabled "
                            "(alignment-only); Ccov = concept coverage fraction",
        "A3_implementation": "A3-rules (compact rule-based monotonicity marker over spaCy en_core_web_sm); Udep2Mono was "
                             "not installed (fallback 10; time box)",
        "signature_domain_bound_N": 3, "labeler_domain_bound": "1..4 (single grounded query) + unbounded z3 check",
        "labeler_max_bijections": 5040, "solver_timeout_ms": 5000,
        "align_thresholds": {"lemma_overlap": 0.5, "minilm_cosine": 0.5},
        "coverage_rule": "covered = parse_ok and <=20% '?' coords and alignment coverage >= 0.5 and >=1 labelled concept",
        "post_T1_text_side_fixes": "optional domain nouns/light verbs (person, people, thing, have, take, ...), "
                                   "predicates may align to PROPN concepts and constants to NOUN concepts; tuned only on "
                                   "gold/mutant/rewrite behaviour (T1), never on real-candidate labels",
        "bootstrap": "1000x, resampling sentences (sid)", "G3": "OOF logistic, 5 sentence-grouped folds x 5 shuffles",
        "seeds": {"mutants": "sha1-derived per sentence", "bootstrap": 0, "b6_sample": 0},
        "budget_cap_usd": 5.80},
        "screen_set_counts": d["counts"]}

    # ---------------- label diagnostics
    lab = {}
    for sy in sorted(real["system"].unique()):
        rr = real[real["system"] == sy]
        lab[sy] = {"n": int(len(rr)), "equiv_rate_primary": float(rr["correct"].dropna().mean()),
                   "equiv_rate_orig_gold": float(rr["correct_orig"].dropna().mean()),
                   "equiv_rate_primary_lex": float(rr["correct_lex"].dropna().mean()),
                   "parse_rate": float(rr["parse_ok"].mean())}
    unl = int(real["correct"].isna().sum())
    eq_items = [r for r in d["real"] if (r.get("label_corr") or r.get("label_orig") or {}).get("status") == "equiv"]
    ub = Counter(((r.get("label_corr") or r["label_orig"]).get("unbounded_status")) for r in eq_items)
    both = real[real["label_corr"].notna()]
    agree_orig_corr = float((both["correct"] == both["correct_orig"]).mean()) if len(both) else None
    corr_but_not_orig = int(((both["correct_orig"] == 1) & (both["correct"] == 0)).sum())
    orig_but_not_corr = int(((both["correct_orig"] == 0) & (both["correct"] == 1)).sum())
    blind_lex_disagree = int((real["correct"].notna() & (real["correct"] != real["correct_lex"])).sum())
    reasons = Counter(((r.get("label_corr") or r["label_orig"]).get("reason") or "") for r in d["real"]
                      if (r.get("label_corr") or r["label_orig"])["status"] == "nonequiv")
    s_corr = [s for s in d["sentences"] if s.get("gold_fol_corr")]
    out["label_diagnostics"] = {
        "per_system": lab, "n_real": int(len(real)), "n_labeled": int(len(L)), "n_unlabeled": unl,
        "unlabeled_rate": unl / len(real), "positive_rate": float(L["y"].mean()),
        "unbounded_check_on_equiv_items": dict(ub),
        "bounded_vs_unbounded_agreement": ub.get("unsat", 0) / max(1, sum(ub.values())),
        "nonequiv_reason_counts": dict(reasons),
        "items_with_both_golds": int(len(both)), "orig_vs_corrected_label_agreement": agree_orig_corr,
        "equiv_to_orig_but_not_corrected": corr_but_not_orig, "equiv_to_corrected_but_not_orig": orig_but_not_corr,
        "blind_vs_lexical_label_disagreements": blind_lex_disagree,
        "gold_source_counts": Counter(s["gold_source"] for s in d["sentences"]),
        "gold_wrong_rate_estimate": {
            "n_sentences_with_curated_gold": len(s_corr),
            "n_curated_marked_corrected": sum(1 for s in s_corr if s.get("corr_flag")),
            "rate": sum(1 for s in s_corr if s.get("corr_flag")) / max(1, len(s_corr)),
            "n_ambiguous": sum(1 for s in s_corr if s.get("ambiguity"))},
        "correct_but_inequivalent_estimate": {
            "note": "Lower bound from label disagreement: an item equivalent to one gold but not the other is correct "
                    "under at least one reference yet inequivalent to the other; vocab_shape nonequiv (different "
                    "predicate arity multiset) dominates nonequiv reasons and is where granularity-correct candidates land.",
            "vocab_shape_share_of_nonequiv": reasons.get("vocab_shape", 0) / max(1, sum(reasons.values()))},
    }

    # ---------------- per-metric AUROC + CIs
    table = {}
    terc = L["tercile"].values
    tercile_counts = {t: {"n": int((terc == t).sum()), "pos": int(L.loc[terc == t, "y"].sum()),
                          "neg": int(((terc == t) & (L["y"] == 0)).sum())} for t in ("low", "mid", "top")}
    under = {t: (v["pos"] < 30 or v["neg"] < 30) for t, v in tercile_counts.items()}
    alt_labels = {"orig_gold": "correct_orig", "lexical_bijection": "correct_lex", "orig_gold_lexical": "correct_orig_lex"}
    for m in metrics_present:
        if m not in L.columns:
            continue
        s = L[m].fillna(0.5).values
        y = L["y"].values
        ent = {"AUROC_real": auc(y, s), "CI95": boot_auc(boot, y, s), "n": int(len(L))}
        # uncovered-because-unparseable -> 0 instead of 0.5
        s0 = s.copy()
        s0[~L["parse_ok"].values.astype(bool)] = 0.0
        ent["AUROC_unparseable_as_0"] = auc(y, s0)
        for nm, col in alt_labels.items():
            mk = L[col].notna().values
            ent[f"AUROC_{nm}"] = auc(L.loc[mk, col].astype(int).values, s[mk])
        mk = (L["gold_source"] == "corrected").values
        ent["AUROC_corrected_gold_subset"] = auc(y[mk], s[mk])
        ent["n_corrected_gold_subset"] = int(mk.sum())
        if L["y"].mean() > 0.85 or L["y"].mean() < 0.15:
            ent["PR_AUC"] = float(average_precision_score(y, s))
        ent["per_tercile"] = {}
        for t in ("low", "mid", "top"):
            mk = terc == t
            ent["per_tercile"][t] = {"AUROC": auc(y[mk], s[mk]), "CI95": boot_auc(boot, y, s, mk),
                                     "underpowered": under[t]}
        # G1 coverage over ALL real candidates
        if m in realcov.columns:
            cv = realcov[m].reindex(df.index)
            ent["G1_coverage"] = float(cv.fillna(False).astype(bool).mean())
        else:
            ent["G1_coverage"] = 1.0
        ent["G4_auroc_ge_0.65"] = bool(ent["AUROC_real"] >= 0.65)
        table[m] = ent

    # Δ vs B1 per tercile (paired) + crossover trend
    if "B1" in L.columns:
        b1 = L["B1"].fillna(0.5).values
        y = L["y"].values
        for m in table:
            if m == "B1":
                continue
            s = L[m].fillna(0.5).values
            per = {}
            deltas_boot = {t: [] for t in ("low", "mid", "top")}
            for idx in boot.indices():
                for t in ("low", "mid", "top"):
                    ii = idx[terc[idx] == t]
                    deltas_boot[t].append(auc(y[ii], s[ii]) - auc(y[ii], b1[ii]))
            pt = {}
            for t in ("low", "mid", "top"):
                mk = terc == t
                pt[t] = auc(y[mk], s[mk]) - auc(y[mk], b1[mk])
                per[t] = {"delta": pt[t], "CI95": ci(deltas_boot[t])}
            slopes = [np.polyfit([0, 1, 2], [deltas_boot["low"][k], deltas_boot["mid"][k], deltas_boot["top"][k]], 1)[0]
                      for k in range(len(deltas_boot["low"]))
                      if not any(math.isnan(deltas_boot[t][k]) for t in ("low", "mid", "top"))]
            rho = spearmanr([0, 1, 2], [pt["low"], pt["mid"], pt["top"]]).correlation
            table[m]["delta_vs_B1_per_tercile"] = per
            table[m]["crossover_trend"] = {"spearman_tercile_vs_delta": None if rho is None or math.isnan(rho) else float(rho),
                                           "slope": float(np.polyfit([0, 1, 2], [pt["low"], pt["mid"], pt["top"]], 1)[0]),
                                           "slope_CI95": ci(slopes),
                                           "caveat": "FOLIO's top tercile is only mildly conditioned (1 unless/except in "
                                                     "2656 pairs); crossover test weak by construction"}
            # halves fallback
            comp = L["sid"].map(lambda s_: sents[s_]["features"]["composite"]).values
            med = np.median(comp)
            hi = comp > med
            table[m]["delta_vs_B1_halves"] = {"bottom": auc(y[~hi], s[~hi]) - auc(y[~hi], b1[~hi]),
                                              "top": auc(y[hi], s[hi]) - auc(y[hi], b1[hi])}

    # ---------------- G2 false alarms on rewrites
    gold_score = sc[sc["set"] == "gold"].set_index(["metric", "sid"])["score"].to_dict()
    rw = sc[sc["set"] == "rewrite"]
    for m in table:
        rr = rw[rw["metric"] == m]
        if not len(rr):
            table[m]["G2_false_alarm"] = None
            continue
        delta = 0.0 if m in SIGNATURE_LIKE else 0.10
        fa, fa0, n = 0, 0, 0
        by_kind = defaultdict(lambda: [0, 0])
        for r in rr.itertuples():
            g = gold_score.get((m, r.sid))
            if g is None:
                continue
            n += 1
            f1 = r.score < g - delta
            fa += f1
            fa0 += r.score < g
            by_kind[r.kind][0] += f1
            by_kind[r.kind][1] += 1
        table[m]["G2_false_alarm"] = fa / n if n else None
        table[m]["G2_false_alarm_delta0"] = fa0 / n if n else None
        table[m]["G2_delta"] = delta
        table[m]["G2_n_rewrites"] = n
        table[m]["G2_by_kind"] = {k: {"rate": v[0] / v[1], "n": v[1]} for k, v in by_kind.items()}
        if m in SIGNATURE_LIKE:
            ren = by_kind.get("SYN_RENAME", [0, 0])
            oth = [sum(v[0] for k, v in by_kind.items() if k != "SYN_RENAME"),
                   sum(v[1] for k, v in by_kind.items() if k != "SYN_RENAME")]
            table[m]["G2_by_cause"] = {"alignment(rename)": ren[0] / ren[1] if ren[1] else None,
                                       "other": oth[0] / oth[1] if oth[1] else None}

    # ---------------- G3 increments
    L_inc = L.copy()
    L_inc["parse_okf"] = L_inc["parse_ok"].astype(float)
    for m in table:
        L_inc[m] = L_inc[m].fillna(0.5)
    for m in table:
        if m in ("B1", "B2") or "B1" not in L_inc.columns:
            continue
        table[m]["G3_increment_over_B1_parse"] = increment(L_inc, ["B1", "parse_okf"], m, boot)
        base2 = [c for c in ["B1", "parse_okf", "B3nli", "B7", "B8"] if c in L_inc.columns and c != m]
        table[m]["increment_over_best_baselines"] = increment(L_inc, base2, m, boot)
        if "B1plus" in L_inc.columns and m != "B1plus":
            table[m]["increment_over_B1plus_parse"] = increment(L_inc, ["B1plus", "parse_okf"], m, boot)

    # ---------------- cost per item
    for m in table:
        rr = sc[(sc["metric"] == m) & (sc["set"] == "real")]
        table[m]["usd_per_item_amortised"] = float(rr["usd"].fillna(0).mean()) if len(rr) else 0.0
        if "usd_per_sentence_probe" in rr.columns and rr["usd_per_sentence_probe"].notna().any():
            table[m]["usd_per_sentence_text_probe"] = float(
                rr.groupby("sid")["usd_per_sentence_probe"].first().fillna(0).mean())
        if "seconds" in rr.columns and rr["seconds"].notna().any():
            table[m]["seconds_per_item"] = float(rr["seconds"].dropna().mean())
    out["per_metric"] = table
    out["tercile_counts"] = tercile_counts

    # ---------------- mutants: per-operator detection
    mut = sc[sc["set"] == "mutant"]
    det = {}
    for m in sorted(set(mut["metric"])):
        det[m] = {}
        mm = mut[mut["metric"] == m]
        for op in sorted(set(mm["operator"].dropna())):
            xs = mm[mm["operator"] == op]
            lt = eq = n = 0
            lt_raw = n_raw = 0
            for r in xs.itertuples():
                g = gold_score.get((m, r.sid))
                if g is None:
                    continue
                n += 1
                lt += r.score < g
                eq += r.score == g
            p_strict = lt / n if n else None
            p_th = (lt + 0.5 * eq) / n if n else None
            det[m][op] = {"n": n, "detection_strict": p_strict, "strict_CI95": wilson(lt, n),
                          "detection_tiehalf": p_th, "tiehalf_CI95": wilson(lt + 0.5 * eq, n) if n else [None, None]}
    # raw-score detection for signature metrics (ignores the coverage 0.5 rule)
    raw_gold = sc[sc["set"] == "gold"].set_index(["metric", "sid"])["raw_score"].to_dict() if "raw_score" in sc else {}
    det_raw = {}
    for m in ("A1", "A2", "A3", "B5", "B5A2", "B4"):
        mm = mut[mut["metric"] == m]
        det_raw[m] = {}
        for op in sorted(set(mm["operator"].dropna())):
            lt = eq = n = 0
            for r in mm[mm["operator"] == op].itertuples():
                g = raw_gold.get((m, r.sid))
                if g is None or r.raw_score is None or (isinstance(r.raw_score, float) and math.isnan(r.raw_score)) \
                        or (isinstance(g, float) and math.isnan(g)):
                    continue
                n += 1
                lt += r.raw_score < g
                eq += r.raw_score == g
            det_raw[m][op] = {"n": n, "detection_tiehalf_raw": (lt + 0.5 * eq) / n if n else None}
    blind = {}
    for op in ("SCOPE", "CARD", "ANDOR"):
        x = det.get("A1", {}).get(op)
        if not x or not x["n"]:
            blind[f"A1_{op}"] = {"status": "not testable: 0 solver-verified mutants of this operator in the screen"}
            continue
        lo, hi = x["tiehalf_CI95"]
        in_band = 0.4 <= x["detection_tiehalf"] <= 0.6
        blind[f"A1_{op}"] = {"detection_tiehalf": x["detection_tiehalf"], "CI95": x["tiehalf_CI95"], "n": x["n"],
                             "predicted_blind_spot_confirmed": bool(in_band and lo <= 0.5 <= hi)}
    x2 = det.get("A2", {}).get("ANDOR")
    if x2 and x2["n"]:
        blind["A2_ANDOR_predicted_to_detect"] = {"detection_tiehalf": x2["detection_tiehalf"], "CI95": x2["tiehalf_CI95"],
                                                 "detects": bool(x2["tiehalf_CI95"][0] > 0.5)}
    out["mutant_detection"] = det
    out["mutant_detection_raw_score"] = det_raw
    out["blind_spot_tests"] = blind

    # confusion matrices
    conf = {}
    for m in ("A1", "A2", "A3"):
        mm = mut[mut["metric"] == m]
        M = defaultdict(Counter)
        for r in mm.itertuples():
            g = gold_score.get((m, r.sid))
            if g is None or not (r.score < g):
                continue
            M[OP_TYPE[r.operator]][r.error_type_pred] += 1
        rec = []
        for op, t in OP_TYPE.items():
            if t in ("scope", "cardinality"):
                continue
            tot = sum(M[t].values())
            if tot:
                rec.append(M[t][t] / tot)
        conf[m] = {"matrix": {k: dict(v) for k, v in M.items()}, "macro_recall_8_nonblind": float(np.mean(rec)) if rec else None,
                   "n_types_present": len(rec)}
    out["confusion_matrices"] = conf

    # ---------------- system level
    sysl = {}
    for m in table:
        per = L.groupby("system").agg(acc=("y", "mean"), ms=(m, lambda v: float(np.nanmean(v))))
        tau = kendalltau(per["acc"], per["ms"]).correlation if len(per) >= 2 else None
        sysl[m] = {"per_system": per.to_dict("index"), "kendall_tau": None if tau is None or math.isnan(tau) else float(tau),
                   "flag": "n=3 systems: tau takes 4 values; uninterpretable"}
    out["system_level"] = sysl

    # correlations
    cols = [m for m in table if m in L.columns]
    C = L[cols].fillna(0.5).corr(method="spearman")
    out["score_correlations_spearman"] = C.round(3).to_dict()

    # ---------------- gold-error flagging (A1/A2/A3 on original gold vs curated corrected flag)
    ge = {}
    go = sc[sc["set"] == "gold_orig"]
    flags = {s["sid"]: bool(s.get("corr_flag")) for s in d["sentences"] if s.get("gold_fol_corr")}
    for m in ("A1", "A2", "A3", "B1"):
        xs = go[go["metric"] == m] if m != "B1" else pd.DataFrame()
        if not len(xs):
            continue
        xs = xs[xs["sid"].isin(flags)]
        rs = xs.assign(flag=xs["sid"].map(flags)).sort_values("score")
        k = min(50, len(rs))
        ge[m] = {"n_orig_golds_scored": int(len(rs)), "base_rate": float(rs["flag"].mean()) if len(rs) else None,
                 "precision_at_k": float(rs["flag"].head(k).mean()) if k else None, "k": k,
                 "AUROC_flag": auc(rs["flag"].astype(int).values, -rs["score"].values) if len(rs) else None,
                 "note": "only sentences whose NL matches the curated release have a corrected flag; orig==corrected "
                         "golds are not re-scored (identical formula)"}
    out["gold_error_flagging"] = ge

    # ---------------- B6 + text diag + configs
    for nm in ("b6_results", "text_diag", "probe_config"):
        p = RES / f"{nm}.json"
        if p.exists():
            out[nm] = json.loads(p.read_text())
    ledger = jl(RES / "cost_ledger.jsonl")
    spend = Counter()
    for r in ledger:
        spend[r["purpose"]] += r.get("cost") or 0.0
    out["cost"] = {"total_usd": float(sum(spend.values())), "by_purpose": dict(spend), "cap_usd": 5.80,
                   "n_calls": len(ledger)}

    # ---------------- selection rule
    gates = {}
    for m in CANDIDATES:
        t = table.get(m)
        if not t:
            continue
        g1 = t["G1_coverage"] >= 0.70
        g2 = t.get("G2_false_alarm") is not None and t["G2_false_alarm"] <= 0.10
        inc = t.get("G3_increment_over_B1_parse", {})
        g3 = bool(inc.get("passes"))
        g4 = t["AUROC_real"] >= 0.65
        gates[m] = {"G1": {"value": t["G1_coverage"], "pass": g1}, "G2": {"value": t.get("G2_false_alarm"), "pass": g2},
                    "G3": {"delta": inc.get("delta_auroc"), "ci95": inc.get("ci95"), "pass": g3},
                    "G4": {"value": t["AUROC_real"], "pass": g4}, "survives": bool(g1 and g2 and g3 and g4),
                    "top_tercile_auroc": t["per_tercile"]["top"]["AUROC"]}
    surv = [m for m in gates if gates[m]["survives"]]
    verdict = {"rule": SELECTION_RULE, "gates": gates, "survivors": surv}
    if surv:
        ranked = sorted(surv, key=lambda m: -gates[m]["top_tercile_auroc"])
        verdict["ranking_top_tercile"] = ranked
        if len(ranked) == 1 or gates[ranked[0]]["top_tercile_auroc"] - gates[ranked[1]]["top_tercile_auroc"] >= 0.03:
            verdict.update(outcome="winner", winner=ranked[0],
                           reason="sole survivor" if len(ranked) == 1 else "leads next survivor by >= 0.03 in top tercile")
        else:
            rho = float(L[[ranked[0], ranked[1]]].fillna(0.5).corr(method="spearman").iloc[0, 1])
            if rho < 0.5:
                verdict.update(outcome="pair", pair=ranked[:2], pair_score_correlation=rho,
                               reason="top two within 0.03; correlation < 0.5 -> combined logistic stack advances")
            else:
                verdict.update(outcome="winner", winner=ranked[0], pair_score_correlation=rho,
                               reason="top two within 0.03 but correlation >= 0.5 -> top one advances alone")
    else:
        deltas = {m: gates[m]["G3"]["delta"] for m in gates if gates[m]["G3"]["delta"] is not None}
        best = max(deltas, key=deltas.get) if deltas else None
        if best is not None and deltas[best] >= 0.03:
            verdict.update(outcome="advance_without_survivor", winner=best,
                           reason=f"no survivor; largest ΔAUROC point estimate {deltas[best]:.3f} >= 0.03")
        else:
            verdict.update(outcome="null", winner=None,
                           reason="no candidate survives all four gates and no ΔAUROC point estimate >= 0.03; screen is "
                                  "null -> iter 2 tests the full stack against baselines on held-out")
        verdict["delta_point_estimates"] = deltas
    out["verdict"] = verdict

    # ---------------- diagnosis
    b6 = out.get("b6_results", {})
    dn = (b6.get("all", {}).get("down") or {}).get("acc")
    diag = {"B6_downward_accuracy": dn,
            "text_side_is_bottleneck": bool(dn is not None and dn < 0.80)}
    if "B5" in table and "A1" in table:
        diag["text_side_gap_B5_minus_A1"] = table["B5"]["AUROC_real"] - table["A1"]["AUROC_real"]
    if "B4" in table and "A1" in table:
        y = L["y"].values
        a1, b4s = L["A1"].fillna(0.5).values, L["B4"].fillna(0.5).values
        mk = L["B4"].notna().values
        bs = [auc(y[i], a1[i]) - auc(y[i], b4s[i]) for i in boot.indices(mk)]
        diag["exact_semantics_vs_decomposition_A1_minus_B4"] = {
            "delta": auc(y[mk], a1[mk]) - auc(y[mk], b4s[mk]), "CI95": ci(bs), "n": int(mk.sum())}
    # polarity vs alignment: does the monotonicity comparison add over the alignment/coverage part alone?
    y = L["y"].values
    pol = {}
    for a_, b_ in (("A1", "A0"), ("A2", "A0"), ("A3", "A0"), ("A1", "Ccov"), ("A3", "Ccov"), ("B5", "A1"), ("A3", "A1"),
                   ("B4", "A0")):
        if a_ in L.columns and b_ in L.columns:
            sa, sb = L[a_].fillna(0.5).values, L[b_].fillna(0.5).values
            bs = [auc(y[i], sa[i]) - auc(y[i], sb[i]) for i in boot.indices()]
            pol[f"{a_}_minus_{b_}"] = {"delta": auc(y, sa) - auc(y, sb), "CI95": ci(bs)}
    for m in ("A1", "A2", "A3", "B4"):
        if m in L_inc.columns and "A0" in L_inc.columns:
            pol[f"increment_{m}_over_B1_parse_A0"] = increment(L_inc, ["B1", "parse_okf", "A0"], m, boot)
    diag["polarity_vs_alignment"] = pol
    al = [x for x in sc[(sc["set"] == "real") & (sc["metric"] == "A1")]["coverage"].dropna()]
    diag["median_alignment_coverage_real"] = float(np.median(al)) if al else None
    diag["alignment_is_bottleneck"] = bool(al and np.median(al) < 0.7)
    out["diagnosis"] = diag

    # ---------------- examples (schema exp_gen_sol_out)
    ex = []
    piv_err = sc[(sc["set"] == "real")].pivot_table(index="item_id", columns="metric", values="error_type_pred",
                                                    aggfunc="first")
    for r in df.reset_index().itertuples():
        e = {"input": f"Sentence: {sents[r.sid]['nl']}\nCandidate FOL: {r.cand_fol}",
             "output": "unlabeled" if r.correct is None or (isinstance(r.correct, float) and math.isnan(r.correct))
             else ("faithful(equiv)" if int(r.correct) == 1 else "unfaithful(nonequiv)"),
             "metadata_item_id": r.item_id, "metadata_system": r.system, "metadata_tercile": r.tercile,
             "metadata_gold_fol": sents[r.sid]["gold_fol"], "metadata_gold_source": sents[r.sid]["gold_source"],
             "metadata_correct_orig_gold": None if r.correct_orig is None or (isinstance(r.correct_orig, float) and math.isnan(r.correct_orig)) else int(r.correct_orig),
             "metadata_parse_ok": bool(r.parse_ok)}
        for m in metrics_present:
            v = getattr(r, m, None) if m in df.columns else None
            e[f"predict_{m}"] = "NA" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{float(v):.4f}"
        for m in ("A1", "A2", "A3"):
            if m in piv_err.columns and r.item_id in piv_err.index:
                e[f"metadata_error_type_pred_{m}"] = piv_err.loc[r.item_id, m]
        ex.append(e)
    mut_ex = []
    for mrow in d["mutants"]:
        e = {"input": f"Sentence: {sents[mrow['sid']]['nl']}\nCandidate FOL: {mrow['fol']}",
             "output": f"unfaithful(mutant:{mrow['operator']})", "metadata_item_id": mrow["mid"],
             "metadata_operator": mrow["operator"], "metadata_error_type": OP_TYPE[mrow["operator"]]}
        xs = sc[(sc["set"] == "mutant") & (sc["item_id"] == mrow["mid"])] if False else None
        mut_ex.append(e)
    mscore = mut.pivot_table(index="item_id", columns="metric", values="score", aggfunc="first")
    for e in mut_ex:
        if e["metadata_item_id"] in mscore.index:
            for m in mscore.columns:
                v = mscore.loc[e["metadata_item_id"], m]
                e[f"predict_{m}"] = "NA" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{float(v):.4f}"
    method_out = {"metadata": {"method_name": "monotonicity-signature screen (Arm A): A1/A2/A3 vs baselines",
                               "description": "Gold-free NL->FOL faithfulness metrics screened on Logic-LM FOLIO-dev outputs",
                               **{k: v for k, v in out.items()}},
                  "datasets": [{"dataset": "folio_logiclm_screen_real", "examples": ex},
                               {"dataset": "folio_screen_gold_mutants", "examples": mut_ex}]}
    (RES / "method_out.json").write_text(json.dumps(method_out, ensure_ascii=False, indent=1, default=_js))
    (ROOT / "method_out.json").write_text(json.dumps(method_out, ensure_ascii=False, indent=1, default=_js))
    summary = {m: {k: table[m].get(k) for k in ("AUROC_real", "CI95", "G1_coverage", "G2_false_alarm")} |
               {"G3": (table[m].get("G3_increment_over_B1_parse") or {}).get("delta_auroc"),
                "G3_ci": (table[m].get("G3_increment_over_B1_parse") or {}).get("ci95"),
                "top": table[m]["per_tercile"]["top"]["AUROC"]} for m in table}
    (RES / "summary.json").write_text(json.dumps({"summary": summary, "verdict": verdict, "diagnosis": diag,
                                                  "cost": out["cost"]}, indent=1, default=_js))
    for m, v in summary.items():
        logger.info(f"{m:7s} AUROC={v['AUROC_real']:.3f} CI={_r(v['CI95'])} G1={v['G1_coverage']:.2f} "
                    f"G2={v['G2_false_alarm']} G3={v['G3']} {_r(v['G3_ci'])} top={v['top']:.3f}")
    logger.info(f"VERDICT: {verdict.get('outcome')} {verdict.get('winner')} survivors={surv}")
    make_figures(L, table, det)


def _r(x):
    return None if x is None else [None if v is None else round(v, 3) for v in x]


def _js(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if math.isnan(o) else float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, Counter):
        return dict(o)
    return str(o)


def make_figures(L, table, det):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from sklearn.metrics import roc_curve
    fig_dir = ROOT / "figures"
    fig_dir.mkdir(exist_ok=True)
    ms = [m for m in ["A1", "A2", "A3", "B1", "B1plus", "B3nli", "B3cos", "B4", "B5", "B2", "B7"] if m in L.columns]
    fig, ax = plt.subplots(figsize=(6, 5))
    for m in ms:
        fpr, tpr, _ = roc_curve(L["y"], L[m].fillna(0.5))
        ax.plot(fpr, tpr, label=f"{m} ({table[m]['AUROC_real']:.3f})", lw=1.5 if m in CANDIDATES else 1,
                ls="-" if m in CANDIDATES else "--")
    ax.plot([0, 1], [0, 1], color="grey", lw=0.5)
    ax.set_xlabel("False positive rate")
    ax.set_ylabel("True positive rate")
    ax.set_title("ROC on real Logic-LM candidates (primary labels)")
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(fig_dir / "roc_real.png", dpi=150)
    fig.savefig(fig_dir / "roc_real.pdf")
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(6, 4))
    for m in [x for x in ms if x != "B1" and "delta_vs_B1_per_tercile" in table[x]]:
        per = table[m]["delta_vs_B1_per_tercile"]
        ys = [per[t]["delta"] for t in ("low", "mid", "top")]
        ax.plot([0, 1, 2], ys, marker="o", label=m)
    ax.axhline(0, color="grey", lw=0.5)
    ax.set_xticks([0, 1, 2], ["low", "mid", "top"])
    ax.set_xlabel("complexity tercile")
    ax.set_ylabel("AUROC(M) - AUROC(B1)")
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(fig_dir / "delta_vs_b1_tercile.png", dpi=150)
    fig.savefig(fig_dir / "delta_vs_b1_tercile.pdf")
    plt.close(fig)
    mets = [m for m in ["A1", "A2", "A3", "B4", "B5", "B1"] if m in det]
    ops = [o for o in OP_TYPE if any(det[m].get(o, {}).get("n") for m in mets)]
    if mets and ops:
        M = np.array([[det[m].get(o, {}).get("detection_tiehalf") or np.nan for o in ops] for m in mets], dtype=float)
        fig, ax = plt.subplots(figsize=(8, 3.2))
        im = ax.imshow(M, vmin=0, vmax=1, cmap="viridis", aspect="auto")
        ax.set_xticks(range(len(ops)), ops, rotation=45, ha="right")
        ax.set_yticks(range(len(mets)), mets)
        for i in range(len(mets)):
            for j in range(len(ops)):
                if not np.isnan(M[i, j]):
                    ax.text(j, i, f"{M[i, j]:.2f}", ha="center", va="center", fontsize=7,
                            color="white" if M[i, j] < 0.6 else "black")
        fig.colorbar(im, ax=ax, label="detection (tie=1/2)")
        ax.set_title("Mutant detection per operator")
        fig.tight_layout()
        fig.savefig(fig_dir / "mutant_detection_heatmap.png", dpi=150)
        fig.savefig(fig_dir / "mutant_detection_heatmap.pdf")
        plt.close(fig)


if __name__ == "__main__":
    main()
