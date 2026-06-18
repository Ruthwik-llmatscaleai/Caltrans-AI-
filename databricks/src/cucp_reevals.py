import json
import datetime
from openai import OpenAI
from PyPDF2 import PdfReader
from src.memory_manager import get_precedents
from src.databricks_client import get_openai_client, MODEL_GPT4O

client = get_openai_client()

def extract_text_from_pdf(pdf_path):
    reader = PdfReader(pdf_path)
    text = ""
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text += page_text + "\n"
    return text

# ==============================================================================
# LEVEL 1: FACT EXTRACTION (The "Perceptual" Layer)
# ==============================================================================
def run_level_1_extraction(narrative_text: str, firm_revenues: dict = None, staged_precedents: list = None) -> dict:
    level_1_precedents = get_precedents(1)
    if staged_precedents:
        level_1_precedents.extend(staged_precedents)
    
    precedents_text = ""
    if level_1_precedents:
        precedents_text = "\n\nINSTITUTIONAL MEMORY - LEVEL 1 HUMAN CORRECTIONS:\n"
        for p in level_1_precedents:
            precedents_text += f"- If you see '{p['target']}', apply correction: '{p['correction']}'. Reason: {p['human_reasoning']}\n"
    
    revenue_context = ""
    if firm_revenues:
        revenue_context = f"\n\nSUPPLEMENTARY REVENUE DATA (From Excel):\n{json.dumps(firm_revenues, indent=2)}\nUse this data to cross-reference the firm name."

    system_prompt = f"""You are an expert fact-extractor acting as a paralegal reading a Social and Economic Disadvantage (SED) narrative under 49 CFR §26.67.
Your ONLY job is to extract raw facts from the text. DO NOT perform legal analysis.

INSTRUCTIONS:
1. Extract the exact Applicant Firm Name. Look SPECIFICALLY at headers, footers, subject lines, or introductory context to identify the Applicant. IGNORE third-party companies, vendors, or former employers mentioned in the body paragraphs.
2. Cross-reference the firm name with the SUPPLEMENTARY REVENUE DATA. Find exact matches.
3. Extract any explicitly stated Personal Net Worth (PNW) of the applicant from the narrative.
4. For EVERY incident/claim in the narrative, extract the "W5" details (When, Where, Who, What, Why, Magnitude).
5. Flag 'demographic_flag' as true if the applicant mentions their race, ethnicity, or sex in relation to the harm.
6. Provide a direct source quote for each fact.{precedents_text}

OUTPUT FORMAT:
You must output ONLY valid JSON in the following format.
CRITICAL: Replace every placeholder below with REAL data extracted from the narrative. If a detail is not mentioned, use "NOT PROVIDED". NEVER return the placeholder description text itself as a value.
{{
  "firm_name": "<extract exact firm name or NONE>",
  "cross_reference_result": "<extract exact revenue or FAILED>",
  "narrative_pnw": "<extract exact PNW stated in narrative or NOT PROVIDED>",
  "extracted_facts": [
    {{
      "id": "fact_1",
      "when": "<extract date/time period or NOT PROVIDED>",
      "where": "<extract location or NOT PROVIDED>",
      "who": "<extract person/group involved or NOT PROVIDED>",
      "what": "<extract the specific incident described>",
      "why": "<extract the cause/motivation or NOT PROVIDED>",
      "magnitude": "<extract the type and amount of economic harm, e.g. lost contracts, dollar amounts, or comparative disadvantage, or NOT PROVIDED>",
      "demographic_flag": true or false,
      "source_quote": "<extract a short exact quote from the narrative>"
    }}
  ]
}}"""

    try:
        response = client.chat.completions.create(
            model=MODEL_GPT4O,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Applicant narrative:\n{narrative_text}\n{revenue_context}"}
            ],
            temperature=0.0
        )
        
        try:
            return json.loads(response.choices[0].message.content)
        except json.JSONDecodeError:
            # Retry once on malformed JSON
            retry = client.chat.completions.create(
                model=MODEL_GPT4O,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Applicant narrative:\n{narrative_text}\n{revenue_context}"}
                ],
                temperature=0.0
            )
            return json.loads(retry.choices[0].message.content)
    except Exception as e:
        return {"error": f"AI service error during fact extraction: {str(e)}", "extracted_facts": [], "firm_name": "NONE", "cross_reference_result": "FAILED", "narrative_pnw": "NOT PROVIDED"}

# ==============================================================================
# LEVEL 2: LEGAL CLASSIFICATION (The "Definitional" Layer)
# ==============================================================================
def run_level_2_classification(facts: list, combined_financials: str = "", staged_precedents: list = None) -> dict:
    level_2_precedents = get_precedents(2)
    if staged_precedents:
        level_2_precedents.extend(staged_precedents)
    
    precedents_text = ""
    if level_2_precedents:
        precedents_text = "\n\nINSTITUTIONAL MEMORY - LEVEL 2 HUMAN CORRECTIONS:\n"
        for p in level_2_precedents:
            precedents_text += f"- Scenario: '{p['target']}' -> Classify as: '{p['correction']}'. Reason: {p['human_reasoning']}\n"
            
    system_prompt = f"""You are an expert legal definer for 49 CFR §26.67 SED determinations.
Your job is to look at extracted raw facts and classify them legally.

Categories to choose from:
- "Social Disadvantage" (Personal experiences of discrimination — bias in contracting, exclusion from networks, personal prejudice)
- "Economic Disadvantage" (Capital access barriers — denied loans, bonding difficulties, financial limitations)
- "Institutional/Systemic Barrier" (Discriminatory institutional policies — not individual acts, but systemic patterns)
- "Ordinary Business Risk" (Setbacks from normal market forces — competition, pricing, general economy)
- "Insufficient Evidence" (The incident lacks enough detail to classify under §26.67){precedents_text}

OUTPUT FORMAT:
Return valid JSON mapping each input fact ID to a classification.
{{
  "classifications": [
    {{
      "fact_id": "fact_1",
      "classification": "Chosen Category",
      "summary": "One-sentence plain-language summary of the fact being classified",
      "reasoning": "Explanation based on 49 CFR §26.67"
    }}
  ]
}}"""

    try:
        response = client.chat.completions.create(
            model=MODEL_GPT4O,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Financial Context:\n{combined_financials}\n\nExtracted Facts to classify:\n{json.dumps(facts, indent=2)}"}
            ],
            temperature=0.0
        )
        
        try:
            return json.loads(response.choices[0].message.content)
        except json.JSONDecodeError:
            retry = client.chat.completions.create(
                model=MODEL_GPT4O,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Financial Context:\n{combined_financials}\n\nExtracted Facts to classify:\n{json.dumps(facts, indent=2)}"}
                ],
                temperature=0.0
            )
            return json.loads(retry.choices[0].message.content)
    except Exception as e:
        return {"error": f"AI service error during classification: {str(e)}", "classifications": []}

# ==============================================================================
# LEVEL 3: EVIDENTIARY THRESHOLD (The "Magnitude" Layer)
# ==============================================================================
def run_level_3_thresholds(classifications: list, facts: list, pnw_result: str, staged_precedents: list = None) -> dict:
    level_3_precedents = get_precedents(3)
    if staged_precedents:
        level_3_precedents.extend(staged_precedents)
    
    precedents_text = ""
    if level_3_precedents:
        precedents_text = "\n\nINSTITUTIONAL MEMORY - LEVEL 3 HUMAN CORRECTIONS:\n"
        for p in level_3_precedents:
            precedents_text += f"- Correction for '{p['target']}': {p['correction']}. Reason: {p['human_reasoning']}\n"
            
    system_prompt = f"""You are the final evaluator applying the exact standard of proof (Preponderance of the Evidence) under 49 CFR §26.67.
You will evaluate against the 7 mandatory CUCP criteria based on the classified evidence.

The 7 Criteria rows are exactly:
1. Meets Requirements of SED (No Race or Sex Presumptions)
2. Meets Personal Net Worth (PNW < $2.047M). Rule: Review the Excel Cross-Reference Revenue/PNW. HOWEVER, if the 'Narrative Declared PNW' provides a specific number, it OVERRIDES the Excel data.
3. Meets Disadvantage in American Society
4. Demonstration of Disadvantage (Past Experiences)
5. Evidence of Specific Impediments
6. Link Between Impediments and Harm
7. Economic Disadvantage in Fact{precedents_text}

OUTPUT FORMAT:
Return valid JSON exactly matching this structure.
pass_fail MUST be "Pass" or "Fail".
request_info MUST be "Yes" or "No".
{{
  "criteria": [
    {{
      "s_no": 1,
      "category": "Mandatory Eligibility Requirements",
      "qualification": "No Race or Sex Presumptions",
      "rule_requires": "Narrative includes individualized examples of social and economic disadvantage without race or sex presumptions",
      "evidence_summary": "1-2 sentence summary of applicant's evidence",
      "reasoning": "Why it passes or fails",
      "pass_fail": "Pass" or "Fail",
      "request_info": "Yes" or "No",
      "confidence": 9.5
    }},
    ... Include all 7 criteria ...
  ],
  "final_decision": "Yes" or "No" or "Not eligible at this time (pending additional information)",
  "certifier_comments": "Professional executive summary of the evaluation."
}}"""

    try:
        response = client.chat.completions.create(
            model=MODEL_GPT4O,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Classified Evidence:\n{json.dumps(classifications, indent=2)}\n\nRaw Facts:\n{json.dumps(facts, indent=2)}\n\nPNW Data point: {pnw_result}"}
            ],
            temperature=0.0
        )
        
        try:
            return json.loads(response.choices[0].message.content)
        except json.JSONDecodeError:
            retry = client.chat.completions.create(
                model=MODEL_GPT4O,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Classified Evidence:\n{json.dumps(classifications, indent=2)}\n\nRaw Facts:\n{json.dumps(facts, indent=2)}\n\nPNW Data point: {pnw_result}"}
                ],
                temperature=0.0
            )
            return json.loads(retry.choices[0].message.content)
    except Exception as e:
        return {"error": f"AI service error during threshold evaluation: {str(e)}", "criteria": [], "final_decision": "Error", "certifier_comments": ""}

# ==============================================================================
# REPORT GENERATION
# ==============================================================================
def generate_final_md_report(level_1_data: dict, level_2_data: dict, level_3_data: dict, analyst_overrides: list = None) -> str:
    """Takes the approved JSON state and synthesizes the exact markdown format for the UI."""
    current_date = datetime.datetime.now().strftime("%B %d, %Y")
    if analyst_overrides is None:
        analyst_overrides = []
    
    # 1. Extraction Block
    md = f"### 📄 CUCP EVALUATION REPORT\n"
    md += f"**Document Source:** CUCP Rubric §26.67\n"
    md += f"**Evaluation Date:** {current_date}\n"
    md += f"**Status:** {level_3_data.get('final_decision', 'Unknown')}\n\n---\n\n"
    
    # Pre-Scoring Audit
    md += "### 🔍 PRE-SCORING AUDIT\n"
    facts = level_1_data.get('extracted_facts', [])
    if not facts:
        md += "NONE\n"
    for idx, f in enumerate(facts):
        md += f"**Incident {idx+1}: {f.get('what', 'N/A')}**\n"
        md += f"- **When:** {f.get('when', 'NOT PROVIDED')}\n"
        md += f"- **Where:** {f.get('where', 'NOT PROVIDED')}\n"
        md += f"- **Who:** {f.get('who', 'NOT PROVIDED')}\n"
        md += f"- **What:** {f.get('what', 'NOT PROVIDED')}\n"
        md += f"- **Why:** {f.get('why', 'NOT PROVIDED')}\n"
        md += f"- **How/Magnitude:** {f.get('magnitude', 'NOT PROVIDED')}\n\n"
        
    if analyst_overrides:
        md += "### 🧑‍⚖️ ANALYST OVERRIDES\n"
        md += "The following external facts or manual adjustments were provided by the human reviewer:\n"
        for override in analyst_overrides:
            md += f"- **{override['field']}:** {override['value']} *(Justification: {override['reasoning']})*\n"
        md += "\n"
    
    md += "---\n\n"
    
    # Classification Summary
    md += "### 🏷️ CLASSIFICATION SUMMARY\n"
    classifications = level_2_data.get('classifications', [])
    if not classifications:
        md += "NONE\n"
    for idx, c in enumerate(classifications):
        md += f"- **Fact {c.get('fact_id', idx+1)}** → `{c.get('classification', 'Unclassified')}`\n"
        md += f"  - *Summary:* {c.get('summary', 'N/A')}\n"
    
    md += "\n---\n\n"
    
    # Part 1 Table
    md += "### PART 1 – EVALUATION TABLE (DECISION SUMMARY)\n\n"
    md += "| S. No | Category | Qualification | Pass (Yes/No) | Fail (Yes/No) | Request Additional Information (Yes/No) | Confidence Score (0.0–10.0) | Eligible for Certification |\n"
    md += "|---|---|---|---|---|---|---|---|\n"
    
    overall_fail = False
    for c in level_3_data.get('criteria', []):
        is_pass = "Yes" if c.get('pass_fail', '').lower() == 'pass' else "No"
        is_fail = "Yes" if c.get('pass_fail', '').lower() == 'fail' else "No"
        req_info = c.get('request_info', 'No')
        if is_fail == "Yes":
           overall_fail = True 
        
        md += f"| {c['s_no']} | {c['category']} | {c['qualification']} | {is_pass} | {is_fail} | {req_info} | {round(float(c.get('confidence', 10.0)), 1)} | N/A – criterion-level only |\n"
        
    final_pass = "No" if overall_fail else "Yes"
    final_fail = "Yes" if overall_fail else "No"
    final_elig = level_3_data.get('final_decision', 'No')
    md += f"| 8 | Final Decision | Meets all SED requirements under §26.67 | {final_pass} | {final_fail} | No | 10.0 | {final_elig} |\n\n---\n\n"
    
    # Part 2 Table
    md += "### PART 2 – EXPLAINABLE AI TABLE (REASONING)\n\n"
    md += "| S. No | Category | Qualification | What the Rule Requires | Summary of Applicant's Evidence | Reasoning (How Evidence Maps to Rule) | Decision Mapping (from Part 1) |\n"
    md += "|---|---|---|---|---|---|---|\n"
    
    for c in level_3_data.get('criteria', []):
        is_pass = "Yes" if c.get('pass_fail', '').lower() == 'pass' else "No"
        is_fail = "Yes" if c.get('pass_fail', '').lower() == 'fail' else "No"
        req_info = c.get('request_info', 'No')
        dec_map = f"Pass = {is_pass}; Fail = {is_fail}; Req Info = {req_info}; Conf = {round(float(c.get('confidence', 10.0)), 1)}"
        
        md += f"| {c['s_no']} | {c['category']} | {c['qualification']} | {c.get('rule_requires','')} | {c.get('evidence_summary','')} | {c.get('reasoning','')} | {dec_map} |\n"
        
    md += "\n---\n\n"
    md += "### 📝 CERTIFIER COMMENTS & FINAL SUMMARY\n"
    md += level_3_data.get('certifier_comments', 'No comments provided.')
    
    # Escape dollar signs to prevent Streamlit from rendering them as LaTeX
    return md.replace('$', '\\$')

# Keep the old top-level function signature for legacy fallback, though app.py should use the new one.
def cucp_reevaluations(uploaded_pdf, firm_revenues=None):
    reader = PdfReader(uploaded_pdf)
    text = ""
    for page in reader.pages:
        if page.extract_text():
            text += page.extract_text() + "\n"
            
    print("#--- Run L1 ---#")
    l1 = run_level_1_extraction(text, firm_revenues)
    print("#--- Run L2 ---#")
    l2 = run_level_2_classification(l1.get("extracted_facts", []))
    print("#--- Run L3 ---#")
    l3 = run_level_3_thresholds(l2.get("classifications", []), l1.get("extracted_facts", []), l1.get("cross_reference_result", "None"))
    print("#--- Gen MD ---#")
    return generate_final_md_report(l1, l2, l3)
