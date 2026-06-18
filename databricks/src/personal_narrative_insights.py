import os
from src.databricks_client import get_openai_client, MODEL_GPT4O


SYSTEM_PROMPT = """You are a Caltrans personal narrative analysis assistant.
You help analyze personal narratives for DBE (Disadvantaged Business Enterprise) certification applications.
Provide insightful analysis of the narrative content, identifying key themes, strengths,
and areas that may need additional documentation or clarification."""


def personal_narrative_insights(user_input):
    """
    Uses Databricks model endpoint to generate personal narrative insights.

    Args:
        user_input: The user's input/question

    Returns:
        str: The model's response
    """
    client = get_openai_client()

    try:
        response = client.chat.completions.create(
            model=MODEL_GPT4O,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_input},
            ],
            temperature=0.4,
            max_tokens=4096,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Error calling model: {str(e)}"
