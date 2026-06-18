# llm_evaluation.py
import os
import time

import PyPDF2
import streamlit as st
from deepeval.metrics import (
    AnswerRelevancyMetric,
    BiasMetric,
    ContextualRelevancyMetric,
    GEval,
    HallucinationMetric,
)
from deepeval.test_case import LLMTestCase, LLMTestCaseParams
from src.databricks_client import get_openai_client, MODEL_LLAMA

groq_client = get_openai_client()


# ---------- Main agent ----------
def llm_evaluation_agent(user_input, knowledge_base=None):
    if not user_input:
        return """
## LLM Evaluation Platform

**Upload a PDF policy document above, then ask questions.**

### Sample Questions:
- "What changes were made to Plan A76A in 2024?"
- "Explain chamfer requirements in concrete barriers"
- "Why was #5 bar preferred over #4 bar?"

---

*After receiving a response, click **"Evaluate Response"** for DeepEval metrics.*
"""

    if knowledge_base is None:
        return "⚠️ Please upload a policy document first."

    try:
        knowledge_base.seek(0)
        pdf_reader = PyPDF2.PdfReader(knowledge_base)
        total_pages = len(pdf_reader.pages)

        # Extract MORE pages for LLM generation (up to 7 pages or all if less)
        llm_page_count = total_pages
        chunks_for_llm = []
        for page_num in range(llm_page_count):
            text = pdf_reader.pages[page_num].extract_text() or ""
            if text:
                chunks_for_llm.append(text)

        # Extract FULL document for judge evaluation (up to 12 pages)
        full_document_pages = []
        knowledge_base.seek(0)
        pdf_reader_full = PyPDF2.PdfReader(knowledge_base)
        judge_page_count = min(12, total_pages)
        for page_num in range(judge_page_count):
            text = pdf_reader_full.pages[page_num].extract_text() or ""
            if text:
                full_document_pages.append(text)

        # Store both versions
        st.session_state["full_document_pages"] = full_document_pages
        st.session_state["llm_page_count"] = llm_page_count
        st.session_state["judge_page_count"] = judge_page_count

    except Exception as e:
        return f"⚠️ Could not read PDF: {str(e)}"

    # Generate response using EXPANDED context (7 pages)
    context_for_generation = "\n\n".join(chunks_for_llm)[:8000]  # Increased from 3000

    with st.spinner("Generating response from document..."):
        response = groq_client.chat.completions.create(
            model=MODEL_LLAMA,
            temperature=0.3,
            max_tokens=500,  # Increased from 400
            messages=[
                {
                    "role": "system",
                    "content": f"Answer based solely on this document:\n\n{context_for_generation}",
                },
                {"role": "user", "content": user_input},
            ],
        )

    llm_response = response.choices[0].message.content

    # Store for evaluation
    st.session_state["last_query"] = user_input
    st.session_state["last_chunks_used"] = chunks_for_llm
    st.session_state["last_answer"] = llm_response

    return llm_response


# ---------- DeepEval Evaluation with Full Document Context + G-Eval Clarity ----------
def evaluate_last_response():
    if "last_answer" not in st.session_state:
        return "⚠️ No response to evaluate yet."

    query = st.session_state["last_query"]
    answer = st.session_state["last_answer"]
    chunks_used_by_llm = st.session_state["last_chunks_used"]
    full_document_pages = st.session_state.get(
        "full_document_pages", chunks_used_by_llm
    )
    llm_page_count = st.session_state.get("llm_page_count", 3)
    judge_page_count = st.session_state.get("judge_page_count", 10)

    # Status indicators
    col1, col2, col3 = st.columns(3)

    with col1:
        status1 = st.status("Request Evaluation", expanded=True)
        with status1:
            st.write("Processing...")
            time.sleep(0.3)
        status1.update(label="Request ✅", state="complete", expanded=False)

    with col2:
        status2 = st.status("Retrieval Evaluation", expanded=True)
        with status2:
            st.write("Analyzing context...")
            time.sleep(0.3)
        status2.update(label="Retrieval ✅", state="complete", expanded=False)

    with col3:
        status3 = st.status("Response Evaluation", expanded=True)

    # Create DeepEval test case
    test_case = LLMTestCase(
        input=query,
        actual_output=answer,
        expected_output="A comprehensive answer based on the document.",
        retrieval_context=chunks_used_by_llm,  # What LLM saw (7 pages)
        context=full_document_pages,  # What judge sees (12 pages)
    )

    # Define G-Eval Clarity metric
    clarity_metric = GEval(
        name="Clarity",
        evaluation_steps=[
            "Evaluate whether the response uses clear and direct language",
            "Check if technical terms are explained appropriately",
            "Assess whether the structure is logical and easy to follow",
            "Identify any confusing parts that reduce understanding",
        ],
        evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT],
        threshold=0.7,
    )

    # DeepEval metrics with ContextualRelevancyMetric instead of Faithfulness
    metrics_list = [
        ("Answer Relevancy", AnswerRelevancyMetric(threshold=0.7, include_reason=True)),
        (
            "Contextual Relevancy",
            ContextualRelevancyMetric(threshold=0.7, include_reason=True),
        ),
        (
            "Hallucination",
            HallucinationMetric(threshold=0.5, include_reason=True, strict_mode=True),
        ),
        ("Bias", BiasMetric(threshold=0.5, include_reason=True)),
        ("Clarity (G-Eval)", clarity_metric),
    ]

    results = {}
    overall_score = 0
    total_metrics = len(metrics_list)

    for idx, (name, metric) in enumerate(metrics_list, 1):
        try:
            with status3:
                st.write(f"Evaluating {name}... ({idx}/{total_metrics})")

            metric.measure(test_case)

            score = round(metric.score, 3)
            reason = getattr(metric, "reason", "N/A")

            results[name] = {"score": score, "reason": reason}

            # Calculate overall
            if name in ["Hallucination", "Bias"]:
                overall_score += 1 - score
            else:
                overall_score += score

        except Exception as e:
            error_msg = str(e)[:200]
            results[name] = {"score": 0.0, "reason": f"Evaluation error: {error_msg}"}

    overall_score = round(overall_score / total_metrics, 3)
    status3.update(label="Evaluation ✅", state="complete", expanded=False)

    # Build HTML
    if overall_score >= 0.8:
        color, grade = "#4CAF50", "Excellent"
    elif overall_score >= 0.7:
        color, grade = "#FFC107", "Good"
    else:
        color, grade = "#FF5722", "Needs Improvement"

    html = f"""
<div style='margin-top: 20px;'>
<div style='padding: 12px; border-radius: 8px; background: {color}20; border-left: 4px solid {color}; display: inline-block;'>
    <h3 style='margin: 0; color: {color};'>Overall Score: {overall_score:.3f} - {grade}</h3>
</div>

<h3 style='margin-top: 20px;'>DeepEval Metrics (Standard + G-Eval)</h3>

<table style='width: 100%; border-collapse: collapse;'>
<tr style='background: #f5f5f5;'>
    <th style='padding: 10px; width: 22%; text-align: left;'>Metric</th>
    <th style='padding: 10px; width: 12%;'>Score</th>
    <th style='padding: 10px; width: 66%; text-align: left;'>Reasoning</th>
</tr>
"""

    for name, data in results.items():
        score = data["score"]
        reason = str(data["reason"])

        if name in ["Hallucination", "Bias"]:
            sc = "#4CAF50" if score <= 0.3 else "#FFC107" if score <= 0.5 else "#FF5722"
        else:
            sc = "#4CAF50" if score >= 0.7 else "#FFC107" if score >= 0.5 else "#FF5722"

        # Add strict mode indicator for Hallucination
        strict_indicator = " (Strict)" if name == "Hallucination" else ""

        html += f"""
<tr style='border-bottom: 1px solid #e0e0e0;'>
    <td style='padding: 10px; vertical-align: top;'><strong>{name}{strict_indicator}</strong></td>
    <td style='padding: 10px; text-align: center; vertical-align: top;'>
        <span style='background: {sc}; color: white; padding: 5px 10px; border-radius: 4px; font-weight: bold;'>{score:.3f}</span>
    </td>
    <td style='padding: 10px; font-size: 0.95em; word-wrap: break-word; line-height: 1.5;'>{reason}</td>
</tr>
"""

    html += f"""
</table>
<p style='margin-top: 20px; font-size: 0.9em; color: #666;'>
    <em>Evaluated using DeepEval framework with OpenAI GPT-4o-mini</em><br>
    <em>LLM used {llm_page_count} pages, Judge evaluated against {judge_page_count} pages</em><br>
</p>
</div>
"""

    return html
