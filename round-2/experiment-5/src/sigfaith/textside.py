"""Text side: concept extraction (iter-1 text_sig.extract, spaCy en_core_web_sm) and, when the frozen text side needs
it, the iter-1 substitution-entailment probe (gemini-2.5-flash, thinking budget 1024, iter-1 prompt and chunking,
so identical requests hit the iter-1 cache for $0).

extract_many(sentences)        -> {sentence: ex}
probe_many(sentences, exs)     -> {sentence: {llm_labels, per_mod, usd, calls, parse_fail}}
labels_for(ex, side, probe)    -> concept labels for text side T0/T1a/T1b/T1c (T2 needs `strong`)
"""
from __future__ import annotations

from collections import defaultdict

import core  # noqa: F401  (sets sys.path for the legacy modules)
import text_sig  # legacy

PROBE_MODEL = "google/gemini-2.5-flash"
PROBE_REASONING = {"max_tokens": 1024}


def extract_many(sentences) -> dict:
    out = {}
    for s in sentences:
        if s in out:
            continue
        try:
            out[s] = text_sig.extract(s)
        except Exception as e:  # noqa: BLE001
            out[s] = {"error": repr(e), "concepts": [], "anchors": [], "coord": [], "marker": {}, "copies": {},
                      "relpairs": []}
    return out


def probe_jobs(sentences, exs: dict):
    jobs, meta = [], []
    for s in sentences:
        ex = exs[s]
        qs = text_sig.probe_questions(ex, with_rel=True)
        chunks = [qs] if len(qs) <= 40 else [qs[: (len(qs) + 1) // 2], qs[(len(qs) + 1) // 2:]]
        for ci, ch in enumerate(chunks):
            if not ch:
                continue
            jobs.append(dict(model=PROBE_MODEL, messages=[{"role": "user", "content": text_sig.render_prompt(ch)}],
                             purpose="probe_A1A2", reasoning=PROBE_REASONING, max_tokens=4000))
            meta.append((s, ci, len(qs)))
    return jobs, meta


def probe_many(sentences, exs: dict, est_cost_each: float = 0.004) -> dict:
    import llm
    sentences = [s for s in dict.fromkeys(sentences) if exs[s].get("copies")]
    jobs, meta = probe_jobs(sentences, exs)
    res = llm.run(jobs, concurrency=16, est_cost_each=est_cost_each)
    answers = defaultdict(dict)
    use = defaultdict(lambda: {"usd": 0.0, "calls": 0, "parse_fail": 0, "cached": 0})
    for (s, ci, nq), r in zip(meta, res):
        off = 0 if ci == 0 else (nq + 1) // 2
        if isinstance(r, Exception):
            use[s]["parse_fail"] += 1
            continue
        a = text_sig.parse_answers(r[0])
        if not a:
            use[s]["parse_fail"] += 1
        for k, v in a.items():
            answers[s][k + off] = v
        use[s]["usd"] += (r[1].get("cost") or 0.0) + (r[1].get("cost_original") or 0.0)
        use[s]["calls"] += 1
        use[s]["cached"] += bool(r[1].get("cached"))
    out = {}
    for s in sentences:
        ex = exs[s]
        qs = text_sig.probe_questions(ex, with_rel=True)
        T = text_sig.labels_from_answers(ex, qs, answers.get(s, {}))
        out[s] = {"llm_labels": T["concept_labels"], "per_mod": T["per_mod"], **use[s]}
    return out


def labels_for(ex: dict, side: str, probe: dict | None = None, strong: dict | None = None) -> dict:
    marker = {int(k): v for k, v in ex.get("marker", {}).items()}
    if side == "T0" or probe is None:
        return core.choose_labels(marker, None, None, "T0")
    return core.choose_labels(marker, probe["llm_labels"], probe["per_mod"], side, strong)
