#!/usr/bin/env python3
"""Polls OpenRouter key availability every 10 min (1-token gemini-2.5-flash request; ~$0) and appends the status to
results/key_status.jsonl. Used because the shared key hit its DAILY limit at 14:38 UTC on 2026-09-23."""
import json, os, time, urllib.request, urllib.error
from pathlib import Path
OUT = Path(__file__).resolve().parent / "results" / "key_status.jsonl"
body = json.dumps({"model": "google/gemini-2.5-flash", "messages": [{"role": "user", "content": "Reply 1"}],
                   "max_tokens": 5, "reasoning": {"max_tokens": 0}, "usage": {"include": True}}).encode()
while True:
    req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=body, headers={
        "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.loads(r.read())
            st = {"ts": time.time(), "utc": time.strftime("%H:%M:%S", time.gmtime()), "ok": True,
                  "cost": (d.get("usage") or {}).get("cost")}
    except urllib.error.HTTPError as e:
        st = {"ts": time.time(), "utc": time.strftime("%H:%M:%S", time.gmtime()), "ok": False,
              "status": e.code, "msg": e.read()[:200].decode(errors="ignore")}
    except Exception as e:  # noqa: BLE001
        st = {"ts": time.time(), "utc": time.strftime("%H:%M:%S", time.gmtime()), "ok": False, "msg": repr(e)[:200]}
    with OUT.open("a") as f:
        f.write(json.dumps(st) + "\n")
    time.sleep(600)
