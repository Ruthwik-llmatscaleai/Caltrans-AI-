"""
Shared OpenAI-compatible client for Databricks Apps.

Uses the Databricks SDK WorkspaceClient to authenticate via the app's
service principal (no API keys needed). All modules import get_openai_client()
instead of instantiating OpenAI() directly.
"""
import os
from openai import OpenAI

_client = None

# Model mappings — matching original app's model choices
MODEL_GPT4O = "databricks-gpt-5-4-mini"
MODEL_GPT4O_MINI = "databricks-gpt-5-4-mini"
MODEL_GPT4_1 = "databricks-gpt-5-4-mini"
MODEL_LLAMA = "databricks-meta-llama-3-3-70b-instruct"
MODEL_CLAUDE_SONNET = "databricks-claude-sonnet-4-6"

# Default for backward compat
DATABRICKS_MODEL = MODEL_GPT4O


def get_openai_client() -> OpenAI:
    global _client
    if _client is not None:
        return _client

    from databricks.sdk import WorkspaceClient

    w = WorkspaceClient()
    auth_headers = w.config.authenticate()
    token = auth_headers.get("Authorization", "").replace("Bearer ", "")
    host = w.config.host.rstrip("/")

    _client = OpenAI(
        api_key=token,
        base_url=f"{host}/serving-endpoints",
    )
    return _client
