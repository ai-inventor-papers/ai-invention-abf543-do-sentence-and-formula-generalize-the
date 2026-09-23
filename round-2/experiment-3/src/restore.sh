#!/usr/bin/env bash
# Restore the files that .aii/manifest.yaml marks as delete (environment + NLTK data).
set -euo pipefail
cd "$(dirname "$0")"
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -r pyproject.toml
mkdir -p .nltk_data/corpora
for p in wordnet omw-1.4; do
  curl -sSL -o .nltk_data/corpora/$p.zip https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/packages/corpora/$p.zip
  (cd .nltk_data/corpora && unzip -q -o $p.zip)
done
# model weights are fetched on first use into $HF_HOME: sentence-transformers/all-MiniLM-L6-v2,
# MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli, Qwen/Qwen3-8B
echo "restored"
