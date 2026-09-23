#!/usr/bin/env bash
# Polls the OpenRouter key budget every 15 min; when gemini is available again, runs the frozen held-out
# LLM stages in plan order (P -> Ccon -> T). All stages are cached/resumable and capped at $9.50 total.
W="$(cd "$(dirname "$0")/.." && pwd)"
cd "$W/src"
while true; do
  if "$W/.venv/bin/python" -c "import judge,sys; ok,m=judge.gemini_available(); print(m); sys.exit(0 if ok else 1)"; then
    echo "$(date -u) gemini available -> running stages"
    "$W/.venv/bin/python" stage_judge.py gemini --sets P --votes 3 --b1x3 && \
    "$W/.venv/bin/python" stage_judge.py gemini --sets Ccon --votes 3 && \
    "$W/.venv/bin/python" stage_judge.py gemini --sets T --votes 3
    echo "$(date -u) gemini stages finished (rc=$?)"; break
  fi
  echo "$(date -u) gemini unavailable; sleeping 900s"
  sleep 900
done
