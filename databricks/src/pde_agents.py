"""
PDE Agentic Pipeline — 5-agent architecture with Result Store.

Agents:
1. Planning Agent — parse, validate, normalize user input
2. Orchestrator Agent — fingerprint, check store, route
3. Prompt Generation Agent — generate system prompt from structured input
4. Code Generation Agent — call LLM with prompt, get evaluation
5. Delivery Agent — format output for UI
"""

import json
import logging

from src.result_store import compute_fingerprint, get_stored, store_result
from src.databricks_client import get_openai_client, MODEL_GPT4O
from src.project_delivery_evaluator import (
    _build_system_prompt,
    _extract_json,
    RUBRIC_QUESTIONS,
)

logger = logging.getLogger(__name__)


# ==============================================================================
# AGENT 1: PLANNING AGENT
# ==============================================================================
def planning_agent(narrative_text: str, kb_text: str, existing_ratings: dict = None,
                   pde_rules: list = None) -> dict:
    """Parse and normalize user input into a structured format."""

    structured_input = {
        "narrative_text": narrative_text.strip(),
        "kb_text": kb_text.strip(),
        "existing_ratings": existing_ratings or {},
        "pde_rules": pde_rules or [],
    }

    if not narrative_text or len(narrative_text.strip()) < 50:
        return {"error": "Insufficient narrative text provided. Please upload a valid document."}

    return {"structured_input": structured_input, "status": "validated"}


# ==============================================================================
# AGENT 2: ORCHESTRATOR AGENT
# ==============================================================================
def orchestrator_agent(structured_input: dict, model_name: str = None) -> dict:
    """Manage the two-stage pipeline with Result Store checks."""

    if not model_name:
        model_name = MODEL_GPT4O

    # --- STAGE 1: PROMPT ---
    # Fingerprint the input (narrative + ratings + rules determine the prompt)
    input_key = json.dumps({
        "narrative_length": len(structured_input["narrative_text"]),
        "narrative_hash": compute_fingerprint(structured_input["narrative_text"]),
        "ratings": structured_input["existing_ratings"],
        "rules_count": len(structured_input["pde_rules"]),
        "rules_hash": compute_fingerprint(json.dumps(structured_input["pde_rules"])) if structured_input["pde_rules"] else "",
    }, sort_keys=True)
    input_fingerprint = compute_fingerprint(input_key)

    # Check Result Store for prompt
    stored_prompt = get_stored(input_fingerprint, "prompt")
    if stored_prompt:
        system_prompt = stored_prompt["system_prompt"]
        user_message = stored_prompt["user_message"]
        stage1_status = "STORED"
        logger.info(f"Stage 1 HIT: input fingerprint {input_fingerprint[:12]}...")
    else:
        # Call Prompt Generation Agent
        system_prompt, user_message = prompt_generation_agent(structured_input)
        store_result(input_fingerprint, "prompt", {
            "system_prompt": system_prompt,
            "user_message": user_message,
        })
        stage1_status = "NEW"
        logger.info(f"Stage 1 MISS: generated and stored prompt for {input_fingerprint[:12]}...")

    # --- STAGE 2: CODE ---
    prompt_content = system_prompt + user_message
    prompt_fingerprint = compute_fingerprint(prompt_content)

    # Check Result Store for code
    stored_code = get_stored(prompt_fingerprint, "code")
    if stored_code:
        eval_result = stored_code
        stage2_status = "STORED"
        logger.info(f"Stage 2 HIT: prompt fingerprint {prompt_fingerprint[:12]}...")
    else:
        # Call Code Generation Agent
        eval_result = code_generation_agent(system_prompt, user_message, model_name)
        if "error" not in eval_result:
            store_result(prompt_fingerprint, "code", eval_result)
            stage2_status = "NEW"
            logger.info(f"Stage 2 MISS: generated and stored code for {prompt_fingerprint[:12]}...")
        else:
            stage2_status = "ERROR"

    # --- DELIVERY ---
    return delivery_agent(eval_result, stage1_status, stage2_status)


# ==============================================================================
# AGENT 3: PROMPT GENERATION AGENT
# ==============================================================================
def prompt_generation_agent(structured_input: dict) -> tuple:
    """Generate the system prompt and user message from structured input."""

    system_prompt = _build_system_prompt(
        structured_input["kb_text"],
        structured_input["existing_ratings"] or None,
        pde_rules=structured_input["pde_rules"] or None,
    )

    user_message = (
        "Please evaluate the following Alternative Delivery Nomination Fact Sheet "
        "against all 25 rubric questions.\n\n"
        f"NOMINATION FACT SHEET CONTENT:\n{structured_input['narrative_text']}"
    )

    return system_prompt, user_message


# ==============================================================================
# AGENT 4: CODE GENERATION AGENT
# ==============================================================================
def code_generation_agent(system_prompt: str, user_message: str, model_name: str) -> dict:
    """Call Claude Opus 4.6 (or configured model) and return the evaluation."""

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
            # Retry once on malformed JSON
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
        return {"error": f"Code Generation Agent error: {str(e)}"}


# ==============================================================================
# AGENT 5: DELIVERY AGENT
# ==============================================================================
def delivery_agent(eval_result: dict, stage1_status: str, stage2_status: str) -> dict:
    """Format output and attach metadata."""

    if "error" in eval_result:
        return eval_result

    eval_result["_pipeline_metadata"] = {
        "stage1_prompt": stage1_status,
        "stage2_code": stage2_status,
    }

    return eval_result


# ==============================================================================
# PUBLIC ENTRY POINT — replaces run_delivery_evaluation for PDE
# ==============================================================================
def run_pde_evaluation(narrative_text: str, kb_text: str, existing_ratings: dict = None,
                       model_name: str = None, pde_rules: list = None) -> dict:
    """
    Agentic pipeline entry point for Project Delivery Evaluation.
    Drop-in replacement for run_delivery_evaluation with Result Store.
    """

    # Agent 1: Planning
    plan_result = planning_agent(narrative_text, kb_text, existing_ratings, pde_rules)
    if "error" in plan_result:
        return plan_result

    # Agent 2: Orchestrator (manages Stage 1 + Stage 2 + Delivery)
    return orchestrator_agent(plan_result["structured_input"], model_name)
