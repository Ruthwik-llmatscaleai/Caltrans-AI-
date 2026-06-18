# Standard library imports
import datetime
import io
import json
import os
import re
import time
import traceback
from io import BytesIO
from typing import List, Tuple

# Third-party imports
import pandas as pd
import streamlit as st

# Document generation (if you use generate_reentry_care_plan)
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor
from dotenv import load_dotenv
from openai import OpenAI
from PIL import Image
from PyPDF2 import PdfReader

from src.databricks_client import get_openai_client, MODEL_GPT4O, MODEL_LLAMA

#
load_dotenv()

HF_TOKEN = os.getenv("HF_TOKEN")


def run_guardrails(user_input: str) -> Tuple[bool, str]:
    """
    Caltrans-specific guardrails that:
    1. Detects safety/compliance violations
    2. Validates against allowable topics
    3. Uses only the moderation endpoint
    """
    try:
        client = get_openai_client()

        # Define acceptable content categories
        ALLOWABLE_CATEGORIES = {
            "standard specifications",
            "plan clarification",
            "technical guidance",
            "implementation questions",
            "material requirements",
            "construction methods",
        }

        # Context with both compliance rules and allowed categories
        compliance_context = f"""
        [CALTRANS COMPLIANCE ANALYST]
        Analyze this input for:

        SAFETY/ETHICS VIOLATIONS:
        - Cost-cutting that compromises safety
        - Attempts to bypass/violate standards
        - Falsification of reports/tests
        - Material substitution fraud
        - Installation shortcuts
        - Weakening barrier strength
        - Bid rigging or bribery

        ALLOWED CATEGORIES (REJECT OTHERS):
        {", ".join(ALLOWABLE_CATEGORIES)}

        Return standardized codes for:
        1. VIOLATION:<type> if safety/ethics violation exists
        2. CATEGORY:invalid if outside allowed categories
        3. PASS if compliant
        """

        # Single omni-moderation call
        response = client.moderations.create(
            model="omni-moderation-latest",
            input=f"{compliance_context}\n\n[USER INPUT]: {user_input}",
            timeout=3,
        )

        result = response.results[0]

        if result.flagged:
            # Parse the raw category scores
            violation_scores = {
                "harassment": result.category_scores.harassment,
                "harassment_threatening": result.category_scores.harassment_threatening,
                "hate": result.category_scores.hate,
                "self_harm": result.category_scores.self_harm,
                "sexual": result.category_scores.sexual,
                "violence": result.category_scores.violence,
                "violence_graphic": result.category_scores.violence_graphic,
            }

            # Get top violation
            top_violation = max(violation_scores.items(), key=lambda x: x[1])

            if top_violation[1] > 0.7:  # High confidence threshold
                violation_map = {
                    "harassment": "Unethical Conduct",
                    "harassment_threatening": "Safety Threat",
                    "hate": "Discriminatory Content",
                    "self_harm": "Public Safety Risk",
                    "sexual": "Inappropriate Content",
                    "violence": "Safety Violation",
                }

                return False, (
                    "⛔ SAFETY & COMPLIANCE VIOLATION\n\n"
                    f"REASON: {violation_map.get(top_violation[0], 'Standards Violation')}\n\n"
                    "All Caltrans Standard Plans must be followed exactly.\n"
                    "Safety standards exist to protect lives.\n\n"
                    "REQUIRED: Revise to focus on compliant implementation"
                )

            # Check for category mismatch (lower confidence threshold)
            category_keywords = "|".join(ALLOWABLE_CATEGORIES)
            if not re.search(category_keywords, user_input, re.IGNORECASE):
                return False, (
                    "⚠️ OFF-TOPIC CONTENT\n\n"
                    f"ALLOWED TOPICS: {', '.join(ALLOWABLE_CATEGORIES)}\n"
                    "Please ask about proper Caltrans standard implementation"
                )

            return False, "⚠️ Content requires manual review"

        return True, "✅ Query passed safety checks"

    except Exception as e:
        print(f"Moderation error: {str(e)}")
        return True, "⚠️ System limited - proceeding with caution"


#
# def run_guardrails(user_input):
# client = OpenAI()
##3. Run OpenAI moderation as fallback
# try:
# healthcare_context = """
# [HEALTHCARE COMPLIANCE CONTEXT]
# You are Serrano Health Advisors' AI moderation system.
# Pay special attention to:
#
# CRITICAL VIOLATIONS:
# 1. Any bribery or financial inducement requests
# 2. Medication/prescription modification requests
# 3. Attempts to circumvent security or protocols
# 4. PHI/PII disclosure risks
# 5. Fraudulent or unethical requests
#
# EXAMPLES TO FLAG:
# - "accept my bribe"
# - "change the prescription"
# - "override the system"
# - "ignore the rules"
# - Any patient identifiers
#
# Return violations in standardized format.
# """
# ALLOWABLE_CATEGORIES = {
# "job assistance", "housing support", "healthcare", "social services"
# }
#
# moderation = client.moderations.create(
# model="omni-moderation-latest",
# input=f"[HEALTHCARE CONTEXT]\n{healthcare_context}\n\n[USER INPUT]\n{user_input}",
# timeout=3  # Fail fast if API is slow
# )
#
# result = moderation.results[0]

# if result.flagged:
# categories = result.categories
# category_scores = result.category_scores
# violation_map = {
# "harassment": "Unethical request",
# "hate": "Unprofessional content",
# "self-harm": "Safety violation",
# "sexual": "Inappropriate content",
# "violence": "Threat concern",
# "pii": "PHI/PII risk",
# "harassment/threatening": "Coercive behavior",
# "financial": "Bribery/fraud indicator"
# }
#
# violations = []
# for category, message in violation_map.items():
# if getattr(result.categories, category, False):
# violations.append(message)
#
# if violations:
# return False, (
# "⚠️ Content blocked for compliance reasons:\n\n"
# f"• {', '.join(violations)}\n\n"
# "Please revise to meet professional healthcare standards."
# )
#
# return False, "⚠️ Content requires compliance review"
# return True, None
#
# except Exception as e:
##Fail open but log the error
# print(f"Moderation error: {str(e)}")
# return True, None


def ensure_file_like(file):
    if hasattr(file, "read") and hasattr(file, "name"):
        # Special handling for Streamlit UploadedFile
        if hasattr(file, "getvalue"):
            content = file.getvalue()
            if isinstance(content, str):
                content = content.encode("utf-8")
            file = io.BytesIO(content)
            file.name = getattr(file, "name", "uploaded_file")
        return file

    # Handle bytes input
    if isinstance(file, bytes):
        return io.BytesIO(file)

    # Handle file path string
    if isinstance(file, str):
        if os.path.isfile(file):
            return open(file, "rb")
        elif file.startswith(("http://", "https://")):
            raise ValueError("URLs not supported - please download file first")

    # Handle other file-like objects
    if hasattr(file, "read"):
        return file

    raise ValueError(
        f"Unsupported file type ({type(file)}). "
        "Please upload a file directly using the file uploader."
    )


def policy_agent(user_input, knowledge_base=None):
    logger = st.session_state.get("logger", print)

    if knowledge_base is None:
        return None

    # Guardrailing the user input
    is_safe, msg = run_guardrails(user_input)
    if not is_safe:
        return msg

    # Initialize client (Databricks)
    if "client" not in st.session_state:
        st.session_state.client = get_openai_client()

    client = st.session_state.client

    try:
        with st.spinner("Generating response..."):
            # Extract PDF text
            import io

            # Ensure knowledge_base is a file-like object
            if isinstance(knowledge_base, str):
                # If it's a file path
                with open(knowledge_base, "rb") as f:
                    pdf_content = f.read()
            else:
                # If it's already a file object (UploadedFile)
                knowledge_base.seek(0)
                pdf_content = knowledge_base.read()

            # Read PDF
            pdf_reader = PdfReader(io.BytesIO(pdf_content))

            # Extract all text from PDF
            full_text = ""
            for page_num, page in enumerate(pdf_reader.pages):
                page_text = page.extract_text()
                full_text += f"\n--- Page {page_num + 1} ---\n{page_text}\n"

            logger(f"Extracted {len(full_text)} characters from PDF")

            # Truncate if too long (keep within token limits)
            max_chars = 80000  # Adjust based on your model's context window
            if len(full_text) > max_chars:
                full_text = (
                    full_text[:max_chars]
                    + "\n\n[Document content truncated due to length]"
                )

            # Create comprehensive prompt
            system_prompt = """You are an expert assistant for Caltrans Standard Plans and transportation engineering documentation.

Your role is to:
1. Provide detailed, comprehensive answers based on the document content
2. Reference specific plan numbers, sections, and details
3. Explain technical specifications clearly
4. Summarize changes and modifications thoroughly
5. Never ask the user to provide additional files - all necessary information is in the document provided

When answering:
- Be specific with plan sheet numbers and references
- Include technical details like dimensions, materials, and specifications
- Explain the reasoning behind changes when mentioned in the document
- Provide context and background information
- Format your response clearly with proper structure"""

            user_prompt = f"""Based on the following Caltrans Standard Plans document, please answer the user's question comprehensively.

DOCUMENT CONTENT:
{full_text}

USER QUESTION: {user_input}

Provide a detailed answer with specific references to plan numbers, sections, and technical details from the document above."""

            response = client.chat.completions.create(
                model=MODEL_GPT4O,
                temperature=0.3,
                max_tokens=2000,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )

            answer = response.choices[0].message.content
            logger(f"Generated response of {len(answer)} characters")

            return answer

    except Exception as e:
        error_msg = f"⚠️ Error processing document: {str(e)}"
        logger(f"ERROR in policy_agent: {error_msg}")
        logger(f"Full traceback: {traceback.format_exc()}")
        return error_msg


def append_feedback_to_vector_file(
    prompt, response, feedback_text, score, client, knowledge_base
):
    """
    Process user feedback and generate refined response
    """
    try:
        if client is None:
            client = get_openai_client()

        # Generate refined response based on feedback
        refinement_prompt = f"""Given a prompt, human feedback on the assistant's last response, and the previous response itself, refine the assistant's response to better align with the feedback while preserving the core intent of the original prompt.

- Carefully analyze the original prompt to determine its main intent and requirements.
- Review the previous response to understand what was said and where it may fall short or conflict with the feedback.
- Read the human feedback thoroughly and reason step by step about each requested change or area for improvement.
- Before revising, think about how the feedback impacts accuracy, tone, completeness, and adherence to user intent.
- Make necessary changes to the response so it fully reflects the feedback, addresses errors or omissions, and better matches the user's needs.
- Keep the response true to the original prompt—do not add or remove substantial information unless required by the feedback.
- Use clear, concise language.

Prompt: {prompt}
Previous Response: {response}
Feedback: {feedback_text}

Provide only the refined response (no meta-commentary):"""

        refined_response_obj = client.chat.completions.create(
            model=MODEL_GPT4O,
            temperature=0.7,
            max_tokens=2048,
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert assistant that refines responses based on user feedback to improve accuracy and helpfulness.",
                },
                {"role": "user", "content": refinement_prompt},
            ],
        )

        refined_response = refined_response_obj.choices[0].message.content
        print(f"Refined response generated: {refined_response[:100]}...")

        # Store feedback in session state
        if "feedback_history" not in st.session_state:
            st.session_state.feedback_history = []

        feedback_entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "prompt": prompt,
            "original_response": response,
            "refined_response": refined_response,
            "feedback": feedback_text,
            "score": score,
        }
        st.session_state.feedback_history.append(feedback_entry)

        # Optional: Update vector store if available
        if knowledge_base and os.environ.get("VECTOR_STORE_ID"):
            try:
                # Read current file content
                knowledge_base.seek(0)
                file_content = knowledge_base.read()

                # Try to parse as JSON
                try:
                    if isinstance(file_content, bytes):
                        file_content_str = file_content.decode("utf-8")
                    else:
                        file_content_str = file_content

                    data = json.loads(file_content_str)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    # If not JSON or can't decode, create new structure
                    data = {"content": "Original document content", "feedback": []}

                # Append new feedback
                if "feedback" not in data:
                    data["feedback"] = []
                data["feedback"].append(feedback_entry)

                # Update vector store
                updated_content = json.dumps(data, indent=2)
                updated_file = io.BytesIO(updated_content.encode("utf-8"))
                updated_file.name = getattr(
                    knowledge_base, "name", "feedback_document.json"
                )

                # Delete old file from vector store
                try:
                    file_list = client.vector_stores.files.list(
                        os.environ["VECTOR_STORE_ID"]
                    )
                    for file in file_list.data:
                        file_name = getattr(
                            file, "filename", getattr(file, "name", str(file.id))
                        )
                        if file_name == updated_file.name:
                            client.vector_stores.files.delete(
                                vector_store_id=os.environ["VECTOR_STORE_ID"],
                                file_id=file.id,
                            )
                except Exception as delete_error:
                    print(f"Warning: Could not delete old file: {str(delete_error)}")

                # Upload new version
                new_file = client.files.create(file=updated_file, purpose="assistants")
                client.vector_stores.files.create(
                    vector_store_id=os.environ["VECTOR_STORE_ID"], file_id=new_file.id
                )

                return "✅ Feedback processed and knowledge base updated"

            except Exception as vector_error:
                print(f"Vector store update error: {str(vector_error)}")
                print(f"Full traceback: {traceback.format_exc()}")
                return f"✅ Feedback stored successfully (knowledge base update skipped: {str(vector_error)})"

        return "✅ Feedback stored successfully"

    except Exception as e:
        error_msg = f"❌ Error processing feedback: {str(e)}"
        print(f"Feedback processing error: {error_msg}")
        print(f"Full traceback: {traceback.format_exc()}")
        return error_msg


# ----------------------------------- LLM as a Judge -------------------------------------------- #
#


# Standard library imports
import io
import json
import os
import re
import traceback

# Third-party imports
import streamlit as st
from openai import APIError, RateLimitError
from PyPDF2 import PdfReader
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# Use Databricks client instead of Groq
groq_client = get_openai_client()


# --------------------------------------------------------------------------------------
# LLM RETRY HELPER (for all LLM calls)
# --------------------------------------------------------------------------------------
@retry(
    wait=wait_exponential(multiplier=1, min=2, max=60),
    stop=stop_after_attempt(5),
    retry=retry_if_exception_type(RateLimitError) | retry_if_exception_type(APIError),
    before_sleep=lambda retry_state: print(
        f"Rate limit hit. Retrying call in {retry_state.next_action.sleep} seconds..."
    ),
)
def groq_completion_with_retry(model, messages, temperature, max_tokens):
    """Handles LLM API call with automatic retries on rate limiting."""
    response = groq_client.chat.completions.create(
        model=MODEL_LLAMA,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content


def llm_as_judge_agent(user_input, knowledge_base=None):
    """
    LLM as a Judge using Pure Groq Architecture (llama-3.1-8b-instant) for reliability
    and to minimize TPD risk compared to llama-3.3-70b.
    """
    if knowledge_base is None:
        return "⚠️ Please upload a policy document to evaluate."

    # Guardrail check (assuming run_guardrails is defined)
    is_safe, msg = run_guardrails(user_input)
    if not is_safe:
        return msg

    try:
        # --- PDF Extraction ---
        GENERATOR_MODEL = MODEL_LLAMA
        JUDGE_MODEL = MODEL_LLAMA

        with st.spinner("Preparing the LLM..."):
            # ... (PDF extraction logic remains the same) ...
            if isinstance(knowledge_base, str):
                with open(knowledge_base, "rb") as f:
                    pdf_content = f.read()
            else:
                knowledge_base.seek(0)
                pdf_content = knowledge_base.read()

            pdf_reader = PdfReader(io.BytesIO(pdf_content))
            full_text = ""
            for page_num, page in enumerate(pdf_reader.pages):
                page_text = page.extract_text()
                full_text += f"\n{page_text}\n"

            max_chars = 12000
            if len(full_text) > max_chars:
                full_text = (
                    full_text[:max_chars] + "\n\n[Document truncated for token limit]"
                )

        # Step 1: Generate initial response (USING GROQ + RETRY)
        with st.spinner(f"📝 Generating response..."):
            initial_messages = [
                {
                    "role": "system",
                    "content": "You are an expert on Caltrans Standard Plans. Provide detailed, accurate answers based on the document. Do NOT include any HTML tags in your response.",
                },
                {
                    "role": "user",
                    "content": f"Document:\n{full_text}\n\nQuestion: {user_input}\n\nProvide a comprehensive answer:",
                },
            ]

            initial_answer = groq_completion_with_retry(
                model=GENERATOR_MODEL,
                messages=initial_messages,
                temperature=0.3,
                max_tokens=1200,
            )
            initial_answer = re.sub(r"</?\s*div\s*>", "", initial_answer)

        # Step 2: Judge evaluates (USING GROQ + RETRY) - Reverting to 0.0-1.0 scale
        with st.spinner(f"⚖️ Evaluating with Judge..."):
            judge_prompt = f"""You are an expert evaluator for technical documentation responses.
Question: {user_input}
Response to evaluate:{initial_answer}
Evaluate on these criteria (0.0 - 1.0 float scale):
1. Accuracy: Factually correct based on Caltrans standards
2. Completeness: Fully answers the question
3. Relevance: Stays on topic
4. Clarity: Well-structured and understandable

Provide JSON ONLY. Ensure scores are floats (e.g., 0.8, 1.0).
{{
    "accuracy_score": 0.0,
    "completeness_score": 0.0,
    "relevance_score": 0.0,
    "clarity_score": 0.0,
    "overall_score": 0.0,
    "strengths": ["list", "strengths"],
    "weaknesses": ["list", "weaknesses"],
    "improvement_suggestions": ["specific", "suggestions"],
    "verdict": "PASS or FAIL"
}}"""

            judge_messages = [
                {
                    "role": "system",
                    "content": "You are an expert evaluator. Respond ONLY with valid JSON.",
                },
                {"role": "user", "content": judge_prompt},
            ]

            judge_text = groq_completion_with_retry(
                model=JUDGE_MODEL,
                messages=judge_messages,
                temperature=0.1,
                max_tokens=600,
            )

            # Robust JSON cleaning
            judge_text = re.sub(r"```json|```", "", judge_text, flags=re.I).strip()

            json_start = judge_text.find("{")
            json_end = judge_text.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                judge_text = judge_text[json_start:json_end]

            evaluation = json.loads(judge_text)

        # Step 3: Generate refined response IF judge says FAIL (USING GROQ + RETRY)
        verdict = evaluation.get("verdict", "PASS")
        refined_answer = None

        if verdict == "FAIL":
            with st.spinner(
                f"🔄 Generating improved response with Groq {GENERATOR_MODEL}..."
            ):
                refinement_prompt = f"""The following response was evaluated and needs improvement.
Original Question: {user_input}
Original Response:{initial_answer}
Issues identified:
- Weaknesses: {", ".join(evaluation.get("weaknesses", []))}
- Suggestions: {", ".join(evaluation.get("improvement_suggestions", []))}

Generate an IMPROVED response that addresses these issues. Use the document below:{full_text}

Provide a better answer (do NOT include any HTML tags):"""

                refinement_messages = [
                    {
                        "role": "system",
                        "content": "You are an expert improving technical responses based on feedback. Do NOT include any HTML tags.",
                    },
                    {"role": "user", "content": refinement_prompt},
                ]

                refined_answer = groq_completion_with_retry(
                    model=GENERATOR_MODEL,
                    messages=refinement_messages,
                    temperature=0.3,
                    max_tokens=1200,
                )
                refined_answer = re.sub(r"</?\s*div\s*>", "", refined_answer)

        # Step 4: Format output
        def format_output(answer, evaluation, verdict, refined=None):
            verdict_icon = "✅" if verdict == "PASS" else "❌"

            output = f"""#### Response generated by the LLM "Llama 4 Scout 17B".".
{answer}

---

<details>
<summary><b>Response evaluated by the LLM "{JUDGE_MODEL}" (Judge LLM).</b></summary>

**Overall Score:** {evaluation.get("overall_score", 0):.2f} / 1.0 - **{verdict_icon} {verdict}**

**Detailed Scores (0.0-1.0 Scale):**
- Accuracy: {evaluation.get("accuracy_score", 0):.2f}
- Completeness: {evaluation.get("completeness_score", 0):.2f}
- Relevance: {evaluation.get("relevance_score", 0):.2f}
- Clarity: {evaluation.get("clarity_score", 0):.2f}

**Strengths:**
{chr(10).join([f"- {s}" for s in evaluation.get("strengths", ["N/A"])])}

**Weaknesses:**
{chr(10).join([f"- {w}" for w in evaluation.get("weaknesses", ["N/A"])])}

"""
            if refined:
                output += f"""
**Improvement Suggestions:**
{chr(10).join([f"- {s}" for s in evaluation.get("improvement_suggestions", ["N/A"])])}
"""
            output += "</details>"

            if refined:
                output = (
                    f"## ✅ Improved Response\n{refined}\n\n---\n\n<details><summary><b>🔍 View Initial Response & Evaluation Details</b></summary>\n\n### 📋 Initial Response\n{answer}\n\n---"
                    + output[output.find("### Response evaluated by the LLM") :]
                )

            return output

        final_output = format_output(
            initial_answer, evaluation, verdict, refined=refined_answer
        )
        return final_output

    except RateLimitError:
        return "❌ Severe API Rate Limit Error (429): The Groq operation failed after 5 retries due to rate limiting (TPD limit likely). Please wait several minutes and try again."
    except json.JSONDecodeError:
        # Initial answer is still available
        return f"## 📋 Response\n\n{initial_answer}\n\n⚠️ Judge evaluation unavailable (Groq JSON formatting error)"
    except Exception as e:
        return f"⚠️ General Error: {str(e)}\n\n{traceback.format_exc()}"
