"""Zero-cost Phase-1 diagnostics (no LLM calls).

T1  world-set identity per rewrite kind: canonical (iter-2 R1) vs iter-1 worlds.
D1  iter-1 judge inconsistency: the same (sentence, verbalised world) judged in different iter-1 prompts —
    how often do gemini's verdicts disagree? (instrument noise that R2's world-level cache removes)
D2  iter-1 paired-FA decomposition: rewrites whose iter-1 world set was identical to the gold's vs changed.
D3  replay: canonical worlds that coincide (same sentence, same verbalisation) with a world gemini already
    judged in iter-1 get that verdict for free → C1_replay on the covered subset of the screen.
"""
from __future__ import annotations

import collections as C
import json
import re

import numpy as np

import common
from common import read_jsonl
import worlds as WW


def _screen():
    return json.loads((common.ARMB / "data" / "screen_set.json").read_text())


def iter1_world_verdicts() -> tuple[dict, dict]:
    """(nl, world_text) → list of (item_id, verdict) from iter-1 TVJT prompts/answers; also item → worlds."""
    wc = {r["item_id"]: r for r in read_jsonl(common.ARMB / "data" / "worlds_cache.jsonl")}
    sc = [r for r in read_jsonl(common.ARMB / "results" / "screen_scores.jsonl") if r["metric"] == "TVJT"]
    V = C.defaultdict(list)
    for r in sc:
        w = wc.get(r["item_id"])
        if not w or not w.get("prompt") or not r.get("answers"):
            continue
        m = re.search(r'Sentence: "(.*)"\n\n', w["prompt"], re.S)
        nl = m.group(1) if m else None
        sits = re.findall(r"^Situation (\d+): (.*)$", w["prompt"], re.M)
        if len(sits) != len(r["answers"]):
            continue
        for (i, txt), a in zip(sits, r["answers"]):
            V[(nl, txt.strip())].append((r["item_id"], a))
    return V, wc


def world_set(worlds: list[dict], norm: bool) -> tuple:
    import canon as K
    if norm:
        return tuple(sorted(w["key_norm"] for w in worlds))
    return tuple(sorted(K.world_key(w) for w in worlds))


def _iter1_set_renamed(worlds: list[dict], pmap: dict | None, cmap: dict | None) -> tuple:
    """iter-1 world set, mapped through the (inverse) rename map so RENAME can be compared with gold."""
    import canon as K
    out = []
    for w in worlds:
        w2 = dict(w)
        if pmap:
            w2["true_atoms"] = [[pmap.get(p, p), t] for p, t in w["true_atoms"]]
        if cmap:
            w2["consts"] = {cmap.get(c, c): e for c, e in w["consts"].items()}
        out.append(K.world_key(w2))
    return tuple(sorted(out))


def run() -> dict:
    import canon as K
    import fol_core as fc
    ss = _screen()
    sent = {s["sid"]: s for s in ss["sentences"]}
    by_key, by_src = WW.load_cache()

    def rec(fol):
        k = by_src.get(fol)
        if k is None:
            k = common.sha1(K.canon(fol))
        return by_key.get(k)

    V, wc = iter1_world_verdicts()
    i1 = {r["item_id"]: r for r in read_jsonl(common.ARMB / "results" / "screen_scores.jsonl") if r["metric"] == "TVJT"}

    # ---------------- T1 + D2
    t1 = C.defaultdict(C.Counter)
    fa_rows = []
    for r in ss["rewrites"]:
        kind, sid = r["kind"], r["sid"]
        g, rw = rec(sent[sid]["gold_fol"]), rec(r["fol"])
        if g is None or rw is None:
            t1[kind]["missing"] += 1
            continue
        t1[kind]["n"] += 1
        t1[kind]["canon_identical"] += int(g["canon"] == rw["canon"]) if kind != "RENAME" else 0
        if kind == "RENAME":
            inv_p = {v: k for k, v in r["map"]["P"].items()}
            inv_c = {v: k for k, v in r["map"]["C"].items()}
            ren = fc.to_str(fc.rename(fc.parse(rw["canon"]), inv_p, inv_c))
            t1[kind]["canon_identical"] += int(ren == g["canon"])
            same_c = world_set(rw["worlds"], True) == world_set(g["worlds"], True)
        else:
            same_c = world_set(rw["worlds"], False) == world_set(g["worlds"], False)
        t1[kind]["worldset_identical_canon"] += int(same_c)
        # iter-1 world sets (seed = item_id → differ by construction unless the operator sites coincide)
        wg, wr = wc.get(f"{sid}:gold"), wc.get(r["item_id"])
        if wg and wr and wg.get("worlds") is not None and wr.get("worlds") is not None:
            if kind == "RENAME":
                s_r = _iter1_set_renamed(wr["worlds"], {v: k for k, v in r["map"]["P"].items()},
                                         {v: k for k, v in r["map"]["C"].items()})
            else:
                s_r = _iter1_set_renamed(wr["worlds"], None, None)
            s_g = _iter1_set_renamed(wg["worlds"], None, None)
            same_1 = s_r == s_g
            t1[kind]["worldset_identical_iter1"] += int(same_1)
            sg, sr = i1.get(f"{sid}:gold"), i1.get(r["item_id"])
            if sg and sr and sg["covered"] and sr["covered"]:
                fa = sr["score"] < sg["score"] - 0.2
                fa_rows.append({"kind": kind, "same_iter1": same_1, "fa": fa, "d": sr["score"] - sg["score"]})
    T1 = {k: {**v, "rate_canon": v["worldset_identical_canon"] / max(1, v["n"]),
              "rate_iter1": v["worldset_identical_iter1"] / max(1, v["n"]),
              "canon_string_rate": v["canon_identical"] / max(1, v["n"])} for k, v in t1.items()}
    allk = [k for k in T1]
    T1["ALL_nonRENAME"] = {"rate_canon": float(np.mean([T1[k]["rate_canon"] for k in allk if k != "RENAME"]))}
    gate = all(T1[k]["rate_canon"] >= 0.90 for k in ("REORDER", "DEMORGAN", "CONTRAPOSITIVE") if k in T1)

    D2 = {}
    for kind in list(t1) + ["ALL"]:
        rows = [x for x in fa_rows if kind == "ALL" or x["kind"] == kind]
        for same in (True, False):
            rr = [x for x in rows if x["same_iter1"] == same]
            D2[f"{kind}|iter1_worlds_{'identical' if same else 'changed'}"] = {
                "n": len(rr), "paired_FA": float(np.mean([x["fa"] for x in rr])) if rr else None,
                "mean_abs_delta": float(np.mean([abs(x["d"]) for x in rr])) if rr else None}
        D2[f"{kind}|all"] = {"n": len(rows), "paired_FA": float(np.mean([x["fa"] for x in rows])) if rows else None}

    # ---------------- D1 judge inconsistency on identical (sentence, world text)
    multi = {k: v for k, v in V.items() if len({i for i, _ in v}) >= 2}
    dis = [len({a for _, a in v}) > 1 for v in multi.values()]
    D1 = {"n_world_texts_judged": len(V), "n_judged_in_>=2_prompts": len(multi),
          "verdict_disagreement_rate": float(np.mean(dis)) if dis else None,
          "note": "same sentence + identical verbalised world, judged by gemini-2.5-flash T=0 inside different "
                  "iter-1 prompts (different companion worlds / positions): share with non-identical verdicts"}

    out = {"T1_worldset_identity": T1, "T1_gate_pass(>=0.90 REORDER/DEMORGAN/CONTRAPOSITIVE)": gate,
           "D1_iter1_judge_inconsistency": D1, "D2_iter1_paired_FA_decomposition": D2}
    (common.RESULTS / "canon_diagnostic.json").write_text(json.dumps(out, indent=1))
    return out


def replay_verdict(V: dict, nl: str, text: str):
    """Deterministic world-level verdict from iter-1 answers: majority, ties → the earliest item_id's."""
    v = V.get((nl, text))
    if not v:
        return None
    cnt = C.Counter(a for _, a in v)
    top = max(cnt.values())
    cands = {a for a, c in cnt.items() if c == top}
    if len(cands) == 1:
        return cands.pop()
    return sorted(v)[0][1]




def _auc(y, s) -> float | None:
    y, s = np.asarray(y), np.asarray(s, dtype=float)
    pos, neg = s[y == 1], s[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return None
    gt = (pos[:, None] > neg[None, :]).sum() + 0.5 * (pos[:, None] == neg[None, :]).sum()
    return float(gt / (len(pos) * len(neg)))


def replay_screen(min_cov: float = 0.5, n_boot: int = 1000) -> dict:
    """D3: C1_replay on screen real items = binary agreement of iter-1 gemini verdicts on the SAME
    (sentence, verbalised canonical world). Items with world coverage >= min_cov only; compared with the
    unrepaired iter-1 TVJT (C0) and B1 on the identical subset (L_bij labels, sentence-clustered bootstrap)."""
    import canon as K
    ss = _screen()
    sent = {s["sid"]: s for s in ss["sentences"]}
    by_key, by_src = WW.load_cache()
    V, _ = iter1_world_verdicts()
    sc = {(r["item_id"], r["metric"]): r for r in read_jsonl(common.ARMB / "results" / "screen_scores.jsonl")}
    rows = []
    for it in ss["real_items"]:
        if not it.get("parse_ok"):
            continue
        k = by_src.get(it["fol"]) or common.sha1(K.canon(it["fol"]))
        rec = by_key.get(k)
        if not rec or not rec["worlds"]:
            continue
        nl = sent[it["sid"]]["nl"]
        ag = []
        for w in rec["worlds"]:
            v = replay_verdict(V, nl, w.get("text"))
            if v in ("TRUE", "FALSE"):
                ag.append(1.0 if (v == "TRUE") == bool(w["F_value"]) else 0.0)
            elif v == "UNCLEAR":
                ag.append(0.5)
        cov = len(ag) / len(rec["worlds"])
        c0, b1 = sc.get((it["item_id"], "TVJT")), sc.get((it["item_id"], "B1"))
        rows.append({"item_id": it["item_id"], "sid": it["sid"], "y": 1 if it["L_bij"] == "correct" else 0,
                     "cov": cov, "C1_replay": float(np.mean(ag)) if ag else None,
                     "C0": c0["score"] if c0 else None, "B1": b1["score"] if b1 else None,
                     "tercile": sent[it["sid"]].get("tercile")})
    sub = [r for r in rows if r["cov"] >= min_cov and r["C1_replay"] is not None and r["C0"] is not None]
    out = {"n_real_parseable_with_worlds": len(rows), "n_covered(>=%.1f)" % min_cov: len(sub),
           "mean_world_coverage": float(np.mean([r["cov"] for r in rows])) if rows else None}
    if len(sub) >= 20:
        y = [r["y"] for r in sub]
        for m in ("C1_replay", "C0", "B1"):
            out[f"AUROC_{m}"] = _auc(y, [r[m] for r in sub])
        sids = sorted({r["sid"] for r in sub})
        idx = {s: [i for i, r in enumerate(sub) if r["sid"] == s] for s in sids}
        rng = np.random.default_rng(0)
        d = []
        for _ in range(n_boot):
            ii = [i for s in rng.choice(sids, len(sids)) for i in idx[s]]
            yy = [sub[i]["y"] for i in ii]
            a1, a0 = _auc(yy, [sub[i]["C1_replay"] for i in ii]), _auc(yy, [sub[i]["C0"] for i in ii])
            if a1 is not None and a0 is not None:
                d.append(a1 - a0)
        out["delta_C1replay_minus_C0"] = [float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))]
    rc = [r for r in ss["rewrites"]]
    out["note"] = ("replay verdicts come from iter-1 prompts judging OTHER world sets; a replayed verdict is the "
                   "majority over iter-1 contexts (ties → earliest item). Screen labels (L_bij) are Phase-1 labels.")
    with open(common.RESULTS / "screen_replay_scores.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    (common.RESULTS / "screen_replay.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    import sys as _s
    if "replay" in _s.argv:
        print(json.dumps(replay_screen(), indent=1))
    else:
        print(json.dumps(run(), indent=1)[:4000])
