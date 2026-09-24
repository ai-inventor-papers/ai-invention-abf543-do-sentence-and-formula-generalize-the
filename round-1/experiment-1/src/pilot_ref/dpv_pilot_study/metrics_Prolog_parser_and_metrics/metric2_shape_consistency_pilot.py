"""Metric 2 (pilot): for each (sentence, condition), do shared predicate names
have consistent arity / arg-shape across the K reruns?
"""

import argparse, json, sys
from pathlib import Path
from collections import defaultdict
import prolog_parser as parser


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot-dir", required=True)
    #ap.add_argument("--parser-dir", required=True)
    ap.add_argument("--out", default="metric2_shape_consistency.json")
    args = ap.parse_args()

    #sys.path.insert(0, args.parser_dir)
    #import prolog_parser as parser

    pilot = Path(args.pilot_dir)
    per_sc = {}

    for sent_dir in sorted(pilot.iterdir()):
        if not sent_dir.is_dir(): continue
        per_sc[sent_dir.name] = {}
        for cond_dir in sorted(sent_dir.iterdir()):
            if not cond_dir.is_dir(): continue

            by_pred = defaultdict(list)
            for run_dir in sorted(cond_dir.iterdir()):
                if not run_dir.is_dir() or not run_dir.name.startswith("run_"):
                    continue
                pl = run_dir / "05_prolog.pl"
                if not pl.exists(): continue
                src = parser.strip_prolog_noise(pl.read_text())
                for clause in parser.split_clauses(src):
                    parsed = parser.parse_clause(clause)
                    if not parsed: continue
                    name, args_str, has_body = parsed
                    args_list = parser.split_args(args_str)
                    shape = tuple(parser.arg_kind(a) for a in args_list)
                    by_pred[name].append({
                        "run": run_dir.name, "arity": len(args_list),
                        "shape": shape, "has_body": has_body})

            shared = inconsistent = 0
            details = {}
            for name, occs in by_pred.items():
                runs = {o["run"] for o in occs}
                if len(runs) < 2: continue
                shared += 1
                sigs = {(o["arity"], o["shape"]) for o in occs}
                bad = len(sigs) > 1
                if bad: inconsistent += 1
                details[name] = {
                    "runs": sorted(runs),
                    "signatures": [{"arity": a, "shape": list(s)} for (a, s) in sigs],
                    "inconsistent": bad,
                }

            per_sc[sent_dir.name][cond_dir.name] = {
                "shared_count": shared,
                "inconsistent_count": inconsistent,
                "inconsistent_rate": inconsistent / shared if shared else 0,
                "details": details,
            }

    by_cond = defaultdict(lambda: {"rates": [], "shared": [], "incon": []})
    for sent, conds in per_sc.items():
        for cond, vals in conds.items():
            by_cond[cond]["rates"].append(vals["inconsistent_rate"])
            by_cond[cond]["shared"].append(vals["shared_count"])
            by_cond[cond]["incon"].append(vals["inconsistent_count"])

    summary = {}
    for cond, lists in by_cond.items():
        n = len(lists["rates"])
        summary[cond] = {
            "mean_inconsistent_rate": sum(lists["rates"]) / n if n else 0,
            "total_shared": sum(lists["shared"]),
            "total_inconsistent": sum(lists["incon"]),
            "n_sentences": n,
        }

    Path(args.out).write_text(json.dumps(
        {"by_sentence_condition": per_sc, "by_condition": summary}, indent=2))

    print("=" * 50, "\nMetric 2 — Shape Consistency\n", "=" * 50)
    for cond, vals in summary.items():
        print(f"  {cond}: inconsistent_rate(mean)={vals['mean_inconsistent_rate']:.2%}  "
              f"shared={vals['total_shared']}  inconsistent={vals['total_inconsistent']}")
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()