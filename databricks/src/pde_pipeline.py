"""
PDE Evaluation Pipeline with Result Store.

Flow:
1. Validate input
2. Check if we've seen this file before (Result Store)
3. If yes → return stored result instantly ($0)
4. If no → call LLM, save result, return
"""

import json
import logging

from src.result_store import compute_fingerprint, get_stored, store_result
from src.databricks_client import get_openai_client, MODEL_GPT4O
from src.project_delivery_evaluator import (
    _build_system_prompt,
    _extract_json,
)

logger = logging.getLogger(__name__)


def _validate_input(narrative_text: str):
    if not narrative_text or len(narrative_text.strip()) < 50:
        return "Insufficient narrative text provided. Please upload a valid document."
    return None


def _build_prompt(narrative_text: str, kb_text: str, existing_ratings: dict = None, pde_rules: list = None):
    system_prompt = _build_system_prompt(
        kb_text,
        existing_ratings or None,
        pde_rules=pde_rules or None,
    )
    user_message = (
        "Please evaluate the following Alternative Delivery Nomination Fact Sheet "
        "against all 25 rubric questions.\n\n"
        f"NOMINATION FACT SHEET CONTENT:\n{narrative_text}"
    )
    return system_prompt, user_message


def _call_llm(system_prompt: str, user_message: str, model_name: str) -> dict:
    try:
        client = get_openai_client()
        response = client.chat.completions.create(
            model=model_name,
            response_format={"type": "json_object"} if any(m in model_name.lower() for m in ["gpt", "json", "gemma"]) else None,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.0,
        )

        main_text = response.choices[0].message.content
        main_reason = response.choices[0].finish_reason

        try:
            return _extract_json(main_text, finish_reason=main_reason)
        except (json.JSONDecodeError, ValueError):
            retry = client.chat.completions.create(
                model=model_name,
                response_format={"type": "json_object"} if any(m in model_name.lower() for m in ["gpt", "json", "gemma"]) else None,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.0,
            )
            retry_text = retry.choices[0].message.content
            retry_reason = retry.choices[0].finish_reason
            return _extract_json(retry_text, finish_reason=retry_reason)
    except Exception as e:
        return {"error": f"LLM evaluation failed: {str(e)}"}


def run_pde_evaluation(narrative_text: str, kb_text: str, existing_ratings: dict = None,
                       model_name: str = None, pde_rules: list = None) -> dict:
    """
    Evaluate a project delivery nomination fact sheet.

    - Validates input
    - Checks Result Store (have we seen this file before?)
    - If yes: returns stored result instantly
    - If no: calls LLM, saves result, returns
    """

    # 1. Validate
    error = _validate_input(narrative_text)
    if error:
        return {"error": error}

    if not model_name:
        model_name = MODEL_GPT4O

    # 2. Build prompt (deterministic — no AI needed)
    system_prompt, user_message = _build_prompt(
        narrative_text.strip(), kb_text.strip(), existing_ratings, pde_rules
    )

    # 3. Check Result Store
    prompt_content = system_prompt + user_message
    content_hash = compute_fingerprint(prompt_content)

    stored = get_stored(content_hash, "evaluation")
    if stored:
        logger.info(f"Result Store HIT: {content_hash[:12]}...")
        stored["_from_store"] = True
        return stored

    # 4. Call LLM (only cost — only for new files)
    logger.info(f"Result Store MISS: calling LLM for {content_hash[:12]}...")
    result = _call_llm(system_prompt, user_message, model_name)

    # 5. Save result for reuse
    if "error" not in result:
        store_result(content_hash, "evaluation", result)
        result["_from_store"] = False

    return result
