"""Metric 3 (pilot): dangling reference rate across the K reruns per (sentence, condition).

Partitions dangling refs into:
  - missing_definition: name maps to a DPV term (LLM should have produced a definition)
  - needs_axiom: name does not map to DPV (likely a primitive or invention)
"""

import argparse, json, re, sys
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


def to_snake(pascal):
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", pascal)
    return s.lower()


def extract_body_calls(body_str):
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
    #ap.add_argument("--parser-dir", required=True)
    ap.add_argument("--dpv-terms", required=True, help="JSON list of DPV term names (PascalCase)")
    ap.add_argument("--out", default="metric3_dangling.json")
    args = ap.parse_args()

    #sys.path.insert(0, args.parser_dir)
    #import prolog_parser as parser

    dpv_pascal = set(json.loads(Path(args.dpv_terms).read_text()))
    dpv_snake = {to_snake(t) for t in dpv_pascal}

    pilot = Path(args.pilot_dir)
    per_sc = {}

    for sent_dir in sorted(pilot.iterdir()):
        if not sent_dir.is_dir(): continue
        per_sc[sent_dir.name] = {}
        for cond_dir in sorted(sent_dir.iterdir()):
            if not cond_dir.is_dir(): continue

            defined = set()
            called = defaultdict(list)
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
                    arity = len(parser.split_args(args_str))
                    defined.add((name, arity))
                    if has_body:
                        body = clause.split(":-", 1)[1].rstrip().rstrip(".").rstrip()
                        for call in extract_body_calls(body):
                            called[call].append(run_dir.name)

            dangling = {k: v for k, v in called.items() if k not in defined}
            missing_def, needs_ax = {}, {}
            for (n, a), runs in dangling.items():
                key = f"{n}/{a}"
                if n in dpv_snake:
                    missing_def[key] = runs
                else:
                    needs_ax[key] = runs

            total = len(called); nd = len(dangling)
            per_sc[sent_dir.name][cond_dir.name] = {
                "total_unique_calls": total,
                "dangling_count": nd,
                "dangling_rate": nd / total if total else 0,
                "missing_definition_count": len(missing_def),
                "needs_axiom_count": len(needs_ax),
                "missing_definition": missing_def,
                "needs_axiom": needs_ax,
            }

    by_cond = defaultdict(lambda: defaultdict(list))
    for sent, conds in per_sc.items():
        for cond, vals in conds.items():
            for k in ("dangling_rate", "dangling_count",
                      "missing_definition_count", "needs_axiom_count",
                      "total_unique_calls"):
                by_cond[cond][k].append(vals[k])

    summary = {}
    for cond, kvs in by_cond.items():
        n = len(kvs["dangling_rate"])
        summary[cond] = {
            "mean_dangling_rate": sum(kvs["dangling_rate"]) / n if n else 0,
            "total_dangling": sum(kvs["dangling_count"]),
            "total_missing_definition": sum(kvs["missing_definition_count"]),
            "total_needs_axiom": sum(kvs["needs_axiom_count"]),
            "total_calls": sum(kvs["total_unique_calls"]),
            "n_sentences": n,
        }

    Path(args.out).write_text(json.dumps(
        {"by_sentence_condition": per_sc, "by_condition": summary}, indent=2))

    print("=" * 50, "\nMetric 3 — Dangling Refs\n", "=" * 50)
    for cond, vals in summary.items():
        print(f"  {cond}: dangling_rate(mean)={vals['mean_dangling_rate']:.2%}  "
              f"missing_def={vals['total_missing_definition']}  "
              f"needs_axiom={vals['total_needs_axiom']}")
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()