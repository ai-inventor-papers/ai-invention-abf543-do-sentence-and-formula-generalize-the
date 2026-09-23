#!/usr/bin/env python3
"""Pre-warms the R2 MED/HELP probe cache (DEV and TEST items) while R1 runs; stage_dev/stage_test then hit the cache."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase1_r2 as r2
dev, dd = r2.prepare(r2.dev_items(), "DEV")
test, td = r2.prepare(r2.test_items(), "TEST")
_, c1 = r2.run_probe(dev, "r2_dev_probe")
_, c2 = r2.run_probe(test, "r2_test_probe")
print("warm done", len(dev), len(test), c1, c2, r2.llm.spent())
