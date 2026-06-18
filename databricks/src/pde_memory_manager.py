"""
PDE Memory Manager
==================
Manages the lifecycle of human correction rules for the Project Delivery Evaluator.
Rule states: draft -> approved | rejected | deprecated

This module is intentionally separate from src/memory_manager.py (which is CUCP-only).
Rules are persisted as a downloadable/uploadable JSON file (state-as-a-file pattern)
to support stateless Cloud Run deployments without requiring a database.
"""

import json
import uuid
import datetime
import logging
import os
from typing import Optional

from openai import OpenAI

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rule Schema
# ---------------------------------------------------------------------------
# Each rule in the rulebook follows this structure:
# {
#   "rule_id":         "pde-2024-04-22T08:30:00Z-a1b2",      # unique, stable
#   "question_id":     "A7",                                    # rubric question this targets
#   "summary":         "If utility relocs unknown, do not rate A7 as A",
#   "source_evidence": "Section 3: 'utility scope is TBD pending survey'",
#   "user_rationale":  "Unknown utilities always introduce contractor risk",
#   "status":          "approved",                             # draft|approved|rejected|deprecated
#   "version":         "2024-04-22T08:30:00Z",                # ISO timestamp of last update
# }

REQUIRED_RULE_KEYS = {"rule_id", "question_id", "summary", "source_evidence",
                       "user_rationale", "status", "version"}
VALID_STATUSES = {"draft", "approved", "rejected", "deprecated"}

# Soft cap: if approved rules exceed this, synthesis will compress aggressively
MAX_APPROVED_RULES = 20


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------

def _make_rule_id() -> str:
    ts = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    uid = str(uuid.uuid4())[:8]
    return f"pde-{ts}-{uid}"


def _now_iso() -> str:
    return datetime.datetime.utcnow().isoformat() + "Z"


def validate_rule(rule: dict) -> tuple[bool, str]:
    """Validate a single rule dict against the expected schema.
    Returns (is_valid, error_message).
    """
    missing = REQUIRED_RULE_KEYS - set(rule.keys())
    if missing:
        return False, f"Missing keys: {missing}"
    if rule.get("status") not in VALID_STATUSES:
        return False, f"Invalid status '{rule.get('status')}'. Must be one of: {VALID_STATUSES}"
    return True, ""


# ---------------------------------------------------------------------------
# Load / Save
# ---------------------------------------------------------------------------

def load_rulebook(file_obj) -> tuple[list, str]:
    """Parse an uploaded pde_rules.json file object.

    Returns:
        (rules, error_message) — rules is [] on failure, error_message is "" on success.
    """
    if file_obj is None:
        return [], ""

    try:
        raw = file_obj.read()
        data = json.loads(raw)
    except (json.JSONDecodeError, Exception) as e:
        return [], f"Could not parse rulebook JSON: {e}"

    # Accept either a bare list or a wrapped object {"rules": [...]}
    if isinstance(data, list):
        rules = data
    elif isinstance(data, dict) and "rules" in data:
        rules = data["rules"]
    else:
        return [], "Rulebook must be a JSON array or an object with a 'rules' key."

    valid_rules = []
    warnings = []
    for i, rule in enumerate(rules):
        ok, err = validate_rule(rule)
        if ok:
            valid_rules.append(rule)
        else:
            warnings.append(f"Rule #{i+1} skipped: {err}")

    warn_str = "; ".join(warnings) if warnings else ""
    return valid_rules, warn_str


def save_rulebook(rules: list) -> str:
    """Serialize rules to a JSON string for download."""
    return json.dumps({"rules": rules, "exported_at": _now_iso()}, indent=2)


def make_draft_rule(question_id: str, summary: str, source_evidence: str,
                    user_rationale: str) -> dict:
    """Create a new rule in DRAFT status, ready for adjudication."""
    return {
        "rule_id": _make_rule_id(),
        "question_id": question_id,
        "summary": summary,
        "source_evidence": source_evidence,
        "user_rationale": user_rationale,
        "status": "draft",
        "version": _now_iso(),
    }


# ---------------------------------------------------------------------------
# LLM Client
# ---------------------------------------------------------------------------

def _get_llm_client():
    from src.databricks_client import get_openai_client
    return get_openai_client()


# ---------------------------------------------------------------------------
# Adjudication Gateway
# ---------------------------------------------------------------------------

def adjudicate_rule(rule: dict) -> dict:
    """Run an LLM check on a single draft rule to detect manipulative or
    illogical corrections before they enter institutional memory.

    Returns:
        {
          "approved": bool,
          "concern": str,          # "" if approved cleanly
          "clarifying_question": str,  # "" if approved cleanly
        }
    On any LLM error, returns a cautious approval with a warning note,
    because we never want a transient API error to silently drop valid rules.
    """
    prompt_system = """You are a public procurement policy analyst reviewing a proposed rule 
correction submitted by a Caltrans project delivery evaluator.

The human evaluator is OVERRIDING the AI's original rating. The 'Summary' field describes the rating change in plain language (e.g., "Rating changed from B to C" means the AI chose B, but the Human corrects it to C).

Your job: assess whether the human's correction is a legitimate, evidence-based adjustment, or whether it appears to be illogical, policy-violating, or an attempt to manipulate the scoring.

Caltrans context: Delivery method scoring follows the PDPM (Project Delivery Procedure Manual). 
Valid corrections are grounded in project-specific evidence. Invalid corrections would claim a 
project always qualifies for a preferred method regardless of evidence, or contradict Caltrans 
statutory eligibility criteria.

Respond ONLY with valid JSON:
{
  "approved": true or false,
  "concern": "Brief explanation if suspicious. Empty string if approved.",
  "clarifying_question": "A single clarifying question to put back to the evaluator if suspicious. Empty string if clean."
}"""

    prompt_user = f"""Proposed rule:
Question: {rule.get('question_id', 'UNKNOWN')}
Summary: {rule.get('summary', '')}
Source evidence: {rule.get('source_evidence', '')}
User rationale: {rule.get('user_rationale', '')}

Assess whether this is a valid, policy-grounded correction."""

    try:
        client = _get_llm_client()
        response = client.chat.completions.create(
            model="databricks-gpt-5-4-mini",  # Use mini for cost efficiency; this is a simple classification
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": prompt_system},
                {"role": "user", "content": prompt_user},
            ],
            temperature=0.0,
            timeout=20,
        )
        result = json.loads(response.choices[0].message.content)
        return {
            "approved": bool(result.get("approved", True)),
            "concern": result.get("concern", ""),
            "clarifying_question": result.get("clarifying_question", ""),
        }
    except Exception as e:
        logger.warning(f"Adjudicator LLM call failed for rule {rule.get('rule_id')}: {e}")
        # On timeout/error: let it through with a warning, don't silently drop
        return {
            "approved": True,
            "concern": f"[Adjudicator offline — rule passed through unreviewed. Error: {e}]",
            "clarifying_question": "",
        }


def adjudicate_defense(rule: dict, defense_text: str) -> dict:
    """Re-run adjudication after the certifier provides a defense of a flagged rule.

    Returns same shape as adjudicate_rule().
    """
    prompt_system = """You are a public procurement policy analyst re-evaluating a flagged rule 
correction. The evaluator has provided additional justification. Assess whether this defense 
adequately explains why the correction is policy-grounded and specific to project evidence.

Respond ONLY with valid JSON:
{
  "approved": true or false,
  "concern": "Brief explanation if still rejected. Empty string if now approved."
}"""

    prompt_user = f"""Original rule:
Question: {rule.get('question_id', 'UNKNOWN')}
Summary: {rule.get('summary', '')}
Source evidence: {rule.get('source_evidence', '')}
User rationale: {rule.get('user_rationale', '')}

Evaluator defense: {defense_text}

Is this defense sufficient to approve the rule?"""

    try:
        client = _get_llm_client()
        response = client.chat.completions.create(
            model="databricks-gpt-5-4-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": prompt_system},
                {"role": "user", "content": prompt_user},
            ],
            temperature=0.0,
            timeout=20,
        )
        result = json.loads(response.choices[0].message.content)
        return {
            "approved": bool(result.get("approved", False)),
            "concern": result.get("concern", ""),
            "clarifying_question": "",
        }
    except Exception as e:
        logger.warning(f"Defense adjudicator LLM call failed: {e}")
        return {
            "approved": False,
            "concern": f"[Adjudicator offline during re-review. Rule dropped to be safe. Error: {e}]",
            "clarifying_question": "",
        }


# ---------------------------------------------------------------------------
# Synthesis (Memory Compression)
# ---------------------------------------------------------------------------

def synthesize_rulebook(existing_rules: list, new_approved_rules: list) -> tuple[list, str]:
    """Merge and compress the existing approved rulebook with newly approved rules.

    Strategy:
    - Always keeps rules in a valid state.
    - If the LLM synthesis returns malformed JSON or fails, falls back to
      a simple append of new_approved_rules (never corrupts existing rules).
    - Compresses when total approved rules exceed MAX_APPROVED_RULES.

    Returns:
        (merged_rules, synthesis_note)
    """
    existing_approved = [r for r in existing_rules if r.get("status") == "approved"]
    existing_other = [r for r in existing_rules if r.get("status") != "approved"]

    all_approved = existing_approved + new_approved_rules
    synthesis_note = ""

    if not all_approved:
        return existing_rules, "No approved rules to synthesize."

    # Only run LLM compression if we're close to or over the soft cap
    should_compress = len(all_approved) >= MAX_APPROVED_RULES

    if should_compress:
        prompt_system = """You are a rule synthesis engine for a Caltrans project delivery evaluation system. 
You receive a list of human correction rules, each with a question_id, summary, source_evidence, 
user_rationale, status, and version.

Your job: merge overlapping or duplicate rules into single, clearer, more general rules where safe. 
Never drop a rule unless it directly contradicts another with identical scope.
Preserve the provenance (source_evidence and user_rationale) in merged rules by combining them.

Return ONLY valid JSON:
{
  "rules": [ ...array of merged rule objects with all original fields preserved... ]
}

Maintain the same schema. Keep "status" as "approved". Update "version" to today. 
If in doubt about merging, keep rules separate rather than conflating them."""

        prompt_user = json.dumps({"rules_to_synthesize": all_approved}, indent=2)

        try:
            client = _get_llm_client()
            response = client.chat.completions.create(
                model="databricks-gpt-5-4-mini",
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": prompt_system},
                    {"role": "user", "content": prompt_user},
                ],
                temperature=0.0,
                timeout=40,
            )
            result = json.loads(response.choices[0].message.content)
            synthesized = result.get("rules", [])

            # Validate each returned rule has required fields
            valid_synthesized = []
            for r in synthesized:
                ok, _ = validate_rule(r)
                if ok:
                    valid_synthesized.append(r)

            if valid_synthesized:
                merged = valid_synthesized + existing_other
                synthesis_note = f"Compressed {len(all_approved)} rules → {len(valid_synthesized)} rules via LLM synthesis."
                return merged, synthesis_note
            else:
                raise ValueError("LLM synthesis returned no valid rules.")

        except Exception as e:
            logger.warning(f"Rulebook synthesis LLM call failed: {e}. Falling back to append.")
            synthesis_note = f"⚠️ Synthesis failed ({e}). New rules appended without compression."
            # Safe fallback: just append, never overwrite
            merged = all_approved + existing_other
            return merged, synthesis_note
    else:
        # Under the cap — just combine without LLM
        merged = all_approved + existing_other
        synthesis_note = f"Merged {len(new_approved_rules)} new rule(s) into rulebook ({len(all_approved)} total approved)."
        return merged, synthesis_note


# ---------------------------------------------------------------------------
# Prompt Injection Helper
# ---------------------------------------------------------------------------

def build_institutional_memory_block(rules: list) -> str:
    """Format approved rules for injection into the LLM system prompt.

    Returns empty string if no approved rules exist.
    """
    approved = [r for r in rules if r.get("status") == "approved"]
    if not approved:
        return ""

    lines = [
        "",
        "INSTITUTIONAL MEMORY — HUMAN CORRECTIONS:",
        "The following corrections were approved by past evaluators. Apply them as strong "
        "prior knowledge when matching evidence to rubric ratings. These do not override "
        "direct evidence from the document, but resolve ambiguity in the evaluator's favor.",
        "",
    ]
    for r in approved:
        qid = r.get("question_id", "?")
        summary = r.get("summary", "")
        rationale = r.get("user_rationale", "")
        lines.append(f"  [{qid}] {summary}")
        if rationale:
            lines.append(f"         ↳ Rationale: {rationale}")
    return "\n".join(lines)
