"""Metric 1 (pilot): swipl warning counts when loading cross-sentence files together.

For each (condition, run), flattens the per-sentence .pl files into one and
consults with check/0. Cross-sentence loading is what surfaces real composition
issues: deployer.pl calls `provider`, and provider.pl from the same run should
resolve it if naming aligns.
"""

import argparse, json, re, subprocess, tempfile
from pathlib import Path
from collections import defaultdict


MODULE_DIR = re.compile(r":-\s*module\([^)]*\)\.", re.DOTALL)
USE_MODULE_DIR = re.compile(r":-\s*use_module\([^)]*\)\.", re.DOTALL)

PATTERNS = {
    "discontiguous": re.compile(r"discontiguous", re.IGNORECASE),
    "undefined":     re.compile(r"[Uu]ndefined|[Uu]nknown procedure"),
    "redefine":      re.compile(r"No permission to redefine"),
    "singleton":     re.compile(r"singleton", re.IGNORECASE),
    "any_warning":   re.compile(r"^Warning:", re.MULTILINE),
    # Headline metric: warnings that aren't just singleton-variable noise.
    "any_warning_nonsingleton": re.compile(r"^Warning:(?!.*singleton).*$",
                                           re.MULTILINE | re.IGNORECASE),
    "any_error":     re.compile(r"^ERROR:", re.MULTILINE),
}


def flatten_files(files, dest_path):
    parts = []
    for pl in files:
        src = pl.read_text()
        src = MODULE_DIR.sub("", src)
        src = USE_MODULE_DIR.sub("", src)
        parts.append(f"% === FILE: {pl} ===\n{src}\n")
    dest_path.write_text("\n\n".join(parts))


def run_swipl(flat_path, timeout=30):
    try:
        r = subprocess.run(
            ["swipl", "-q", "-g", f"consult('{flat_path}'), check, halt", "-t", "halt(1)"],
            capture_output=True, text=True, timeout=timeout)
        return (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return ""


def count_categories(text):
    return {k: len(p.findall(text)) for k, p in PATTERNS.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot-dir", required=True)
    ap.add_argument("--out", default="metric1_load_warnings.json")
    args = ap.parse_args()

    pilot = Path(args.pilot_dir)

    # Discover conditions and run IDs from the tree
    conditions, run_ids = set(), set()
    for sent_dir in pilot.iterdir():
        if not sent_dir.is_dir(): continue
        for cond_dir in sent_dir.iterdir():
            if not cond_dir.is_dir(): continue
            conditions.add(cond_dir.name)
            for run_dir in cond_dir.iterdir():
                if run_dir.is_dir() and run_dir.name.startswith("run_"):
                    run_ids.add(run_dir.name)
    conditions = sorted(conditions)
    run_ids = sorted(run_ids)

    per_cr = {}  # condition -> run -> counts
    for cond in conditions:
        per_cr[cond] = {}
        for run_id in run_ids:
            pls = [
                sent_dir / cond / run_id / "05_prolog.pl"
                for sent_dir in sorted(pilot.iterdir())
                if sent_dir.is_dir()
                and (sent_dir / cond / run_id / "05_prolog.pl").exists()
            ]
            if not pls:
                per_cr[cond][run_id] = {"n_files": 0, "skipped": "no .pl files"}
                continue
            with tempfile.NamedTemporaryFile(mode='w', suffix='.pl', delete=False) as f:
                flat = Path(f.name)
            flatten_files(pls, flat)
            output = run_swipl(flat)
            per_cr[cond][run_id] = {"n_files": len(pls), **count_categories(output)}
            flat.unlink(missing_ok=True)

    summary = {}
    for cond, runs in per_cr.items():
        valid = [v for v in runs.values() if "skipped" not in v]
        n = len(valid)
        agg = defaultdict(list)
        for v in valid:
            for k, val in v.items():
                if k == "n_files": continue
                agg[k].append(val)
        summary[cond] = {"n_runs": n}
        for k, vals in agg.items():
            summary[cond][f"mean_{k}"] = sum(vals) / len(vals) if vals else 0
            summary[cond][f"sum_{k}"] = sum(vals)

    Path(args.out).write_text(json.dumps(
        {"by_condition_run": per_cr, "by_condition": summary}, indent=2))

    print("=" * 50, "\nMetric 1 — Cross-Sentence Load Warnings\n", "=" * 50)
    for cond, vals in summary.items():
        print(f"  {cond}: "
              f"warnings_nonsingleton(mean)={vals.get('mean_any_warning_nonsingleton', 0):.1f}  "
              f"errors(mean)={vals.get('mean_any_error', 0):.1f}  "
              f"undefined(mean)={vals.get('mean_undefined', 0):.1f}  "
              f"discontiguous(mean)={vals.get('mean_discontiguous', 0):.1f}")
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()