# src/foundation_model_chat.py

import streamlit as st
from openai import AuthenticationError, APIError
from src.databricks_client import get_openai_client, MODEL_GPT4O


def foundation_model_chat_ui():
    col1, col2, col3 = st.columns([1, 7, 1])
    with col2:
        st.subheader("Foundation Model Chat Assistant")

        # st.markdown(
        #     "<p style='font-size:14px; color:gray;'>Ask questions about Caltrans</p>",
        #     unsafe_allow_html=True,
        # )

        # Store chat history in session
        if "foundation_history" not in st.session_state:
            st.session_state.foundation_history = []

        # Input field
        user_input = st.text_input("Enter your prompt:")

        # Button to submit
        if st.button("Interact with the LLM", key="foundation_ask"):
            if user_input.strip():
                with st.spinner("Generating response..."):
                    try:
                        client = get_openai_client()

                        completion = client.chat.completions.create(
                            model=MODEL_GPT4O,
                            messages=[
                                {
                                    "role": "system",
                                    "content": (
                                        "You are a helpful assistant that answers questions factually and concisely "
                                        "about California probation associations, officers, and general knowledge.\n\n"
                                        "If the user asks about PITMA, respond with:\n"
                                        "'The Probation Information Technology Managers Association (PITMA), along with the Probation Business Managers Association (PBMA), supports California’s Chief Probation Officers and county probation departments. They provide a platform for professionals to collaborate and solve fiscal, IT, and administrative challenges in criminal and juvenile justice.'\n\n"
                                        "If the user asks about the website of PITMA, respond with:\n"
                                        "'The official website of PITMA (Probation and Pretrial Managers Association) is https://pbma-pitma.memberclicks.net/'\n\n"
                                        "If the user asks about the Chief Probation Officers of California, respond with:\n"
                                        "'The Chief Probation Officers of California (CPOC) is an association of all 58 counties' probation chiefs. CPOC promotes a research-based approach to public safety, rehabilitation, and community corrections. Their work spans client accountability, victim restoration, and policy leadership in juvenile and adult justice.'\n\n"
                                        "If the user asks to list Chief Probation Officers in California, reply with:\n"
                                        "'You can view the full list of California Chief Probation Officers at: https://www.cpoc.org/all-chiefs'\n"
                                    ),
                                },
                                {"role": "user", "content": user_input},
                            ],
                        )
                        response = completion.choices[0].message.content
                        st.session_state.foundation_history.append((user_input, response))
                    
                    except AuthenticationError:
                        st.error("Authentication Error: The OpenAI API key provided is invalid or does not have access to the requested project/model. Please check your .env file.")
                    except APIError as e:
                        st.error(f"OpenAI API Error: {str(e)}")
                    except Exception as e:
                        st.error(f"An unexpected error occurred: {str(e)}")

            else:
                st.warning("Please enter a question before asking.")

        # Display chat history
        if st.session_state.foundation_history:
            st.markdown("### Conversation History")
            for q, a in st.session_state.foundation_history:
                st.write(f"*Q:* {q}")
                st.write(f"*A:* {a}")
