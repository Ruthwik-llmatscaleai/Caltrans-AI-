import json
from io import BytesIO
from pathlib import Path

import streamlit as st

from src.ai_content_detector import (
    detect_ai_content,
    extract_text_from_file,
    generate_detector_docx,
    generate_detector_report,
)
from src.ai_judge import (
    generate_judge_docx,
    generate_judge_report,
    judge_detector_output,
)


RESULT_KEY = "ai_content_detector_ui_result"


def _safe_stem(source_name: str) -> str:
    stem = Path(source_name).stem or "narrative"
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in stem)


def _read_narrative(uploaded_file, pasted_text: str) -> tuple[str, str]:
    if uploaded_file is None:
        return pasted_text.strip(), "Pasted narrative"

    source_name = uploaded_file.name or "Uploaded narrative"
    file_bytes = uploaded_file.getvalue()
    if source_name.lower().endswith(".txt"):
        return file_bytes.decode("utf-8", errors="replace"), source_name

    return extract_text_from_file(BytesIO(file_bytes), source_name), source_name


def _store_result(source_name: str, detector_result: dict, judge_result: dict | None) -> None:
    st.session_state[RESULT_KEY] = {
        "source_name": source_name,
        "detector_result": detector_result,
        "judge_result": judge_result,
    }


def _render_downloads(source_name: str, detector_result: dict, judge_result: dict | None) -> None:
    safe_stem = _safe_stem(source_name)

    detector_col, detector_json_col = st.columns(2)
    with detector_col:
        st.download_button(
            "Download detector report (.docx)",
            data=generate_detector_docx(detector_result, source_name),
            file_name=f"{safe_stem}_ai_content_detector.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    with detector_json_col:
        st.download_button(
            "Download detector JSON",
            data=json.dumps(detector_result, indent=2),
            file_name=f"{safe_stem}_ai_content_detector.json",
            mime="application/json",
        )

    if judge_result:
        judge_col, judge_json_col = st.columns(2)
        with judge_col:
            st.download_button(
                "Download judge audit (.docx)",
                data=generate_judge_docx(judge_result, detector_result, source_name),
                file_name=f"{safe_stem}_ai_judge_audit.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        with judge_json_col:
            st.download_button(
                "Download judge JSON",
                data=json.dumps(judge_result, indent=2),
                file_name=f"{safe_stem}_ai_judge_audit.json",
                mime="application/json",
            )


def ai_content_detector_ui() -> None:
    st.subheader("AI Content Detector")
    st.caption("Analyze a personal narrative and audit the detector output with the LLM judge.")

    uploaded_file = st.file_uploader(
        "Upload narrative",
        type=["pdf", "doc", "docx", "txt"],
        key="ai_content_detector_upload",
    )
    pasted_text = st.text_area(
        "Or paste narrative text",
        height=220,
        key="ai_content_detector_pasted_text",
    )
    run_judge = st.checkbox(
        "Run judge audit after detection",
        value=True,
        key="ai_content_detector_run_judge",
    )

    has_input = uploaded_file is not None or bool(pasted_text.strip())
    if st.button("Analyze Narrative", type="primary", disabled=not has_input):
        try:
            narrative_text, source_name = _read_narrative(uploaded_file, pasted_text)
        except Exception as exc:
            print(f"AI content detector file read failed: {type(exc).__name__}")
            st.error("Could not read that file. Please upload a text-based PDF, DOC, DOCX, or TXT file.")
            st.stop()

        if not narrative_text.strip():
            st.error("No readable narrative text found.")
            st.stop()

        with st.spinner("Running AI content detector..."):
            detector_result = detect_ai_content(narrative_text)

        if "error" in detector_result:
            print("AI content detector model call failed.")
            st.error("The detector could not complete the analysis. Please check the local API configuration.")
            st.stop()

        judge_result = None
        if run_judge:
            with st.spinner("Running judge audit..."):
                judge_result = judge_detector_output(narrative_text, detector_result)
            if judge_result and "error" in judge_result:
                print("AI content detector judge call failed.")
                judge_result = None
                st.warning("Detector finished, but the judge audit could not complete.")

        _store_result(source_name, detector_result, judge_result)

    result = st.session_state.get(RESULT_KEY)
    if not result:
        return

    source_name = result["source_name"]
    detector_result = result["detector_result"]
    judge_result = result.get("judge_result")

    st.markdown("---")
    st.markdown(f"#### Detector Result: {source_name}")
    st.markdown(generate_detector_report(detector_result, source_name))

    if judge_result:
        st.markdown("---")
        st.markdown("#### Judge Audit")
        st.markdown(generate_judge_report(judge_result, detector_result, source_name))

    _render_downloads(source_name, detector_result, judge_result)
