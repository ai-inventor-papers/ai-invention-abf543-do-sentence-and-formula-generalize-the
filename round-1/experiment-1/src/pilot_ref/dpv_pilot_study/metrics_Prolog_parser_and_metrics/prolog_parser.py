"""
Minimal Prolog parser. Not general-purpose. Assumes:
- ASCII identifiers
- % line comments, /* ... */ block comments
- Single/double-quoted strings without escapes
- Clauses end at '.' when paren/bracket depth is 0 and we're outside strings
"""

import re
from typing import Optional

LINE_COMMENT  = re.compile(r'%[^\n]*')
BLOCK_COMMENT = re.compile(r'/\*.*?\*/', re.DOTALL)


def strip_prolog_noise(src: str) -> str:
    src = BLOCK_COMMENT.sub('', src)
    src = LINE_COMMENT.sub('', src)
    return src


def split_clauses(src: str) -> list[str]:
    """Walk char-by-char, tracking paren/bracket depth and string state.
    Emit a clause every time we hit '.' at depth 0 outside a string."""
    clauses: list[str] = []
    buf: list[str] = []
    paren = 0
    bracket = 0
    in_string: Optional[str] = None  # None, "'", or '"'

    for ch in src:
        if in_string is not None:
            buf.append(ch)
            if ch == in_string:
                in_string = None
            continue

        if ch in ("'", '"'):
            in_string = ch
            buf.append(ch)
            continue

        if ch == '(':
            paren += 1
        elif ch == ')':
            paren -= 1
        elif ch == '[':
            bracket += 1
        elif ch == ']':
            bracket -= 1

        if ch == '.' and paren == 0 and bracket == 0:
            buf.append(ch)
            text = ''.join(buf).strip()
            if text:
                clauses.append(text)
            buf = []
            continue

        buf.append(ch)

    return clauses


def parse_clause(clause: str) -> Optional[tuple[str, str, bool]]:
    """Return (name, args_str, has_body) or None.
    Skips directives (clauses starting with ':-')."""
    s = clause.strip().rstrip('.')
    s = s.strip()

    if s.startswith(':-'):
        return None

    if ':-' in s:
        head = s.split(':-', 1)[0]
        has_body = True
    else:
        head = s
        has_body = False

    head = head.strip()
    m = re.match(r'^([a-z_]\w*)\s*(?:\((.*)\))?\s*$', head, re.DOTALL)
    if not m:
        return None

    return (m.group(1), m.group(2) or '', has_body)


def split_args(args_str: str) -> list[str]:
    """Top-level comma split, respecting nesting and strings.
    Returns list of individual argument strings."""
    args: list[str] = []
    buf: list[str] = []
    paren = 0
    bracket = 0
    in_string: Optional[str] = None

    for ch in args_str:
        if in_string is not None:
            buf.append(ch)
            if ch == in_string:
                in_string = None
            continue

        if ch in ("'", '"'):
            in_string = ch
            buf.append(ch)
            continue

        if ch == '(':
            paren += 1
        elif ch == ')':
            paren -= 1
        elif ch == '[':
            bracket += 1
        elif ch == ']':
            bracket -= 1

        if ch == ',' and paren == 0 and bracket == 0:
            args.append(''.join(buf).strip())
            buf = []
            continue

        buf.append(ch)

    last = ''.join(buf).strip()
    if last:
        args.append(last)

    return args


def arg_kind(arg: str) -> str:
    """Classify a single Prolog term."""
    s = arg.strip()
    if not s:
        return 'empty'
    if re.match(r'^[A-Z_]\w*$', s):
        return 'var'              # variable
    if s.startswith('[') or s.startswith('{'):
        return 'compound'        # list/dict literal
    if '(' in s:
        return 'compound'        # functor application
    if re.match(r'^-?\d', s):
        return 'literal'         # number
    if s.startswith("'") or s.startswith('"'):
        return 'literal'         # quoted atom/string
    return 'atom'                # bare lowercase atom
