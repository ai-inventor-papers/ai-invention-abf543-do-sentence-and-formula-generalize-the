"""signature_score(T, S, A, variant) -> {score, raw_score, mismatches, error_type_pred, covered, ...}

T : text signature  {labels: {cid: + - 0 ± ?}, anchors: [{verb_cid, slot, arg_cid}], rel: {(c,q,side): lab}}
S : formula signature from solver_sig.signature (or an LLM-decomposed analogue for B4)
A : alignment from align.align
Coordinates (weights):
 (i)   each text concept with label != '?': dropped (no aligned predicate) -> mismatch w=1;
       else each aligned predicate P: mismatch if S[P] != T[c] (sign-flipped for lex-neg), w = 1/|aligned P|
 (ii)  each formula predicate unaligned or labelled '0' (vacuous) -> 'added' mismatch w=1 (else a match)
 (iii) each text role slot (verb v, slot i, arg a) with aligned relation R and aligned A/constant:
       'swap' mismatch if NOT anchored(R,i,A) while anchored(R,1-i,A); else match (w=1)
 (iv)  A2 / A3: relativized coordinates (w=0.5) vs S.rel[P_c|P_q|side]
score = 1 - Σ w·mismatch / Σ w.  covered = parse_ok ∧ ≤20% '?' coords ∧ coverage ≥ 0.5 ∧ ≥1 labelled
concept; uncovered -> score 0.5 (raw_score kept).
"""
from __future__ import annotations

FLIP = {"+": "-", "-": "+", "0": "0", "±": "±", "?": "?"}
ERROR_TYPES = ["swapped_args", "conflation", "dropped_condition", "added_condition", "wrong_split",
               "reversed_implication", "quantifier", "negation_polarity", "connective_andor", "other", "none"]


def _anch(S: dict, R: str, i: int, arg: str):
    return S.get("anchors", {}).get(f"{R}|{i}|{arg}")


def signature_score(T: dict, S: dict | None, A: dict | None, *, variant: str, parse_ok: bool = True,
                    optional: set | None = None) -> dict:
    if not parse_ok or S is None or A is None:
        return {"score": 0.5, "raw_score": None, "covered": False, "coverage": 0.0, "n_coords": 0,
                "mismatches": [], "error_type_pred": "other", "why_uncovered": "unparseable_or_no_signature"}
    labels_T = T.get("labels", {})
    by_c: dict[int, list] = {}
    for P, a in A["preds"].items():
        if a["cid"] is not None:
            by_c.setdefault(a["cid"], []).append(P)
    coords = []  # (w, mismatch:bool, record)
    n_q = 0
    concepts_labeled = 0
    for cid, tl in labels_T.items():
        cid = int(cid)
        if tl == "?":
            continue
        concepts_labeled += 1
        Ps = by_c.get(cid, [])
        covered_other = any(cid in a["covered"] for a in A["preds"].values()) or cid in A["consts"].values()
        if not Ps:
            if covered_other or (optional and cid in optional):
                continue  # compound-other / constant-covered / optional domain noun: not compared
            coords.append((1.0, True, {"type": "dropped", "cid": cid, "t": tl}))
            continue
        for P in Ps:
            sl = S["labels"].get(P, "?")
            if sl == "?":
                n_q += 1
                continue
            if A["preds"][P]["flip"]:
                sl = FLIP[sl]
            mis_l = (sl != tl) and variant != "A0"  # A0 ablation: polarity labels ignored (alignment-only)
            coords.append((1.0 / len(Ps), mis_l, {"type": "label", "cid": cid, "pred": P, "t": tl, "s": sl}))
    for P, a in A["preds"].items():
        sl = S["labels"].get(P, "?")
        mis = a["cid"] is None or (sl == "0" and variant != "A0")
        coords.append((1.0, mis, {"type": "added" if mis else "pred_ok", "pred": P, "s": sl,
                                  "why": "unaligned" if a["cid"] is None else ("vacuous" if sl == "0" else "")}))
    # role slots
    for an in (T.get("anchors", []) if variant != "A0" else []):
        Rs = [P for P in by_c.get(an["verb_cid"], []) if S.get("arity", {}).get(P, 1) >= 2]
        if not Rs:
            continue
        args = [P for P in by_c.get(an["arg_cid"], []) if S.get("arity", {}).get(P, 1) == 1]
        args += [f"c:{k}" for k, cid in A["consts"].items() if cid == an["arg_cid"]]
        if not args:
            continue
        for R in Rs:
            k = S["arity"][R]
            i = an["slot"]
            if i >= k:
                continue
            others = [j for j in range(k) if j != i]
            swap = False
            decided = False
            for ag in args:
                a_i = _anch(S, R, i, ag)
                a_o = [_anch(S, R, j, ag) for j in others]
                if a_i is None and all(x is None for x in a_o):
                    continue
                decided = True
                if (a_i is False) and any(x is True for x in a_o):
                    swap = True
            if decided:
                coords.append((1.0, swap, {"type": "swap" if swap else "slot_ok", "verb": an["verb_cid"],
                                           "slot": i, "R": R, "args": args}))
    # relativized
    if variant in ("A2", "A3", "B5A2", "B4A2"):
        for (c, q, side), tl in T.get("rel", {}).items():
            if tl == "?":
                continue
            Pc = [P for P in by_c.get(int(c), []) if S.get("arity", {}).get(P, 1) == 1]
            Pq = [P for P in by_c.get(int(q), []) if S.get("arity", {}).get(P, 1) == 1]
            for pc in Pc:
                for pq in Pq:
                    if pc == pq:
                        continue
                    sl = S.get("rel", {}).get(f"{pc}|{pq}|{side}")
                    if sl is None or sl == "?":
                        continue
                    if A["preds"][pc]["flip"]:
                        sl = FLIP[sl]
                    coords.append((0.5, sl != tl, {"type": "rel" if sl != tl else "rel_ok", "c": c, "q": q,
                                                   "side": side, "t": tl, "s": sl}))
    tot = sum(w for w, _, _ in coords)
    bad = sum(w for w, m, _ in coords if m)
    raw = 1.0 - bad / tot if tot > 0 else None
    n_coords = len(coords) + n_q
    frac_q = n_q / n_coords if n_coords else 1.0
    cov_ok = A["coverage"] >= 0.5
    covered = bool(raw is not None and frac_q <= 0.2 and cov_ok and concepts_labeled >= 1)
    mism = [r for _, m, r in coords if m]
    why = "" if covered else ("no_coords" if raw is None else "low_coverage" if not cov_ok else
                              "solver_unknown" if frac_q > 0.2 else "no_labelled_concept")
    return {"score": raw if covered else 0.5, "raw_score": raw, "covered": covered, "coverage": A["coverage"],
            "n_coords": n_coords, "mismatches": mism, "error_type_pred": error_type(mism, A), "why_uncovered": why}


def error_type(mism: list, A: dict) -> str:
    if not mism:
        return "none"
    types = [m["type"] for m in mism]
    if "swap" in types:
        return "swapped_args"
    lab = [m for m in mism if m["type"] == "label"]
    if "dropped" in types and lab:  # a concept vanished AND a remaining predicate's label is off (± or mismatch)
        return "conflation"
    if "dropped" in types:
        return "dropped_condition"
    if "added" in types:
        return "added_condition"
    # wrong split: a concept whose aligned predicates carry opposite signs
    by_c = {}
    for m in lab:
        by_c.setdefault(m["cid"], set()).add(m["s"])
    if any({"+", "-"} <= v for v in by_c.values()):
        return "wrong_split"
    down_up = any(m["t"] == "-" and m["s"] == "+" for m in lab)
    up_down = any(m["t"] == "+" and m["s"] == "-" for m in lab)
    if down_up and up_down:
        return "reversed_implication"
    if any(m["t"] == "-" and m["s"] in ("+", "±") for m in lab) and not up_down:
        return "quantifier"
    flips = [m for m in lab if {m["t"], m["s"]} == {"+", "-"}]
    if len(flips) == 1:
        return "negation_polarity"
    if types and all(t == "rel" for t in types):
        return "connective_andor"
    return "other"
