
import os
import re
import json
from openai import OpenAI
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MODEL = "anthropic/claude-sonnet-4.6"   # LLM used for all NL steps (any OpenRouter model)
NLI_MODEL = "facebook/bart-large-mnli"  # NLI model for background knowledge
MAX_TOKENS = 1024
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# ---------------------------------------------------------------------------
# OpenAI client via OpenRouter
# ---------------------------------------------------------------------------
USAGE = 0.0

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

client = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url=OPENROUTER_BASE_URL,
)

def llm(system: str, user: str) -> str:
    """Call the OpenRouter API (OpenAI-compatible) and return the text response."""
    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    global USAGE
    USAGE = USAGE + response.usage.cost
    return response.choices[0].message.content.strip()

def load_prompts(grounded: bool) -> dict:
    suf = "_with_DPV" if grounded else ""
    base = os.path.dirname(__file__)
    return {
        "referring": open(f"{base}/referring_expression_extractor_legal_examples{suf}.txt").read(),
        "entity": open(f"{base}/entity_relation_classifier_legal_examples.txt").read(),
        "property":  open(f"{base}/property_extractor_legal_examples{suf}.txt").read(),
        "fol":       open(f"{base}/logical_formulation_engine_legal_examples{suf}.txt").read(),
        "prolog": open(f"{base}/FOL_to_Prolog.txt").read(),
    }

def get_entity_relation(prompt: str, entity_a: str, entity_b: str) -> str:
    """Returns one of: equal, A_sub_B, B_sub_A, unrelated."""
    user = (
        f"Entity A: \"{entity_a}\"  Entity B: \"{entity_b}\""
    )
    raw = llm(prompt, user)
    raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("```").strip()
    data = json.loads(raw)
    return data["relation"]


def classify_all_entity_relations(prompt: str, referring_expressions: dict) -> list[str]:
    """Compare every pair of entities and collect non-trivial relations."""
    nouns = [ref_ex["noun"] for ref_ex in referring_expressions]
    vars  = [ref_ex["variable"] for ref_ex in referring_expressions]

    relations = []
    for i in range(len(nouns)):
        for j in range(i + 1, len(nouns)):
            a, b = nouns[i], nouns[j]
            rel = get_entity_relation(prompt, a, b)
            va, vb = vars[i], vars[j]
            if rel == "equal":
                relations.append(f"{va} = {vb}")
            elif rel == "A_sub_B":
                relations.append(f"{va} ⊆ {vb}")
            elif rel == "B_sub_A":
                relations.append(f"{vb} ⊆ {va}")
            # "unrelated" → skip
    return relations
import os
import re
import json
import asyncio
from openai import AsyncOpenAI
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MODEL = "anthropic/claude-sonnet-4.6"
NLI_MODEL = "facebook/bart-large-mnli"
MAX_TOKENS = 1024
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# ---------------------------------------------------------------------------
# OpenAI client via OpenRouter
# ---------------------------------------------------------------------------

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))



def load_prompts(grounded: bool) -> dict:
    suf = "_with_DPV" if grounded else ""
    base = os.path.dirname(__file__)

    return {
        "referring": open(f"{base}/referring_expression_extractor_legal_examples{suf}.txt").read(),
        "entity": open(f"{base}/entity_relation_classifier_legal_examples.txt").read(),
        "property": open(f"{base}/property_extractor_legal_examples{suf}.txt").read(),
        "fol": open(f"{base}/logical_formulation_engine_legal_examples{suf}.txt").read(),
        "prolog": open(f"{base}/FOL_to_Prolog.txt").read(),
    }


async def get_entity_relation(
    prompt: str,
    entity_a: str,
    entity_b: str,
) -> tuple[str, float]:
    """
    Returns:
        (relation, cost)

    relation ∈ {
        "equal",
        "A_sub_B",
        "B_sub_A",
        "unrelated"
    }
    """

    user = f'Entity A: "{entity_a}"  Entity B: "{entity_b}"'

    raw, cost = await llm(prompt, user)

    raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("```").strip()

    data = json.loads(raw)

    return data["relation"], cost


async def classify_all_entity_relations(
    prompt: str,
    referring_expressions: dict,
) -> tuple[list[str], float]:
    """
    Compare every pair of entities concurrently.

    Returns:
        (relations, total_cost)
    """

    nouns = [ref_ex["noun"] for ref_ex in referring_expressions]
    vars_ = [ref_ex["variable"] for ref_ex in referring_expressions]

    tasks = []
    metadata = []

    for i in range(len(nouns)):
        for j in range(i + 1, len(nouns)):
            a, b = nouns[i], nouns[j]

            tasks.append(get_entity_relation(prompt, a, b))
            metadata.append((vars_[i], vars_[j]))

    results = await asyncio.gather(*tasks)

    relations = []
    total_cost = 0.0

    for (rel, cost), (va, vb) in zip(results, metadata):

        total_cost += cost

        if rel == "equal":
            relations.append(f"{va} = {vb}")

        elif rel == "A_sub_B":
            relations.append(f"{va} ⊆ {vb}")

        elif rel == "B_sub_A":
            relations.append(f"{vb} ⊆ {va}")

        # "unrelated" → skip

    return relations, total_cost