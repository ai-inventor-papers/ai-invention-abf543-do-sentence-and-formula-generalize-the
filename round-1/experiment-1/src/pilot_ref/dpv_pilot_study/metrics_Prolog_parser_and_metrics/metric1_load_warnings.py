"""
Metric 1: Namespace-collision & undefined-predicate warnings.

Quantifies how badly per-definition .pl files compose by flattening them into
a single namespace and counting swipl warnings/errors.

Key insight: the files declare ':- module(...)'. Loading as-is hides cross-
file issues because module-scoped predicates won't be reported as undefined.
We strip module/use_module directives before consulting.
"""

import argparse
import csv
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# ── Regex patterns ────────────────────────────────────────────────────────────

MODULE_DIR     = re.compile(r':-\s*module\(.*?\)\.', re.DOTALL)
USE_MODULE_DIR = re.compile(r':-\s*use_module\(.*?\)\.', re.DOTALL)

WARNING_PATTERNS: dict[str, re.Pattern] = {
    "discontiguous": re.compile(r'discontiguous'),
    "redefine":      re.compile(r'No permission to redefine'),
    "undefined":     re.compile(r'Undefined procedure|Unknown procedure'),
    "any_warning":   re.compile(r'^Warning:', re.MULTILINE),
    "any_error":     re.compile(r'^ERROR:',   re.MULTILINE),
}

# ── Core functions ────────────────────────────────────────────────────────────

def make_flat_pl(files: list[Path], dest_path: Path) -> None:
    """Concatenate *files* into a single flat .pl file at *dest_path*,
    stripping module/use_module directives so everything shares one namespace.

    Prepends ':- set_prolog_flag(unknown, error).' so that calls to undefined
    predicates raise errors rather than silently failing — check/0 alone only
    traces from module exports/top-level and may miss some undefined calls.

    Note: 'discontiguous' warnings will be numerous when the same predicate is
    spread across multiple files; that's expected and is itself useful signal.
    """
    # The flag makes swipl error on any call to an undefined predicate,
    # which surfaces issues that check/0 alone might not catch.
    header = ':- set_prolog_flag(unknown, error).\n\n'
    parts: list[str] = [header]
    for pl in files:
        src = pl.read_text(encoding='utf-8', errors='replace')
        src = MODULE_DIR.sub('', src)
        src = USE_MODULE_DIR.sub('', src)
        parts.append(f'% === FILE: {pl.name} ===\n{src}\n')
    dest_path.write_text(''.join(parts), encoding='utf-8')


def run_swipl(driver_path: Path, timeout: int = 60) -> tuple[str, str]:
    """Consult *driver_path* in swipl, run check/0, and return (combined, stderr).

    check/0 forces static analysis after consult, surfacing undefined calls.
    Returns the combined stdout+stderr string and raw stderr separately.
    """
    cmd = [
        'swipl', '-q',
        '-g', f"consult('{driver_path}'), check, halt",
        '-t', 'halt(1)',
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        sys.exit(
            'ERROR: swipl not found on PATH. '
            'Install SWI-Prolog and make sure it is on your PATH.'
        )
    except subprocess.TimeoutExpired:
        sys.exit(f'ERROR: swipl timed out after {timeout}s on {driver_path}')

    combined = result.stdout + result.stderr
    return combined, result.stderr


def count_categories(text: str) -> dict[str, int]:
    """Count how many times each WARNING_PATTERNS pattern matches in *text*."""
    return {
        category: len(pattern.findall(text))
        for category, pattern in WARNING_PATTERNS.items()
    }


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description='Metric 1: count swipl warnings/errors as .pl files accumulate.'
    )
    parser.add_argument(
        '--pl-dir', required=True, type=Path,
        help='Directory containing per-definition .pl files.',
    )
    parser.add_argument(
        '--out', default='metric1_warnings.csv', type=Path,
        help='Output CSV path (default: metric1_warnings.csv).',
    )
    parser.add_argument(
        '--timeout', default=60, type=int,
        help='Per-run swipl timeout in seconds (default: 60).',
    )
    args = parser.parse_args()

    pl_dir: Path = args.pl_dir
    if not pl_dir.is_dir():
        sys.exit(f'ERROR: --pl-dir {pl_dir!r} is not a directory.')

    files = sorted(pl_dir.glob('*.pl'))
    if not files:
        sys.exit(f'ERROR: no .pl files found in {pl_dir}.')

    print(f'Found {len(files)} .pl file(s) in {pl_dir}. Running swipl incrementally…\n')

    fieldnames = ['n_files', 'last_added'] + list(WARNING_PATTERNS)
    rows: list[dict] = []
    last_stderr: str = ''

    with tempfile.TemporaryDirectory() as tmpdir:
        flat_path = Path(tmpdir) / 'flat.pl'

        for n in range(1, len(files) + 1):
            subset = files[:n]
            make_flat_pl(subset, flat_path)
            combined, stderr = run_swipl(flat_path, timeout=args.timeout)
            last_stderr = stderr

            counts = count_categories(combined)
            row = {'n_files': n, 'last_added': files[n - 1].name, **counts}
            rows.append(row)

            # Live feedback
            counts_str = '  '.join(f'{k}={v}' for k, v in counts.items())
            print(f'[{n:>{len(str(len(files)))}}/{len(files)}] '
                  f'{files[n-1].name:<40} {counts_str}')

    # ── Headline: all-files row (the top-line number for the deck) ────────────
    headline = rows[-1]
    print('\n' + '─' * 60)
    print('HEADLINE (all files merged):')
    for k in WARNING_PATTERNS:
        print(f'  {k:<16} {headline[k]}')
    print('─' * 60)
    print('(discontiguous count is expected to be high — it is real signal.)')
    print()

    # Write CSV
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f'\nCSV written to {args.out}')

    # Save full swipl stderr from the all-files run
    log_path = args.out.with_suffix('').with_name(args.out.stem + '.full_log.txt')
    log_path.write_text(last_stderr, encoding='utf-8')
    print(f'Full swipl log written to {log_path}')


if __name__ == '__main__':
    main()
