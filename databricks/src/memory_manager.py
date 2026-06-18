import json
import os
import shutil
import datetime as dt
from typing import List, Dict
from openai import OpenAI
from src.databricks_client import get_openai_client, MODEL_GPT4O

MEMORY_FILE = os.path.join(os.path.dirname(__file__), 'memory_db.json')
BACKUP_DIR = os.path.join(os.path.dirname(__file__), 'memory_backups')

def _load_db() -> dict:
    if not os.path.exists(MEMORY_FILE):
        return {
            "level_1_precedents": [],
            "level_2_precedents": [],
            "level_3_precedents": []
        }
    with open(MEMORY_FILE, 'r') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {
                "level_1_precedents": [],
                "level_2_precedents": [],
                "level_3_precedents": []
            }

def _save_db(db: dict):
    with open(MEMORY_FILE, 'w') as f:
        json.dump(db, f, indent=4)

def _backup_db():
    """Create a timestamped backup of memory_db.json before destructive operations."""
    if not os.path.exists(MEMORY_FILE):
        return
    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(BACKUP_DIR, f"memory_db_backup_{timestamp}.json")
    shutil.copy2(MEMORY_FILE, backup_path)

def overwrite_db(new_db: dict):
    """Completely overwrite the memory DB with an uploaded rules.json file."""
    _backup_db()
    _save_db(new_db)

def get_precedent_count(level: int) -> int:
    """Returns the total number of active precedents for the given level."""
    db = _load_db()
    key = f"level_{level}_precedents"
    return len(db.get(key, []))

def get_precedents(level: int) -> List[Dict]:
    """Retrieve precedents for a specific reasoning level (1, 2, or 3)."""
    db = _load_db()
    key = f"level_{level}_precedents"
    return db.get(key, [])

def add_precedent(level: int, target: str, correction: str, reasoning: str):
    """
    Log a human correction as a precedent for future evaluation.
    
    level: 1, 2, or 3
    target: The specific fact, classification, or threshold being modified
    correction: The correct value provided by the analyst
    reasoning: The human's rationale for the change
    """
    db = _load_db()
    key = f"level_{level}_precedents"
    
    db[key].append({
        "target": target,
        "correction": correction,
        "human_reasoning": reasoning
    })
    
    _save_db(db)

def commit_staged_precedents(staged_db: dict):
    """
    Commit a dictionary of staged precedents to the main DB.
    staged_db should have keys: 'level_1_precedents', 'level_2_precedents', 'level_3_precedents'
    """
    db = _load_db()
    
    for level in [1, 2, 3]:
        key = f"level_{level}_precedents"
        if key not in db:
            db[key] = []
        db[key].extend(staged_db.get(key, []))
        
    _save_db(db)

def consolidate_memory_via_llm() -> str:
    """
    Sends the entire raw DB to GPT-4o to deduplicate and synthesize 
    overlapping rules into a clean `rules.json` format.
    Returns the JSON string blob for download.
    """
    # Create a backup before the LLM overwrites the DB
    _backup_db()
    
    db = _load_db()
    client = get_openai_client()
    
    system_prompt = """You are an expert Legal Architect. The user will provide a raw JSON dump of an Institutional Memory Database containing piece-meal human overrides.
Your job is to read all precedents across level_1, level_2, and level_3.
Find overlapping or duplicate human corrections, and synthesize them into single, broader, clear rules.
If corrections conflict, keep the most logically sound and comprehensive interpretation.

Return exactly valid JSON matching this structure:
{
  "level_1_precedents": [ { "target": "Context", "correction": "Unified Rule", "human_reasoning": "Synthesized rationale" } ],
  "level_2_precedents": [ ... ],
  "level_3_precedents": [ ... ]
}
"""
    
    response = client.chat.completions.create(
        model=MODEL_GPT4O,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(db, indent=2)}
        ],
        temperature=0.0
    )
    
    new_rules = response.choices[0].message.content
    
    # Overwrite the active DB with the newly consolidated, clean rules immediately
    try:
        parsed = json.loads(new_rules)
        _save_db(parsed)
    except json.JSONDecodeError:
        pass  # Don't overwrite DB with malformed JSON — original stays intact
        
    return new_rules

