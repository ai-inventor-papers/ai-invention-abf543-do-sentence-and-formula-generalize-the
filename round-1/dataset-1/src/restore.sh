#!/usr/bin/env bash
# Restore every path marked `delete` in .aii/manifest.yaml. Run from the workspace root.
set -euo pipefail
cd "$(dirname "$0")"
PY=.venv/bin/python
if [ ! -x "$PY" ]; then
  uv venv .venv --python=3.12
  uv pip install --python=.venv/bin/python z3-solver nltk aiohttp loguru huggingface_hub numpy scipy tenacity requests pyyaml pytest
fi
$PY - <<'PYEOF'
import os, shutil
from huggingface_hub import hf_hub_download, HfApi
files = {
    "tasksource/folio": ["folio_v2_train.jsonl", "folio_v2_validation.jsonl", "README.md"],
    "yuan-yang/MALLS-v0": ["MALLS-v0.1-test.json", "README.md"],
    "DSAVlab-UNIUD/MALLS_test_subset-CURATED": None,
    "DSAVlab-UNIUD/FOLIO_validation-curated": None,
    "opendatalab/ProverQA": ["dev/easy.json", "dev/medium.json", "dev/hard.json", "README.md"],
    "yfxiao/folio-refined": ["train.csv", "validation.csv", "README.md"],
}
for rid, fl in files.items():
    fl = fl or [s.rfilename for s in HfApi().dataset_info(rid).siblings if not s.rfilename.startswith(".")]
    for f in fl:
        p = hf_hub_download(rid, f, repo_type="dataset")
        d = os.path.join("raw/hf_downloads", rid.replace("/", "__"), f)
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copy(p, d)
for rid in ["kenken6696/folio_by_ccg2lambda", "kenken6696/MALLS_by_ccg2lambda"]:
    for s in HfApi().dataset_info(rid).siblings:
        if s.rfilename.startswith("."):
            continue
        p = hf_hub_download(rid, s.rfilename, repo_type="dataset")
        d = os.path.join("temp/datasets", rid.replace("/", "__"), s.rfilename)
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copy(p, d)
import zipfile
zipfile.ZipFile("/ai-inventor/aii_data/runs/run_qY2a2IS-WLIs/user_uploads/dpv_pilot_study.zip").extractall("raw/pilot")
import nltk
for pkg in ("wordnet", "omw-1.4"):
    nltk.download(pkg, download_dir="nltk_data", quiet=True)
PYEOF
mkdir -p raw/github temp/datasets
for f in gpt-3.5-turbo gpt-4 text-davinci-003; do
  [ -f raw/github/FOLIO_dev_$f.json ] || curl -sfL -o raw/github/FOLIO_dev_$f.json https://raw.githubusercontent.com/teacherpeterpan/Logic-LLM/main/outputs/logic_programs/FOLIO_dev_$f.json
done
[ -f raw/github/folio-validation_v0.0.jsonl ] || curl -sfL -o raw/github/folio-validation_v0.0.jsonl https://raw.githubusercontent.com/Yale-LILY/FOLIO/main/data/v0.0/folio-validation.jsonl
[ -f raw/github/folio-train_v0.0.jsonl ] || curl -sfL -o raw/github/folio-train_v0.0.jsonl https://raw.githubusercontent.com/Yale-LILY/FOLIO/main/data/v0.0/folio-train.jsonl
cd temp/datasets
for d in tasksource__folio yuan-yang__MALLS-v0 DSAVlab-UNIUD__MALLS_test_subset-CURATED DSAVlab-UNIUD__FOLIO_validation-curated opendatalab__ProverQA yfxiao__folio-refined; do ln -sfn ../../raw/hf_downloads/$d $d; done
ln -sfn ../../raw/github github_FOLIO_v0.0_and_LogicLM_outputs; ln -sfn ../../raw/pilot user_dpv_pilot
echo "restored"
