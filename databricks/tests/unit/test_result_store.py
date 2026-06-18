"""
Unit tests for the Result Store module.

Run: pytest tests/unit/test_result_store.py -v
"""

import os
import sys
import tempfile
import pytest

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.result_store import compute_fingerprint, get_stored, store_result, get_stats, DB_PATH


@pytest.fixture(autouse=True)
def use_temp_db(monkeypatch, tmp_path):
    """Use a temporary database for each test."""
    temp_db = str(tmp_path / "test_store.db")
    monkeypatch.setattr("src.result_store.DB_PATH", temp_db)
    yield temp_db


class TestFingerprint:
    def test_same_input_same_hash(self):
        assert compute_fingerprint("hello") == compute_fingerprint("hello")

    def test_different_input_different_hash(self):
        assert compute_fingerprint("hello") != compute_fingerprint("world")

    def test_whitespace_matters(self):
        assert compute_fingerprint("hello ") != compute_fingerprint("hello")

    def test_returns_64_char_hex(self):
        fp = compute_fingerprint("test")
        assert len(fp) == 64
        assert all(c in "0123456789abcdef" for c in fp)


class TestStoreAndRetrieve:
    def test_store_and_get(self):
        fp = compute_fingerprint("test_input")
        store_result(fp, "prompt", {"system_prompt": "You are...", "user_message": "Evaluate..."})

        result = get_stored(fp, "prompt")
        assert result is not None
        assert result["system_prompt"] == "You are..."
        assert result["user_message"] == "Evaluate..."

    def test_miss_returns_none(self):
        result = get_stored("nonexistent_fingerprint", "prompt")
        assert result is None

    def test_stage_separation(self):
        fp = compute_fingerprint("same_key")
        store_result(fp, "prompt", {"data": "prompt_value"})
        store_result(fp, "code", {"data": "code_value"})

        prompt_result = get_stored(fp, "prompt")
        code_result = get_stored(fp, "code")

        assert prompt_result["data"] == "prompt_value"
        assert code_result["data"] == "code_value"

    def test_overwrite_on_same_key(self):
        fp = compute_fingerprint("overwrite_test")
        store_result(fp, "prompt", {"version": 1})
        store_result(fp, "prompt", {"version": 2})

        result = get_stored(fp, "prompt")
        assert result["version"] == 2

    def test_complex_json_value(self):
        fp = compute_fingerprint("complex")
        complex_data = {
            "ratings": [{"question_id": "A1", "selected_rating": "B", "confidence": 0.85}],
            "summary": "Test summary",
            "nested": {"deep": [1, 2, 3]},
        }
        store_result(fp, "code", complex_data)

        result = get_stored(fp, "code")
        assert result["ratings"][0]["question_id"] == "A1"
        assert result["nested"]["deep"] == [1, 2, 3]


class TestStats:
    def test_empty_stats(self):
        stats = get_stats()
        assert stats["prompt_entries"] == 0
        assert stats["code_entries"] == 0

    def test_counts_by_stage(self):
        store_result("fp1", "prompt", {"a": 1})
        store_result("fp2", "prompt", {"b": 2})
        store_result("fp3", "code", {"c": 3})

        stats = get_stats()
        assert stats["prompt_entries"] == 2
        assert stats["code_entries"] == 1
