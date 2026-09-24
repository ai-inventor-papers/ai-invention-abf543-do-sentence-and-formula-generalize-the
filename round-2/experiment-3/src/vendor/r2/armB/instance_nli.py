"""Metric (iii) instance-consequence NLI (zero LLM calls in the primary DeBERTa variant).

For a target F, z3 labels (premise set P, hypothesis h) pairs about a few named individuals as
E (F∧P ⊨ h), C (F∧P ⊨ ¬h) or N (neither), over a bounded domain of |I|+1 elements with unique names on I.
Hypotheses: ground literals plus templated quantified consequences (Q1 shared witness, Q2 existence,
Q3 universal restrictor→scope, Q4 at-least-two). An NLI model then reads SENTENCE + verbalized P and
predicts entailment of verbalized h. score = mean agreement (binary entail-vs-not) with the F labels.
"""
from __future__ import annotations

import hashlib
import itertools
import random

import z3

from fol_core import Grounder, constants, count_ops, predicates
from mutants import OPERATORS, make_mutant, preorder
from verbalize import fact, individual_names

A1, A2 = "@a1", "@a2"
MAX_ATOMS = 40
MAX_PAIRS = 12


def restrictor_preds(F, preds: dict[str, int]) -> list[str]:
    out = []
    for _, m in preorder(F):
        if m[0] == "imp":
            ante = m[1]
            for _, a in preorder(ante):
                if a[0] == "atom" and preds.get(a[1]) == 1 and a[1] not in out:
                    out.append(a[1])
        elif m[0] == "exists" and m[2][0] == "and":
            for _, a in preorder(m[2][1]):
                if a[0] == "atom" and preds.get(a[1]) == 1 and a[1] not in out:
                    out.append(a[1])
    if not out:
        out = [p for p, k in sorted(preds.items()) if k == 1]
    return out


def scope_preds(F, preds: dict[str, int]) -> list[str]:
    out = []
    for _, m in preorder(F):
        if m[0] == "imp":
            for _, a in preorder(m[2]):
                if a[0] == "atom" and preds.get(a[1]) == 1 and a[1] not in out:
                    out.append(a[1])
    return out


def at(p, *args):
    return ("atom", p, tuple(("c", a) for a in args))


def build_items(F, seed_key: str) -> dict:
    """Construct premise sets + hypotheses for F (label-free); returns structure reused for mutants."""
    preds = predicates(F)
    consts = constants(F)
    nested = count_ops(F, {"forall", "exists"}) >= 2
    has_bin = any(k == 2 for k in preds.values())
    has_ex = count_ops(F, {"exists"}) > 0
    extra = [A1] + ([A2] if (has_bin or nested) else [])
    inds = consts + extra
    atoms = []
    for p, k in sorted(preds.items(), key=lambda x: (x[1], x[0])):
        if k == 0:
            atoms.append(at(p))
        else:
            for tup in itertools.product(inds, repeat=k):
                atoms.append(at(p, *tup))
        if len(atoms) >= MAX_ATOMS:
            break
    atoms = atoms[:MAX_ATOMS]
    R = restrictor_preds(F, preds)
    S = scope_preds(F, preds)
    prem = [()]
    for r in R:
        prem.append(((r, A1, True),))
        prem.append(((r, A1, False),))
    if A2 in inds:
        for r in R:
            prem.append(((r, A1, True), (r, A2, True)))
    prem = prem[:6] if len(prem) <= 6 else [prem[0]] + random.Random(seed_key).sample(prem[1:], 5)
    hyps = []
    for a in atoms:
        hyps.append(("lit", a, True))
        hyps.append(("lit", a, False))
    un = [p for p, k in sorted(preds.items()) if k == 1]
    bi = [p for p, k in sorted(preds.items()) if k == 2]
    if A2 in inds:
        for r in bi:
            for b in un:
                hyps.append(("Q1", ("exists", "y", ("and", ("atom", b, (("v", "y"),)),
                                                     ("atom", r, (("c", A1), ("v", "y"))),
                                                     ("atom", r, (("c", A2), ("v", "y"))))), (r, b)))
    for p in un:
        hyps.append(("Q2", ("exists", "x", ("atom", p, (("v", "x"),))), (p,)))
        hyps.append(("Q4", ("exists", "x", ("exists", "y", ("and", ("not", ("eq", ("v", "x"), ("v", "y"))),
                                                          ("atom", p, (("v", "x"),)), ("atom", p, (("v", "y"),))))), (p,)))
    for r in R:
        for s in S:
            if r != s:
                hyps.append(("Q3", ("forall", "x", ("imp", ("atom", r, (("v", "x"),)), ("atom", s, (("v", "x"),)))), (r, s)))
    return {"inds": inds, "consts": consts, "premises": prem, "hyps": hyps,
            "force_q": nested or has_ex, "n_dom": len(inds) + 1}


def hyp_ast(h):
    if h[0] == "lit":
        return h[1] if h[2] else ("not", h[1])
    return h[1]


def prem_ast(pr):
    lits = [at(p, a) if pos else ("not", at(p, a)) for p, a, pos in pr]
    return lits


def label_pairs(F, items: dict, pairs: list[tuple[int, int]] | None = None, timeout_ms: int = 2000) -> dict:
    """Label (premise_idx, hyp_idx) pairs under F. Returns {(pi,hi): 'E'|'C'|'N'} ; premise sets
    inconsistent with F are reported in '_inconsistent'."""
    inds = items["inds"]
    extra_needed = [c for c in constants(F) if c not in inds]  # mutants may add constants (rare)
    g = Grounder(items["n_dom"] + len(extra_needed), inds + extra_needed, una=True)
    s = z3.Solver()
    s.set("timeout", timeout_ms)
    s.add(g.g(F))
    out, incons = {}, set()
    hyp_g = {}
    prem_idx = sorted({p for p, _ in pairs}) if pairs is not None else range(len(items["premises"]))
    for pi in prem_idx:
        s.push()
        for lit in prem_ast(items["premises"][pi]):
            s.add(g.g(lit))
        if s.check() != z3.sat:
            incons.add(pi)
            s.pop()
            continue
        hs = [h for p, h in pairs if p == pi] if pairs is not None else range(len(items["hyps"]))
        for hi in hs:
            h = items["hyps"][hi]
            if pairs is None and h[0] == "lit" and any(h[1] == at(p, a) for p, a, _ in items["premises"][pi]):
                continue
            if hi not in hyp_g:
                hyp_g[hi] = g.g(hyp_ast(h))
            hz = hyp_g[hi]
            r_not = s.check(z3.Not(hz)) if False else None
            s.push()
            s.add(z3.Not(hz))
            r1 = s.check()
            s.pop()
            s.push()
            s.add(hz)
            r2 = s.check()
            s.pop()
            if z3.unknown in (r1, r2):
                continue
            if r1 == z3.unsat and r2 == z3.sat:
                out[(pi, hi)] = "E"
            elif r2 == z3.unsat and r1 == z3.sat:
                out[(pi, hi)] = "C"
            elif r1 == z3.sat and r2 == z3.sat:
                out[(pi, hi)] = "N"
        s.pop()
    return {"labels": out, "inconsistent": sorted(incons)}


def select_pairs(labels: dict, items: dict, seed_key: str) -> list[tuple[int, int]]:
    rng = random.Random(int(hashlib.sha1(f"{seed_key}|NLI".encode()).hexdigest()[:12], 16))
    keys = sorted(labels)
    forced = []
    if items["force_q"]:
        forced = [k for k in keys if items["hyps"][k[1]][0] in ("Q1", "Q4")]
        rng.shuffle(forced)
        forced = forced[:6]
    rest = [k for k in keys if k not in forced]
    by = {"E": [], "C": [], "N": []}
    for k in rest:
        by[labels[k]].append(k)
    for v in by.values():
        rng.shuffle(v)
    chosen = list(forced)
    budget = MAX_PAIRS - len(chosen)
    while budget > 0 and any(by.values()):
        for lab in ("E", "C", "N"):
            if by[lab] and budget > 0:
                chosen.append(by[lab].pop())
                budget -= 1
    return sorted(chosen)


def verbalize_pair(sentence: str, items: dict, pi: int, hi: int, glosses: dict | None = None) -> tuple[str, str]:
    consts = items["consts"]
    n_extra = sum(1 for x in items["inds"] if x.startswith("@"))
    cnames, fresh = individual_names(consts, n_extra)
    names = dict(cnames)
    for x, f in zip([i for i in items["inds"] if i.startswith("@")], fresh):
        names[x] = f
    pr = items["premises"][pi]
    facts = [fact(p, [names[a]], pos, glosses) + "." for p, a, pos in pr]
    premise = sentence.strip()
    if not premise.endswith((".", "!", "?")):
        premise += "."
    if facts:
        premise += " " + " ".join(facts)
    h = items["hyps"][hi]
    if h[0] == "lit":
        a = h[1]
        hyp = fact(a[1], [names[t[1]] for t in a[2]], h[2], glosses) + "."
    elif h[0] == "Q1":
        r, b = h[2]
        hyp = (f"There is an individual such that {fact(b, ['it'], True, glosses)}, "
               f"{fact(r, [names[A1], 'it'], True, glosses)}, and {fact(r, [names[A2], 'it'], True, glosses)}.")
    elif h[0] == "Q2":
        hyp = f"There is an individual such that {fact(h[2][0], ['it'], True, glosses)}."
    elif h[0] == "Q3":
        r, s_ = h[2]
        hyp = f"For every individual, if {fact(r, ['it'], True, glosses)}, then {fact(s_, ['it'], True, glosses)}."
    else:
        hyp = f"There are at least two different individuals, and {fact(h[2][0], ['each of them'], True, glosses)}."
    return premise, hyp


def mutant_label_sets(F, items: dict, pairs: list, seed_key: str) -> dict[str, dict]:
    """Relabel the SAME selected pairs under each typed mutant of F (for error-type prediction)."""
    out = {}
    for op in OPERATORS:
        m = make_mutant(F, op, seed_key)
        if not m.get("kept"):
            continue
        try:
            lab = label_pairs(m["ast"], items, pairs=pairs)
        except (ValueError, z3.Z3Exception):
            continue
        out[op] = {f"{k[0]}|{k[1]}": v for k, v in lab["labels"].items()}
    return out


def process_target(F, sentence: str, seed_key: str, glosses: dict | None = None) -> dict:
    items = build_items(F, seed_key)
    lab = label_pairs(F, items)
    pairs = select_pairs(lab["labels"], items, seed_key)
    texts = [verbalize_pair(sentence, items, pi, hi) for pi, hi in pairs]
    gl_texts = [verbalize_pair(sentence, items, pi, hi, glosses) for pi, hi in pairs] if glosses else None
    mut = mutant_label_sets(F, items, pairs, seed_key) if pairs else {}
    return {"pairs": [f"{pi}|{hi}" for pi, hi in pairs], "labels": [lab["labels"][p] for p in pairs],
            "hyp_kinds": [items["hyps"][hi][0] for _, hi in pairs], "texts": texts, "gloss_texts": gl_texts,
            "mutant_labels": mut, "n_inconsistent_premises": len(lab["inconsistent"]),
            "n_labeled_candidates": len(lab["labels"])}


# ------------------------------------------------------------------------------------------ scoring
def agree_scores(labels: list[str], probs: list[dict]) -> tuple[float, float]:
    ab, a3 = [], []
    for lab, p in zip(labels, probs):
        pe = p["entailment"]
        ab.append(pe if lab == "E" else 1 - pe)
        a3.append(p[{"E": "entailment", "C": "contradiction", "N": "neutral"}[lab]])
    return sum(ab) / len(ab), sum(a3) / len(a3)


def error_type(labels: list[str], pairs: list[str], probs: list[dict], mut: dict[str, dict]) -> str:
    def am(p):
        return {"entailment": "E", "contradiction": "C", "neutral": "N"}[max(p, key=p.get)]
    pred = [am(p) for p in probs]
    base = sum(pl == lab for pl, lab in zip(pred, labels)) / max(1, len(labels))
    best, best_gain = "none", 0.0
    for op in OPERATORS:
        if op not in mut:
            continue
        ml = mut[op]
        idx = [i for i, k in enumerate(pairs) if k in ml]
        if not idx:
            continue
        agree_m = sum(pred[i] == ml[pairs[i]] for i in idx) / len(idx)
        agree_f = sum(pred[i] == labels[i] for i in idx) / len(idx)
        gain = agree_m - agree_f
        if gain > best_gain + 1e-12:
            best, best_gain = op, gain
    return best
