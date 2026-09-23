"""B3 round-trip similarity on GPU, exactly as Arm A run_baselines.stage_b3:
B3cos = MiniLM (sentence-transformers/all-MiniLM-L6-v2) cosine(sentence, back-translation), normalised embeddings;
B3nli = min(P_entail(sentence -> back), P_entail(back -> sentence)) with
        MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli (max_length 256, batch 32).
Uncovered (no back-translation) -> 0.5, covered=False.
"""
from __future__ import annotations

import time
from pathlib import Path

from loguru import logger


def _fast_load(name: str, dev: str):
    """Sequential-read loader (memory-mapped reads from the workspace network filesystem are very slow):
    build the classifier from its config, then copy the weights read in one sequential pass."""
    import torch
    from huggingface_hub import snapshot_download
    from transformers import AutoConfig, AutoModelForSequenceClassification
    path = Path(snapshot_download(name))
    cfg = AutoConfig.from_pretrained(path)
    mdl = AutoModelForSequenceClassification.from_config(cfg)
    st = sorted(path.glob("*.safetensors"))
    if st:
        from safetensors.torch import load as st_load
        sd = {}
        for f in st:
            sd.update(st_load(f.read_bytes()))
    else:
        import io
        sd = torch.load(io.BytesIO((path / "pytorch_model.bin").read_bytes()), map_location="cpu", weights_only=True)
    res = mdl.load_state_dict(sd, strict=False)
    bad = [k for k in res.missing_keys if "position_ids" not in k]
    if bad:
        logger.warning(f"{name}: missing keys {bad[:5]}")
    return mdl.to(dev).eval()


def score_b3(items: list[dict]) -> list[dict]:
    import torch
    from sentence_transformers import SentenceTransformer
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    if dev == "cuda" and torch.cuda.memory_allocated() == 0:
        torch.cuda.set_per_process_memory_fraction(0.5)  # alone on the GPU; otherwise keep the caller's cap
    ok = [i for i, it in enumerate(items) if it.get("back")]
    t0 = time.time()
    st = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2", device=dev)
    e1 = st.encode([items[i]["sentence"] for i in ok], normalize_embeddings=True, batch_size=128)
    e2 = st.encode([items[i]["back"] for i in ok], normalize_embeddings=True, batch_size=128)
    cos = {i: float(a @ b) for i, a, b in zip(ok, e1, e2)}
    del st
    name = "MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli" if dev == "cuda" else \
        "MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli"
    tok = AutoTokenizer.from_pretrained(name)
    mdl = _fast_load(name, dev)
    ent = [k for k, v in mdl.config.id2label.items() if v.lower().startswith("entail")][0]

    def p_ent(prem, hyp):
        out = []
        bs = 32
        i = 0
        while i < len(prem):
            try:
                b = tok(prem[i:i + bs], hyp[i:i + bs], return_tensors="pt", padding=True, truncation=True,
                        max_length=256).to(dev)
                with torch.no_grad():
                    pr = torch.softmax(mdl(**b).logits.float(), -1)[:, ent]
                out += pr.cpu().tolist()
                i += bs
            except torch.cuda.OutOfMemoryError:
                torch.cuda.empty_cache()
                bs = max(1, bs // 2)
                logger.warning(f"OOM -> batch {bs}")
        return out
    pa = p_ent([items[i]["sentence"] for i in ok], [items[i]["back"] for i in ok])
    pb = p_ent([items[i]["back"] for i in ok], [items[i]["sentence"] for i in ok])
    nli = {i: min(a, b) for i, a, b in zip(ok, pa, pb)}
    secs = (time.time() - t0) / max(1, len(items))
    rows = []
    for i, it in enumerate(items):
        for m, val in (("B3cos", cos.get(i)), ("B3nli", nli.get(i))):
            rows.append({"key": it["key"], "metric": m, "score": 0.5 if val is None else val, "covered": val is not None,
                         "seconds": secs, "nli_model": name if m == "B3nli" else None})
    logger.info(f"B3 GPU scored {len(ok)}/{len(items)} in {time.time() - t0:.0f}s on {dev} ({name})")
    del mdl
    if dev == "cuda":
        torch.cuda.empty_cache()
    return rows
