"""R2 + R3 — TVJT judge protocol (world-level deterministic cache, 3 order-permuted votes, confidence scores)
and the B1 / B1x3 fixed-prompt judge baseline, over two interchangeable backends:

  backend 'gemini'  google/gemini-2.5-flash via OpenRouter (T=0, reasoning off exactly as iter 1), global
                    cost ledger results/cost_ledger.jsonl, HARD breaker at $9.50, per-stage soft stops.
  backend 'local'   a local llama.cpp GGUF model (CPU), $0; a SEPARATELY LABELLED judge variant, never mixed
                    with gemini results (plan F4).

World-level cache key = sha1(model | prompt_version | sentence | world_text | vote_idx). A target's worlds are
presented in canonical key order permuted by perm_k (k=0 canonical, 1 reversed, 2 rotated by ceil(|U|/2));
only worlds not yet cached for vote k are sent, in ONE batched call.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import re
import threading
import time
from pathlib import Path

from loguru import logger

import common
from common import CACHE, RESULTS, append_jsonl, read_jsonl, sha1

PROMPT_VERSION = "tvjt_v2_conf"
TVJT_V2 = ("You will read a sentence and several small, self-contained situations. For each situation, decide "
           "whether the sentence is TRUE or FALSE in that situation, using ONLY the listed individuals and facts "
           "(anything not listed is false; interpret general statements as being about the individuals listed). "
           "Sentence: \"{S}\"\n\n{SITUATIONS}\n\n"
           "Answer with JSON only, one entry per situation: {{\"1\": [v, c], ...}} where v is 1 if the sentence is "
           "TRUE in that situation and 0 if FALSE, and c is your confidence 0-100.")
B1_PROMPT = ("Sentence: {s}\nFOL: {f}\nGive the probability (0-100) that this FOL is a faithful formalization of "
             "the sentence. Reply with a number only.")
GEMINI = "google/gemini-2.5-flash"
GEMINI_LITE = "google/gemini-2.5-flash-lite"
HARD_CAP = 9.50
URL = "https://openrouter.ai/api/v1/chat/completions"
LEDGER = RESULTS / "cost_ledger.jsonl"


class BudgetExceeded(RuntimeError):
    pass


class JudgeUnavailable(RuntimeError):
    pass


# ------------------------------------------------------------------------------------------ prompts
def perm(n: int, k: int) -> list[int]:
    idx = list(range(n))
    if k == 0:
        return idx
    if k == 1:
        return idx[::-1]
    r = math.ceil(n / 2)
    return idx[r:] + idx[:r]


def build_tvjt_prompt(sentence: str, texts: list[str]) -> str:
    sits = "\n".join(f"Situation {i}: {t}" for i, t in enumerate(texts, 1))
    return TVJT_V2.format(S=sentence, SITUATIONS=sits)


def parse_tvjt(text: str, k: int) -> dict[int, tuple[int, float]] | None:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    out = {}
    for i in range(1, k + 1):
        v = d.get(str(i), d.get(i))
        if isinstance(v, dict):
            v = [v.get("v"), v.get("c")]
        if not isinstance(v, (list, tuple)) or len(v) < 1:
            return None
        try:
            vv = int(v[0]) if not isinstance(v[0], str) else (1 if v[0].strip().upper() in ("1", "TRUE") else 0)
            cc = float(v[1]) if len(v) > 1 and v[1] is not None else 100.0
        except (TypeError, ValueError):
            return None
        if vv not in (0, 1):
            return None
        out[i] = (vv, min(100.0, max(0.0, cc)))
    return out


def parse_prob(text: str) -> float | None:
    m = re.search(r"-?\d+(\.\d+)?", text or "")
    if not m:
        return None
    v = float(m.group(0))
    return v / 100.0 if 0 <= v <= 100 else None


# ------------------------------------------------------------------------------------------ backends
class GeminiBackend:
    """OpenRouter chat call identical to iter-1 llm.py (reasoning max_tokens 0 / exclude)."""

    def __init__(self, model: str = GEMINI, concurrency: int = 16, stage_caps: dict | None = None):
        self.model, self.name = model, model
        self.sem = asyncio.Semaphore(concurrency)
        self.cum = sum(float(r.get("cost", 0) or 0) for r in read_jsonl(LEDGER))
        self.stage_caps = stage_caps or {}
        self.stage_spend: dict[str, float] = {}
        for r in read_jsonl(LEDGER):
            self.stage_spend[r["stage"]] = self.stage_spend.get(r["stage"], 0) + float(r.get("cost", 0) or 0)
        self.key = os.environ.get("OPENROUTER_API_KEY", "")
        self.session = None

    async def __aenter__(self):
        import aiohttp
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120))
        return self

    async def __aexit__(self, *a):
        await self.session.close()

    def payload(self, prompt: str, max_tokens: int) -> dict:
        return {"model": self.model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.0,
                "max_tokens": max_tokens, "reasoning": {"max_tokens": 0, "exclude": True}, "usage": {"include": True}}

    async def complete(self, prompt: str, max_tokens: int, stage: str, item_id: str) -> dict:
        import aiohttp
        if self.cum >= HARD_CAP:
            raise BudgetExceeded(f"cum ${self.cum:.3f} >= ${HARD_CAP}")
        cap = self.stage_caps.get(stage)
        if cap is not None and self.stage_spend.get(stage, 0) >= cap:
            raise BudgetExceeded(f"stage {stage} soft stop ${cap}")
        async with self.sem:
            t0, data = time.time(), None
            for attempt in range(6):
                try:
                    async with self.session.post(URL, json=self.payload(prompt, max_tokens),
                                                 headers={"Authorization": f"Bearer {self.key}"}) as r:
                        if r.status == 403:
                            body = await r.text()
                            raise JudgeUnavailable(f"403 {body[:160]}")
                        if r.status in (429, 500, 502, 503, 504, 408):
                            raise aiohttp.ClientResponseError(r.request_info, r.history, status=r.status)
                        data = await r.json(content_type=None)
                        if "choices" not in data:
                            raise ValueError(str(data)[:200])
                        break
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
                    await asyncio.sleep(min(60, 2 ** attempt))
                    logger.warning(f"retry {attempt} {stage}/{item_id}: {str(e)[:120]}")
            if data is None:
                raise RuntimeError(f"failed {item_id}")
        u = data.get("usage") or {}
        cost = float(u.get("cost", 0) or 0)
        self.cum += cost
        self.stage_spend[stage] = self.stage_spend.get(stage, 0) + cost
        append_jsonl(LEDGER, [{"ts": time.time(), "model": self.model, "stage": stage, "item_id": item_id,
                               "prompt_tokens": u.get("prompt_tokens"), "completion_tokens": u.get("completion_tokens"),
                               "cost": cost, "cum": round(self.cum, 6), "seconds": round(time.time() - t0, 3)}])
        text = ((data["choices"][0].get("message") or {}).get("content")) or ""
        return {"text": text, "usd": cost, "seconds": time.time() - t0}


class LocalBackend:
    """llama.cpp CPU model; calls are serialised (one model instance) and run in a worker thread."""

    def __init__(self, model_path: str, n_threads: int = 3, n_ctx: int = 4096):
        from llama_cpp import Llama
        self.model_path = model_path
        self.name = "local:" + Path(model_path).name
        self.llm = Llama(model_path=model_path, n_ctx=n_ctx, n_threads=n_threads, seed=0, verbose=False)
        self.lock = threading.Lock()
        self.cum = 0.0
        self.n_calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None

    def _call(self, prompt: str, max_tokens: int, json_mode: bool) -> dict:
        t0 = time.time()
        kw = {"response_format": {"type": "json_object"}} if json_mode else {}
        with self.lock:
            r = self.llm.create_chat_completion(messages=[{"role": "user", "content": prompt}], temperature=0.0,
                                                max_tokens=max_tokens, seed=0, **kw)
        self.n_calls += 1
        return {"text": r["choices"][0]["message"]["content"] or "", "usd": 0.0, "seconds": time.time() - t0}

    async def complete(self, prompt: str, max_tokens: int, stage: str, item_id: str) -> dict:
        json_mode = stage.startswith("TVJT")
        return await asyncio.to_thread(self._call, prompt, max_tokens, json_mode)


# ------------------------------------------------------------------------------------------ caches
class WorldCache:
    """(backend, prompt_version, sentence, world_text, vote) → [v, c]; append-only jsonl."""

    def __init__(self, backend_name: str, namespace: str = "main"):
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", backend_name)
        self.path = CACHE / f"judge_worlds__{safe}__{namespace}.jsonl"
        self.backend_name = backend_name
        self.d = {r["k"]: r["a"] for r in read_jsonl(self.path)}

    def key(self, sentence: str, text: str, vote: int) -> str:
        return sha1(f"{self.backend_name}|{PROMPT_VERSION}|{sentence}|{text}|{vote}")

    def get(self, sentence, text, vote):
        return self.d.get(self.key(sentence, text, vote))

    def put(self, sentence, text, vote, ans) -> None:
        k = self.key(sentence, text, vote)
        self.d[k] = ans
        append_jsonl(self.path, [{"k": k, "a": ans}])


class CallCache:
    """Whole-prompt cache for B1 (key includes vote index so B1x3 votes are distinct calls)."""

    def __init__(self, backend_name: str, namespace: str = "main"):
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", backend_name)
        self.path = CACHE / f"judge_calls__{safe}__{namespace}.jsonl"
        self.backend_name = backend_name
        self.d = {r["k"]: r for r in read_jsonl(self.path)}

    def key(self, prompt: str, vote: int) -> str:
        return sha1(f"{self.backend_name}|{prompt}|{vote}")


# ------------------------------------------------------------------------------------------ TVJT
async def judge_target(be, wcache: WorldCache, sentence: str, worlds: list[dict], votes: int, stage: str,
                       item_id: str) -> dict:
    """worlds: canonical-ordered dicts with 'text', 'F_value', 'op'. Fills the world cache for votes 0..votes-1
    and returns per-world answers {vote: [[v,c]|None per world]} plus usd/seconds/malformed counts."""
    usd = sec = 0.0
    malformed = 0
    texts = [w["text"] for w in worlds]
    for k in range(votes):
        unc = [i for i, t in enumerate(texts) if wcache.get(sentence, t, k) is None]
        # dedupe identical texts inside a target (possible after name mapping)
        seen, U = set(), []
        for i in unc:
            if texts[i] not in seen:
                seen.add(texts[i])
                U.append(i)
        if not U:
            continue
        order = [U[j] for j in perm(len(U), k)]
        prompt = build_tvjt_prompt(sentence, [texts[i] for i in order])
        ans = None
        for attempt in range(2):
            p = prompt if attempt == 0 else prompt + "\nReturn ONLY the JSON object, with every key."
            r = await be.complete(p, 60 + 14 * len(order), stage, f"{item_id}:v{k}:a{attempt}")
            usd += r["usd"]
            sec += r["seconds"]
            ans = parse_tvjt(r["text"], len(order))
            if ans is not None:
                break
            malformed += 1
        if ans is None:
            continue
        for pos, i in enumerate(order, 1):
            wcache.put(sentence, texts[i], k, list(ans[pos]))
    got = {k: [wcache.get(sentence, t, k) for t in texts] for k in range(votes)}
    return {"answers": got, "usd": usd, "seconds": sec, "malformed": malformed}


def score_tvjt(worlds: list[dict], answers: dict, votes_used: int) -> dict:
    """C1 (vote 0 binary), C2 (3-vote majority binary), C3 (mean confidence-weighted P(true) agreement)."""
    from mutants import OPERATORS
    c1, c2, c3, per_w = [], [], [], []
    for j, w in enumerate(worlds):
        F = bool(w["F_value"])
        a = [answers.get(k, [None] * len(worlds))[j] for k in range(votes_used)]
        a = [x for x in a if x is not None]
        if not a:
            per_w.append(None)
            continue
        if answers.get(0) and answers[0][j] is not None:
            c1.append(1.0 if bool(answers[0][j][0]) == F else 0.0)
        maj = sum(x[0] for x in a) / len(a)
        c2.append(1.0 if (maj > 0.5) == F else (0.5 if maj == 0.5 else 0.0))
        p = [x[1] / 100 if x[0] == 1 else 1 - x[1] / 100 for x in a]
        pbar = sum(p) / len(p)
        agree = pbar if F else 1 - pbar
        c3.append(agree)
        per_w.append(agree)
    fam: dict[str, list[float]] = {}
    for w, a in zip(worlds, per_w):
        if a is not None:
            fam.setdefault(w["op"], []).append(a)
    if not fam or all(sum(v) / len(v) >= 0.5 for v in fam.values()):
        et = "none"
    else:
        et = min(OPERATORS, key=lambda o: (sum(fam[o]) / len(fam[o]) if o in fam else 9, OPERATORS.index(o)))
    mean = lambda x: sum(x) / len(x) if x else None  # noqa: E731
    return {"C1": mean(c1), "C2": mean(c2), "C3": mean(c3), "n_worlds": len(worlds),
            "n_judged": sum(a is not None for a in per_w), "error_type": et, "per_world_agree": per_w}


# ------------------------------------------------------------------------------------------ B1
async def judge_b1(be, ccache: CallCache, sentence: str, fol: str, vote: int, stage: str, item_id: str) -> dict:
    prompt = B1_PROMPT.format(s=sentence, f=fol)
    k = ccache.key(prompt, vote)
    if k in ccache.d:
        r = ccache.d[k]
        return {"p": r["p"], "usd": 0.0, "seconds": 0.0, "cached": True}
    r = await be.complete(prompt, 8, stage, f"{item_id}:v{vote}")
    p = parse_prob(r["text"])
    rec = {"k": k, "p": p, "text": r["text"][:20]}
    ccache.d[k] = rec
    append_jsonl(ccache.path, [rec])
    return {"p": p, "usd": r["usd"], "seconds": r["seconds"], "cached": False}


def gemini_available() -> tuple[bool, str]:
    """Checks the OpenRouter key budget (GET /api/v1/key); False when the daily limit is exhausted."""
    import urllib.request
    try:
        req = urllib.request.Request("https://openrouter.ai/api/v1/key",
                                     headers={"Authorization": f"Bearer {os.environ.get('OPENROUTER_API_KEY', '')}"})
        d = json.loads(urllib.request.urlopen(req, timeout=20).read())["data"]
        rem = d.get("limit_remaining")
        ok = rem is None or rem > 0.5
        return ok, f"limit={d.get('limit')} reset={d.get('limit_reset')} remaining={rem}"
    except Exception as e:  # noqa: BLE001
        return False, f"key check failed: {e!r}"[:200]
