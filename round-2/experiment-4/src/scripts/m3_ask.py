#!/usr/bin/env python3
"""Re-ask the M3 arbiter from the SAVED prompts (work/m3_dose.jsonl, work/m3_real.jsonl) -> work/m3_arbiter_answers.json.
With --poll: first poll the key (1 cheap call) every 10 min for up to 60 min (fallback 8); log to work/key_status.jsonl."""
import asyncio, json, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
from loguru import logger
from dc.common import WORK, rj
from m3_boundary import ask
from dc.llm import Client, FLASH

logger.remove(); logger.add(sys.stdout, level="INFO", format="{time:HH:mm:ss}|{level:<7}|{message}")


async def probe():
    async with Client("key_probe", 0.01) as c:
        r = await c.chat({"model": FLASH, "messages": [{"role": "user", "content": f"Reply OK. {time.time()}"}],
                          "temperature": 0.0, "max_tokens": 3, "reasoning": {"max_tokens": 0, "exclude": True}}, retries=1)
    return r


def main():
    if "--poll" in sys.argv:
        for i in range(7):
            r = asyncio.run(probe())
            ok = r.get("text") is not None
            with open(WORK / "key_status.jsonl", "a") as f:
                f.write(json.dumps({"ts": time.time(), "ok": ok, "error": (r.get("error") or "")[:200]}) + "\n")
            logger.info(f"key probe {i}: ok={ok} {(r.get('error') or '')[:120]}")
            if ok:
                break
            if i < 6:
                time.sleep(600)
        else:
            logger.error("key still down after 60 min: arbiter NOT RUN")
            return
        if not ok:
            return
    D = rj(WORK / "m3_dose.jsonl"); R = rj(WORK / "m3_real.jsonl")
    A1 = ask([a for d in D for a in d["arb"] if a.get("prompt")], "M3b_arb", 0.6)
    A2 = ask([r for r in R if r.get("prompt")], "M3c_arb", 0.4)
    json.dump({"constructed": A1["answers"], "real": A2["answers"], "info": [A1["info"], A2["info"]]},
              open(WORK / "m3_arbiter_answers.json", "w"), ensure_ascii=False)
    logger.info("arbiter answers written")


if __name__ == "__main__":
    main()
