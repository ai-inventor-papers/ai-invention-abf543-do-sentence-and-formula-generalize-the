"""Tolerant first-order-logic parser / printer for NL->FOL outputs.

Extended from the GEN_HYPO feasibility prototype
(iter_1/gen_hypo/claude_agent/feasibility/monotonicity_profile.py, Pratt parser).

Accepted syntax
- Quantifiers: ∀ ∃ and ASCII `forall` `exists` (also `all`/`some` when followed by a variable
  and a formula); multi-binders `∀x ∀y`, `∀x,y`, `∀x y`, `∀x.` `∀x:` `(∀x)`.
- Connectives: ¬ ~ ! not | ∧ & and | ∨ | or | → -> => ⇒ ⊃ | ↔ <-> <=> ⇔ ≡ | ⊕ xor ^ ⊻.
- Equality `=`, `≠`, `!=`. Predicates in CamelCase or snake_case; 0-ary propositions.
- Constants: any argument identifier that is not bound by an enclosing quantifier.
- Unsupported (parse error): function terms, ∈ ⊆ < > and arithmetic.

AST (hashable tuples)
  ('forall', var, body) ('exists', var, body) ('not', a) ('and', a, b) ('or', a, b)
  ('imp', a, b) ('iff', a, b) ('xor', a, b) ('atom', name, (term, ...)) ('eq', t1, t2)
  term = ('var', name) | ('const', name)

Scope policy: a quantifier followed by '(' scopes over that group (FOLIO convention). If the
result leaves variables free that a quantifier binds elsewhere, the formula is re-parsed with
WIDE scope (quantifier body extends to the right as far as possible); remaining free
single-letter variables are universally closed. Both repairs are reported in `ParseResult.notes`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

QUANT = {"∀": "forall", "∃": "exists", "forall": "forall", "exists": "exists", "exist": "exists",
         "all": "forall", "some": "exists", "∀∀": "forall"}
NOT_TOK = {"¬", "~", "!", "not", "∼", "￢"}
BIN = {
    "∧": "and", "&": "and", "&&": "and", "and": "and", "/\\": "and", "⋀": "and",
    "∨": "or", "|": "or", "||": "or", "or": "or", "\\/": "or", "⋁": "or",
    "→": "imp", "->": "imp", "=>": "imp", "⇒": "imp", "⊃": "imp", "⟶": "imp", "implies": "imp",
    "↔": "iff", "<->": "iff", "<=>": "iff", "⇔": "iff", "≡": "iff", "⟷": "iff", "iff": "iff",
    "⊕": "xor", "xor": "xor", "⊻": "xor", "^": "and",  # ASCII ^ is read as conjunction (∧ look-alike)
}
PREC = {"iff": 1, "xor": 1, "imp": 2, "or": 3, "and": 4}
SYM = {"and": "∧", "or": "∨", "imp": "→", "iff": "↔", "xor": "⊕"}

TOK_RE = re.compile(
    r"\s*(<->|<=>|->|=>|&&|\|\||/\\|\\/|!=|≠|∀|∃|¬|∧|∨|→|↔|⊕|⇒|⇔|⊃|≡|⊻|⟶|⟷|⋀|⋁|∼|￢|"
    r"[~!&|^()\[\],.:=]|∈|⊆|⊂|<|>|≤|≥|\+|\*|/|-|"
    r"\"[^\"]{0,60}\"|[0-9]+\.[0-9]+[A-Za-z0-9_%]*|"
    r"[A-Za-z0-9_À-ɏ]+(?:['\-][A-Za-z0-9_À-ɏ]+)*)"
)
VARLIKE = re.compile(r"^[a-z][0-9]*'*$|^[a-z]{1,2}[0-9]+$")


class FOLParseError(ValueError):
    pass


@dataclass
class ParseResult:
    ast: tuple | None
    ok: bool
    error: str = ""
    notes: list[str] = field(default_factory=list)
    text: str = ""


def tokenize(s: str) -> list[str]:
    out, pos = [], 0
    s = s.strip()
    while pos < len(s):
        m = TOK_RE.match(s, pos)
        if not m or m.end() == pos:
            raise FOLParseError(f"cannot tokenize at {s[pos:pos + 20]!r}")
        out.append(m.group(1))
        pos = m.end()
        while pos < len(s) and s[pos].isspace():
            pos += 1
    return out


def _is_ident(t: str | None) -> bool:
    return t is not None and bool(re.match(r"^[\"A-Za-z0-9_À-ɏ]", t)) \
        and t.lower() not in ("and", "or", "not", "xor", "implies", "iff") and t not in QUANT


class _Parser:
    def __init__(self, toks: list[str], wide: bool):
        self.t, self.i, self.wide = toks, 0, wide

    def peek(self, k: int = 0):
        j = self.i + k
        return self.t[j] if j < len(self.t) else None

    def eat(self, x: str | None = None) -> str:
        tok = self.peek()
        if tok is None:
            raise FOLParseError(f"unexpected end (expected {x})" if x else "unexpected end")
        if x is not None and tok != x:
            raise FOLParseError(f"expected {x!r} got {tok!r}")
        self.i += 1
        return tok

    def binop(self) -> str | None:
        tok = self.peek()
        if tok is None:
            return None
        return BIN.get(tok) or BIN.get(tok.lower()) if (tok in BIN or tok.lower() in BIN) else None

    def parse_formula(self, minp: int = 1) -> tuple:
        lhs = self.unary()
        while True:
            op = self.binop()
            if op is None or PREC[op] < minp:
                break
            self.eat()
            p = PREC[op]
            rhs = self.parse_formula(p if op == "imp" else p + 1)
            lhs = (op, lhs, rhs)
        return lhs

    def is_quant_start(self) -> bool:
        tok = self.peek()
        if tok in ("∀", "∃"):
            return True
        if tok is not None and tok.lower() in ("forall", "exists", "exist"):
            return True
        if tok is not None and tok.lower() in ("all", "some"):
            nxt, nxt2 = self.peek(1), self.peek(2)
            return nxt is not None and bool(VARLIKE.match(nxt)) and nxt2 not in (")", ",", None)
        return False

    def binders(self) -> list[str]:
        vars_ = []
        while True:
            tok = self.peek()
            if tok is None:
                raise FOLParseError("quantifier without variable")
            if not _is_ident(tok):
                raise FOLParseError(f"bad quantified variable {tok!r}")
            self.eat()
            vars_.append(tok)
            nxt = self.peek()
            if nxt == ",":
                # ∀x,y (...)  -- only if an identifier that is not a predicate call follows
                call_like = self.peek(2) == "(" and _is_ident(self.peek(3)) and self.peek(4) in (",", ")")
                if _is_ident(self.peek(1)) and (self.peek(2) != "(" or (VARLIKE.match(self.peek(1)) and not call_like)):
                    self.eat(",")
                    continue
                self.eat(",")
                break
            if nxt in (".", ":"):
                self.eat()
                break
            # ∀x y (...)  : a following lowercase var-like identifier not followed by '('
            if _is_ident(nxt) and VARLIKE.match(nxt) and self.peek(1) is not None \
                    and self.peek(1) not in BIN and self.peek(1) not in (")", ",", "=", "≠", "!="):
                looks_call = self.peek(1) == "(" and _is_ident(self.peek(2)) and self.peek(3) in (",", ")")
                if not looks_call:
                    continue
            break
        return vars_

    def unary(self) -> tuple:
        tok = self.peek()
        if tok is None:
            raise FOLParseError("unexpected end of formula")
        if self.is_quant_start():
            q = QUANT[tok.lower()] if tok.lower() in QUANT else QUANT[tok]
            self.eat()
            if self.peek() == "(" and _is_ident(self.peek(1)) and self.peek(2) == ")" :
                # ∀(x) body
                self.eat("(")
                vars_ = [self.eat()]
                self.eat(")")
            else:
                vars_ = self.binders()
            body = self.quant_body()
            for v in reversed(vars_):
                body = (q, v, body)
            return body
        if tok in NOT_TOK or tok.lower() == "not":
            self.eat()
            return ("not", self.unary())
        if tok in ("(", "["):
            close = ")" if tok == "(" else "]"
            # (∀x) body  -- parenthesised quantifier prefix
            if self.peek(1) in ("∀", "∃") and _is_ident(self.peek(2)) and self.peek(3) == close:
                self.eat(tok)
                q = QUANT[self.eat()]
                v = self.eat()
                self.eat(close)
                return (q, v, self.quant_body())
            self.eat(tok)
            n = self.parse_formula()
            self.eat(close)
            return n
        return self.atom()

    def quant_body(self) -> tuple:
        if self.wide:
            return self.parse_formula()
        tok = self.peek()
        if tok in ("(", "["):
            return self.unary()
        if self.is_quant_start() or tok in NOT_TOK:
            return self.unary()
        # "∀x P(x) → Q(x)" : without a group the body extends to the right (standard reading)
        return self.parse_formula()

    def term(self) -> tuple:
        tok = self.eat()
        if not _is_ident(tok):
            raise FOLParseError(f"bad term {tok!r}")
        if self.peek() == "(":
            raise FOLParseError(f"function term {tok}(...) unsupported")
        return ("t", tok)

    def atom(self) -> tuple:
        tok = self.peek()
        if not _is_ident(tok):
            raise FOLParseError(f"unexpected token {tok!r}")
        name = self.eat()
        if self.peek() == "(":
            self.eat("(")
            args = []
            if self.peek() == ")":
                self.eat(")")
                return ("atom", name, tuple())
            while True:
                args.append(self.term())
                if self.peek() == ",":
                    self.eat(",")
                    continue
                self.eat(")")
                break
            return ("atom", name, tuple(args))
        # equality between bare terms
        if self.peek() in ("=", "≠", "!="):
            op = self.eat()
            rhs = self.term()
            eq = ("eq", ("t", name), rhs)
            return ("not", eq) if op in ("≠", "!=") else eq
        if self.peek() in ("∈", "⊆", "⊂", "<", ">", "≤", "≥"):
            raise FOLParseError(f"unsupported relation {self.peek()!r}")
        return ("atom", name, tuple())


def _resolve(n: tuple, bound: frozenset, free_vars: set) -> tuple:
    op = n[0]
    if op in ("forall", "exists"):
        return (op, n[1], _resolve(n[2], bound | {n[1]}, free_vars))
    if op == "not":
        return ("not", _resolve(n[1], bound, free_vars))
    if op in SYM:
        return (op, _resolve(n[1], bound, free_vars), _resolve(n[2], bound, free_vars))
    if op in ("atom", "eq"):
        terms = n[2] if op == "atom" else n[1:]
        res = []
        for t in terms:
            name = t[1]
            if name in bound:
                res.append(("var", name))
            else:
                if VARLIKE.match(name):
                    free_vars.add(name)
                res.append(("const", name))
        return ("atom", n[1], tuple(res)) if op == "atom" else ("eq", res[0], res[1])
    raise FOLParseError(f"bad node {op}")


def _bound_names(n: tuple, acc: set) -> set:
    if n[0] in ("forall", "exists"):
        acc.add(n[1])
        _bound_names(n[2], acc)
    elif n[0] == "not":
        _bound_names(n[1], acc)
    elif n[0] in SYM:
        _bound_names(n[1], acc)
        _bound_names(n[2], acc)
    return acc


def _close(ast: tuple, names: list[str]) -> tuple:
    for v in sorted(names, reverse=True):
        ast = ("forall", v, ast)
    return ast


def _to_var(n: tuple, names: set) -> tuple:
    op = n[0]
    if op in ("forall", "exists"):
        return (op, n[1], _to_var(n[2], names - {n[1]} if False else names))
    if op == "not":
        return ("not", _to_var(n[1], names))
    if op in SYM:
        return (op, _to_var(n[1], names), _to_var(n[2], names))
    if op == "atom":
        return ("atom", n[1], tuple(("var", t[1]) if t[0] == "const" and t[1] in names else t for t in n[2]))
    if op == "eq":
        return ("eq",) + tuple(("var", t[1]) if t[0] == "const" and t[1] in names else t for t in n[1:])
    return n


FENCE = re.compile(r"```[a-zA-Z]*")


LATEX_WRAP = re.compile(r"\\(?:text|mathrm|mathit|textit|operatorname|mathsf|texttt)\s*\{([^{}]*)\}")


def clean_text(s: str) -> str:
    s = FENCE.sub(" ", s).replace("`", " ")
    s = LATEX_WRAP.sub(r"\1", s)
    for a, b in (("\\left(", "("), ("\\right)", ")"), ("\\left[", "("), ("\\right]", ")"), ("\\(", " "), ("\\)", " "),
                 ("\\[", " "), ("\\]", " "), ("\\,", " "), ("\\;", " "), ("\\!", ""), ("\\quad", " "),
                 ("\\wedge", "∧"), ("\\vee", "∨"), ("\\Rightarrow", "→"), ("\\Leftrightarrow", "↔"),
                 ("\\neq", "≠"), ("\\ne ", "≠ "), ("\\lnot", "¬"), ("\\neg", "¬")):
        s = s.replace(a, b)
    s = s.replace("$", " ").replace("\\forall", "∀").replace("\\exists", "∃").replace("\\neg", "¬")
    s = s.replace("\\land", "∧").replace("\\wedge", "∧").replace("\\lor", "∨").replace("\\vee", "∨")
    s = s.replace("\\rightarrow", "→").replace("\\to", "→").replace("\\leftrightarrow", "↔")
    s = s.replace("\\oplus", "⊕").replace("\\lnot", "¬").replace("\\iff", "↔").replace("\\implies", "→")
    s = s.replace("​", "").replace(" ", " ").replace("’", "'").replace("‘", "'")
    s = s.strip()
    s = re.sub(r"^(FOL|Formula|Answer|Output|Translation|First-order logic)\s*[:：]\s*", "", s, flags=re.I)
    s = re.sub(r"^\*\*|\*\*$", "", s).strip()
    s = s.rstrip(" .;")
    return s.strip()


def parse(s: str) -> ParseResult:
    """Parse a FOL string. Never raises; returns ParseResult(ok=False, error=...) on failure."""
    text = clean_text(s or "")
    if not text:
        return ParseResult(None, False, "empty", text=text)
    try:
        toks = tokenize(text)
    except FOLParseError as e:
        return ParseResult(None, False, f"tokenize: {e}", text=text)
    errors = []
    for wide in (False, True):
        try:
            p = _Parser(toks, wide)
            raw = p.parse_formula()
            if p.i != len(toks):
                raise FOLParseError(f"trailing tokens from {toks[p.i:p.i + 4]}")
            free: set = set()
            ast = _resolve(raw, frozenset(), free)
            notes = [] if not wide else ["wide_scope_reparse"]
            quantified = _bound_names(ast, set())
            if free & quantified and not wide:
                errors.append("free vars bound elsewhere; retry wide")
                continue
            if free:
                ast = _close(_to_var(ast, free), sorted(free))
                notes.append("implicit_universal_closure:" + ",".join(sorted(free)))
            return ParseResult(ast, True, "", notes, text)
        except (FOLParseError, IndexError, KeyError, RecursionError) as e:
            errors.append(str(e))
    return ParseResult(None, False, "; ".join(dict.fromkeys(errors)), text=text)


def to_str(n: tuple) -> str:
    op = n[0]
    if op in ("forall", "exists"):
        return ("∀" if op == "forall" else "∃") + n[1] + " " + _wrap(n[2], tight=True)
    if op == "not":
        return "¬" + _wrap(n[1], tight=True)
    if op in SYM:
        return f"{_wrap(n[1])} {SYM[op]} {_wrap(n[2])}"
    if op == "atom":
        return n[1] + ("(" + ", ".join(t[1] for t in n[2]) + ")" if n[2] else "")
    if op == "eq":
        return f"{n[1][1]} = {n[2][1]}"
    raise ValueError(op)


def _wrap(n: tuple, tight: bool = False) -> str:
    s = to_str(n)
    if n[0] in SYM or (n[0] == "eq") or (not tight and n[0] in ("forall", "exists")):
        return "(" + s + ")"
    return s


def signature(ast: tuple) -> tuple[dict[str, int], set[str]]:
    """Predicates {name: arity} and constants of a parsed formula (equality excluded)."""
    preds: dict[str, int] = {}
    consts: set[str] = set()

    def walk(n):
        op = n[0]
        if op in ("forall", "exists"):
            walk(n[2])
        elif op == "not":
            walk(n[1])
        elif op in SYM:
            walk(n[1]); walk(n[2])
        elif op in ("atom", "eq"):
            terms = n[2] if op == "atom" else n[1:]
            if op == "atom":
                key = n[1]
                if key in preds and preds[key] != len(terms):
                    key = f"{n[1]}/{len(terms)}"
                preds[key] = len(terms)
            for t in terms:
                if t[0] == "const":
                    consts.add(t[1])
    walk(ast)
    return preds, consts


def normalize_arity_overloads(ast: tuple) -> tuple:
    """Rename predicates used with two arities (P/1, P/2) so every name has one arity."""
    seen: dict[str, int] = {}
    clash: set[str] = set()

    def scan(n):
        if n[0] in ("forall", "exists"):
            scan(n[2])
        elif n[0] == "not":
            scan(n[1])
        elif n[0] in SYM:
            scan(n[1]); scan(n[2])
        elif n[0] == "atom":
            if n[1] in seen and seen[n[1]] != len(n[2]):
                clash.add(n[1])
            seen.setdefault(n[1], len(n[2]))
    scan(ast)
    if not clash:
        return ast

    def rw(n):
        if n[0] in ("forall", "exists"):
            return (n[0], n[1], rw(n[2]))
        if n[0] == "not":
            return ("not", rw(n[1]))
        if n[0] in SYM:
            return (n[0], rw(n[1]), rw(n[2]))
        if n[0] == "atom" and n[1] in clash:
            return ("atom", f"{n[1]}__{len(n[2])}", n[2])
        return n
    return rw(ast)


def complexity_ast(ast: tuple) -> dict:
    """n_quantifiers, nesting_depth (quantifier+connective nodes), n_connectives (→ ↔ ⊕ ∨ ¬)."""
    nq = 0
    ncon = 0

    def depth(n) -> int:
        nonlocal nq, ncon
        op = n[0]
        if op in ("forall", "exists"):
            nq += 1
            return 1 + depth(n[2])
        if op == "not":
            ncon += 1
            return 1 + depth(n[1])
        if op in SYM:
            if op != "and":
                ncon += 1
            return 1 + max(depth(n[1]), depth(n[2]))
        return 0
    d = depth(ast)
    return {"n_quantifiers": nq, "nesting_depth": d, "n_gold_connectives": ncon}


def has_quantifier(ast: tuple) -> bool:
    return complexity_ast(ast)["n_quantifiers"] > 0


def n_all_connectives(ast: tuple) -> int:
    c = 0

    def walk(n):
        nonlocal c
        if n[0] in ("forall", "exists"):
            walk(n[2])
        elif n[0] == "not":
            c += 1; walk(n[1])
        elif n[0] in SYM:
            c += 1; walk(n[1]); walk(n[2])
    walk(ast)
    return c


FORMULA_HINT = re.compile(r"[∀∃¬∧∨→↔⊕]|->|<->|\(")


def extract_formula(raw: str) -> str:
    """Pick the formula line out of a model response (first line with a quantifier/connective/'(')."""
    if raw is None:
        return ""
    txt = FENCE.sub("\n", raw)
    lines = [l.strip() for l in txt.splitlines() if l.strip()]
    cleaned = [clean_text(l) for l in lines]
    for l2 in cleaned:  # pass 1: a line carrying FOL operator symbols
        if re.search(r"[∀∃¬∧∨→↔⊕]|->|<->", l2) and not re.match(r"^[-*•]\s", l2):
            return l2
    for l2 in cleaned:  # pass 2: any line with a predicate call
        if re.match(r"^(here|the|this|note|explanation|sentence|let|where|to)\b", l2, re.I) or re.match(r"^[-*•]\s", l2):
            continue
        if FORMULA_HINT.search(l2):
            return l2
    return cleaned[0] if cleaned else ""
