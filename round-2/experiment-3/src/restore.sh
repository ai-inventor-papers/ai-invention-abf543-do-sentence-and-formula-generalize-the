#!/usr/bin/env bash
# Recreate the removed heavy paths (.venv/, .nltk_data/). Run from the repository root.
set -euo pipefail
uv venv .venv --python 3.12
# exact versions of the original .venv (also pinned in pyproject.toml); torch 2.11.0+cu128 comes from the PyTorch cu128 index
uv pip install --python .venv/bin/python -r requirements.lock.txt \
  --extra-index-url https://download.pytorch.org/whl/cu128 --index-strategy unsafe-best-match
mkdir -p .nltk_data/corpora
for p in wordnet omw-1.4; do
  curl -sSL -o .nltk_data/corpora/$p.zip https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/packages/corpora/$p.zip
  (cd .nltk_data/corpora && unzip -q -o $p.zip)
done
.venv/bin/python -m pytest -q -c pytest.ini tests/test_dc.py
