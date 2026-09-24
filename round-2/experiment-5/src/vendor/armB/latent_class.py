"""Metric (iv): latent-class estimation of candidate correctness from cross-system agreement (no gold).

Per sentence, parseable candidates are clustered by solver equivalence (blind bijection; secondary:
trigram map). Latent z_s ∈ {class_1..class_K} ∪ {NONE}. One-coin model: system w's output lies in the
true class with prob p_w; two wrong outputs coincide with prob rho. P(some output correct) = pi.
Likelihood(z=c) = Π_{w∈c} p_w Π_{w∉c}(1-p_w) · rho^{#coincident wrong pairs} (1-rho)^{#other wrong pairs};
Likelihood(NONE) = Π_w (1-p_w) · (same coincidence term over all pairs). EM, 10 restarts.
Score(candidate) = posterior P(z_s = class(candidate)). Variants: Hui–Walter (pi, p_w per complexity
tercile), gold-as-4th-rater (no AUROC: circular), MAJ agreement, crowd-kit Dawid–Skene sanity row, B3sc.
"""
from __future__ import annotations

import itertools

import numpy as np
from loguru import logger


def _clusters(systems: list[str], parse_ok: dict, pairs: dict, key: str) -> dict[str, int]:
    parent = {s: s for s in systems}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for a, b in itertools.combinations(sorted(systems), 2):
        if not (parse_ok[a] and parse_ok[b]):
            continue
        p = pairs.get(f"{a}|{b}") or pairs.get(f"{b}|{a}")
        if p and p.get(key) == "equiv":
            parent[find(a)] = find(b)
    roots = {}
    out = {}
    for s in sorted(systems):
        r = find(s)
        out[s] = roots.setdefault(r, len(roots))
    return out


def build_obs(ss: dict, pairs: dict, key: str) -> list[dict]:
    sent = {s["sid"]: s for s in ss["sentences"]}
    by = {}
    for r in ss["real_items"]:
        by.setdefault(r["sid"], {})[r["system"]] = r
    obs = []
    for sid, items in by.items():
        systems = sorted(items)
        po = {s: bool(items[s]["parse_ok"]) for s in systems}
        cl = _clusters(systems, po, pairs.get(sid, {}), key)
        valid = sorted({cl[s] for s in systems if po[s]})
        obs.append({"sid": sid, "systems": systems, "cls": cl, "parse_ok": po, "valid": valid,
                    "tercile": sent[sid].get("tercile", 0)})
    return obs


def _lik(ob: dict, z, p: dict, rho: float) -> float:
    """z = class id or None."""
    L = 1.0
    wrong = []
    for s in ob["systems"]:
        if z is not None and ob["parse_ok"][s] and ob["cls"][s] == z:
            L *= p[s]
        else:
            L *= (1 - p[s])
            wrong.append(s)
    for a, b in itertools.combinations(wrong, 2):
        same = ob["parse_ok"][a] and ob["parse_ok"][b] and ob["cls"][a] == ob["cls"][b]
        L *= rho if same else (1 - rho)
    return L


def em(obs: list[dict], systems: list[str], groups: list[int] | None = None, n_iter: int = 200, tol: float = 1e-6,
       restarts: int = 10, seed: int = 0, fixed_p: dict | None = None) -> dict:
    """groups: per-observation population index (Hui–Walter: separate pi and p_w per population)."""
    rng = np.random.default_rng(seed)
    G = sorted(set(groups)) if groups is not None else [0]
    grp = groups if groups is not None else [0] * len(obs)
    best = None
    for r in range(restarts):
        if r == 0:
            p = {(g, s): 0.7 for g in G for s in systems}
            pi = {g: 0.8 for g in G}
            rho = 0.1
        else:
            p = {(g, s): float(rng.uniform(0.5, 0.95)) for g in G for s in systems}
            pi = {g: float(rng.uniform(0.5, 0.95)) for g in G}
            rho = float(rng.uniform(0.02, 0.3))
        if fixed_p:
            for g in G:
                for s, v in fixed_p.items():
                    p[(g, s)] = v
        prev = -np.inf
        for it in range(n_iter):
            ll = 0.0
            post = []
            for ob, g in zip(obs, grp):
                pw = {s: p[(g, s)] for s in ob["systems"]}
                K = len(ob["valid"])
                w = {}
                for c in ob["valid"]:
                    w[c] = pi[g] / K * _lik(ob, c, pw, rho)
                w[None] = (1 - pi[g]) * _lik(ob, None, pw, rho) if K > 0 else _lik(ob, None, pw, rho)
                Z = sum(w.values())
                ll += np.log(max(Z, 1e-300))
                post.append({k: v / Z for k, v in w.items()})
            # M-step
            num = {k: 1e-3 for k in p}
            den = {k: 2e-3 for k in p}
            pin = {g: 1e-3 for g in G}
            pid = {g: 2e-3 for g in G}
            rn, rd = 1e-3, 1e-2
            for ob, g, po in zip(obs, grp, post):
                pid[g] += 1
                pin[g] += 1 - po.get(None, 0.0)
                for s in ob["systems"]:
                    den[(g, s)] += 1
                    if ob["parse_ok"][s]:
                        num[(g, s)] += po.get(ob["cls"][s], 0.0)
                for z, pz in po.items():
                    wrong = [s for s in ob["systems"] if not (z is not None and ob["parse_ok"][s] and ob["cls"][s] == z)]
                    for a, b in itertools.combinations(wrong, 2):
                        rd += pz
                        if ob["parse_ok"][a] and ob["parse_ok"][b] and ob["cls"][a] == ob["cls"][b]:
                            rn += pz
            if not fixed_p:
                p = {k: min(0.999, max(0.001, num[k] / den[k])) for k in p}
            else:
                p = {k: (fixed_p[k[1]] if k[1] in fixed_p else min(0.999, max(0.001, num[k] / den[k]))) for k in p}
            pi = {g: min(0.999, max(0.001, pin[g] / pid[g])) for g in G}
            rho = min(0.999, max(0.001, rn / rd))
            if abs(ll - prev) < tol:
                break
            prev = ll
        if best is None or ll > best["ll"]:
            best = {"ll": float(ll), "p": dict(p), "pi": dict(pi), "rho": rho, "post": post, "iters": it + 1, "restart": r}
    return best


def run_latent_class(ss: dict, pairs: dict, alts: list[dict]) -> tuple[list[dict], dict]:
    systems = sorted({r["system"] for r in ss["real_items"]})
    rows, info = [], {}
    items = {r["item_id"]: r for r in ss["real_items"]}
    for key, metric in (("bij", "LC_onecoin"), ("str", "LC_onecoin_str")):
        obs = build_obs(ss, pairs, key)
        fit = em(obs, systems)
        info[metric] = {"loglik": fit["ll"], "p_w": {s: fit["p"][(0, s)] for s in systems}, "pi": fit["pi"][0],
                        "rho": fit["rho"], "iters": fit["iters"], "best_restart": fit["restart"],
                        "degenerate": bool(any(fit["p"][(0, s)] > 0.99 for s in systems) or fit["pi"][0] < 0.02)}
        logger.info(f"{metric}: {info[metric]}")
        for ob, po in zip(obs, fit["post"]):
            n_parse = sum(ob["parse_ok"].values())
            for s in ob["systems"]:
                iid = f"{ob['sid']}:{s}"
                cov = ob["parse_ok"][s] and n_parse >= 2
                sc = po.get(ob["cls"][s], 0.0) if ob["parse_ok"][s] else 0.0
                rows.append({"item_id": iid, "metric": metric, "score": sc, "covered": cov})
                if key == "bij":
                    size = sum(1 for s2 in ob["systems"] if ob["parse_ok"][s2] and ob["cls"][s2] == ob["cls"][s])
                    maj = (size - 1) / (n_parse - 1) if (ob["parse_ok"][s] and n_parse >= 2) else 0.0
                    rows.append({"item_id": iid, "metric": "LC_maj", "score": maj, "covered": cov})
        if key == "bij":
            # Hui–Walter variant: pi and p_w per complexity tercile
            hw = em(obs, systems, groups=[ob["tercile"] for ob in obs])
            info["LC_huiwalter"] = {"loglik": hw["ll"], "p_w": {f"{g}:{s}": v for (g, s), v in hw["p"].items()},
                                    "pi": {str(g): v for g, v in hw["pi"].items()}, "rho": hw["rho"]}
            for ob, po in zip(obs, hw["post"]):
                n_parse = sum(ob["parse_ok"].values())
                for s in ob["systems"]:
                    cov = ob["parse_ok"][s] and n_parse >= 2
                    rows.append({"item_id": f"{ob['sid']}:{s}", "metric": "LC_huiwalter",
                                 "score": po.get(ob["cls"][s], 0.0) if ob["parse_ok"][s] else 0.0, "covered": cov})
            # gold-as-4th-rater: gold joins the class of candidates bijection-equivalent to it (L_bij)
            obs_g = []
            for ob in obs:
                o2 = {**ob, "systems": ob["systems"] + ["GOLD"], "cls": dict(ob["cls"]), "parse_ok": dict(ob["parse_ok"])}
                gcls = None
                for s in ob["systems"]:
                    if items[f"{ob['sid']}:{s}"].get("L_bij") == "correct":
                        gcls = ob["cls"][s]
                if gcls is None:
                    gcls = max(ob["cls"].values()) + 1
                o2["cls"]["GOLD"] = gcls
                o2["parse_ok"]["GOLD"] = True
                o2["valid"] = sorted({o2["cls"][s] for s in o2["systems"] if o2["parse_ok"][s]})
                obs_g.append(o2)
            gg = em(obs_g, systems + ["GOLD"])
            sent = {s["sid"]: s for s in ss["sentences"]}
            cur_changed = [bool(sent[ob["sid"]].get("curated_changed")) for ob in obs if sent[ob["sid"]].get("curated_fol")]
            v1_vs_cur = [sent[ob["sid"]]["orig_vs_curated"]["label"] for ob in obs
                         if sent[ob["sid"]].get("orig_vs_curated")]
            info["LC_gold_as_rater"] = {"p_gold": gg["p"][(0, "GOLD")], "est_gold_error": 1 - gg["p"][(0, "GOLD")],
                                        "p_w": {s: gg["p"][(0, s)] for s in systems}, "pi": gg["pi"][0], "rho": gg["rho"],
                                        "observed_curated_changed_rate": (float(np.mean(cur_changed)) if cur_changed else None),
                                        "n_curated": len(cur_changed),
                                        "observed_v1_nonequiv_curated_rate": (float(np.mean([x != "equiv" for x in v1_vs_cur]))
                                                                              if v1_vs_cur else None),
                                        "note": "no AUROC for this variant (gold is the label source: circular)"}
            logger.info(f"gold-as-rater: {info['LC_gold_as_rater']}")
    # crowd-kit Dawid–Skene sanity row: task = candidate item, worker = each OTHER system, label = agrees (1/0)
    try:
        import pandas as pd
        from crowdkit.aggregation import DawidSkene
        obs = build_obs(ss, pairs, "bij")
        recs = []
        for ob in obs:
            for s in ob["systems"]:
                for s2 in ob["systems"]:
                    if s2 == s:
                        continue
                    ag = int(ob["parse_ok"][s] and ob["parse_ok"][s2] and ob["cls"][s] == ob["cls"][s2])
                    recs.append({"task": f"{ob['sid']}:{s}", "worker": s2, "label": ag})
        df = pd.DataFrame(recs)
        ds = DawidSkene(n_iter=100, tol=1e-5).fit(df)
        pr = ds.probas_
        col = 1 if 1 in pr.columns else pr.columns[-1]
        for ob in obs:
            n_parse = sum(ob["parse_ok"].values())
            for s in ob["systems"]:
                iid = f"{ob['sid']}:{s}"
                sc = float(pr.loc[iid, col]) if iid in pr.index else 0.5
                rows.append({"item_id": iid, "metric": "LC_ds_binary", "score": sc,
                             "covered": ob["parse_ok"][s] and n_parse >= 2})
        info["LC_ds_binary"] = {"priors": {str(k): float(v) for k, v in ds.priors_.items()}}
    except Exception as e:  # noqa: BLE001 - sanity row only
        logger.error(f"crowd-kit DawidSkene failed: {e!r}")
        info["LC_ds_binary"] = {"error": repr(e)}
    # B3sc zero-cost self-consistency against the same system's other translations of the sentence
    per = {}
    for a in alts:
        per.setdefault(a["primary_item_id"], []).append(a.get("equiv_to_primary"))
    for iid, r in items.items():
        eq = [x for x in per.get(iid, []) if x is not None]
        if not r["parse_ok"] or not eq:
            rows.append({"item_id": iid, "metric": "B3sc", "score": 0.5, "covered": False})
        else:
            rows.append({"item_id": iid, "metric": "B3sc", "score": float(np.mean([x == "equiv" for x in eq])),
                         "covered": True, "n_alts": len(eq)})
    return rows, info
