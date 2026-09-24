"""Metric 2 (pilot): per (sentence, condition), do shared predicate names have
consistent arity/shape across the K reruns?

Now collects BOTH clause heads and body predicate calls. Heads provide actual
argument shapes; body calls contribute (name, arity) only (shape approximated
as all-variables). When a name has any body occurrence, signature comparison
becomes arity-only — that's the dimension that meaningfully varies.
"""

import argparse, json, re
from pathlib import Path
from collections import defaultdict
import prolog_parser as parser


CALL_PATTERN = re.compile(r"(?<![a-zA-Z0-9_])([a-z_]\w*)\s*\(")

BUILTINS = {
    "true", "false", "fail", "is", "write", "nl", "format",
    "atom", "number", "var", "nonvar", "ground",
    "atom_concat", "atom_chars", "member", "append", "length", "between",
    "msort", "sort", "findall", "bagof", "setof",
    "assert", "asserta", "assertz", "retract", "call", "not",
    "current_predicate", "succ", "plus",
    "consult", "module", "use_module", "discontiguous", "dynamic", "multifile",
}


def extract_body_calls(body_str):
    """Returns set of (name, arity) tuples called in body."""
    calls = set()
    for m in CALL_PATTERN.finditer(body_str):
        name = m.group(1)
        if name in BUILTINS: continue
        i = m.end(); depth = 1; commas = 0; non_empty = False
        while i < len(body_str) and depth > 0:
            c = body_str[i]
            if c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
                if depth == 0: break
            elif c == ',' and depth == 1:
                commas += 1
            elif not c.isspace():
                non_empty = True
            i += 1
        if depth == 0:
            arity = (commas + 1) if non_empty else 0
            calls.add((name, arity))
    return calls


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot-dir", required=True)
    ap.add_argument("--out", default="metric2_shape_consistency.json")
    args = ap.parse_args()

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
                    head_shape = tuple(parser.arg_kind(a) for a in args_list)
                    by_pred[name].append({
                        "run": run_dir.name,
                        "arity": len(args_list),
                        "shape": head_shape,
                        "role": "head",
                    })
                    if has_body:
                        body = clause.split(":-", 1)[1].rstrip().rstrip(".").rstrip()
                        for (call_name, call_arity) in extract_body_calls(body):
                            body_shape = tuple(["var"] * call_arity)
                            by_pred[call_name].append({
                                "run": run_dir.name,
                                "arity": call_arity,
                                "shape": body_shape,
                                "role": "body",
                            })

            shared = inconsistent = 0
            details = {}
            for name, occs in by_pred.items():
                runs = {o["run"] for o in occs}
                if len(runs) < 2: continue
                shared += 1
                has_body_occ = any(o["role"] == "body" for o in occs)
                if has_body_occ:
                    # Arity-only signature: body shapes are approximated, can't compare reliably
                    sigs = {o["arity"] for o in occs}
                    bad = len(sigs) > 1
                    sig_repr = [{"arity": a} for a in sorted(sigs)]
                else:
                    sigs = {(o["arity"], o["shape"]) for o in occs}
                    bad = len(sigs) > 1
                    sig_repr = [{"arity": a, "shape": list(s)} for (a, s) in sigs]
                if bad: inconsistent += 1
                details[name] = {
                    "runs": sorted(runs),
                    "roles": sorted({o["role"] for o in occs}),
                    "signatures": sig_repr,
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

    print("=" * 50, "\nMetric 2 — Shape Consistency (heads + body calls)\n", "=" * 50)
    for cond, vals in summary.items():
        print(f"  {cond}: inconsistent_rate(mean)={vals['mean_inconsistent_rate']:.2%}  "
              f"shared={vals['total_shared']}  inconsistent={vals['total_inconsistent']}")
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()