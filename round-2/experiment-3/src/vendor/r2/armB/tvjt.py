"""Metric (ii) TVJT — Truth-Value Judgement over solver-built distinguishing worlds.

For a target formula F: generate F's own typed mutants M_j (non-equivalent), let z3 find a minimal
finite world w_j separating F from M_j (F(w)!=M(w)), verbalize the worlds, and ask the LLM ONLY whether
the SENTENCE is true in each world (it never sees F or M). Score = mean agreement of the judged truth
value with F(w_j). A faithful F agrees with the sentence on worlds where it disagrees with its mutants.
"""
from __future__ import annotations

import json
import re

import z3

from fol_core import Grounder, constants, predicates, py_eval
from mutants import OPERATORS, make_mutant
from verbalize import fact, individual_names

PROMPT_VERSION = "tvjt_v1"
TVJT_PROMPT = ("You will read a sentence and several small, self-contained situations. For each situation, decide "
               "whether the sentence is TRUE or FALSE in that situation, using ONLY the listed individuals and facts "
               "(anything not listed is false; interpret general statements as being about the individuals listed). "
               "Sentence: \"{S}\"\n\n{SITUATIONS}\n\nAnswer with JSON only: {{{KEYS}}}")
HEADER = "These are ALL the individuals and ALL the facts in this situation; anything not stated is false."


def universal_restrictors(F) -> list[str]:
    """Unary predicates in the antecedent of a → directly under ∀ (the generic-plural restrictor)."""
    from mutants import preorder
    out = []
    preds = predicates(F)
    for _, m in preorder(F):
        if m[0] == "forall" and m[2][0] == "imp":
            for _, a in preorder(m[2][1]):
                if a[0] == "atom" and preds.get(a[1]) == 1 and a[1] not in out:
                    out.append(a[1])
    return out


def find_world(F, M, prefer: int, nmax: int = 4, timeout_ms: int = 3000, nonvacuous: list[str] | None = None) -> dict | None:
    """Minimal world with F(w) != M(w). prefer=0 tries F∧¬M first, 1 tries ¬F∧M first.
    nonvacuous (TVJT_nv variant): hard-require >=1 instance of each listed unary predicate; falls back to
    the unconstrained search (flag nv_fallback) when no such distinguishing world exists."""
    if nonvacuous:
        w = _find_world(F, M, prefer, nmax, timeout_ms, nonvacuous)
        if w is not None:
            w["nv_fallback"] = False
            return w
        w = _find_world(F, M, prefer, nmax, timeout_ms, None)
        if w is not None:
            w["nv_fallback"] = True
        return w
    return _find_world(F, M, prefer, nmax, timeout_ms, None)


def _find_world(F, M, prefer: int, nmax: int, timeout_ms: int, nonvacuous: list[str] | None) -> dict | None:
    consts = list(dict.fromkeys(constants(F) + constants(M)))
    for una in (True, False):
        start = max(1, len(consts)) if una else 1
        for n in range(start, nmax + 1):
            g = Grounder(n, consts, una=una)
            fF, fM = g.g(F), g.g(M)
            for d in ([prefer, 1 - prefer]):
                opt = z3.Optimize()
                opt.set("timeout", timeout_ms)
                opt.add(*g.side)
                opt.add(z3.And(fF, z3.Not(fM)) if d == 0 else z3.And(z3.Not(fF), fM))
                for rp in (nonvacuous or []):
                    opt.add(z3.Or(*[g.atom(rp, (e,)) for e in range(n)]))
                for a in g.atoms.values():
                    opt.add_soft(z3.Not(a), 1)
                r = opt.check()
                if r == z3.sat:
                    mdl = opt.model()
                    true_atoms = sorted([list(k) for k, v in g.atoms.items()
                                         if z3.is_true(mdl.eval(v, model_completion=True))],
                                        key=lambda x: (x[0], x[1]))
                    true_atoms = [[p, list(t)] for p, t in true_atoms]
                    if una:
                        cmap = {c: i for i, c in enumerate(consts)}
                    else:
                        cmap = {c: mdl.eval(v, model_completion=True).as_long() for c, v in g.C.items()}
                    w = {"n": n, "una": una, "consts": cmap, "true_atoms": true_atoms, "F_value": d == 0,
                         "M_value": d != 0}
                    # re-check with pure-python evaluation (independent of z3 grounding)
                    interp = {"P": {}, "C": cmap}
                    for p, t in true_atoms:
                        interp["P"].setdefault(p, set()).add(tuple(t))
                    if py_eval(F, interp, n) != w["F_value"] or py_eval(M, interp, n) != w["M_value"]:
                        continue
                    return w
    return None


def worlds_for(F, seed_key: str, ops=OPERATORS, max_worlds: int = 12, card_variants: bool = False,
               nonvacuous: bool = False) -> list[dict]:
    worlds = []
    nv = universal_restrictors(F) if nonvacuous else None
    jobs = []
    for op in ops:
        if op == "CARD" and card_variants:
            jobs += [("CARD", "two"), ("CARD", "unique")]
        else:
            jobs.append((op, None))
    for j, (op, var) in enumerate(jobs):
        if len(worlds) >= max_worlds:
            break
        m = make_mutant(F, op, seed_key, variant=var)
        if not m.get("kept"):
            continue
        w = find_world(F, m["ast"], prefer=j % 2, nonvacuous=nv)
        if w is None:
            continue
        w.update({"op": op, "variant": var, "mutant_fol": m["fol"]})
        worlds.append(w)
    return worlds


def verbalize_world(w: dict, preds: dict[str, int], glosses: dict | None = None) -> tuple[str, bool]:
    n = w["n"]
    consts = w["consts"]
    elem_consts: dict[int, list[str]] = {}
    for c, e in consts.items():
        elem_consts.setdefault(e, []).append(c)
    cnames, fresh = individual_names(list(consts), n)
    names, fi, same = {}, 0, []
    for e in range(n):
        if e in elem_consts:
            cs = elem_consts[e]
            names[e] = cnames[cs[0]]
            for c2 in cs[1:]:
                same.append(f"{cnames[cs[0]]} and {cnames[c2]} are the same individual.")
        else:
            names[e] = fresh[fi] if fi < len(fresh) else f"Person{fi}"
            fi += 1
    true = {(p, tuple(t)) for p, t in w["true_atoms"]}
    lines = [HEADER, "Individuals: " + ", ".join(names[e] for e in range(n)) + "."] + same
    for p in sorted(preds):
        if preds[p] == 0:
            lines.append(fact(p, [], (p, ()) in true, glosses) + ".")
    for e in range(n):
        for p in sorted(preds):
            if preds[p] == 1:
                lines.append(fact(p, [names[e]], (p, (e,)) in true, glosses) + ".")
    has_rel = False
    for p in sorted(preds):
        if preds[p] >= 2:
            has_rel = True
            for (q, t) in sorted(true):
                if q == p:
                    lines.append(fact(p, [names[i] for i in t], True, glosses) + ".")
    if has_rel:
        lines.append("No other relationships hold.")
    return " ".join(lines), False


def build_prompt(sentence: str, F, worlds: list[dict], glosses: dict | None = None) -> str:
    preds = {}
    for w in worlds:
        preds.update(predicates(F))
        for p, t in w["true_atoms"]:
            preds.setdefault(p, len(t))
    # predicates of mutants that are false everywhere (e.g. fresh NewCond) are listed only if in F
    sits = []
    for i, w in enumerate(worlds, 1):
        txt, _ = verbalize_world(w, preds, glosses)
        sits.append(f"Situation {i}: {txt}")
    keys = ", ".join(f'"{i}": "TRUE"|"FALSE"|"UNCLEAR"' for i in range(1, len(worlds) + 1))
    return TVJT_PROMPT.format(S=sentence, SITUATIONS="\n".join(sits), KEYS=keys)


def parse_answer(text: str, k: int) -> dict[int, str] | None:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    out = {}
    for i in range(1, k + 1):
        v = str(d.get(str(i), d.get(i, ""))).strip().upper()
        if v not in ("TRUE", "FALSE", "UNCLEAR"):
            return None
        out[i] = v
    return out


def score_answers(worlds: list[dict], ans: dict[int, str]) -> tuple[float, list[float], str]:
    agrees = []
    for i, w in enumerate(worlds, 1):
        v = ans[i]
        if v == "UNCLEAR":
            agrees.append(0.5)
        else:
            agrees.append(1.0 if (v == "TRUE") == w["F_value"] else 0.0)
    score = sum(agrees) / len(agrees)
    fam: dict[str, list[float]] = {}
    for w, a in zip(worlds, agrees):
        fam.setdefault(w["op"], []).append(a)
    if all(a == 1.0 for a in agrees):
        et = "none"
    else:
        et = min(OPERATORS, key=lambda o: (sum(fam[o]) / len(fam[o]) if o in fam else 9, OPERATORS.index(o)))
    return score, agrees, et
