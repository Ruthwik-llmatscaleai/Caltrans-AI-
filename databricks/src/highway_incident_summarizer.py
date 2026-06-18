import os
import re

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

from src.databricks_client import get_openai_client, MODEL_LLAMA

# =========================
# Client initialization (Databricks)
# =========================
client = get_openai_client()


# ======================================
# 1. Fetch Caltrans highway page (same)
# ======================================
BASE_ROAD_URL = "https://roads.dot.ca.gov/"


def fetch_caltrans_page(highway_number: str) -> str:
    params = {"roadnumber": highway_number}
    resp = requests.get(BASE_ROAD_URL, params=params)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    return soup.get_text(separator="\n")


# ============================================================
# 2. Extract incident section from raw Caltrans HTML (same)
# ============================================================
def extract_incident_text(raw_text: str) -> str:
    lines = [l.strip() for l in raw_text.splitlines() if l.strip()]

    capturing = False
    output = []

    for line in lines:
        upper = line.upper()

        if upper.startswith("[IN THE") and "AREA" in upper:
            capturing = True

        if capturing:
            output.append(line)

        if "CONDITIONS OF USE" in upper or "PRIVACY POLICY" in upper:
            break

    bad = [
        "ENTER HIGHWAY NUMBER",
        "CHECK CURRENT",
        "MAPS",
        "QUICKMAP",
        "CONTACT US",
        "ACCESSIBILITY",
        "PRIVACY POLICY",
        "CONDITIONS OF USE",
        "BACK TO TOP",
        "KNOW BEFORE YOU GO",
    ]

    clean = [l for l in output if not any(b in l.upper() for b in bad)]
    return "\n".join(clean)


# =====================================================
# 3. Extract highway number from prompt (same logic)
# =====================================================
def extract_highway_from_prompt(user_prompt: str) -> str:
    pattern = r"\b(?:I[-\s]?|SR[-\s]?|HWY[-\s]?|HIGHWAY[-\s]?)*(\d{1,3})\b"
    m = re.search(pattern, user_prompt.upper())
    return m.group(1) if m else "5"  # Default to I-5


# =====================================================
# 4. Bullet point normalization (same logic)
# =====================================================
def normalize_bullets(text: str) -> str:
    if "\n" in text.strip():
        return text

    parts = re.split(r"\s*-\s+", text)
    parts = [p.strip() for p in parts if p.strip()]
    bullets = [f"- {p}" for p in parts]
    return "\n".join(bullets)


# =====================================================
# 5. Groq Llama-3.1 Summarizer Engine (replacement)
# =====================================================
def groq_summarize_incidents(incident_text: str) -> str:
    prompt = f"""
You are summarizing official Caltrans highway incident reports.

Summarize into 5–8 clear bullet points.

RULES:
- Each bullet MUST be on its own line.
- Bullets must start with "- ".
- Include closures, washouts, long delays, flooding, construction, and regions.
- Keep bullets short.

REPORT:
----------------
{incident_text}
----------------
"""

    completion = client.chat.completions.create(
        model=MODEL_LLAMA,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=300,
    )

    return completion.choices[0].message.content


# ============================================================
# 6. Full final pipeline (equivalent to summarize_caltrans_incidents)
# ============================================================
def summarize_caltrans_incidents(user_prompt: str) -> str:
    highway_number = extract_highway_from_prompt(user_prompt)

    raw_text = fetch_caltrans_page(highway_number)

    incident_text = extract_incident_text(raw_text)

    raw_summary = groq_summarize_incidents(incident_text)

    clean_summary = normalize_bullets(raw_summary)

    return clean_summary
