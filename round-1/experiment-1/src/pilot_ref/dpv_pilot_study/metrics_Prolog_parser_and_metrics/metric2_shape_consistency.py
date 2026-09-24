"""
Metric 2: Shared-predicate shape consistency.

For each predicate name that appears in ≥2 files, checks whether its arity and
argument-shape signature is consistent across files.

Example finding: provider_type/2 with shape (atom, atom) in provider.pl vs
deployer_type/2 with shape (var, atom) in deployer.pl — same naming pattern
but class-level vs instance-level semantics.

Note: "shared" means literal name match only. Semantic similarity
(e.g. provides_ai_system vs is_provider_of) is out of scope — that needs
embeddings and is too noisy for the pilot.
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from prolog_parser import (
    strip_prolog_noise,
    split_clauses,
    parse_clause,
    split_args,
    arg_kind,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Metric 2: check arity/shape consistency for predicates shared across ≥2 files.'
    )
    parser.add_argument(
        '--pl-dir', required=True, type=Path,
        help='Directory containing per-definition .pl files.',
    )
    parser.add_argument(
        '--out', default='metric2_shape_consistency.json', type=Path,
        help='Output JSON path (default: metric2_shape_consistency.json).',
    )
    args = parser.parse_args()

    pl_dir: Path = args.pl_dir
    if not pl_dir.is_dir():
        sys.exit(f'ERROR: --pl-dir {pl_dir!r} is not a directory.')

    files = sorted(pl_dir.glob('*.pl'))
    if not files:
        sys.exit(f'ERROR: no .pl files found in {pl_dir}.')

    # ── Collect all clause occurrences ───────────────────────────────────────

    # name -> list of occurrence dicts
    by_predicate: dict[str, list[dict]] = defaultdict(list)

    for pl in files:
        src = strip_prolog_noise(pl.read_text(encoding='utf-8', errors='replace'))
        for clause in split_clauses(src):
            parsed = parse_clause(clause)
            if not parsed:
                continue
            name, args_str, has_body = parsed
            args_list = split_args(args_str)
            shape = tuple(arg_kind(a) for a in args_list)
            by_predicate[name].append({
                'file':     pl.name,
                'arity':    len(args_list),
                'shape':    shape,       # kept as tuple internally; serialised as list
                'has_body': has_body,
            })

    # ── Aggregate: predicates shared across ≥2 files ─────────────────────────

    summary: dict[str, dict] = {}
    shared_count     = 0
    inconsistent_count = 0

    for name, occurrences in by_predicate.items():
        files_set = {o['file'] for o in occurrences}
        if len(files_set) < 2:
            continue

        shared_count += 1
        signatures = {(o['arity'], o['shape']) for o in occurrences}
        is_inconsistent = len(signatures) > 1
        if is_inconsistent:
            inconsistent_count += 1

        summary[name] = {
            'files': sorted(files_set),
            # Tuples → lists for JSON serialisation
            'signatures': [
                {'arity': arity, 'shape': list(shape)}
                for arity, shape in sorted(signatures)
            ],
            'inconsistent': is_inconsistent,
        }

    inconsistent_rate = inconsistent_count / shared_count if shared_count else 0.0

    output = {
        'shared_predicate_count': shared_count,
        'inconsistent_count':     inconsistent_count,
        'inconsistent_rate':      round(inconsistent_rate, 4),
        'details':                summary,
    }

    # ── Write JSON ────────────────────────────────────────────────────────────

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2), encoding='utf-8')

    # ── Headline numbers ──────────────────────────────────────────────────────

    print('─' * 60)
    print('METRIC 2 — Shared-predicate shape consistency')
    print(f'  Shared predicates (≥2 files):  {shared_count}')
    print(f'  Inconsistent shape/arity:       {inconsistent_count}')
    print(f'  Inconsistency rate:             {inconsistent_rate:.1%}')
    print(f'  Output written to:              {args.out}')
    print('─' * 60)

    # ── Deck slide: top 5 inconsistent predicates ─────────────────────────────
    # Sort by number of distinct signatures desc, then name for stability.
    inconsistent = [
        (name, data)
        for name, data in summary.items()
        if data['inconsistent']
    ]
    inconsistent.sort(key=lambda nd: (-len(nd[1]['signatures']), nd[0]))
    top5 = inconsistent[:5]

    if top5:
        print('\nTop inconsistent predicates (for deck slide):')
        print(f'  {"Predicate":<35} {"Files":<6} {"Signatures"}')
        print(f'  {"─"*35} {"─"*6} {"─"*40}')
        for name, data in top5:
            sigs = '  |  '.join(
                f'arity={s["arity"]} shape=({", ".join(s["shape"])})'
                for s in data['signatures']
            )
            print(f'  {name:<35} {len(data["files"]):<6} {sigs}')
    else:
        print('\nNo inconsistent predicates found.')


if __name__ == '__main__':
    main()
