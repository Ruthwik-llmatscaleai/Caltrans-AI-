import time

import streamlit as st
from streamlit_feedback import streamlit_feedback

from src.highway_incident_summarizer import summarize_caltrans_incidents
from src.personal_narrative_insights import personal_narrative_insights
from src.reentry_care_plan import (
    append_feedback_to_vector_file,
    policy_agent,
    run_guardrails,
)


def text_based(usecase_option, knowledge_base):
    # --- New Logic ---
    if "current_usecase" not in st.session_state:
        st.session_state["current_usecase"] = usecase_option
        st.session_state["reset_needed"] = False
    elif st.session_state["current_usecase"] != usecase_option:
        st.session_state["current_usecase"] = usecase_option
        st.session_state["reset_needed"] = True
    # --- End New Logic ---
    m1, m2, m3 = st.columns([1, 7, 1])

    with m2:
        st.write("## ")

        # Special handling for LLM Training
        if usecase_option == "LLM Training":
            # Check if we have training data loaded
            if knowledge_base is not None:
                from src.llm_training import llm_finetuning_agent, perform_training

                # Get initial response (file info)
                initial_response = llm_finetuning_agent("", knowledge_base)

                if initial_response:
                    # Show file info
                    st.markdown(initial_response, unsafe_allow_html=True)
                    return

                # File is loaded, show training button
                if not st.session_state.get("model_trained", False):
                    st.markdown("## 📁 Training Data Loaded")
                    st.markdown(
                        f"**File:** {st.session_state.get('training_file_name', 'Unknown')}"
                    )
                    st.markdown(
                        f"**Examples:** {len(st.session_state.get('training_data', []))}"
                    )

                    # Preview
                    if st.session_state.get("training_data"):
                        with st.expander("📋 View First Example"):
                            st.json(st.session_state["training_data"][0])

                    st.markdown("---")

                    # Small, simple training button
                    col1, col2, col3 = st.columns([1, 2, 1])
                    with col2:
                        if st.button("🚀 Train Model", type="primary"):
                            # Perform training
                            training_summary = perform_training(
                                st.session_state["training_data"],
                                st.session_state["training_file_name"],
                            )

                            if training_summary:
                                st.markdown(training_summary, unsafe_allow_html=True)
                                st.session_state["model_trained"] = True
                                st.session_state["training_data_size"] = len(
                                    st.session_state["training_data"]
                                )
                                st.rerun()

                    return
                else:
                    # Model is trained, show status message
                    st.success("✅ Model training has been completed successfully!")
                    st.markdown("""
**Try these sample prompts:**
- "What is the purpose of chamfer requirements in Plan A76A?"
- "What is the role of PCC base in barrier construction?"
- "How do Caltrans standard plans ensure roadway safety?"
                    """)
                    st.markdown("---")
            else:
                # No file uploaded yet
                from src.llm_training import llm_finetuning_agent

                response = llm_finetuning_agent("", None)
                st.markdown(response, unsafe_allow_html=True)
                return

        # ---------------- Session initialization ----------------
        if "history" not in st.session_state or st.session_state.get("reset_needed"):
            st.session_state["history"] = []
            st.session_state["generated"] = [
                "Greetings! I am LLMAI Live Agent. How can I help you?"
            ]
            st.session_state["past"] = [
                "We are delighted to have you here in the LLMAI Live Agent Chat room!"
            ]
            # Crucially, reset the evaluation flag
            st.session_state.pop("evaluated_ix", None)
            st.session_state["reset_needed"] = False  # clear the flag

        if "generated" not in st.session_state:
            # (Keep the original checks in case 'reset_needed' failed for some reason,
            # though they are now redundant if the above block runs correctly)
            st.session_state["generated"] = [
                "Greetings! I am LLMAI Live Agent. How can I help you?"
            ]

        # ---------------- Input and button ----------------
        response_container = st.container()
        container = st.container()

        with container:
            with st.form(key="my_form", clear_on_submit=True):
                user_input = st.text_input(
                    "Prompt:", placeholder="How can I help you?", key="input"
                )
                submit_button = st.form_submit_button(label="Interact with LLM")

            if submit_button and user_input:
                if (
                    usecase_option == "RAG-Document Intelligence"
                    or usecase_option == "Human in the feedback Loop"
                ):
                    st.session_state.knowledge_base = knowledge_base
                    vAR_Response = policy_agent(user_input, knowledge_base)
                    if knowledge_base is None:
                        return st.error("Please upload the policy analysis file")
                elif usecase_option == "LLM as a Judge":
                    from src.reentry_care_plan import llm_as_judge_agent

                    st.session_state.knowledge_base = knowledge_base
                    vAR_Response = llm_as_judge_agent(user_input, knowledge_base)
                elif usecase_option == "LLM Training":
                    from src.llm_training import llm_finetuning_agent

                    st.session_state.knowledge_base = knowledge_base
                    vAR_Response = llm_finetuning_agent(user_input, knowledge_base)
                elif usecase_option == "LLM Evaluation":
                    from src.llm_evaluation import llm_evaluation_agent

                    st.session_state.knowledge_base = knowledge_base
                    vAR_Response = llm_evaluation_agent(user_input, knowledge_base)
                elif usecase_option == "Highway Incident Summarizer Bot":
                    vAR_Response = summarize_caltrans_incidents(user_input)
                elif usecase_option == "Guardrails":
                    is_safe, msg = run_guardrails(user_input)
                    vAR_Response = (
                        msg if not is_safe else "Your input passed the safety checks."
                    )
                elif usecase_option == "Personal Narrative Insights":
                    vAR_Response = personal_narrative_insights(user_input)

                # elif usecase_option == "CUCP Re-Evaluations":
                #     vAR_Response = cucp_reevaluations(user_input)

                # src/chat_ui.py
                st.session_state["past"].append(user_input)
                st.session_state["generated"].append(vAR_Response)
                # mark the newest answer as “just created”
                st.session_state["evaluated_ix"] = (
                    len(st.session_state["generated"]) - 1
                )

        # ---------------- Response display ----------------
        if st.session_state["generated"]:
            with response_container:
                for i in range(len(st.session_state["generated"])):
                    # Display user message in blue box (right-aligned)
                    st.markdown(
                        f"""
                        <div style="display: flex; justify-content: flex-end; margin-bottom: 1rem;">
                            <div style="
                                background: linear-gradient(135deg, #e3f2fd 0%, #bbdefb 100%);
                                padding: 12px 16px;
                                border-radius: 12px;
                                max-width: 75%;
                                box-shadow: 0 2px 4px rgba(0,0,0,0.08);
                                border-left: 4px solid #2196f3;
                            ">
                                <div style="font-weight: 600; color: #1976d2; font-size: 13px; margin-bottom: 4px;">You</div>
                                <div style="color: #333; font-size: 15px; line-height: 1.5;">{st.session_state["past"][i]}</div>
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                    # Display Assistant response
                    current_response = st.session_state["generated"][i]

                    st.markdown(
                        """
                        <div style="display: flex; justify-content: flex-start; margin-bottom: 0.5rem;">
                            <div style="
                                background: linear-gradient(135deg, #f5f5f5 0%, #eeeeee 100%);
                                padding: 8px 12px;
                                border-radius: 8px;
                                box-shadow: 0 2px 4px rgba(0,0,0,0.08);
                                border-left: 4px solid #3b82c8;
                            ">
                                <div style="font-weight: 600; color: #3b82c8; font-size: 13px;">Assistant</div>
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                    # Render response content
                    st.markdown(current_response, unsafe_allow_html=True)
                    # ----------  Evaluate Response button for the newest answer only  ----------
                    if usecase_option == "LLM Evaluation" and i == st.session_state.get(
                        "evaluated_ix"
                    ):
                        # Check if already evaluated
                        eval_key = f"eval_results_{i}"

                        if eval_key not in st.session_state:
                            # Button hasn't been clicked yet - show button
                            if st.button(
                                "🔍 Evaluate Response",
                                key=f"eval_btn_{i}",
                                type="primary",
                            ):
                                from src.llm_evaluation import evaluate_last_response

                                # Run evaluation and store results
                                eval_output = evaluate_last_response()
                                st.session_state[eval_key] = eval_output
                                st.rerun()
                        else:
                            # Already evaluated - show results (no button)
                            st.markdown(
                                st.session_state[eval_key], unsafe_allow_html=True
                            )
                    # ----------  end  ----------

                    # ---- Legacy thumbs feedback (keep as-is) ----
                    if usecase_option not in [
                        "LLM as a Judge",
                        "LLM Training",
                        "LLM Evaluation",
                    ]:
                        feedback_ = streamlit_feedback(
                            align="flex-start",
                            feedback_type="thumbs",
                            optional_text_label="[ Human Feedback Optional ] Please provide an explanation",
                            key=f"thumbs_{i}",
                        )

                        if feedback_ and "score" in feedback_:
                            prompt = st.session_state["past"][i]
                            response = st.session_state["generated"][i]
                            feedback_text = feedback_.get("text", "")
                            score = feedback_.get("score", None)

                            if score is not None:
                                result = append_feedback_to_vector_file(
                                    prompt,
                                    response,
                                    feedback_text,
                                    score,
                                    st.session_state.client,
                                    st.session_state.knowledge_base,
                                )
                                if result.startswith("✅"):
                                    st.success(result)
                                    if (
                                        "feedback_history" in st.session_state
                                        and st.session_state.feedback_history
                                        and "refined_response"
                                        in st.session_state.feedback_history[-1]
                                    ):
                                        st.session_state["generated"][i] = (
                                            st.session_state.feedback_history[-1][
                                                "refined_response"
                                            ]
                                        )
                                        st.rerun()
                                else:
                                    st.error(result)

                                st.success("Thank you for your feedback!")
