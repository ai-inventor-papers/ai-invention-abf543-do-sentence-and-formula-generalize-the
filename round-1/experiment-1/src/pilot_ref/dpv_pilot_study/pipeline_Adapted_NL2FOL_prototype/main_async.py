"""
NL2FOL - Module A: Natural Language to First-Order Logic
=========================================================
Based on: "Autoformalizing Natural Language to First-Order Logic:
A Case Study in Logical Fallacy Detection" (arXiv:2405.02318)

Module A pipeline steps:
  1. Claim & Implication Parser      - splits input into claim(s) + implication
  2. Referring Expression Extractor  - finds noun-phrase entities + assigns variables
  3. Entity Relation Classifier      - determines subset / equality / unrelated between entity pairs
  4. Property Extractor              - finds predicates describing entities
  5. Background Knowledge Retriever  - uses NLI to find entailment between property pairs
  6. FOL Formulation Engine          - combines everything into a FOL formula

Requirements:
    pip install openai transformers torch

Usage:
    # Set your OpenRouter API key:
    export OPENROUTER_API_KEY="sk-or-..."

    python nl2fol_module_a.py

    # Or import and call directly:
    from nl2fol_module_a import module_a
    result = module_a("I met a tall man who loved cheese, now I believe all tall people like cheese.")
    print(result["fol"])
"""

import asyncio
import os
from pathlib import Path
import re
import json
from dataclasses import dataclass, field
import subprocess
import tempfile
from openai import OpenAI, AsyncOpenAI
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MODEL = "anthropic/claude-sonnet-4.6"   # LLM used for all NL steps (any OpenRouter model)
NLI_MODEL = "facebook/bart-large-mnli"  # NLI model for background knowledge
MAX_TOKENS = 1024
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ModuleAResult:
    input_sentence: str
    claim: str = ""
    implication: str = ""
    referring_expressions: dict = field(default_factory=dict)   # {noun: variable}
    entity_relations: list = field(default_factory=list)        # list of strings like "x ⊆ y"
    properties: list = field(default_factory=list)              # list of strings like "IsTall(x)"
    background_knowledge: list = field(default_factory=list)    # list of strings like "∀x(A(x) ⇒ B(x))"
    fol: str = ""
    prolog: str = ""

# ---------------------------------------------------------------------------
# OpenAI client via OpenRouter
# ---------------------------------------------------------------------------
USAGE = 0.0

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

client = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url=OPENROUTER_BASE_URL,
)

client_async = AsyncOpenAI(
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

async def llm_async(system: str, user: str) -> tuple[str, float]:
    """
    Call the OpenRouter API (OpenAI-compatible)
    and return (text_response, cost).
    """

    response = await client_async.chat.completions.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )

    content = response.choices[0].message.content.strip()
    cost = response.usage.cost

    return content, cost


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

PROMPTS_DICT = {}

# ---------------------------------------------------------------------------
# Step 2 – Referring Expression Extractor  (Prompt 3 in paper)
# ---------------------------------------------------------------------------

def extract_referring_expressions(prompt: str, sentence: str) -> dict:
    """Returns {noun: variable}."""
    user = f"Input: \"{sentence}\""
    raw = llm(prompt, user)
    raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("```").strip()
    data = json.loads(raw)
    return data["expressions"]  # list of {"noun", "variable", "dpv"}


# ---------------------------------------------------------------------------
# Step 3 – Entity Relation Classifier  (Prompt 4 in paper)
# ---------------------------------------------------------------------------

async def get_entity_relation(
    prompt: str,
    entity_a: str,
    entity_b: str,
) -> tuple[str, float]:
    """Returns one of: equal, A_sub_B, B_sub_A, unrelated."""
    user = (
        f"Entity A: \"{entity_a}\"  Entity B: \"{entity_b}\""
    )
    raw, cost = await llm_async(prompt, user)
    raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("```").strip()
    data = json.loads(raw)

    return data["relation"], cost


async def classify_all_entity_relations(
    prompt: str,
    referring_expressions: dict,
) -> tuple[list[str], float]:

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

# ---------------------------------------------------------------------------
# Step 4 – Property Extractor  (Prompt 5 in paper)
# ---------------------------------------------------------------------------

def extract_properties(prompt: str, sentence: str, referring_expressions: dict) -> list[str]:
    user = (
        f"Sentence: \"{sentence}\"\n"
        f"Referring expressions: {json.dumps(referring_expressions)}"
    )
    raw = llm(prompt, user)
    raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("```").strip()
    data = json.loads(raw)
    return data["properties"]


# ---------------------------------------------------------------------------
# Step 6 – FOL Formulation Engine  (Prompt 7 in paper)
# ---------------------------------------------------------------------------

def formulate_fol(
    prompt: str,
    sentence: str,
    referring_expressions: dict,
    entity_relations: list[str],
    properties: list[str],
) -> str:
    user = (
        f"Sentence: \"{sentence}\"\n"
        f"Referring expressions: {json.dumps(referring_expressions)}\n"
        f"Entity relations: {json.dumps(entity_relations)}\n"
        f"Properties: {json.dumps(properties)}\n"
    )
    raw = llm(prompt, user)
    raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("```").strip()
    data = json.loads(raw)
    return data["fol"]

# ---------------------------------------------------------------------------
# Step + – FOL 
# ---------------------------------------------------------------------------

def fol_to_prolog(prompt: str, fol: str, extra_context: str = "") -> str:
    user = f"FOL: {fol}"
    if extra_context:
        user += f"\n\n{extra_context}"
    raw = llm(prompt, user)
    raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("```").strip()
    return json.loads(raw)["prolog"]

def validate_prolog(prolog_text: str, timeout: int = 10) -> tuple[bool, str]:
    with tempfile.NamedTemporaryFile(mode='w', suffix='.pl', delete=False) as f:
        f.write(prolog_text); path = f.name
    try:
        r = subprocess.run(
            ["swipl", "-q", "-g", f"consult('{path}'), halt", "-t", "halt(1)"],
            capture_output=True, text=True, timeout=timeout,
        )
        stderr = r.stderr or ""
        return ("ERROR:" not in stderr, stderr)
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    finally:
        os.unlink(path)

def fol_to_prolog_with_retry(prompt: str, fol: str, max_attempts: int = 3) -> dict:
    attempts, last_error, prolog = [], None, None
    for i in range(max_attempts):
        extra = f"Previous attempt produced this swipl error — fix it:\n{last_error}" if last_error else ""
        try:
            prolog = fol_to_prolog(prompt, fol, extra)
        except Exception as e:
            attempts.append({"attempt": i, "stage": "generate", "error": str(e)})
            last_error = f"JSON parse: {e}"
            continue
        ok, err = validate_prolog(prolog)
        attempts.append({"attempt": i, "prolog": prolog, "ok": ok, "swipl_error": "" if ok else err})
        if ok:
            return {"attempts": attempts, "final_prolog": prolog, "final_status": "ok", "n_attempts": i + 1}
        last_error = err
    return {"attempts": attempts, "final_prolog": prolog, "final_status": "still_invalid", "n_attempts": max_attempts}

# ---------------------------------------------------------------------------
# Full Pipeline
# ---------------------------------------------------------------------------

def run_pipeline(
    sentence: str,
    prompts: dict,
    verbose: bool = True,
) -> ModuleAResult:

    result = ModuleAResult(input_sentence=sentence)

    def log(step: str, value = ""):
        if verbose:
            print(f"\n{'='*60}")
            print(f"  {step}")
            print(f"{'='*60}")
            if isinstance(value, (list, dict)):
                print(json.dumps(value, ensure_ascii=False, indent=2))
            else:
                print(value)
    global USAGE

    log("INPUT", sentence)

    # --- Step 2: Referring Expressions ---
    # Extract from both claims and implication combined
    log("\n Extracting referring expressions...")
    referring_expressions = extract_referring_expressions(prompts["referring"], sentence)
    result.referring_expressions = referring_expressions
    log("Referring Expressions", referring_expressions)
    log("Cost: ", USAGE)

    # --- Step 3: Entity Relations ---
    log("\n Classifying entity relations...")
    entity_relations, total_cost = asyncio.run(
        classify_all_entity_relations(prompts["entity"], referring_expressions)
    )
    USAGE = USAGE + total_cost
    result.entity_relations = entity_relations
    log("Entity Relations", entity_relations)
    log("Cost: ", USAGE)

    # --- Step 4: Properties ---
    log("\n Extracting properties...")
    properties = extract_properties(prompts["property"], sentence, referring_expressions)
    result.properties = properties
    log("Properties", properties)
    log("Cost: ", USAGE)

    # --- Step 6: FOL Formula ---
    log("\n Formulating FOL expression...")
    fol = formulate_fol(
        prompts["fol"],
        sentence,
        referring_expressions,
        entity_relations,
        properties,
    )
    result.fol = fol
    log("FOL Formula", fol)
    log("Cost: ", USAGE)

    # --- Step 6: FOL Formula ---
    log("\n Converting FOL to Prolog + Validating Prolog code...")
    prolog = fol_to_prolog_with_retry(prompts["prolog"], fol)
    result.prolog = prolog
    log("Prolog Code", prolog)
    log("Cost: ", USAGE)


    return result


# ---------------------------------------------------------------------------
# Module A – Full Pipeline
# ---------------------------------------------------------------------------


def run_pilot(sentences, k_reruns=3, out_dir="pilot_results"):
    for slug, text in sentences:
        print("Converting: ", slug)
        for cond in [True, False]:
            prompts = load_prompts(cond)
            cond_slug = "grounded" if cond else "ungrounded"
            for k in range(1, k_reruns + 1):
                run_dir = Path(out_dir) / slug / cond_slug / f"run_{k}"
                run_dir.mkdir(parents=True, exist_ok=True)
                try:
                    result = run_pipeline(text, prompts, verbose=False)
                    (run_dir / "01_referring_expressions.json").write_text(
                        json.dumps(result.referring_expressions, ensure_ascii=False, indent=2))
                    (run_dir / "02_entity_relations.json").write_text(
                        json.dumps(result.entity_relations, indent=2))
                    (run_dir / "03_properties.json").write_text(
                        json.dumps(result.properties, indent=2))
                    (run_dir / "04_fol.json").write_text(
                        json.dumps({"fol": result.fol}, ensure_ascii=False, indent=2))
                    pr = fol_to_prolog_with_retry(prompts["prolog"], result.fol)
                    if pr["final_prolog"]:
                        (run_dir / "05_prolog.pl").write_text(pr["final_prolog"])
                    (run_dir / "prolog_validation.json").write_text(json.dumps(pr, indent=2))
                except Exception as e:
                    (run_dir / "error.json").write_text(
                        json.dumps({"error": str(e)}))
        print("Total cost: ", "{:.2}".format(USAGE))


if __name__ == "__main__":

    with open(os.path.join(os.path.dirname(__file__), "euaiact_enacting_terms.json")) as f:
        euaiact = json.load(f)
    
    sentences = []
    for paragraph in euaiact["enacting_terms"]["chapters"][0]["articles"][2]["paragraphs"][1:]:
        words = paragraph.split(" ")
        num = words[0]

        if num == "(4)" or num == "(7)" or num == "(22)":
            continue

        start = paragraph.index("‘")+1
        end = paragraph.index("’")
        title = paragraph[start:end]
        num_prefix = len(num)


        num = num.replace("(", "").replace(")", "")
        if len(num) == 1:
            num = "0" + num
        title = title.replace(" ", "_")
        text = paragraph[num_prefix:]
        slug = num + "_" + title

        sentences.append((slug,text))

    run_pilot(sentences = sentences, k_reruns=3, out_dir=os.path.join(os.path.dirname(__file__), "pilot_results"))

