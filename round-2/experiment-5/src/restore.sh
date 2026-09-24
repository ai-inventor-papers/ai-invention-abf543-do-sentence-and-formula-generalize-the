#!/usr/bin/env bash
# Restores the files marked `delete` in .aii/manifest.yaml.
set -euo pipefail
cd "$(dirname "$0")"
[ -d .venv ] || { uv venv .venv --python=3.12 && uv pip install --python .venv/bin/python z3-solver numpy scipy scikit-learn pandas aiohttp loguru tenacity beautifulsoup4 lxml requests torch transformers sentence-transformers safetensors huggingface_hub psutil pyyaml sentencepiece protobuf tiktoken; }
[ -d raw/pilot/dpv_pilot_study ] || unzip -q -o /ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/user_uploads/dpv_pilot_study.zip -d raw/pilot/
if [ ! -d raw/sara/sara ]; then mkdir -p raw/sara && curl -sL -o raw/sara/sara.tar.gz https://nlp.jhu.edu/law/sara/sara.tar.gz && tar xzf raw/sara/sara.tar.gz -C raw/sara && find raw/sara -name '._*' -delete; fi
