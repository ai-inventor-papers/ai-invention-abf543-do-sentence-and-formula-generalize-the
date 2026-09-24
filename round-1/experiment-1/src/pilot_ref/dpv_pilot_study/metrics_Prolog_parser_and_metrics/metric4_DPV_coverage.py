"""Metric 4: DPV coverage across the pilot.

Per (sentence, condition, run) computes three coverage rates:
  - ref:  fraction of referring expressions with non-null dpv tag
  - prop: fraction of property predicates matching DPV term set
  - fol:  fraction of distinct FOL predicates matching DPV term set

Rolls up by (sentence, condition) and by condition.
"""

import argparse, json, re
from pathlib import Path
from collections import defaultdict


def predicate_names_from_props(props):
    names = []
    for p in props:
        m = re.match(r"([A-Za-z_]\w*)\s*\(", p)
        if m:
            names.append(m.group(1))
    return names


def predicate_names_from_fol(fol):
    return set(re.findall(r"([A-Z]\w*)\s*\(", fol))


def compute_run_coverage(run_dir, dpv_terms):
    out = {"ref": None, "prop": None, "fol": None, "missing": []}

    refs_path = run_dir / "01_referring_expressions.json"
    if refs_path.exists():
        refs = json.loads(refs_path.read_text())
        if isinstance(refs, list):
            n = len(refs)
            n_grounded = sum(1 for r in refs if r.get("dpv"))
            out["ref"] = (n_grounded / n) if n else 0.0
        else:
            out["ref"] = 0.0
    else:
        out["missing"].append("01_referring_expressions.json")

    props_path = run_dir / "03_properties.json"
    if props_path.exists():
        props = json.loads(props_path.read_text())
        names = predicate_names_from_props(props)
        out["prop"] = sum(1 for n in names if n in dpv_terms) / len(names) if names else 0.0
    else:
        out["missing"].append("03_properties.json")

    fol_path = run_dir / "04_fol.json"
    if fol_path.exists():
        fol = json.loads(fol_path.read_text())["fol"]
        preds = predicate_names_from_fol(fol)
        out["fol"] = len(preds & dpv_terms) / len(preds) if preds else 0.0
    else:
        out["missing"].append("04_fol.json")

    return out


def mean_or_none(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot-dir", required=True)
    ap.add_argument("--dpv-terms", required=True)
    ap.add_argument("--out", default="metric4_dpv_coverage.json")
    args = ap.parse_args()

    pilot = Path(args.pilot_dir)
    dpv_terms = set(json.loads(Path(args.dpv_terms).read_text()))

    per_run = []
    by_sc = defaultdict(lambda: defaultdict(list))

    for sent_dir in sorted(pilot.iterdir()):
        if not sent_dir.is_dir(): continue
        for cond_dir in sorted(sent_dir.iterdir()):
            if not cond_dir.is_dir(): continue
            for run_dir in sorted(cond_dir.iterdir()):
                if not run_dir.is_dir() or not run_dir.name.startswith("run_"):
                    continue
                cov = compute_run_coverage(run_dir, dpv_terms)
                per_run.append({"sentence": sent_dir.name, "condition": cond_dir.name,
                                "run": run_dir.name, **cov})
                by_sc[sent_dir.name][cond_dir.name].append(cov)

    summary_sc = {}
    for sent, conds in by_sc.items():
        summary_sc[sent] = {}
        for cond, runs in conds.items():
            summary_sc[sent][cond] = {
                "ref":  mean_or_none([r["ref"] for r in runs]),
                "prop": mean_or_none([r["prop"] for r in runs]),
                "fol":  mean_or_none([r["fol"] for r in runs]),
                "n_runs": len(runs),
            }

    by_condition = defaultdict(lambda: {"ref": [], "prop": [], "fol": []})
    for sent, conds in summary_sc.items():
        for cond, vals in conds.items():
            for k in ("ref", "prop", "fol"):
                if vals[k] is not None:
                    by_condition[cond][k].append(vals[k])
    summary_cond = {
        cond: {k: (sum(v) / len(v) if v else None) for k, v in lists.items()}
        for cond, lists in by_condition.items()
    }

    out_obj = {"per_run": per_run, "by_sentence_condition": summary_sc, "by_condition": summary_cond}
    Path(args.out).write_text(json.dumps(out_obj, indent=2))

    print("=" * 50, "\nMetric 4 — DPV Coverage\n", "=" * 50)
    for cond, vals in summary_cond.items():
        line = f"  {cond}:"
        for k, v in vals.items():
            line += f"  {k}={v:.2%}" if v is not None else f"  {k}=n/a"
        print(line)
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()