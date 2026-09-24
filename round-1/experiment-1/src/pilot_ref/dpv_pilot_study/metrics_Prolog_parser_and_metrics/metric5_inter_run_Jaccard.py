"""Metric 5: Inter-run predicate stability (Jaccard).

Per (sentence, condition), pairwise Jaccard over the K runs' (name, arity) sets.
"""

import argparse, json, sys, itertools
from pathlib import Path
from collections import defaultdict
import prolog_parser as parser

def predicate_set(pl_text, parser):
    src = parser.strip_prolog_noise(pl_text)
    defs = set()
    for clause in parser.split_clauses(src):
        parsed = parser.parse_clause(clause)
        if parsed:
            name, args, _ = parsed
            defs.add((name, len(parser.split_args(args))))
    return defs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot-dir", required=True)
    #ap.add_argument("--parser-dir", required=True, help="Dir containing prolog_parser.py")
    ap.add_argument("--out", default="metric5_jaccard.json")
    args = ap.parse_args()

    #sys.path.insert(0, args.parser_dir)
    #import prolog_parser as parser

    pilot = Path(args.pilot_dir)
    results = {}

    for sent_dir in sorted(pilot.iterdir()):
        if not sent_dir.is_dir(): continue
        results[sent_dir.name] = {}
        for cond_dir in sorted(sent_dir.iterdir()):
            if not cond_dir.is_dir(): continue
            sets, run_names = [], []
            for run_dir in sorted(cond_dir.iterdir()):
                if not run_dir.is_dir() or not run_dir.name.startswith("run_"):
                    continue
                pl = run_dir / "05_prolog.pl"
                if not pl.exists(): continue
                sets.append(predicate_set(pl.read_text(), parser))
                run_names.append(run_dir.name)

            if len(sets) < 2:
                results[sent_dir.name][cond_dir.name] = {
                    "mean_jaccard": None, "pairs": [], "n_runs": len(sets),
                    "note": "Fewer than 2 runs available"}
                continue

            pairs, scores = [], []
            for (i, a), (j, b) in itertools.combinations(enumerate(sets), 2):
                union = a | b
                score = (len(a & b) / len(union)) if union else 1.0
                pairs.append({"a": run_names[i], "b": run_names[j], "jaccard": score,
                              "|a|": len(a), "|b|": len(b), "|a∩b|": len(a & b)})
                scores.append(score)
            results[sent_dir.name][cond_dir.name] = {
                "mean_jaccard": sum(scores) / len(scores),
                "pairs": pairs, "n_runs": len(sets)}

    by_cond = defaultdict(list)
    for sent, conds in results.items():
        for cond, vals in conds.items():
            if vals["mean_jaccard"] is not None:
                by_cond[cond].append(vals["mean_jaccard"])
    summary = {c: (sum(v) / len(v) if v else None) for c, v in by_cond.items()}

    Path(args.out).write_text(json.dumps(
        {"by_sentence_condition": results, "by_condition": summary}, indent=2))

    print("=" * 50, "\nMetric 5 — Inter-Run Jaccard\n", "=" * 50)
    for cond, mean in summary.items():
        print(f"  {cond}: {mean:.3f}" if mean is not None else f"  {cond}: n/a")
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()