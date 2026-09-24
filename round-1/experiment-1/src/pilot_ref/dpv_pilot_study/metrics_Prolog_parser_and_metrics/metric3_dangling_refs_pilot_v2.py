"""Metric 3 (pilot): dangling-reference analysis with cross-sentence pooling.

For each condition, pools all definitions and calls across all sentences AND
all runs. Then 3-way partitions every called predicate:
  - resolved_in_pilot: defined somewhere in the pilot's outputs
  - missing_definition: undefined locally, name maps to a DPV term
                        (could be imported from DPV externally)
  - needs_axiom: undefined locally AND not in DPV — invented or external
                 primitive that needs explicit grounding

The needs_axiom count is the actionable headline: it quantifies how many
ungrounded inventions the condition produced.
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


def harvest(pl_path):
    """Return (defined_set, called_dict) for one .pl file.

    defined_set: set of (name, arity)
    called_dict: (name, arity) -> set of source-file paths
    """
    defined = set()
    called = defaultdict(set)
    src = parser.strip_prolog_noise(pl_path.read_text())
    for clause in parser.split_clauses(src):
        parsed = parser.parse_clause(clause)
        if not parsed: continue
        name, args_str, has_body = parsed
        arity = len(parser.split_args(args_str))
        defined.add((name, arity))
        if has_body:
            body = clause.split(":-", 1)[1].rstrip().rstrip(".").rstrip()
            for call in extract_body_calls(body):
                called[call].add(str(pl_path))
    return defined, called


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot-dir", required=True)
    ap.add_argument("--dpv-terms", required=True,
                    help="JSON list of DPV term names (PascalCase)")
    ap.add_argument("--out", default="metric3_dangling.json")
    args = ap.parse_args()

    dpv_pascal = set(json.loads(Path(args.dpv_terms).read_text()))
    dpv_snake = {to_snake(t) for t in dpv_pascal}

    pilot = Path(args.pilot_dir)

    # Pool across all sentences + runs within each condition
    by_cond_pool = {}  # cond -> {"defined": set, "called": dict}

    for sent_dir in sorted(pilot.iterdir()):
        if not sent_dir.is_dir(): continue
        for cond_dir in sorted(sent_dir.iterdir()):
            if not cond_dir.is_dir(): continue
            cond = cond_dir.name
            if cond not in by_cond_pool:
                by_cond_pool[cond] = {"defined": set(), "called": defaultdict(set)}
            for run_dir in sorted(cond_dir.iterdir()):
                if not run_dir.is_dir() or not run_dir.name.startswith("run_"):
                    continue
                pl = run_dir / "05_prolog.pl"
                if not pl.exists(): continue
                d, c = harvest(pl)
                by_cond_pool[cond]["defined"] |= d
                for k, v in c.items():
                    by_cond_pool[cond]["called"][k] |= v

    by_condition = {}
    for cond, pool in by_cond_pool.items():
        defined = pool["defined"]
        called = pool["called"]

        resolved, missing_def, needs_ax = {}, {}, {}

        for (name, arity), files in called.items():
            key = f"{name}/{arity}"
            if (name, arity) in defined:
                resolved[key] = sorted(files)
            elif name in dpv_snake:
                missing_def[key] = sorted(files)
            else:
                needs_ax[key] = sorted(files)

        total = len(called)
        n_res, n_miss, n_axiom = len(resolved), len(missing_def), len(needs_ax)

        by_condition[cond] = {
            "total_unique_calls": total,
            "defined_count": len(defined),
            "resolved_in_pilot_count": n_res,
            "resolved_in_pilot_rate": n_res / total if total else 0,
            "missing_definition_count": n_miss,
            "missing_definition_rate": n_miss / total if total else 0,
            "needs_axiom_count": n_axiom,
            "needs_axiom_rate": n_axiom / total if total else 0,
            "resolved_in_pilot": resolved,
            "missing_definition": missing_def,
            "needs_axiom": needs_ax,
        }
        needs_ax_unary = {k: v for k, v in needs_ax.items() if k.endswith("/1")}
        needs_ax_nary  = {k: v for k, v in needs_ax.items() if not k.endswith("/1")}

        by_condition[cond]["needs_axiom_unary_count"]   = len(needs_ax_unary)
        by_condition[cond]["needs_axiom_nary_count"]    = len(needs_ax_nary)
        by_condition[cond]["needs_axiom_unary"]         = needs_ax_unary
        by_condition[cond]["needs_axiom_nary"]          = needs_ax_nary

    Path(args.out).write_text(json.dumps({"by_condition": by_condition}, indent=2))

    print("=" * 50, "\nMetric 3 — Dangling Refs (cross-sentence pool, 3-way)\n", "=" * 50)
    for cond, vals in by_condition.items():
        print(f"  {cond}:")
        print(f"    total_unique_calls = {vals['total_unique_calls']}")
        print(f"    resolved_in_pilot  = {vals['resolved_in_pilot_count']} "
              f"({vals['resolved_in_pilot_rate']:.2%})")
        print(f"    missing_definition = {vals['missing_definition_count']} "
              f"({vals['missing_definition_rate']:.2%})")
        print(f"    needs_axiom        = {vals['needs_axiom_count']} "
              f"({vals['needs_axiom_rate']:.2%})  ← invented / ungrounded")
        print(f"    needs_axiom (unary, class-like)    = {vals['needs_axiom_unary_count']}")
        print(f"    needs_axiom (n-ary, relation-like) = {vals['needs_axiom_nary_count']}")
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()