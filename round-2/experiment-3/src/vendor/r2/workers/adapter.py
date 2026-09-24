#!/usr/bin/env python3
"""INPUT ADAPTER (dataset parser ONLY in this interpreter).

The iter-1 metric parsers accept only the FOLIO unicode dialect, while held-out candidates come in ASCII /
LaTeX / snake_case variants. For every distinct candidate string we run the dataset's tolerant parser
(vendor/ds/src/fol_parse.parse) and print it back with its printer (to_str) -> `canon`. Metrics are scored on
canon when available, else on raw. This is an input normalisation, not metric logic.

Also computes the dataset-parser-side structural facts used by B7 (arity overloads inside one formula,
predicate-name set for the Jaccard component).

in : work/strings.jsonl  {h, s}
out: work/canon.jsonl    {h, raw, canon, ds_ok, ds_error, ds_notes, arity_self_ok, preds, n_preds, arity}
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor" / "ds" / "src"))
import fol_parse as dsp  # noqa: E402  (dataset parser; never co-imported with Arm A's fol_parse)


def atoms(n, acc):
    op = n[0]
    if op in ("forall", "exists"):
        atoms(n[2], acc)
    elif op == "not":
        atoms(n[1], acc)
    elif op in ("and", "or", "imp", "iff", "xor"):
        atoms(n[1], acc)
        atoms(n[2], acc)
    elif op == "atom":
        acc.setdefault(n[1], set()).add(len(n[2]))
    return acc


def main():
    inp, outp = ROOT / "work" / "strings.jsonl", ROOT / "work" / "canon.jsonl"
    done = set()
    if outp.exists():
        for line in outp.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line)["h"])
    todo = [json.loads(x) for x in inp.read_text(encoding="utf-8").splitlines() if x.strip()]
    todo = [t for t in todo if t["h"] not in done]
    t0 = time.time()
    with open(outp, "a", encoding="utf-8") as f:
        for t in todo:
            s = t["s"] or ""
            rec = {"h": t["h"], "raw": s, "canon": None, "ds_ok": False, "ds_error": "", "ds_notes": [],
                   "arity_self_ok": None, "preds": [], "n_preds": 0, "arity": {}}
            try:
                pr = dsp.parse(s)
                rec["ds_ok"] = bool(pr.ok)
                rec["ds_error"] = pr.error
                rec["ds_notes"] = list(pr.notes)
                if pr.ok:
                    rec["canon"] = dsp.to_str(pr.ast)
                    ar = atoms(pr.ast, {})
                    rec["arity_self_ok"] = all(len(v) == 1 for v in ar.values())
                    rec["preds"] = sorted(ar)
                    rec["n_preds"] = len(ar)
                    rec["arity"] = {k: sorted(v) for k, v in ar.items()}
                    # round-trip check (T0a): printed canon must re-parse to the same AST
                    pr2 = dsp.parse(rec["canon"])
                    rec["roundtrip_same_ast"] = bool(pr2.ok and pr2.ast == pr.ast)
            except (RecursionError, ValueError) as e:
                rec["ds_error"] = f"{type(e).__name__}: {e}"[:200]
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(json.dumps({"n_new": len(todo), "seconds": round(time.time() - t0, 2)}))


if __name__ == "__main__":
    main()
