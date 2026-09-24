#!/usr/bin/env python3
"""Frozen B1 judge (exp3 prompt + request, gemini-2.5-flash, T=0, reasoning off) on the M1 probes, arms in priority
order syn > conf > tok. Retry once with max_tokens 48 on an unparseable answer. Output work/m1_b1.jsonl."""
import asyncio, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from loguru import logger
from dc.common import LOGS, WORK, rj, wj
from dc.llm import b1_body, first_number, run_bodies, ledger_total

logger.remove(); logger.add(sys.stdout, level="INFO", format="{time:HH:mm:ss}|{level:<7}|{message}")
logger.add(str(LOGS / "m1_b1.log"), level="DEBUG")
CAPS = {"syn": 0.35, "conf": 0.35, "tok": 0.35}


@logger.catch(reraise=True)
def main():
    probes = [p for p in rj(WORK / "m1_probes.jsonl") if p.get("fol")]
    out = []
    for arm in ("syn", "conf", "tok"):
        P = [p for p in probes if p["arm"] == arm]
        bodies = [b1_body(p["sentence"], p["fol"]) for p in P]
        tags = [f"{p['sid']}:{arm}:{p['kind']}:{p['op']}" for p in P]
        res, info = asyncio.run(run_bodies(f"M1_B1_{arm}", CAPS[arm], bodies, tags))
        logger.info(f"{arm}: {json.dumps(info)}")
        retry = [i for i, r in enumerate(res) if r and r.get("text") is not None and first_number(r["text"]) is None]
        if retry:
            rr, _ = asyncio.run(run_bodies(f"M1_B1_{arm}", CAPS[arm], [b1_body(P[i]["sentence"], P[i]["fol"], 48) for i in retry],
                                           [tags[i] + ":retry" for i in retry], n_pilot=0))
            for i, r in zip(retry, rr):
                if r and first_number(r.get("text")) is not None:
                    res[i] = r
        for p, r in zip(P, res):
            v = first_number((r or {}).get("text"))
            out.append({"sid": p["sid"], "arm": arm, "kind": p["kind"], "op": p["op"], "B1": 0.5 if v is None else v,
                        "B1_parsed": v is not None, "usd": (r or {}).get("cost_usd", 0.0), "error": (r or {}).get("error")})
    wj(WORK / "m1_b1.jsonl", out)
    logger.info(f"B1 rows {len(out)}; parse rate {sum(o['B1_parsed'] for o in out)/max(1,len(out)):.3f}; ledger ${ledger_total():.4f}")


if __name__ == "__main__":
    main()
