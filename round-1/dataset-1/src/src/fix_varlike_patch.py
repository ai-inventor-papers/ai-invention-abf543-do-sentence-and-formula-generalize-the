#!/usr/bin/env python3
"""Post-hoc repair after the VARLIKE fix in fol_parse.py (constants such as yr2028 / p1080 were read as
free variables and universally closed by the v1 regex). The drawn sample is kept frozen; this script
(1) recomputes complexity features of affected held-out sentences with the stored z-params/cut-points,
(2) re-derives panel corrections in work/audit_results.json from the stored member votes with the
fixed parser. No API calls."""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from audit import validate_correction  # noqa: E402
from fol_parse import complexity_ast, parse, to_str  # noqa: E402
from prep_sources import n_conditions_text  # noqa: E402

spec = importlib.util.spec_from_file_location("oldp", ROOT / "work" / "fol_parse_v1_buggy_varlike.py")
old = importlib.util.module_from_spec(spec)
sys.modules["oldp"] = old
spec.loader.exec_module(old)

W = ROOT / "work"
prep = json.loads((W / "prep_report.json").read_text())
zp = prep["complexity"]["z_params"]
q1, q2 = prep["complexity"]["tercile_cutpoints"]
held = json.loads((W / "heldout_sentences.json").read_text())
n_fix = 0
for s in held:
    g = s["gold_fol_paper"] if s.get("gold_fol_paper") else s["gold_fol_original"]
    a, b = old.parse(g), parse(g)
    if (a.ast if a.ok else None) == (b.ast if b.ok else None):
        continue
    c = complexity_ast(b.ast)
    s["complexity_v1_buggy"] = {k: s[k] for k in ("n_quantifiers", "nesting_depth", "n_conditions", "complexity_composite", "complexity_tercile")}
    s["n_quantifiers"], s["nesting_depth"] = c["n_quantifiers"], c["nesting_depth"]
    s["n_conditions"] = n_conditions_text(s["sentence"]) + c["n_gold_connectives"]
    s["complexity_composite"] = sum((s[f] - zp[f]["mean"]) / zp[f]["sd"] for f in zp) / 4
    x = s["complexity_composite"]
    s["complexity_tercile"] = "bottom" if x < q1 else ("middle" if x < q2 else "top")
    n_fix += 1
(W / "heldout_sentences.json").write_text(json.dumps(held, ensure_ascii=False, indent=1))
print("complexity recomputed for", n_fix, "held-out sentences")

aud = json.loads((W / "audit_results.json").read_text())
changed = 0
for k, r in aud["results"].items():
    if r["gold_faithful_final"] is not False:
        continue
    item_gold = None
    if k.startswith("heldout:"):
        sid = k.split(":", 1)[1]
        item_gold = next(s["gold_fol_original"] for s in held if s["sentence_id"] == sid)
    else:
        sc = json.loads((W / "screen_sentences.json").read_text())
        item_gold = next(s["gold_fol_original"] for s in sc if f"screen:{s['sentence_id']}" == k)
    order = [m for m in ("M1", "M2", "M3") if r["votes"].get(m) and r["votes"][m]["faithful"] is False]
    new_corr, by, tried = None, None, []
    for m in order:
        ok, why = validate_correction(item_gold, r["votes"][m]["corrected_fol"])
        tried.append(f"{m}:{why}")
        if ok:
            new_corr, by = to_str(parse(r["votes"][m]["corrected_fol"]).ast), m
            break
    if new_corr != r.get("correction"):
        changed += 1
    r["correction"], r["correction_by"], r["correction_status"] = new_corr, by, ";".join(tried)
    r["correction_raw"] = r["votes"][by]["corrected_fol"] if by else None
(W / "audit_results.json").write_text(json.dumps(aud, ensure_ascii=False, indent=1))
print("corrections changed:", changed)
