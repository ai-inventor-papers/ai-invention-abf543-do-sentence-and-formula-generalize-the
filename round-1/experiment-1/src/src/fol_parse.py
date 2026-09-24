"""FOLIO-syntax FOL parser -> hashable tuple AST, printer, and AST utilities.

Grammar (Unicode, FOLIO / Logic-LM style):
  quantifiers ∀x ∃x (variables: any identifier bound by a quantifier)
  connectives ¬ ∧ ∨ → ↔ ⊕ with precedence ¬ > ∧ > ∨ > → > ↔,⊕ ; → is right-associative
  atoms Name(t1, ..., tk), zero-arity atoms Name, equalities t1 = t2, t1 ≠ t2
  terms: identifiers only (constants may contain digits/underscores/unicode letters); no function terms.
Anything else (∈, ⊆, ≤, '::', ForAll(, LaTeX, nested function terms) raises ParseError.

Quantifier scope: if the quantifier is followed by '(' the scope is that parenthesised group
(FOLIO convention); otherwise (∀x Dog(x) → Bark(x)) the scope extends as far right as possible.
Unbound single-letter lowercase arguments (x, y, z, x1 ...) are treated as FREE VARIABLES and
universally closed (flag free_vars=True). All other unbound arguments are constants.

AST node forms (tuples, hashable):
  ('atom', name, (term, ...))  term = ('v', name) | ('c', name)
  ('eq', t1, t2)
  ('not', f)
  ('and', (f1, f2, ...)) / ('or', (f1, f2, ...))   n-ary, flattened
  ('imp', a, b) / ('iff', a, b) / ('xor', a, b)
  ('all', var, f) / ('ex', var, f)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

TOKEN_RE = re.compile(r"\s*(∀|∃|¬|∧|∨|→|↔|⊕|≠|=|\(|\)|,|\w+|\S)", re.U)
BINOPS = {"↔": (1, "iff"), "⊕": (1, "xor"), "→": (2, "imp"), "∨": (3, "or"), "∧": (4, "and")}
FREE_VAR_RE = re.compile(r"^[a-z]\d*$")


class ParseError(ValueError):
    pass


def tokenize(s: str) -> list[str]:
    s = s.strip()
    toks, pos = [], 0
    while pos < len(s):
        m = TOKEN_RE.match(s, pos)
        if not m:
            break
        toks.append(m.group(1))
        pos = m.end()
        while pos < len(s) and s[pos].isspace():
            pos += 1
    for t in toks:
        if not (t in "∀∃¬∧∨→↔⊕≠=(),") and not re.fullmatch(r"\w+", t, re.U):
            raise ParseError(f"unsupported symbol {t!r}")
    return toks


@dataclass
class Parsed:
    ast: tuple
    free_vars: bool = False
    preds: dict = field(default_factory=dict)   # name -> arity
    consts: list = field(default_factory=list)  # sorted constant names
    arity_conflict: bool = False


class _Parser:
    def __init__(self, toks: list[str]):
        self.t, self.i = toks, 0
        self.bound: list[str] = []
        self.free: set[str] = set()

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def eat(self, x=None):
        tok = self.peek()
        if tok is None:
            raise ParseError("unexpected end")
        if x is not None and tok != x:
            raise ParseError(f"expected {x!r} got {tok!r}")
        self.i += 1
        return tok

    def parse(self, minp: int = 1):
        lhs = self.unary()
        while self.peek() in BINOPS and BINOPS[self.peek()][0] >= minp:
            op = self.eat()
            p, name = BINOPS[op]
            rhs = self.parse(p if name == "imp" else p + 1)
            if name in ("and", "or"):
                parts = []
                for x in (lhs, rhs):
                    parts.extend(x[1] if x[0] == name else (x,))
                lhs = (name, tuple(parts))
            else:
                lhs = (name, lhs, rhs)
        return lhs

    def unary(self):
        tok = self.peek()
        if tok in ("∀", "∃"):
            self.eat()
            v = self.eat()
            if not re.fullmatch(r"\w+", v, re.U):
                raise ParseError(f"bad variable {v!r}")
            self.bound.append(v)
            try:
                if self.peek() == "(":
                    body = self.group()
                elif self.peek() in ("∀", "∃", "¬"):
                    body = self.unary()
                    # allow ∀x ∀y A(x) → B(y): if an operator follows, widen scope
                    while self.peek() in BINOPS:
                        op = self.eat()
                        _, name = BINOPS[op]
                        rhs = self.parse(1)
                        body = (name, body, rhs) if name not in ("and", "or") else (name, (body, rhs))
                else:
                    body = self.parse(1)  # wide scope
            finally:
                self.bound.pop()
            return ("all" if tok == "∀" else "ex", v, body)
        if tok == "¬":
            self.eat()
            return ("not", self.unary())
        if tok == "(":
            return self.group()
        return self.atom()

    def group(self):
        self.eat("(")
        n = self.parse()
        self.eat(")")
        return n

    def term(self, name: str):
        if not re.fullmatch(r"\w+", name, re.U):
            raise ParseError(f"bad term {name!r}")
        if name in self.bound:
            return ("v", name)
        if FREE_VAR_RE.match(name):
            self.free.add(name)
            return ("v", name)
        return ("c", name)

    def atom(self):
        name = self.eat()
        if not re.fullmatch(r"\w+", name, re.U):
            raise ParseError(f"unexpected token {name!r}")
        if self.peek() == "(":
            self.eat("(")
            args = []
            if self.peek() == ")":
                self.eat(")")
                return ("atom", name, ())
            while True:
                a = self.eat()
                if self.peek() == "(":
                    raise ParseError("function terms unsupported")
                args.append(self.term(a))
                if self.peek() == ",":
                    self.eat(",")
                    continue
                self.eat(")")
                break
            return ("atom", name, tuple(args))
        if self.peek() in ("=", "≠"):
            op = self.eat()
            rhs = self.eat()
            e = ("eq", self.term(name), self.term(rhs))
            return e if op == "=" else ("not", e)
        return ("atom", name, ())


def parse(s: str) -> Parsed:
    if s is None or not str(s).strip():
        raise ParseError("empty")
    toks = tokenize(str(s))
    p = _Parser(toks)
    ast = p.parse()
    if p.i != len(toks):
        raise ParseError(f"trailing tokens {toks[p.i:p.i + 5]}")
    free = sorted(p.free)
    for v in reversed(free):
        ast = ("all", v, ast)
    ast, conflict = _fix_arity(ast)
    return Parsed(ast=ast, free_vars=bool(free), preds=preds(ast), consts=sorted(consts(ast)),
                  arity_conflict=conflict)


def _fix_arity(ast):
    """If a predicate name is used with 2 arities, rename the minority uses Name#k."""
    ar: dict[str, set] = {}
    for n in walk(ast):
        if n[0] == "atom":
            ar.setdefault(n[1], set()).add(len(n[2]))
    bad = {k for k, v in ar.items() if len(v) > 1}
    if not bad:
        return ast, False

    def fix(n):
        if n[0] == "atom":
            return ("atom", f"{n[1]}#{len(n[2])}", n[2]) if n[1] in bad else n
        return map_children(n, fix)
    return fix(ast), True


# ---------------------------------------------------------------- utilities
def children(n) -> list:
    op = n[0]
    if op in ("and", "or"):
        return list(n[1])
    if op == "not":
        return [n[1]]
    if op in ("imp", "iff", "xor"):
        return [n[1], n[2]]
    if op in ("all", "ex"):
        return [n[2]]
    return []


def map_children(n, fn):
    op = n[0]
    if op in ("and", "or"):
        return (op, tuple(fn(c) for c in n[1]))
    if op == "not":
        return ("not", fn(n[1]))
    if op in ("imp", "iff", "xor"):
        return (op, fn(n[1]), fn(n[2]))
    if op in ("all", "ex"):
        return (op, n[1], fn(n[2]))
    return n


def walk(n):
    yield n
    for c in children(n):
        yield from walk(c)


def preds(ast) -> dict:
    out = {}
    for n in walk(ast):
        if n[0] == "atom":
            out[n[1]] = len(n[2])
    return out


def consts(ast) -> set:
    out = set()
    for n in walk(ast):
        if n[0] == "atom":
            out.update(t[1] for t in n[2] if t[0] == "c")
        elif n[0] == "eq":
            out.update(t[1] for t in n[1:] if t[0] == "c")
    return out


def depth(ast) -> int:
    ch = children(ast)
    return 1 + (max(depth(c) for c in ch) if ch else 0)


def n_quant(ast) -> int:
    return sum(1 for n in walk(ast) if n[0] in ("all", "ex"))


def n_binconn(ast) -> int:
    c = 0
    for n in walk(ast):
        if n[0] in ("and", "or"):
            c += len(n[1]) - 1
        elif n[0] in ("imp", "iff", "xor"):
            c += 1
    return c


def _t(t) -> str:
    return t[1]


SYM = {"and": " ∧ ", "or": " ∨ ", "imp": " → ", "iff": " ↔ ", "xor": " ⊕ "}


def to_str(n) -> str:
    op = n[0]
    if op == "atom":
        return n[1] + (f"({', '.join(_t(a) for a in n[2])})" if n[2] else "")
    if op == "eq":
        return f"{_t(n[1])} = {_t(n[2])}"
    if op == "not":
        c = n[1]
        if c[0] == "eq":
            return f"{_t(c[1])} ≠ {_t(c[2])}"
        inner = to_str(c)
        return "¬" + (inner if c[0] in ("atom", "not", "all", "ex") else f"({inner})")
    if op in ("and", "or"):
        return SYM[op].join(_wrap(c) for c in n[1])
    if op in ("imp", "iff", "xor"):
        return f"{_wrap(n[1])}{SYM[op]}{_wrap(n[2])}"
    if op in ("all", "ex"):
        q = "∀" if op == "all" else "∃"
        return f"{q}{n[1]} ({to_str(n[2])})"
    raise ValueError(op)


def _wrap(c) -> str:
    s = to_str(c)
    return s if c[0] in ("atom", "not", "eq") else f"({s})"


def rename(ast, pmap: dict | None = None, cmap: dict | None = None):
    pmap, cmap = pmap or {}, cmap or {}

    def term(t):
        return ("c", cmap.get(t[1], t[1])) if t[0] == "c" else t

    def fn(n):
        if n[0] == "atom":
            return ("atom", pmap.get(n[1], n[1]), tuple(term(a) for a in n[2]))
        if n[0] == "eq":
            return ("eq", term(n[1]), term(n[2]))
        return map_children(n, fn)
    return fn(ast)


def canon(ast) -> str:
    return to_str(ast)


if __name__ == "__main__":
    tests = [
        "∀x ((Dog(x) ∧ ¬Trained(x)) → Bark(x))",
        "∀x (Student(x) → ∃y (Book(y) ∧ Reads(x, y)))",
        "(Attend(bonnie) ∧ Student(bonnie)) ⊕ ¬(Attend(bonnie) ∨ Student(bonnie))",
        "∀x ∀y (Owns(x, y) ∧ x ≠ y → Rich(x))",
        "∃x∃y(Cat(x) ∧ Cat(y) ∧ ¬(x = y))",
        "∀x Dog(x) → Animal(x)",
        "Rain → Wet",
        "Mammal(x) → Animal(x)",
        "Owns(tom, car2020)",
    ]
    for s in tests:
        p = parse(s)
        print(s, "=>", to_str(p.ast), p.preds, p.consts, p.free_vars)
    for bad in ["x ∈ S", "Owns(x, f(y))", "∀x (A(x) ≤ B(x))"]:
        try:
            parse(bad)
            print("NO ERROR?", bad)
        except ParseError as e:
            print("ParseError ok:", bad, e)
