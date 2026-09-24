"""
Metric 3: Dangling-reference rate, partitioned.

Measures the % of predicate calls in rule bodies that have no defining clause
anywhere in the directory, split into two buckets:

  missing_definition — dangling AND the predicate name is in the Article 3
      reference term list.  The LLM was supposed to produce a defining clause
      for this concept and didn't.

  needs_axiom — dangling AND the name is NOT in the reference list.  The
      predicate is a primitive at this ontology level and needs external
      grounding from an upper ontology (e.g. LKIF or DPV).

Implementation notes
────────────────────
* BUILTINS will need tuning. Run once, scan the dangling list, fold in obvious
  standard predicates that show up as false positives. Don't try to be
  exhaustive up front.
* Counts are over unique (name, arity) pairs, not raw occurrences. For
  occurrence-level rates keep a counter when populating `called`.
* A predicate defined as a fact (foo(bar).) and called with the same arity in
  a body (baz :- foo(X)) resolves correctly — `defined` records by name/arity
  regardless of whether the head used atoms or variables.
* Partition edge-case: a predicate defined in one file whose filename stem is
  not in the reference list will never be dangling, so the partition never sees
  it. That's correct — the partition only applies to actually-dangling calls.
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from prolog_parser import (
    strip_prolog_noise,
    split_clauses,
    parse_clause,
    split_args,
)

# ── Builtins ──────────────────────────────────────────────────────────────────
# Standard-library / builtin predicates that should not be flagged as dangling.
# Extend this set as false positives appear in your corpus.

BUILTINS: frozenset[str] = frozenset({
    # Control
    'true', 'false', 'fail', 'halt',
    # I/O
    'write', 'writeln', 'read', 'nl', 'format', 'print',
    # Type checks
    'atom', 'number', 'integer', 'float', 'is_list',
    'var', 'nonvar', 'ground', 'compound', 'callable', 'atomic',
    # Arithmetic
    'is', 'succ', 'plus', 'between',
    # Atom / string
    'atom_concat', 'atom_chars', 'atom_codes', 'atom_length',
    'number_codes', 'number_chars', 'char_code', 'sub_atom',
    'upcase_atom', 'downcase_atom', 'concat_atom', 'split_string',
    # List
    'member', 'memberchk', 'append', 'length', 'nth0', 'nth1',
    'last', 'reverse', 'flatten', 'permutation',
    'msort', 'sort', 'predsort', 'include', 'exclude', 'maplist',
    'foldl', 'aggregate_all', 'numlist',
    # Aggregation
    'findall', 'bagof', 'setof', 'aggregate',
    # Meta / assert
    'assert', 'asserta', 'assertz', 'retract', 'retractall', 'abolish',
    'call', 'once', 'ignore', 'not', '\\+',
    'forall', 'catch', 'throw',
    # Reflection
    'functor', 'arg', 'copy_term', 'numbervars',
    'current_predicate', 'predicate_property',
    # Module / load
    'consult', 'module', 'use_module', 'ensure_loaded',
    # Declarations (appear as calls after ':-')
    'discontiguous', 'dynamic', 'multifile', 'module_transparent',
    'meta_predicate', 'use_foreign_library',
    # Comparison
    'compare',
    # String (SWI-Prolog 7+)
    'string_concat', 'string_codes', 'string_chars', 'string_length',
    'string_lower', 'string_upper', 'string_to_atom',
    # Pairs / assoc
    'pairs_keys', 'pairs_values', 'pairs_keys_values',
    'list_to_assoc', 'assoc_to_list', 'get_assoc', 'put_assoc',
    # Misc SWI
    'char_type', 'read_term', 'term_to_atom',
    'nb_getval', 'nb_setval', 'b_getval', 'b_setval',
    'set_prolog_flag', 'current_prolog_flag',
    'writef', 'with_output_to',
})

# Matches a lowercase identifier immediately followed by '('.
# The negative lookbehind prevents matching the tail of a longer identifier
# (e.g. won't fire on the 'foo' inside 'barfoo(').
CALL_PATTERN = re.compile(r'(?<![a-zA-Z0-9_])([a-z_]\w*)\s*\(')


# ── Helper functions ──────────────────────────────────────────────────────────

def normalize(name: str) -> str:
    """Canonical form for matching filenames against predicate names.

    Handles the traversal/v1 filename conventions, e.g.:
      'AI_system'                               -> 'ai_system'
      'real-time_remote_biometric_...'          -> 'real_time_remote_biometric_...'
      'High-RiskAISystem'                       -> 'high_risk_ai_system'  (camelCase)

    If predicate names in the corpus use camelCase, extend this function to
    insert underscores at lowercase→uppercase boundaries before lowercasing.
    """
    # Insert underscore at camelCase boundaries before lowercasing
    name = re.sub(r'(?<=[a-z0-9])(?=[A-Z])', '_', name)
    return name.lower().replace('-', '_').replace(' ', '_')


def load_reference_terms(path: Path) -> frozenset[str]:
    """Return the set of normalized term names that SHOULD be defined here.

    If *path* is a directory: derive terms from its .pl filenames (stems).
    If *path* is a file: read one term per line.

    All names are normalized via normalize() so they match predicate names.
    """
    if path.is_dir():
        return frozenset(
            normalize(pl.stem)
            for pl in path.glob('*.pl')
        )
    elif path.is_file():
        return frozenset(
            normalize(line.strip())
            for line in path.read_text(encoding='utf-8').splitlines()
            if line.strip()
        )
    else:
        sys.exit(f'ERROR: --term-list {path!r} is neither a file nor a directory.')


def extract_body_calls(body_str: str) -> set[tuple[str, int]]:
    """Return the set of (name, arity) pairs called in a rule body.

    For each CALL_PATTERN match, walks forward from '(' to find the matching
    ')' and counts top-level commas to infer arity. Skips BUILTINS.
    """
    calls: set[tuple[str, int]] = set()

    for match in CALL_PATTERN.finditer(body_str):
        name = match.group(1)
        if name in BUILTINS:
            continue

        i = match.end()   # position just after the opening '('
        depth = 1
        commas = 0
        non_empty = False

        while i < len(body_str) and depth > 0:
            c = body_str[i]
            if c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
                if depth == 0:
                    break
            elif c == ',' and depth == 1:
                commas += 1
            elif not c.isspace():
                non_empty = True
            i += 1

        if depth == 0:   # found the matching closing paren
            arity = (commas + 1) if non_empty else 0
            calls.add((name, arity))

    return calls


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            'Metric 3: dangling-reference rate, partitioned into '
            'missing-definition (LLM failure) vs needs-axiom (external primitive).'
        )
    )
    parser.add_argument(
        '--pl-dir', required=True, type=Path,
        help='Directory containing per-definition .pl files.',
    )
    parser.add_argument(
        '--term-list', default=None, type=Path,
        help=(
            'Directory (uses .pl filenames as terms) or file (one term per line) '
            'naming the concepts that SHOULD be defined here. '
            'Defaults to --pl-dir, which is correct when each term has its own '
            'eponymous file (e.g. traversal/v1/). For paragraph-indexed layouts '
            '(e.g. building_on_top_of_last_paragraph_v3/) pass an explicit '
            'article3_terms.txt instead.'
        ),
    )
    parser.add_argument(
        '--out', default='metric3_dangling.json', type=Path,
        help='Output JSON path (default: metric3_dangling.json).',
    )
    args = parser.parse_args()

    pl_dir: Path = args.pl_dir
    if not pl_dir.is_dir():
        sys.exit(f'ERROR: --pl-dir {pl_dir!r} is not a directory.')

    files = sorted(pl_dir.glob('*.pl'))
    if not files:
        sys.exit(f'ERROR: no .pl files found in {pl_dir}.')

    term_list_path: Path = args.term_list if args.term_list is not None else pl_dir

    # ── Collect defined predicates and body calls ─────────────────────────────

    defined: set[tuple[str, int]] = set()
    # (name, arity) -> list of files in which it is called (may repeat)
    called: dict[tuple[str, int], list[str]] = defaultdict(list)

    for pl in files:
        src = strip_prolog_noise(pl.read_text(encoding='utf-8', errors='replace'))
        for clause in split_clauses(src):
            parsed = parse_clause(clause)
            if not parsed:
                continue
            name, args_str, has_body = parsed
            arity = len(split_args(args_str))
            defined.add((name, arity))

            if has_body:
                body = clause.split(':-', 1)[1].rstrip().rstrip('.').rstrip()
                for call in extract_body_calls(body):
                    called[call].append(pl.name)

    # ── Identify dangling references ──────────────────────────────────────────

    dangling: dict[tuple[str, int], list[str]] = {
        (name, arity): file_list
        for (name, arity), file_list in called.items()
        if (name, arity) not in defined
    }

    # ── Partition: missing-definition vs needs-axiom ──────────────────────────

    reference_terms = load_reference_terms(term_list_path)

    missing_definition: dict[str, list[str]] = {}
    needs_axiom:        dict[str, list[str]] = {}

    for (name, arity), file_list in dangling.items():
        key = f'{name}/{arity}'
        if normalize(name) in reference_terms:
            missing_definition[key] = file_list
        else:
            needs_axiom[key] = file_list

    # ── Summary numbers ───────────────────────────────────────────────────────

    total      = len(called)
    n_dangling = len(dangling)
    n_missing  = len(missing_definition)
    n_needs_ax = len(needs_axiom)

    output = {
        'total_unique_calls':       total,
        'dangling_count':           n_dangling,
        'dangling_rate':            round(n_dangling / total if total else 0.0, 4),
        'missing_definition_count': n_missing,
        'missing_definition_rate':  round(n_missing  / n_dangling if n_dangling else 0.0, 4),
        'needs_axiom_count':        n_needs_ax,
        'needs_axiom_rate':         round(n_needs_ax  / n_dangling if n_dangling else 0.0, 4),
        'missing_definition':       missing_definition,
        'needs_axiom':              needs_axiom,
    }

    # ── Write JSON ────────────────────────────────────────────────────────────

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2), encoding='utf-8')

    # ── Headline ──────────────────────────────────────────────────────────────

    dang_pct    = output['dangling_rate']            * 100
    missing_pct = output['missing_definition_rate']  * 100
    axiom_pct   = output['needs_axiom_rate']         * 100

    print('─' * 60)
    print('METRIC 3 — Dangling-reference rate (partitioned)')
    print(f'  unique calls:   {total}')
    print(f'  dangling:       {n_dangling}  ({dang_pct:.1f}%)')
    print(f'    missing-definition (in Article 3):     {n_missing}  ({missing_pct:.1f}% of dangling)')
    print(f'    needs-axiom        (external concept): {n_needs_ax}  ({axiom_pct:.1f}% of dangling)')
    print(f'  wrote {args.out}')
    print('─' * 60)

    # ── Top offenders per bucket (useful for deck / triage) ───────────────────

    def _top(bucket: dict[str, list[str]], label: str, n: int = 8) -> None:
        if not bucket:
            return
        ranked = sorted(bucket.items(), key=lambda kv: (-len(set(kv[1])), kv[0]))
        print(f'\nTop {label}:')
        for pred, file_list in ranked[:n]:
            unique_files = sorted(set(file_list))
            print(f'  {pred:<40} {", ".join(unique_files)}')

    _top(missing_definition, 'missing-definition predicates')
    _top(needs_axiom,        'needs-axiom predicates')


if __name__ == '__main__':
    main()
