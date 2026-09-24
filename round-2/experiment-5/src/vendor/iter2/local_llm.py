"""LOCAL-GPU SUBSTITUTE JUDGES (deviation D-LLM, results/deviations.json).

The run's OpenRouter key hit its shared $50 DAILY limit (limit_remaining 0 at 14:22 UTC, reset 00:00 UTC, after this
session ends; see results/deviations.json). The frozen gemini-based metrics (B1, B1plus, A1, B3*, B3c, RECALL) are fully
implemented in src/llm_stages.py, cached and resumable, but could not be called. To keep a judge baseline and the LLM
text side in the confirmation table, the SAME prompts are answered by open-weight models on the local RTX 4090:
  B1L       Qwen/Qwen3-8B (bf16, non-thinking chat template, greedy)  -- the frozen B1 prompt verbatim
  B1plusL   Qwen/Qwen3-8B in THINKING mode (greedy, <=1024 new tokens, panel items only) -- same B1 prompt, reasoning judge (the planned
            Qwen3-14B could not be loaded: its cached blobs were deleted and 4-bit loading needs the slow mmap path)
  A1L       Qwen3-8B answers the frozen Arm A substitution-entailment probe prompts (A1 text side)
  B3L       Qwen3-8B back-translation with the frozen B3 prompt -> MiniLM cosine / DeBERTa NLI (B3cosL, B3nliL)
  B3cL      Qwen3-8B clause conformance (same B3c prompt)
  RECALL_L  Qwen3-8B gold-recall probe (contamination of the local judge)
These are SUBSTITUTES, never reported as the frozen iter-1 metrics. Qwen shares a family with generator qwen-2.5-7b
(own-family check reported). Outputs are cached in work/local_llm/<tag>.jsonl keyed by sha1(model|params|prompt).
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from loguru import logger

from common import WORK, append_jsonl, sha1

MODEL_8B = "Qwen/Qwen3-8B"
MODEL_14B = "Qwen/Qwen3-14B"
CACHE = WORK / "local_llm"


class LocalLLM:
    def __init__(self, model_id: str, vram_frac: float = 0.92):
        """Weights are read SEQUENTIALLY shard by shard (safetensors.torch.load on the bytes) and copied into a model
        allocated directly on the GPU: memory-mapped loading from this workspace's network filesystem ran at ~20 s per
        tensor (2+ h for 399 tensors), a sequential read takes ~100 s for 16 GB."""
        import torch
        from huggingface_hub import snapshot_download
        from safetensors.torch import load as st_load
        from transformers import AutoConfig, AutoModelForCausalLM, AutoTokenizer
        self.torch = torch
        self.model_id = model_id
        t0 = time.time()
        torch.cuda.set_per_process_memory_fraction(vram_frac)
        path = Path(snapshot_download(model_id, allow_patterns=["*.json", "*.safetensors", "*.txt", "tokenizer*"]))
        self.tok = AutoTokenizer.from_pretrained(path)
        self.tok.padding_side = "left"
        if self.tok.pad_token is None:
            self.tok.pad_token = self.tok.eos_token
        cfg = AutoConfig.from_pretrained(path)
        torch.manual_seed(0)
        with torch.device("cuda:0"):
            self.model = AutoModelForCausalLM.from_config(cfg, dtype=torch.bfloat16)
        n_loaded = 0
        missing = set(self.model.state_dict().keys())
        for f in sorted(path.glob("*.safetensors")):
            sd = st_load(f.read_bytes())
            res = self.model.load_state_dict(sd, strict=False)
            missing -= set(sd.keys())
            n_loaded += len(sd)
            del sd
        missing = {k for k in missing if not k.endswith("inv_freq")}
        if cfg.tie_word_embeddings:
            self.model.tie_weights()
            missing.discard("lm_head.weight")
        assert not missing, f"weights not loaded: {sorted(missing)[:5]}"
        self.model.eval()
        self.tag = model_id + ":bf16"
        logger.info(f"loaded {self.tag} ({n_loaded} tensors) in {time.time() - t0:.0f}s; "
                    f"VRAM {torch.cuda.memory_allocated() / 1e9:.1f} GB")

    def _chat(self, prompt: str, thinking: bool = False) -> str:
        return self.tok.apply_chat_template([{"role": "user", "content": prompt}], tokenize=False,
                                            add_generation_prompt=True, enable_thinking=thinking)

    def generate(self, prompts: list[str], max_new_tokens: int, cache_name: str, batch_size: int = 32,
                 log_every: int = 10, thinking: bool = False) -> list[dict]:
        """Greedy decoding; results cached by sha1(model|max_new_tokens|prompt)."""
        CACHE.mkdir(parents=True, exist_ok=True)
        cp = CACHE / f"{cache_name}.jsonl"
        cache = {}
        if cp.exists():
            for line in cp.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    r = json.loads(line)
                    cache[r["k"]] = r
        keys = [sha1(f"{self.tag}|{max_new_tokens}|{'think' if thinking else ''}|{p}") for p in prompts]
        todo = sorted({k: p for k, p in zip(keys, prompts) if k not in cache}.items(), key=lambda kv: len(kv[1]))
        logger.info(f"[{cache_name}] {len(prompts)} prompts, {len(todo)} to generate (bs {batch_size})")
        t0 = time.time()
        i, nb, bs = 0, 0, batch_size
        while i < len(todo):
            chunk = todo[i:i + bs]
            texts = [self._chat(p, thinking) for _, p in chunk]
            try:
                enc = self.tok(texts, return_tensors="pt", padding=True).to("cuda:0")
                t1 = time.time()
                with self.torch.no_grad():
                    out = self.model.generate(**enc, max_new_tokens=max_new_tokens, do_sample=False, temperature=None,
                                              top_p=None, top_k=None, pad_token_id=self.tok.pad_token_id)
                gen = out[:, enc["input_ids"].shape[1]:]
                dec = self.tok.batch_decode(gen, skip_special_tokens=True)
                dt = (time.time() - t1) / len(chunk)
                rows = []
                for (k, p), d, g in zip(chunk, dec, gen):
                    if thinking and "</think>" not in d:
                        d_final = ""  # reasoning truncated: no final answer
                    else:
                        d_final = re.sub(r"<think>.*?</think>", "", d, flags=re.S).split("</think>")[-1].strip()
                    d = d_final
                    rows.append({"k": k, "text": d, "seconds": round(dt, 4),
                                 "n_out": int((g != self.tok.pad_token_id).sum())})
                append_jsonl(cp, rows)
                for r in rows:
                    cache[r["k"]] = r
                i += len(chunk)
                nb += 1
                if nb % log_every == 0:
                    logger.info(f"[{cache_name}] {i}/{len(todo)} {time.time() - t0:.0f}s")
            except self.torch.cuda.OutOfMemoryError:
                self.torch.cuda.empty_cache()
                bs = max(1, bs // 2)
                logger.warning(f"[{cache_name}] OOM -> batch {bs}")
        return [cache[k] for k in keys]

    def close(self):
        del self.model
        self.torch.cuda.empty_cache()
