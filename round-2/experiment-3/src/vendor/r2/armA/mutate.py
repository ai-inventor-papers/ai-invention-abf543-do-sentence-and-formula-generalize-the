"""Typed mutation operators (known error types) and meaning-preserving rewrites on gold ASTs.

Every mutant must be solver-verified NON-equivalent to its gold (identity names, sizes 1..4);
every rewrite must be solver-verified EQUIVALENT (under its rename map). Verification is done by
the caller (build_screen_set.py) with labeler.identity_equiv.

Operators (one mutant per operator per gold, seeded):
 NEG, QUANT, IMPL_REV, DROP, ADD, ARG_SWAP, ANDOR, SCOPE, MERGE, CARD
Rewrites: SYN_RENAME, REORDER, CONTRAPOS, DEMORGAN, PRENEX
"""
from __future__ import annotations

import random
import re

from fol_parse import children, map_children, preds, rename, walk

OPERATORS = ["NEG", "QUANT", "IMPL_REV", "DROP", "ADD", "ARG_SWAP", "ANDOR", "SCOPE", "MERGE", "CARD"]
REWRITES = ["SYN_RENAME", "REORDER", "CONTRAPOS", "DEMORGAN", "PRENEX"]
OP_TYPE = {"NEG": "negation_polarity", "QUANT": "quantifier", "IMPL_REV": "reversed_implication",
           "DROP": "dropped_condition", "ADD": "added_condition", "ARG_SWAP": "swapped_args",
           "MERGE": "conflation", "ANDOR": "connective_andor", "SCOPE": "scope", "CARD": "cardinality"}


# ------------------------------------------------------------ path helpers
def paths(n, pred=lambda x: True, path=()):
    """All paths (tuples of child indices) to nodes satisfying pred."""
    out = [path] if pred(n) else []
    for i, c in enumerate(children(n)):
        out += paths(c, pred, path + (i,))
    return out


def get(n, path):
    for i in path:
        n = children(n)[i]
    return n


def replace(n, path, new):
    if not path:
        return new
    ch = children(n)
    i = path[0]
    ch[i] = replace(ch[i], path[1:], new)
    op = n[0]
    if op in ("and", "or"):
        return (op, tuple(ch))
    if op == "not":
        return ("not", ch[0])
    if op in ("imp", "iff", "xor"):
        return (op, ch[0], ch[1])
    if op in ("all", "ex"):
        return (op, n[1], ch[0])
    raise ValueError(op)


def flat(n):
    """Re-flatten nested and/or after edits; collapse 1-element and/or."""
    n = map_children(n, flat)
    if n[0] in ("and", "or"):
        parts = []
        for c in n[1]:
            parts.extend(c[1] if c[0] == n[0] else (c,))
        if len(parts) == 1:
            return parts[0]
        return (n[0], tuple(parts))
    return n


def free_vars(n, bound=frozenset()):
    op = n[0]
    if op == "atom":
        return {a[1] for a in n[2] if a[0] == "v" and a[1] not in bound}
    if op == "eq":
        return {a[1] for a in n[1:] if a[0] == "v" and a[1] not in bound}
    if op in ("all", "ex"):
        return free_vars(n[2], bound | {n[1]})
    out = set()
    for c in children(n):
        out |= free_vars(c, bound)
    return out


def subst_var(n, old, new):
    op = n[0]
    if op == "atom":
        return ("atom", n[1], tuple(("v", new) if a == ("v", old) else a for a in n[2]))
    if op == "eq":
        return ("eq",) + tuple(("v", new) if a == ("v", old) else a for a in n[1:])
    if op in ("all", "ex") and n[1] == old:
        return n
    return map_children(n, lambda c: subst_var(c, old, new))


def all_vars(n):
    s = set()
    for x in walk(n):
        if x[0] in ("all", "ex"):
            s.add(x[1])
        elif x[0] == "atom":
            s |= {a[1] for a in x[2] if a[0] == "v"}
    return s


# ------------------------------------------------------------ mutation operators
def m_neg(f, rng):
    negs = paths(f, lambda x: x[0] == "not")
    if negs:
        p = rng.choice(negs)
        return flat(replace(f, p, get(f, p)[1]))
    atoms = paths(f, lambda x: x[0] == "atom")
    p = rng.choice(atoms)
    return replace(f, p, ("not", get(f, p)))


def m_quant(f, rng):
    qs = paths(f, lambda x: x[0] in ("all", "ex"))
    if not qs:
        return None
    special = [p for p in qs if (get(f, p)[0] == "all" and get(f, p)[2][0] == "imp") or
               (get(f, p)[0] == "ex" and get(f, p)[2][0] == "and")]
    if special:
        p = rng.choice(special)
        q = get(f, p)
        if q[0] == "all":
            return replace(f, p, ("ex", q[1], flat(("and", (q[2][1], q[2][2])))))
        parts = q[2][1]
        k = rng.randrange(len(parts))
        # ∃x(A∧B) -> ∀x(A→B): first conjunct(s) become antecedent
        k = max(1, min(k, len(parts) - 1))
        ante = parts[0] if k == 1 else ("and", parts[:k])
        cons = parts[k] if len(parts) - k == 1 else ("and", parts[k:])
        return replace(f, p, ("all", q[1], ("imp", ante, cons)))
    p = qs[0]
    q = get(f, p)
    return replace(f, p, ("ex" if q[0] == "all" else "all", q[1], q[2]))


def m_impl_rev(f, rng):
    ps = paths(f, lambda x: x[0] == "imp")
    if not ps:
        return None
    p = rng.choice(ps)
    x = get(f, p)
    return replace(f, p, ("imp", x[2], x[1]))


def m_drop(f, rng):
    ps = paths(f, lambda x: x[0] == "and" and len(x[1]) >= 2)
    if not ps:
        return None
    # prefer conjunctions that are antecedents of an implication
    ante = [p for p in ps if len(p) >= 1 and get(f, p[:-1])[0] == "imp" and p[-1] == 0]
    p = rng.choice(ante or ps)
    x = get(f, p)
    k = rng.randrange(len(x[1]))
    rest = tuple(c for i, c in enumerate(x[1]) if i != k)
    return flat(replace(f, p, ("and", rest)))


def m_add(f, rng, pool: list[str]):
    fp = preds(f)
    cands = [q for q in pool if q not in fp]
    q = rng.choice(cands) if cands else "Extra"
    imps = paths(f, lambda x: x[0] == "imp")
    if imps:
        p = rng.choice(imps)
        x = get(f, p)
        fv = sorted(free_vars(x[1]) | free_vars(x[2]))
        arg = ("v", fv[0]) if fv else _first_const(f)
        if arg is None:
            return None
        return flat(replace(f, p, ("imp", ("and", (x[1], ("atom", q, (arg,)))), x[2])))
    qs = paths(f, lambda x: x[0] in ("all", "ex"))
    if qs:
        p = qs[-1]
        x = get(f, p)
        return flat(replace(f, p, (x[0], x[1], ("and", (x[2], ("atom", q, (("v", x[1]),)))))))
    arg = _first_const(f)
    if arg is None:
        return None
    return flat(("and", (f, ("atom", q, (arg,)))))


def _first_const(f):
    for x in walk(f):
        if x[0] == "atom":
            for a in x[2]:
                if a[0] == "c":
                    return a
    return None


def m_arg_swap(f, rng):
    ps = paths(f, lambda x: x[0] == "atom" and len(x[2]) == 2 and x[2][0] != x[2][1])
    if not ps:
        return None
    p = rng.choice(ps)
    x = get(f, p)
    return replace(f, p, ("atom", x[1], (x[2][1], x[2][0])))


def m_andor(f, rng):
    ps = paths(f, lambda x: x[0] in ("and", "or"))
    if not ps:
        return None
    p = rng.choice(ps)
    x = get(f, p)
    return flat(replace(f, p, ("or" if x[0] == "and" else "and", x[1])))


def prenex(f):
    """Prenex normal form (after eliminating ↔/⊕ occurrences only where quantifiers sit below them).
    Returns None if a quantifier sits under ↔/⊕ (not handled)."""
    used = set(all_vars(f))

    def fresh(v):
        i = 1
        while f"{v}{i}" in used:
            i += 1
        used.add(f"{v}{i}")
        return f"{v}{i}"

    def pn(n):
        op = n[0]
        if op in ("atom", "eq"):
            return [], n
        if op in ("all", "ex"):
            qs, m = pn(n[2])
            return [(op, n[1])] + qs, m
        if op == "not":
            qs, m = pn(n[1])
            return [("ex" if q == "all" else "all", v) for q, v in qs], ("not", m)
        if op in ("iff", "xor"):
            qa, ma = pn(n[1])
            qb, mb = pn(n[2])
            if qa or qb:
                raise ValueError("quantifier under iff/xor")
            return [], (op, ma, mb)
        if op == "imp":
            qa, ma = pn(n[1])
            qb, mb = pn(n[2])
            qa = [("ex" if q == "all" else "all", v) for q, v in qa]
            parts = [(qa, ma), (qb, mb)]
        else:
            parts = [pn(c) for c in n[1]]
        # rename bound vars to avoid capture between siblings
        allq, mats = [], []
        seen = set()
        for i, (qs, m) in enumerate(parts):
            other_free = set()
            for j, (_, mm) in enumerate(parts):
                if j != i:
                    other_free |= free_vars(mm)
            newq = []
            for q, v in qs:
                if v in seen or v in other_free:
                    nv = fresh(v)
                    m = subst_var(m, v, nv)
                    v = nv
                seen.add(v)
                newq.append((q, v))
            allq += newq
            mats.append(m)
        if op == "imp":
            return allq, ("imp", mats[0], mats[1])
        return allq, (op, tuple(mats))

    try:
        qs, m = pn(f)
    except ValueError:
        return None
    out = m
    for q, v in reversed(qs):
        out = (q, v, out)
    return flat(out)


def m_scope(f, rng):
    pf = prenex(f)
    if pf is None:
        return None
    chain = []
    n = pf
    while n[0] in ("all", "ex"):
        chain.append((n[0], n[1]))
        n = n[2]
    idx = [i for i in range(len(chain) - 1) if chain[i][0] != chain[i + 1][0]]
    if not idx:
        return None
    i = rng.choice(idx)
    chain[i], chain[i + 1] = chain[i + 1], chain[i]
    out = n
    for q, v in reversed(chain):
        out = (q, v, out)
    return out


def m_merge(f, rng):
    un = sorted(p for p, k in preds(f).items() if k == 1)
    if len(un) < 2:
        return None
    q, p = rng.sample(un, 2)
    return rename(f, {q: p})


def m_card(f, rng):
    ps = paths(f, lambda x: x[0] == "ex")
    if not ps:
        return None
    p = rng.choice(ps)
    x = get(f, p)
    v = x[1]
    used = all_vars(f)
    w = v + "2"
    while w in used:
        w += "2"
    phi_w = subst_var(x[2], v, w)
    new = ("ex", v, ("ex", w, flat(("and", (("not", ("eq", ("v", v), ("v", w))), x[2], phi_w)))))
    return replace(f, p, new)


def mutate(f, op: str, rng: random.Random, pool: list[str]):
    fn = {"NEG": m_neg, "QUANT": m_quant, "IMPL_REV": m_impl_rev, "DROP": m_drop,
          "ARG_SWAP": m_arg_swap, "ANDOR": m_andor, "SCOPE": m_scope, "MERGE": m_merge, "CARD": m_card}
    if op == "ADD":
        return m_add(f, rng, pool)
    return fn[op](f, rng)


# ------------------------------------------------------------ rewrites
def split_camel(name: str) -> list[str]:
    s = re.sub(r"[_#]", " ", name)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)
    return [w for w in s.split() if w]


def r_syn_rename(f, rng):
    from nltk.corpus import wordnet as wn
    pmap = {}
    for p in preds(f):
        toks = split_camel(p)
        if not toks:
            continue
        head = toks[-1].lower()
        if len(head) <= 2 or head in {"the", "and", "for", "with", "from", "into", "onto", "of", "at", "in", "on", "by", "to"}:
            continue
        syns = []
        ss = wn.synsets(head)
        if ss:
            for l in ss[0].lemma_names():
                if l.lower() != head and "_" not in l and "-" not in l and l.isalpha():
                    syns.append(l)
        if not syns:
            continue
        syn = sorted(set(syns))[rng.randrange(len(set(syns)))]
        new = "".join(t[:1].upper() + t[1:] for t in toks[:-1]) + syn[:1].upper() + syn[1:]
        if new not in preds(f).keys() and new not in pmap.values():
            pmap[p] = new
    if not pmap:
        return None, {}
    return rename(f, pmap), pmap


def r_reorder(f, rng):
    ps = paths(f, lambda x: x[0] in ("and", "or") and len(x[1]) >= 2)
    if not ps:
        return None
    out = f
    for p in ps[::-1]:
        x = get(out, p)
        parts = list(x[1])
        for _ in range(5):
            rng.shuffle(parts)
            if tuple(parts) != x[1]:
                break
        out = replace(out, p, (x[0], tuple(parts)))
    return out if out != f else None


def r_contrapos(f, rng):
    ps = paths(f, lambda x: x[0] == "imp")
    if not ps:
        return None
    p = rng.choice(ps)
    x = get(f, p)
    neg = lambda y: y[1] if y[0] == "not" else ("not", y)  # noqa: E731
    return replace(f, p, ("imp", neg(x[2]), neg(x[1])))


def r_demorgan(f, rng):
    ps = paths(f, lambda x: x[0] == "not" and x[1][0] in ("and", "or"))
    if ps:
        p = rng.choice(ps)
        x = get(f, p)[1]
        dual = "or" if x[0] == "and" else "and"
        return flat(replace(f, p, (dual, tuple(c[1] if c[0] == "not" else ("not", c) for c in x[1]))))
    ps = paths(f, lambda x: x[0] in ("and", "or"))
    if not ps:
        return None
    p = rng.choice(ps)
    x = get(f, p)
    dual = "or" if x[0] == "and" else "and"
    return replace(f, p, ("not", (dual, tuple(c[1] if c[0] == "not" else ("not", c) for c in x[1]))))


def r_prenex(f, rng):
    pf = prenex(f)
    return pf if pf is not None and pf != f else None


def rewrite(f, kind: str, rng: random.Random):
    """Returns (ast or None, rename_map)."""
    if kind == "SYN_RENAME":
        return r_syn_rename(f, rng)
    fn = {"REORDER": r_reorder, "CONTRAPOS": r_contrapos, "DEMORGAN": r_demorgan, "PRENEX": r_prenex}[kind]
    return fn(f, rng), {}
