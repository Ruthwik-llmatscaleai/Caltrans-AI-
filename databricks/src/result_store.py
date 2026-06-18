"""
Result Store — SQLite-based persistence for the two-stage agentic pipeline.

Stage 1: input fingerprint → system prompt
Stage 2: prompt fingerprint → generated code (LLM output)
"""

import hashlib
import json
import os
import sqlite3
import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "result_store.db")


def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS results (
            fingerprint TEXT NOT NULL,
            stage TEXT NOT NULL,
            value TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (fingerprint, stage)
        )
    """)
    conn.commit()
    return conn


def compute_fingerprint(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def get_stored(fingerprint: str, stage: str):
    conn = _get_conn()
    row = conn.execute(
        "SELECT value FROM results WHERE fingerprint = ? AND stage = ?",
        (fingerprint, stage),
    ).fetchone()
    conn.close()
    if row:
        return json.loads(row[0])
    return None


def store_result(fingerprint: str, stage: str, value) -> None:
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO results (fingerprint, stage, value, created_at) VALUES (?, ?, ?, ?)",
        (fingerprint, stage, json.dumps(value), datetime.datetime.now(datetime.timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


def get_stats():
    conn = _get_conn()
    stage1 = conn.execute("SELECT COUNT(*) FROM results WHERE stage = 'prompt'").fetchone()[0]
    stage2 = conn.execute("SELECT COUNT(*) FROM results WHERE stage = 'code'").fetchone()[0]
    conn.close()
    return {"prompt_entries": stage1, "code_entries": stage2}
