#!/usr/bin/env python3
"""LOCAL-GPU SUBSTITUTES for the frozen gemini baselines that could not be called (deviation D-KEY: the run's
shared OpenRouter key reached its $7.00 limit at 04:22 UTC, after generation, B1, L0 and L3 had run).

  B3L  : Qwen/Qwen3-8B (bf16, non-thinking, greedy) back-translation with the FROZEN B3 prompt, first line kept ->
         MiniLM cosine / DeBERTa-v3-large NLI (vendor/r2/src/gpu_b3.score_b3)  -> B3cosL, B3nliL on the panel items
  TJ_L : Qwen3-8B answering the FROZEN TJ typed-judge prompt (panel items)     -> TJ_L p_faithful + primary type
These are SUBSTITUTES (round 2 used the same model and loader for its 'L' metrics); never reported as the frozen
gemini metrics. Qwen shares a family with generator qwen-2.5-7b (own-family AUROC is reported).
The model is read from a local snapshot of Qwen/Qwen3-8B (read-only; revision recorded in the output).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import time
from pathlib import Path

from loguru import logger

from common import ROOT, WORK, read_jsonl, setup_logging, sha1, write_jsonl

SNAP = Path("/ai-inventor/aii_data/runs/run_u75jRHUss0zo/.shared_cache/hf/hub/models--Qwen--Qwen3-8B/snapshots/"
            "b968826d9c46dd6066d109eabc6255188de91218")
CACHE = WORK / "local_llm"


class LocalLLM:
    """vendor/r2/src/local_llm.LocalLLM with the weights path given explicitly (sequential shard reads)."""

    def __init__(self, path: Path, vram_frac: float = 0.85):
        import torch
        from safetensors.torch import load as st_load
        from transformers import AutoConfig, AutoModelForCausalLM, AutoTokenizer
        self.torch = torch
        t0 = time.time()
        torch.cuda.set_per_process_memory_fraction(vram_frac)
        self.tok = AutoTokenizer.from_pretrained(path)
        self.tok.padding_side = "left"
        if self.tok.pad_token is None:
            self.tok.pad_token = self.tok.eos_token
        cfg = AutoConfig.from_pretrained(path)
        torch.manual_seed(0)
        with torch.device("cuda:0"):
            self.model = AutoModelForCausalLM.from_config(cfg, dtype=torch.bfloat16)
        missing = set(self.model.state_dict().keys())
        for f in sorted(path.glob("*.safetensors")):
            sd = st_load(f.read_bytes())
            self.model.load_state_dict(sd, strict=False)
            missing -= set(sd.keys())
            del sd
        missing = {k for k in missing if not k.endswith("inv_freq")}
        if cfg.tie_word_embeddings:
            self.model.tie_weights()
            missing.discard("lm_head.weight")
        assert not missing, f"weights not loaded: {sorted(missing)[:5]}"
        self.model.eval()
        self.tag = "Qwen/Qwen3-8B@" + path.name[:12] + ":bf16"
        logger.info(f"loaded {self.tag} in {time.time() - t0:.0f}s; VRAM {torch.cuda.memory_allocated() / 1e9:.1f} GB")

    def generate(self, prompts: list[str], max_new_tokens: int, cache_name: str, batch_size: int = 32) -> list[dict]:
        CACHE.mkdir(parents=True, exist_ok=True)
        cp = CACHE / f"{cache_name}.jsonl"
        cache = {r["k"]: r for r in read_jsonl(cp)}
        keys = [sha1(f"{self.tag}|{max_new_tokens}||{p}") for p in prompts]
        todo = sorted({k: p for k, p in zip(keys, prompts) if k not in cache}.items(), key=lambda kv: len(kv[1]))
        logger.info(f"[{cache_name}] {len(prompts)} prompts, {len(todo)} to generate")
        i, bs = 0, batch_size
        while i < len(todo):
            chunk = todo[i:i + bs]
            texts = [self.tok.apply_chat_template([{"role": "user", "content": p}], tokenize=False,
                                                  add_generation_prompt=True, enable_thinking=False) for _, p in chunk]
            try:
                enc = self.tok(texts, return_tensors="pt", padding=True).to("cuda:0")
                t1 = time.time()
                with self.torch.no_grad():
                    out = self.model.generate(**enc, max_new_tokens=max_new_tokens, do_sample=False, temperature=None,
                                              top_p=None, top_k=None, pad_token_id=self.tok.pad_token_id)
                dec = self.tok.batch_decode(out[:, enc["input_ids"].shape[1]:], skip_special_tokens=True)
                dt = (time.time() - t1) / len(chunk)
                with open(cp, "a", encoding="utf-8") as f:
                    for (k, p), d in zip(chunk, dec):
                        d = re.sub(r"<think>.*?</think>", "", d, flags=re.S).strip()
                        r = {"k": k, "text": d, "seconds": round(dt, 4)}
                        cache[k] = r
                        f.write(json.dumps(r, ensure_ascii=False) + "\n")
                i += len(chunk)
            except self.torch.cuda.OutOfMemoryError:
                self.torch.cuda.empty_cache()
                bs = max(1, bs // 2)
                logger.warning(f"OOM -> batch {bs}")
        return [cache[k] for k in keys]

    def close(self):
        del self.model
        self.torch.cuda.empty_cache()


@logger.catch(reraise=True)
def main() -> None:
    import s09_llm_baselines as s9
    rows = s9.l3_items()
    llm = LocalLLM(SNAP)
    back = llm.generate([s9.B3_PROMPT.format(f=r["cand"] or "") for r in rows], 200, "b3L_back")
    tj = llm.generate([s9.TJ_PROMPT.format(s=r["sentence"], f=r["cand"] or "", tax=s9.TAX) for r in rows], 200, "tjL")
    llm.close()
    out_tj = [{"item_id": r["item_id"], **s9.parse_tj(x["text"]), "seconds": x["seconds"], "usd": 0.0,
               "model": llm.tag} for r, x in zip(rows, tj)]
    write_jsonl(WORK / "tjL_fresh.jsonl", out_tj)
    items = [{"key": r["item_id"], "sentence": r["sentence"],
              "back": (x["text"].strip().split("\n")[0].strip() or None) if x["text"] else None} for r, x in zip(rows, back)]
    spec = importlib.util.spec_from_file_location("gpu_b3", ROOT / "vendor" / "r2" / "src" / "gpu_b3.py")
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)
    sc = g.score_b3(items)
    by = {}
    for s in sc:
        by.setdefault(s["key"], {})[s["metric"]] = (s["score"], s["covered"])
    out = [{"item_id": it["key"], "back": it["back"], "B3cosL": by[it["key"]]["B3cos"][0],
            "B3nliL": by[it["key"]]["B3nli"][0], "covered": by[it["key"]]["B3nli"][1], "model": llm.tag}
           for it in items]
    write_jsonl(WORK / "b3L_fresh.jsonl", out)
    logger.info(f"TJ_L parsed {sum(o['parse_ok'] for o in out_tj)}/{len(out_tj)}; B3L covered {sum(o['covered'] for o in out)}")


if __name__ == "__main__":
    setup_logging("s09b_local")
    sys.exit(main())
