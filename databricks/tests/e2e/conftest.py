"""
Playwright E2E test fixtures for the Caltrans Databricks Streamlit app.

Usage:
    pip install playwright pytest-playwright
    playwright install chromium
    pytest tests/e2e/ --base-url http://localhost:8501
"""

import pytest
import subprocess
import time
import os

APP_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEST_PDF_PATH = os.path.join(APP_DIR, "tests", "e2e", "fixtures", "sample_nomination.pdf")


@pytest.fixture(scope="session")
def app_url():
    """Return the base URL of the running Streamlit app."""
    return os.environ.get("APP_URL", "http://localhost:8501")


@pytest.fixture(scope="session")
def test_pdf_path():
    """Path to the sample nomination fact sheet used in tests."""
    return TEST_PDF_PATH
