#!/usr/bin/env python3
"""M6 (part 1, $0): verbatim round-2 record (+ sha256 of each source) and the arXiv:2606.02837 wrong-gold numbers
per version (grep evidence saved under work/web/)."""
import hashlib, json, re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dc.common import EXP3, EXP4, EXP5, RES, WORK, jdump


def load(p):
    p = Path(p)
    if not p.exists():
        return {"missing": str(p)}, None
    return json.loads(p.read_text()), hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    rec, shas = {}, {}
    for key, p in [("exp4_verdict", EXP4 / "results" / "verdict.json"), ("exp5_verdict", EXP5 / "results" / "verdict.json"),
                   ("screen_rerank", EXP3 / "results" / "screen_rerank.json"),
                   ("confirmation_table", EXP3 / "results" / "confirmation_table.json")]:
        rec[key], shas[key] = load(p)
    A, shas["exp3_analysis"] = load(EXP3 / "results" / "analysis.json")
    for k in ["complexity", "contamination", "system_level", "circularity", "judge_reliability", "stacking"]:
        rec["exp3_" + k] = A.get(k, "missing") if isinstance(A, dict) else "missing"
    rec["_sha256"] = shas
    rec["_note"] = "verbatim copies; nothing recomputed here (the within-sentence recomputation is results/m6_within_sentence.json)"
    jdump(rec, RES / "round2_record.json")
    # wrong-gold citation
    ev = {}
    for f in sorted((WORK / "web").glob("*.txt")):
        t = f.read_text()
        ev[f.name] = {"n_chars": len(t),
                      "incorrect_quotes": re.findall(r"approximately\s+[\d.\\%]+\s+and\s+[\d.\\%]+\s+of entries", t),
                      "ambiguous": re.findall(r"ambiguous NL sentences \(([^)]*)\)", t),
                      "review": re.findall(r"accuracy after reviewing fewer than (\d+)% of\s+instances, compared to over (\d+)%", t.replace("\n", " "))}
    cit = {"paper": "Brunello et al., arXiv:2606.02837 (NL-to-FOL dataset audit + relabelling framework)",
           "versions": {
               "v1": {"url": "https://arxiv.org/abs/2606.02837v1", "section": "abstract",
                      "incorrect_FOL": {"FOLIO_validation": "39%", "MALLS_subset": "36%"},
                      "ambiguous_NL": {"FOLIO": "16.4%", "MALLS": "48%"}, "incorrect_NLI_FOLIO": "8.4%",
                      "guided_review": "90% dataset accuracy after reviewing fewer than 24% of instances (unguided: over 70%)"},
               "v2_current": {"url": "https://arxiv.org/abs/2606.02837v2 (= https://arxiv.org/abs/2606.02837)",
                              "section": "abstract; PDF Introduction and Section 2 / Table 1",
                              "incorrect_FOL": {"FOLIO_validation": "42.5%", "MALLS_subset": "42%"},
                              "ambiguous_NL": {"FOLIO": "17.8%", "MALLS": "51%"}, "incorrect_NLI_FOLIO": "8.4%",
                              "guided_review": "90% dataset accuracy after reviewing fewer than 20% of instances (unguided: over 76%); ~20% of FOLIO validation and ~5% of the MALLS test subset"}},
           "reading": "The handbook's 39%/36% and '<24%' quote v1; the current version (v2) reports 42.5%/42% and '<20%'. Cite v2 and name the version.",
           "this_run_audit_for_comparison": "dataset L0 panel: MALLS 45.6%, FOLIO-v2-train 62%, screen FOLIO-v1-val 44%, ProverQA 17.5%",
           "grep_evidence": ev}
    jdump(cit, RES / "wrong_gold_citation.json")
    print(json.dumps({k: (v if isinstance(v, str) else "ok") for k, v in cit["versions"].items()}))


if __name__ == "__main__":
    main()
