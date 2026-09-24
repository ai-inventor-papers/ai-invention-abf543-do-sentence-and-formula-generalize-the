"""Metric 1 (pilot): swipl warning counts when loading the K reruns together.

Per (sentence, condition), flattens the K run .pl files into one and consults
with check/0. Counts warning categories. Rolls up by condition.
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
    per_sc = {}

    for sent_dir in sorted(pilot.iterdir()):
        if not sent_dir.is_dir(): continue
        per_sc[sent_dir.name] = {}
        for cond_dir in sorted(sent_dir.iterdir()):
            if not cond_dir.is_dir(): continue
            pls = sorted([
                run_dir / "05_prolog.pl"
                for run_dir in cond_dir.iterdir()
                if run_dir.is_dir() and run_dir.name.startswith("run_")
                   and (run_dir / "05_prolog.pl").exists()
            ])
            if not pls:
                per_sc[sent_dir.name][cond_dir.name] = {"n_files": 0, "skipped": "no .pl files"}
                continue
            with tempfile.NamedTemporaryFile(mode='w', suffix='.pl', delete=False) as f:
                flat = Path(f.name)
            flatten_files(pls, flat)
            output = run_swipl(flat)
            per_sc[sent_dir.name][cond_dir.name] = {"n_files": len(pls), **count_categories(output)}
            flat.unlink(missing_ok=True)

    by_cond = defaultdict(lambda: defaultdict(list))
    for sent, conds in per_sc.items():
        for cond, vals in conds.items():
            if "skipped" in vals: continue
            for k, v in vals.items():
                if k == "n_files": continue
                by_cond[cond][k].append(v)

    summary = {}
    for cond, kvs in by_cond.items():
        summary[cond] = {"n_sentences": len(next(iter(kvs.values()))) if kvs else 0}
        for k, vals in kvs.items():
            summary[cond][f"mean_{k}"] = sum(vals) / len(vals) if vals else 0
            summary[cond][f"sum_{k}"] = sum(vals)

    out_obj = {"by_sentence_condition": per_sc, "by_condition": summary}
    Path(args.out).write_text(json.dumps(out_obj, indent=2))

    print("=" * 50, "\nMetric 1 — Load Warnings\n", "=" * 50)
    for cond, vals in summary.items():
        print(f"  {cond}: warnings(mean)={vals.get('mean_any_warning', 0):.1f}  "
              f"errors(mean)={vals.get('mean_any_error', 0):.1f}  "
              f"discontiguous(mean)={vals.get('mean_discontiguous', 0):.1f}")
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()