#!/usr/bin/env bash
# Restore the removed (regenerable / redownloadable) parts of this workspace.
set -euo pipefail
cd "$(dirname "$0")"
uv venv .venv --python=3.12
uv pip install --python=.venv/bin/python z3-solver numpy scipy scikit-learn pandas nltk loguru aiohttp tenacity pytest orjson psutil spacy \
  "en_core_web_sm @ https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"
mkdir -p nltk_data/corpora
curl -sL -o nltk_data/corpora/wordnet.zip https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/packages/corpora/wordnet.zip
(cd nltk_data/corpora && unzip -q -o wordnet.zip)
.venv/bin/python -m pytest -q -c pytest.ini tests/test_dc.py
