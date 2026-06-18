"""
Landing AI OCR Integration for Right of Way Evaluation - v3 (Vision Fallback)

v3 adds: Vision-based fallback for map-based categories when OCR fails to extract content.
- When text-only scoring returns Score 1 for any map category, PDF pages are rendered as images
  and sent to GPT-4o Vision for direct visual analysis.
- Map categories covered: Subject Assessor Map, Subject Photos, Comparable Map Sheet, Appraisal Maps.
- Vision only activates on NOT FOUND cases — normal cases stay text-only (no cost impact).

v2 features retained:
- GPT-4.1 primary model, chunk size 8 (4 API calls)
- Updated rubric per client's revised rubric
- 32 category-specific extraction rules
- Cross-reference logic for Certificate of Appraiser + Delegations
- Dependency-grouped chunking
- Consistency enforcement (Certificate→Delegations, HABU Improved→HABU Reconciliation)
"""

import os
import io
import json
import re
import base64
from typing import Dict, Any, List, Tuple, Optional
from dataclasses import dataclass

from dotenv import load_dotenv
from openai import OpenAI
from src.databricks_client import get_openai_client, MODEL_GPT4O, MODEL_GPT4_1

load_dotenv()

client = get_openai_client()

GPT_MODEL = MODEL_GPT4_1
VISION_MODEL = MODEL_GPT4O
FALLBACK_MODEL = MODEL_GPT4O

# 8 categories per chunk → 4 API calls total (was 8 calls at chunk size 4)
CHUNK_SIZE = 8

# Map-based categories that should trigger vision fallback when OCR returns Score 1
VISION_FALLBACK_CATEGORIES = {
    "Subject Assessor Map",
    "Subject Photos",
    "Comparable Map Sheet",
    "Appraisal Maps",
}

LANDING_AI_OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)))

LANDING_AI_PDF_MAPPING = {
    "Appraisal_EA2F590_Parcel_36668 (1).pdf": "landing_ai_output.md",
    "Appraisal_EA2F590_Parcel_36668.pdf": "landing_ai_output.md",
    "Appraisal_EA_2F590_Parcel_36674 (1).pdf": "REPORT2_landing_ai_output.md",
    "Appraisal_EA_0J910,_Parcel_38355.pdf": "REPORT3_landing_ai_output.md",
    "37857_-_Lee_Appraisal (2).pdf": "REPORT4_LeeAppraisal_landing_ai_output.md",
    "37857_-_Lee_Appraisal.pdf": "REPORT4_LeeAppraisal_landing_ai_output.md",
}


@dataclass
class EvaluationResult:
    """Data class to hold evaluation results for Excel export."""
    category: str
    score: int  # -1 = N/A
    criteria_met: str
    evidence: str
    status: str
    comments: str


# All 32 valid categories in rubric_schema.json
VALID_CATEGORIES = [
    "Title Page", "Certificate of Appraiser", "Senior Review Certificate",
    "Subject Assessor Map", "Subject Photos", "RW 7-9", "Scope of Work",
    "General Assumptions & Limiting Conditions", "Introduction", "Area Description",
    "Parcel Description", "HABU Vacant", "HABU Improved", "HABU Reconciliation",
    "Construction in the Manner Proposed", "Methodology", "Sales Comparison Approach (If used)",
    "Income Approach (If used)", "Cost Approach (If Used)", "Reconciliation",
    "The Acquisition - Land", "Improvements", "After Analysis (if required)",
    "Cost to Cure", "Construction Contract Work", "Summary of Just Compensation",
    "Comparable Summary Page", "Comparable Map Sheet", "Comparable Data Sheets",
    "Appraisal Maps", "Appraisal Terms", "Delegations",
    # NEW SECTIONS added per client's updated rubric (previously missed)
    "COS & HMDD",
    "Diary, Notice of Decision to Appraise & Loss of Business Goodwill"
]


def extract_text_from_landing_ai_md(md_file_path: str) -> str:
    """Extract and clean text from Landing AI OCR output markdown file."""
    try:
        with open(md_file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        markdown_pattern = r'markdown="([^"]*(?:\\.[^"]*)*)"'
        matches = re.findall(markdown_pattern, content)

        if matches:
            extracted_texts = []
            for match in matches:
                decoded = match.replace('\\n', '\n').replace('\\"', '"').replace("\\'", "'")
                decoded = re.sub(r'<a id=\'[^\']*\'></a>\s*', '', decoded)
                decoded = re.sub(r'<a id="[^"]*"></a>\s*', '', decoded)
                if decoded.strip():
                    extracted_texts.append(decoded.strip())

            return "\n\n".join(extracted_texts)

        return content

    except Exception as e:
        print(f"Error reading Landing AI output file: {e}")
        return ""


def find_landing_ai_output_for_pdf(pdf_filename: str, pdf_bytes: bytes) -> Optional[str]:
    """Find the corresponding Landing AI OCR output file for a given PDF."""
    if pdf_filename in LANDING_AI_PDF_MAPPING:
        md_filename = LANDING_AI_PDF_MAPPING[pdf_filename]
        md_path = os.path.join(LANDING_AI_OUTPUT_DIR, md_filename)
        if os.path.exists(md_path):
            print(f"✓ Found Landing AI output mapping: {pdf_filename} -> {md_filename}")
            return md_path

    default_md_path = os.path.join(LANDING_AI_OUTPUT_DIR, "landing_ai_output.md")
    if os.path.exists(default_md_path):
        print(f"✓ Using default Landing AI output: landing_ai_output.md")
        return default_md_path

    return None


def load_rubric_schema() -> Dict[str, Any]:
    """Load the rubric schema from JSON file."""
    schema_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "rubric_schema.json")

    try:
        with open(schema_path, "r", encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading rubric schema: {e}")
        return {}


# =============================================================================
# CATEGORY-SPECIFIC EXTRACTION RULES (updated per client feedback + new rubric)
# =============================================================================

def get_extraction_rules(category_name: str) -> str:
    """Get category-specific extraction and scoring rules."""

    rules = {
        "Title Page": """- Scan the document for the 'APPRAISAL TITLE PAGE' or 'TITLE PAGE' heading (NOT the Front Cover on page 1).
- Extract: form revision date (e.g. 'REV 10/05'), all signers with their titles, HQs/District approval checkboxes.
- Check delegation matrix: HQs approved = name under HQs Approved Parcels; District approved = name under District Approved Parcels.
- Verify correct title page type for the assignment type.
- SCORING:
  - Score 1: Title page missing, wrong delegations, OR wrong title page type.
  - Score 3: Correct delegations but minor missing info, OR everything correct but form outdated.
  - Score 5: All info correct, correct delegations, form updated.""",

        "Certificate of Appraiser": """- CRITICAL STRUCTURAL EXTRACTION (do NOT skip these steps):

STEP 1 — TITLE PAGE SIGNERS:
Locate the TITLE PAGE or APPRAISAL TITLE PAGE section. List every attestation/signature block that appears on the Title Page. For each, extract: signer name + role/title.
Example Title Page attestations: 'Blake Starr / Appraiser, Range B, R/W Agent', 'Jason M. Ybarra / Appraiser, Associate R/W Agent', 'Kelle Adair / Calculations verified by'.
From this list, identify who is an APPRAISER (roles containing 'Appraiser', 'R/W Agent', 'Range-A', 'Range-B', 'Associate R/W Agent'). EXCLUDE: 'calculations, content, and arrangement verified by', 'recommending approval', 'approved by', 'Senior Right of Way Agent' (if only acting as reviewer), 'Chief'.

STEP 2 — CERTIFICATE SECTION SIGNERS (STRUCTURAL TEST):
Find the text 'CERTIFICATE OF APPRAISER' heading. Starting from that heading, scan forward until the NEXT section heading begins.
Within that range, count ONLY the attestation/signature blocks that EXPLICITLY appear under the Certificate of Appraiser heading. Do NOT count signatures from the Title Page, Senior Review Certificate, or any other section.
In Landing AI OCR format, look for patterns like `<::attestation: Signature ... Signature: legible ... [Name] ... [Title] ... Date: ...::>` that appear AFTER the CERTIFICATE heading.
Example: In Parcel 36668, ONLY ONE attestation block ('Blake Starr / Right of Way Agent / 08/23/16') appears under the Certificate heading. Jason Ybarra's signature appears on the Title Page but NOT under the Certificate section.

STEP 3 — COMPARE:
Title Page appraiser count vs Certificate section signature count. They MUST be equal. List the specific names missing from the Certificate section.
If Title Page has N appraisers but Certificate section has only M signatures (M < N) → Score 1. List the missing names.

STEP 4 — DELEGATION RULE:
If any appraiser is a 'R/W Agent', 'Range-A', or 'Range-B' (NOT 'Associate R/W Agent'), there MUST also be an Associate (or higher) with their own certificate. Missing Associate certificate → Score 1.

STEP 5 — FORM CHECK:
Certificate form revision: 'RW 7-6(E) V.6/2003' or earlier = outdated.

# ANTI-HALLUCINATION HARD RULE:
Do NOT assume that a name appearing elsewhere in the document (e.g., Title Page) is also on the Certificate. Require an explicit signature block under the CERTIFICATE OF APPRAISER heading. If in doubt → count as MISSING.

SCORING:
  - Score 1: At least one Title Page appraiser NOT in Certificate section, OR R/W Agent without Associate certificate, OR wrong certificate type.
  - Score 2: Right number of certificates but outdated form or contains incorrect info.
  - Score 3: Right number of certificates, correct info, updated form version.

OUTPUT REQUIREMENT: In your evidence field, explicitly state (a) Title Page appraiser list, (b) Certificate section signature list, (c) whether counts match.""",

        "Senior Review Certificate": """- Locate the 'SENIOR REVIEW CERTIFICATE' section.
- MANDATORY FORM REVISION EXTRACTION: Locate the form revision code (patterns like "REV 10/05", "REV 9/2002", "NEW 2023", "EXHIBIT 7-EX-24A (REV ...)"). Extract the YEAR from the revision.
- OUTDATED FORM RULE (HARD CAP): If form revision year is 2010 or older → MAX Score 4 (outdated form, even if no errors).
- If no REV date visible at all → treat as outdated → MAX Score 4.
- If REV date is 2020 or later → form is current → eligible for Score 5.
- Extract signer name and title (must be Senior Right of Way Agent). Verify correct certificate type matches the assignment.
- SCORING:
  - Score 1: Missing, wrong delegation, OR wrong certificate type.
  - Score 2: Correct delegation but outdated + many errors/omissions.
  - Score 3: Correct delegation, outdated, few errors.
  - Score 4: Correct delegation, outdated (REV 2010 or older), but contains no errors or omissions. ← MOST COMMON SCORE for reports with REV 10/05 forms.
  - Score 5: Correct delegation + no errors + current form (REV 2020 or later).
- OUTPUT REQUIREMENT: Quote the exact form revision code in evidence (e.g., 'EXHIBIT 7-EX-24A (REV 10/05)').""",

        "Subject Assessor Map": """- Locate the SUBJECT ASSESSOR PARCEL MAP. This is usually on an early page (page 5-6), NOT the Comparable Data Map.

- DO NOT CONFUSE WITH:
  - Comparable Data Map (different category — shows comparable sales locations)
  - Comparable Parcel Maps (individual assessor maps for each comparable)
  - R/W Appraisal Map (different category)
  The Subject Assessor Map shows the SUBJECT PROPERTY ONLY highlighted on a tax assessor parcel map.

- SEARCH KEYWORDS to find the Subject Assessor Map (EXHAUSTIVE SEARCH required):
  PRIMARY HEADINGS: 'ASSESSOR'S PARCEL MAP', 'Assessor Parcel Map', 'Subject Assessor Map', 'SUBJECT ASSESSOR MAP', 'ASSESSOR MAP'
  ALTERNATE PATTERNS: Look for map images on EARLY pages (typically pages 4-6) that show:
    - Subject parcel outlined in red/pink/magenta on an assessor-style plat map
    - Caption referencing 'Subject parcel', 'Subject property', 'Parcel [number]' with highlighting language
    - 'Book X, Page Y' assessor reference
    - 'highlighted in red', 'outlined in red', 'red polygon', 'red box' near subject property reference
  OCR IMAGE DESCRIPTIONS: The OCR sometimes describes the assessor map as 'A tax assessor parcel map showing...' or 'Aerial map with parcel boundaries highlighted'.

- FALLBACK RULE: If the OCR contains ANY early-page map description (pages 1-8) that:
  (a) Shows the subject parcel/property identified, AND
  (b) Mentions highlighting/outlining/coloring of the subject, AND
  (c) Is NOT the Comparable Data Map or R/W Appraisal Map or photo,
  → treat it as the Subject Assessor Map and score accordingly.

- If OCR genuinely has NO subject map content of any kind → Score 1 (may be OCR extraction gap — note this in evidence).

- RED COLOR DETECTION:
  OCR may not always describe colors perfectly. Accept the following as 'red':
    - Text 'highlighted in red' or 'red outline'
    - Text 'Red Box' or 'Red polygon'
    - Caption explicitly states red
    - Subject property is marked differently from surroundings with color language indicating red/crimson/scarlet
  If the OCR description says 'highlighted' or 'outlined' WITHOUT specifying color — check for caption language. If a caption explicitly describes red highlights → accept as red.

- CLIENT-CONFIRMED EXAMPLES:
  - Parcel 36668 (p.5): 'The red highlights the subject parcel, and the green highlights the remaining portion...' → Red + caption → Score 5.
  - Parcel 36674 (p.4-5): Assessor's Map with subject outlined in red with caption → Score 5.
  - Parcel 38355 (p.5): Caption states 'The red outlined the subject larger parcel' → Score 5.

- Extract: map_present (true/false), outline_color (quote description), caption_present (quote caption text if present).

- SCORING:
  - Score 1: Subject Assessor Map not present in the report.
  - Score 2: Map present but subject NOT outlined at all.
  - Score 3: Subject outlined but color is clearly NOT red (e.g., 'outlined in blue', 'yellow outline').
  - Score 4: Subject outlined in red but NO caption.
  - Score 5: Subject outlined in red AND has caption explaining the map.

- OUTPUT REQUIREMENT: Quote the map caption text. State the outline color based on caption or OCR text.""",

        "Subject Photos": """- CRITICAL CLIENT CLARIFICATION: 'RW lines denoted' means the photo caption EXPLICITLY references lines labeled as 'existing right of way line', 'the state's right of way line', 'current right of way line', 'R/W line', or similar RW terminology.
- Lines labeled as 'utility easement', 'easement line', 'subparcel outline', 'property boundary', 'fee acquisition outline' do NOT count as RW lines.
- Example CORRECT RW line caption (Parcel 36668): 'The State's current Right of Way, and underlying fee, is marked by the orange line'.
- Example WRONG (Parcel 36674): 'The red line illustrates the current location of the utility easement' = easement, NOT RW line.
- Example WRONG (Parcel 38355): 'Subparcel 38355-1 (Fee) is outlined in red' = subparcel outline, NOT RW line.

- PROPOSED ACQUISITION TERMINOLOGY CHECK (for Score 4+):
  Captions must mention the PROPOSED ACQUISITION — keywords: 'acquisition area', 'proposed acquisition', 'fee acquisition', 'acquisition boundary', 'area to be acquired', 'red area marks the acquisition'.
  Just showing 'current Right of Way' WITHOUT mentioning the proposed acquisition area = NOT Score 4 eligible.
  Captions that only describe direction ('standing on the north side, looking south') without mentioning acquisition = Score 3 max.

- Extract: photo count, captions present (true/false), dates present (true/false), direction mentioned (true/false), proposed acquisition mentioned in captions (true/false, quote exact text), RW lines denoted using client-approved terminology (true/false, quote exact text), photos of impacted substantial improvements (if any).

- SCORING (strict hierarchy — must meet ALL lower scores to be eligible for higher):
  - Score 1: No photos at all.
  - Score 2: Has photos but no dates AND no RW lines, OR missing photos of impacted substantial improvements.
  - Score 3: Sufficient photos + dates + who took present, BUT captions do NOT mention proposed acquisition.
  - Score 4: Sufficient photos + captions mention BOTH direction AND proposed acquisition (quote 'acquisition' keyword), but RW lines NOT denoted with approved terminology.
  - Score 5: All of 4 + RW lines denoted using approved RW terminology (quote 'right of way line' or similar from caption).""",

        "RW 7-9": """- Locate the 'RW 7-9' form (appraisal summary).
- REQUIRED HEADER FIELDS (per client): APN, F.P.#, Parcel No., Report No., Date, District, Co, Rte, P.M., Exp Auth, Map No., Owner, Proj ID, Property Address, Locale, Zone, Present Use, Best Use, Land, Total, Hazardous Waste checkbox (yes/no), Date Acquired, DTT, Consideration, Total Property Area, Full/Part checkbox, Include Access Rights (yes/no).
- Property Address must be a STREET NAME, not the APN number. If APN appears in Address field → Score 3.
- Check form revision date (REV 9/2002 or older = outdated).

- STRICT SEE-SECTION DETECTION (HARD RULE for Score 3):
  Search the FULL RW 7-9 content for any of these patterns in the Land/Improvements/Damages/Benefits/CCW rows:
    - '(See ' or '(see '
    - 'See ___ section' (any wildcard)
    - 'Refer to ___'
    - 'see other section'
    - 'See "___" section'
  Example from 36668: '(See "Improvements" section)' next to $4,466.34. This is a see-section reference → Score 3.
  Example from 36668: '(See "Remainder - Damages & Benefits" section)' next to $6,052.00. This is a see-section reference → Score 3.
  If ANY see-section reference appears in a line item → MAX Score 3 (cannot be Score 4).
  If APN appears in Property Address field → MAX Score 3.
  If BOTH conditions present → still Score 3, but note both in evidence.

- Cross-check subparcels match appraisal map.

- SCORING (strict hierarchy):
  - Score 1: Missing or not filled out.
  - Score 2: Missing fee/improvements/damages line items OR math errors.
  - Score 3: Missing top info applicable to the assignment OR has see-section references in line items OR APN in Property Address field. ← APPLIES IF ANY of these are true.
  - Score 4: ALL top fields filled appropriately + all line items listed directly (NO see-section references) + form outdated + values allocated to RW or excess + no inconsistencies.
- OUTPUT REQUIREMENT: In evidence, quote any see-section reference found (if any) or confirm none present.""",

        "Scope of Work": """- CRITICAL ANTI-HALLUCINATION: Content may be in a titled 'Scope of Work' section OR scattered across multiple sections.

- SCORE 3 REQUIRED ELEMENTS (6 items — at least 4 MUST be explicitly present):
  (1) Problem identified (subject property, parcel number, acquisition type)
  (2) Extent of inspection stated (what was inspected, how, by whom)
  (3) Type of data researched (market data, comparable sales, cost data)
  (4) Analysis applied (sales comparison, summation method, etc.)
  (5) Assumptions and hypotheticals disclosed
  (6) Assistance by others disclosed (or explicit "no assistance")

- HARD THRESHOLD RULE:
  Count how many of the 6 Score 3 elements are EXPLICITLY found in the document.
    - 0-1 elements found → Score 1 ('There is none').
    - 2-3 elements found → Score 2 ('attempt but falls short').
    - 4-6 elements found → Score 3.
    - All 6 + full identification (client/users/intended use/value definition/effective dates/assignment conditions/hypotheticals/subject property) + Chapter 7 reference + state summation (if partial) → Score 4.
    - All of 4 + easy to find and clearly labeled → Score 5.

- ANTI-HALLUCINATION RULE:
  DO NOT count the following as Scope of Work elements:
    - Certificate of Appraiser boilerplate ('to the best of my knowledge', 'I hereby certify')
    - General Introduction text describing the project
    - Methodology section (that's a separate rubric category)
  For each element claimed present, you MUST be able to quote the specific sentence supporting it.

- CLIENT-CONFIRMED REPORT EXAMPLES:
  - Parcel 36674: NO Scope of Work exists in the report — max elements findable = 0-1 → Score 1.
  - Parcel 36668: NO Scope of Work exists in the report — max elements findable = 0-1 → Score 1.
  - Parcel 38355: Has detailed Scope of Work on page 8 — Score 4.

- OUTPUT REQUIREMENT: In evidence, list the 6 elements and state for each whether found (with quote) or NOT FOUND.""",

        "General Assumptions & Limiting Conditions": """- CRITICAL ANTI-HALLUCINATION: Client requires this to be an INDEPENDENT PARAGRAPH TITLED 'General Assumptions & Limiting Conditions' (or similar heading). A heading match is mandatory.
- Certificate of Appraiser boilerplate language ('to the best of my knowledge', 'subject to limiting conditions therein set forth') does NOT count. These are certificate-only statements.
- SCORING:
  - Score 1: No such titled section exists, OR section exists but content insufficient.
  - Score 3: Contains one that is sufficient to high-quality appraisal examples.
  - Score 4: Contains one that is exemplary compared to most examples.""",

        "Introduction": """- Locate a standalone introduction paragraph.
- SCORING (max achievable is Score 3):
  - Score 1: Missing.
  - Score 2: Attempt present but doesn't meet Score 3.
  - Score 3: Brief description of report type, proposed acquisitions, ownership, current use. For partial acquisitions, mentions after-condition of remainder.""",

        "Area Description": """- Locate the Area Description / Neighborhood Description section. READ THE ENTIRE SECTION.
- MARKET TREND KEYWORDS (required for Score 3+): 'market trend', 'market conditions', 'appreciation', 'depreciation', 'prices have increased/decreased', 'demand', 'supply', 'sales activity', 'property value trend', 'market is trending'.
- Geographic-only keywords (Score 2): location description, county, city, terrain, climate, altitude, nearby cities — WITHOUT market trend language.
- Employment/economic data keywords (Score 4): 'employment', 'unemployment rate', 'median income', 'major employers', 'jobs', 'census', 'population', 'business closures', 'business openings'.

- SCORE 5 STRICT CRITERIA (HARD CAP):
  Requires ALL of:
    (a) Everything in Score 4 (market trends + current uses + employment data), AND
    (b) EXPLICIT mention of NEW DEVELOPMENTS — keywords: 'new development', 'upcoming project', 'planned development', 'recent construction', 'new subdivision', 'proposed residential development', 'recently opened', 'recent announcement of development'. AND
    (c) EXPLICIT geographical boundaries — keywords: 'bounded by', 'north of', 'south of', 'east of', 'west of', 'from X street to Y street', 'defined by the city of X to the Y'.
  If (b) OR (c) is missing → MAX Score 4.

- SCORING:
  - Score 1: No area description.
  - Score 2: Only geographical/historical info — no market trend keywords found.
  - Score 3: Contains market area trends but missing current uses or employment data.
  - Score 4: Market trends + current uses + employment data (most common score for good reports).
  - Score 5: All of 4 + EXPLICIT new developments + EXPLICIT geographical boundaries.""",

        "Parcel Description": """- Locate the PARCEL DESCRIPTION section (standalone paragraph).
- REQUIRED ELEMENTS FOR SCORE 3 (all must be present IN THIS SECTION): (1) larger parcel analysis, (2) parcel size, (3) zoning, (4) easements/contracts/leases/restrictions, (5) current use, (6) physical characteristics.
- Easements mentioned elsewhere (engineering maps, acquisition section, methodology section) do NOT satisfy the Score 3 requirement — they MUST be in the Parcel Description section proper.

- STRICT EASEMENT DETECTION (HARD RULE):
  The Parcel Description section MUST contain the LITERAL word 'easement' (case-insensitive) OR 'contract' OR 'lease' OR 'restriction' (as a property encumbrance) OR 'encumbrance'.
  IMPROVEMENTS ARE NOT EASEMENTS — these DO NOT satisfy the easement requirement:
    - 'utility lines' or 'irrigation lines' (these are improvements/infrastructure on the parcel, not easements)
    - 'fencing' (improvement)
    - 'off-site improvements like water, electricity, telephone' (off-site services, not easements on subject)
    - 'driveway' (improvement)
    - 'paved streets' (off-site)
  ONLY count as satisfying the easement requirement:
    - Literal 'easement' word (e.g., 'utility easement crosses the parcel', 'public road easement')
    - Literal 'lease' word (e.g., 'parcel is subject to a 5-year lease')
    - Literal 'restriction' or 'restrictive covenant' (e.g., 'CC&Rs restrict development')
    - Literal 'contract' (e.g., 'mineral rights contract')
    - Literal 'encumbrance'

  If the Parcel Description section does NOT contain any of these literal words → easements element NOT satisfied → MAX Score 2.

- Cross-check parcel size matches appraisal map.

- CLIENT-CONFIRMED EXAMPLES:
  - Parcel 36674 Parcel Description contains 'fencing', 'irrigation lines', 'paved streets' — but NO literal 'easement'/'lease'/'restriction' word → Score 2.
  - Parcel 36668 Parcel Description: no easement language → Score 2.
  - Parcel 38355 Parcel Description: has easement discussion → Score 3.

- SCORING (max achievable is Score 3):
  - Score 1: Missing larger parcel analysis + address + size.
  - Score 2: Missing one or more Score 3 elements (especially NO literal 'easement'/'lease'/'restriction' word in section).
  - Score 3: All six required elements present INCLUDING literal easement/lease/restriction language.

- OUTPUT REQUIREMENT: In evidence, quote the exact sentence where 'easement'/'lease'/'restriction' appears. If no such word exists in Parcel Description → explicitly state 'NO easement/lease/restriction language found in Parcel Description section'.""",

        "HABU Vacant": """- Locate 'HIGHEST AND BEST USE AS VACANT' or 'HABU Vacant' section.
- Check for the 4 tests: (1) legally permissible (zoning, general plan, CCRs), (2) physically possible (topography, size, physical characteristics), (3) financially feasible (market demand), (4) maximally productive (final conclusion with 'why').

- SCORE 4 STRICT CRITERIA (most likely buyer) — HARD GATE FOR SCORE 4 AND 5:
  Requires EXPLICIT statement about the most likely buyer — the report MUST contain ONE of these exact phrase patterns:
    - 'most likely buyer is...'
    - 'typical buyer would be...'
    - 'probable purchaser is...'
    - 'target buyer is...'
    - 'this property would appeal to...'
    - 'the buyer pool consists of...'

  HARD RULE (NO EXCEPTIONS):
  If the most likely buyer is only IMPLIED, INFERRED, or NOT STATED:
    - CANNOT award Score 4 (Score 4 requires it explicitly)
    - CANNOT award Score 5 (Score 5 requires Score 4 prerequisite met)
    - MAX Score = 3

  ANTI-BYPASS RULE: You may NOT reason that "Score 5 can be awarded despite missing most likely buyer because the legal uses are enumerated." Legal use enumeration is the Score 5-specific requirement ON TOP OF Score 4. Without the most likely buyer statement, max is Score 3 regardless of enumeration quality.

  If your reasoning explicitly notes "most likely buyer is not explicitly stated" OR "most likely buyer is implied" → your final score MUST be 3, NOT 4 or 5.

- SCORE 5 STRICT CRITERIA (HARD CAP — ALL 4 required, NO exceptions):
  Requires ALL of:
    (a) Score 4 strictly met (EXPLICIT most likely buyer quote — not implied), AND
    (b) EXPLICIT enumeration of EACH legal use under the zoning code, with analysis for each, AND
    (c) Explanation of WHY the non-concluded uses were rejected, AND
    (d) Must see phrases that EXPLICITLY discuss each alternative use type:
       - 'Single Family Residential was considered...'
       - 'Multifamily is permitted but was rejected because...'
       - 'Commercial retail was evaluated but not maximally productive because...'

  HARD REJECTION RULES for Score 5:
  - If the report just LISTS legal uses as a set (e.g., 'this zoning allows residential, commercial, and agricultural uses') WITHOUT individually analyzing each = NOT Score 5 (this only satisfies Score 3).
  - If most likely buyer is 'implied' rather than 'explicitly stated' = NOT Score 5 (fails Score 4 prerequisite).
  - If the analysis only discusses the concluded use (e.g., only residential) without comparative rejection of alternatives = NOT Score 5.

- REASONING VERIFICATION (CRITICAL):
  Before awarding Score 4 or 5, you MUST be able to quote (not paraphrase) the specific sentence identifying the most likely buyer. If you cannot quote such a sentence → MAX Score 3.
  Do NOT reason yourself into Score 5 by saying 'most likely buyer is implied' — implicit is insufficient.

- SCORING (strict hierarchy):
  - Score 1: Missing one or more of the 4 tests.
  - Score 2: Has all 4 tests but unclear maximally productive use OR two uses concluded.
  - Score 3: All 4 tests + HABU definition + clear maximally productive use with explanation. ← MOST COMMON SCORE.
  - Score 4: All of 3 + EXPLICIT statement of most likely buyer.
  - Score 5: All of 4 + EXPLICIT enumeration and analysis of each legal use under zoning code.

- OUTPUT REQUIREMENT: For Score 4+, quote the exact 'most likely buyer' statement. For Score 5, list the legal uses enumerated with quotes.""",

        "HABU Improved": """- CRITICAL CONDITIONAL: HABU Improved is ONLY done for properties improved WITH A BUILDING. Otherwise → N/A.

- PROPERTY TYPE CHECK (MANDATORY FIRST STEP — output this in evidence):
  STEP 1: Search for BUILDING-type improvements. Keywords indicating a BUILDING:
    - 'single family residence', 'SFR', 'home', 'dwelling', 'house'
    - 'commercial building', 'retail building', 'office building', 'warehouse'
    - 'barn', 'shed' (if substantial), 'garage'
    - 'structure', 'improvement with' (+ building type)

  STEP 2: Search for NON-building-only improvement indicators. These mean HABU Improved = N/A:
    - 'fencing' (as the only improvement)
    - 'irrigation' (as the only improvement)
    - 'landscaping'
    - 'gravel driveway' (alone)
    - 'no major improvements'
    - 'no buildings'
    - 'vacant'
    - 'unimproved'
    - 'the larger parcel as improved will not be valued' ← EXPLICIT N/A signal

  STEP 3: Decision:
    - If evidence mentions a building (Step 1 keywords) → Property IS improved → score 1-5.
    - If ONLY fencing/irrigation/landscaping found AND no building keywords → Property is effectively UNIMPROVED for HABU purposes → N/A.
    - If explicit 'vacant', 'unimproved', or 'no improvements' language → N/A.

- CLIENT-CONFIRMED EXAMPLES:
  - Parcel 36668: Has fencing only, no buildings. Methodology says 'larger parcel as improved will not be valued' → N/A.
  - Parcel 36674: Has fencing and irrigation only, no buildings → N/A.
  - Parcel 38355: Explicitly states 'subject is not improved' → N/A.

- If property HAS a building but NO HABU Improved section → Score 1.
- Do NOT attribute text from HABU Vacant to HABU Improved.
- Require explicit 'HABU Improved', 'HABU As Improved', or 'CONCLUSION AS THOUGH IMPROVED' heading before scoring 2-5.

- SCORING:
  - N/A: Property has no building (fencing/irrigation/landscaping only) OR explicit unimproved language.
  - Score 1: Property has a building but HABU Improved section omitted.
  - Score 2: States current use but doesn't explain.
  - Score 3: Sufficiently explains one of 3 conclusions (continue as is / modify / demolish).
  - Score 5: Extensively explains with market research why one of the 3 conclusions was chosen.

- OUTPUT REQUIREMENT: In evidence, explicitly state the building detection result (has building: yes/no) with quoted text.""",

        "HABU Reconciliation": """- CRITICAL PREREQUISITE: HABU Reconciliation is ONLY done when BOTH HABU Vacant AND HABU Improved were performed. Otherwise → N/A.
- If HABU Improved = N/A (unimproved property) → HABU Reconciliation = N/A automatically.
- If only HABU Vacant was performed → HABU Reconciliation = N/A.
- Require explicit heading like 'RECONCILIATION OF HIGHEST AND BEST USE' or 'HABU Reconciliation'.
- SCORING:
  - N/A: Only one HABU type performed (typically unimproved properties).
  - Score 1: Both HABU Vacant and Improved performed but no reconciliation section.
  - Score 2: States which HABU without explanation, or explains non-previously-concluded use.
  - Score 3: Reconciles to HABU Vacant OR Improved with explanation.""",

        "Construction in the Manner Proposed": """- Locate 'CONSTRUCTION IN THE MANNER PROPOSED' or similar section describing the project.

- SECTION CONTENT ASSESSMENT (two components required):
  Component A: PROJECT-LEVEL description (what the project is, scope, purpose).
  Component B: PARCEL-SPECIFIC description (what specifically will happen at this parcel).

- DETAIL QUALITY CRITERIA (NOT strict word count — focus on CONTENT SPECIFICITY):
  The rubric cares about "detailed description" and "detailed illustration of the changes" — quality over quantity.

- SCORE 5 REQUIRES ALL THREE ELEMENTS:
  (a) PROJECT-LEVEL DETAIL: Describes the project with multiple specific elements:
      - Named engineering actions (e.g., 'realigning curves', 'widening shoulders', 'turn lanes', 'drainage improvements', 'slope changes')
      - At least 3+ specific elements mentioned
      - Often presented as a bullet list or enumerated description
  (b) QUANTITATIVE SPECIFICS: Contains specific measurements/dimensions:
      - Lane widths, shoulder widths, setback distances (e.g., '12-foot lanes', '8-foot shoulders')
      - OR specific acquisition dimensions (e.g., '66,077 SF fee acquisition', '794 LF along Highway 20')
      - OR specific slope/grade changes (e.g., '4:1 side slope')
  (c) PARCEL-SPECIFIC ILLUSTRATION: Explicitly describes what changes at THIS specific parcel:
      - Fencing relocation specifics
      - Access/driveway changes
      - Grade changes at this parcel
      - Specific acquisition footprint on the parcel
      - Utility easement relocation details

  If ALL 3 elements above are present → Score 5 regardless of total word count.
  If only 2 of 3 present → Score 4.
  If only 1 of 3 (e.g., project described but parcel impact is generic) → Score 3.

- SCORE 4 CRITERIA:
  Has 2 of the 3 Score 5 elements — typically has project detail + some specifics but parcel-specific detail is lighter, OR vice versa.

- CLIENT-CONFIRMED EXAMPLES:
  - Parcel 36668/36674: Safety project with multiple engineering elements (realigning curves, widening shoulders, turn lanes, 12-ft lanes, 8-ft shoulders, 4:1 slopes) + specific acquisition dimensions (66,077 SF, 794 LF) + parcel-specific impact (fencing affected, TCE for driveway conforming, utility easement relocation) → Score 5.
  - Parcel 38355: Project with bullet list of actions (aligning wooden guardrail, extending shoulders) + parcel mention → Score 4.

- SCORING:
  - Score 1: Section missing entirely.
  - Score 2: Only describes project OR only describes property impact (not both).
  - Score 3: Brief description of both (1-2 sentences each), no specific engineering elements or quantitative details.
  - Score 4: Moderate detail (2 of 3 Score 5 elements present).
  - Score 5: Detailed description with ALL 3 elements: (a) multiple project engineering elements, (b) quantitative specifics, (c) parcel-specific illustration of changes.

- OUTPUT REQUIREMENT: In evidence, list which of the 3 Score 5 elements are present with quotes. Count matters less than content specificity.

- OUTPUT REQUIREMENT: In evidence, quote representative sentences showing the detail level. State approximate word count for each component.""",

        "Methodology": """- Locate 'METHODOLOGY' section.
- For FULL acquisitions (no remainder): methodology should NOT rely on state summation. Should use sales comparison, cost, or income approach (or Schenck Ruling / ATF Method for definition-b cases).
- For PARTIAL acquisitions: must state 'state summation method was used' OR 'abbreviated state summation was used' with 3 justifying conditions: (1) HABU won't change, (2) principal improvements/supporting infrastructure not impacted, (3) full summation wouldn't add clarity.

- SCORE 5 STRICT CRITERIA (HARD CAP — all required):
  Requires ALL of:
    (a) Methodology section content is AT LEAST 3 substantial paragraphs (not 1-2 brief paragraphs).
    (b) EXPLICIT reference to 'Chapter 7' of the Caltrans R/W Manual (or ROW Manual Chapter 7).
    (c) DETAILED justification for WHY the state summation method (or abbreviated) was chosen — not just stating it.
    (d) DETAILED reasoning for EACH valuation approach used or NOT used (sales comparison, cost, income) with explanation.
    (e) If abbreviated method used: explicit mention of ALL 3 justifying conditions (HABU won't change + principal improvements not impacted + full summation wouldn't add clarity).
  If ANY of (a)-(e) is missing → MAX Score 3.

- SCORING (strict hierarchy):
  - Score 1: No methodology section at all.
  - Score 2: Partial methodology attempt but missing required Score 3 elements.
  - Score 3: States summation method / abbreviated method + provides methodology for before (and after if applicable). This is the NORMAL score for competent methodology sections.
  - Score 5: Only if ALL Score 5 strict criteria are met. Most reports should NOT score 5.

- OUTPUT REQUIREMENT: For Score 5, quote the Chapter 7 reference and each approach justification.""",

        "Sales Comparison Approach (If used)": """- Locate Sales Comparison Approach section.
- If methodology explicitly states Sales Comparison NOT used → N/A.
- ADJUSTMENT TYPE DETECTION:
  - Quantitative = specific dollar amounts ('$6,000 downward') or percentages ('+10% for zoning', '-5% market conditions').
  - Qualitative = word rankings ('superior', 'inferior', 'similar', 'better', 'worse') without dollar/percent values.
  - Transactional adjustments MUST be quantitative.
- DO NOT claim qualitative adjustments were used if you only see dollar/percent values. Only claim qualitative if you see superior/inferior/similar rankings used as adjustments.
- SCORING:
  - Score 1: Missing grid, discussion of comparables, or reconciliation.
  - Score 2: Grid + adjustments explained + qualitative adjustments (if used) explained — BUT reconciliation not logically sound (can be fixed with available data).
  - Score 3: Same as Score 2 + reconciliation IS logically sound.""",

        "Income Approach (If used)": """- Locate Income Approach section. If not used (methodology states so) → N/A.
- Data must be market-derived (not subject's own rent/lease) UNLESS: outdoor advertising sign with no data OR lease longer than 5 years.
- Cap rate source hierarchy: comparable sales → industry publications (CoStar, NAR) → comparative risk analysis.
- Lease types: NNN, NN, gross, net, modified gross. NOI must be normalized if varying types used.
- SCORING:
  - Score 1: Unreliable (wrong data type used, lease type not reconciled, assumed data).
  - Score 2: Correct data + reliable value but missing RW 07-11 pages OR uses lesser data without noting absence.
  - Score 3: Correct data + all comparables have RW 07-11/11A + final indicative value provided.""",

        "Cost Approach (If Used)": """- CRITICAL DISTINCTION: Cost APPROACH = full valuation method (RCN − depreciation + land value). Cost TO CURE = repair cost for damages. These are DIFFERENT categories.
- FIRST check methodology: does it explicitly state 'Cost Approach was used' to value the subject? If not → likely N/A.
- Cost guide references in Improvements section or Cost to Cure section do NOT constitute Cost Approach.
- CLIENT CLARIFIED: Senior Review Certificate checkbox 'Cost Approach supported' can be marked INCORRECTLY by the appraiser. Do NOT rely on it alone.
- If no formal Cost Approach section in report body + methodology doesn't mention it → N/A.
- Required for full Cost Approach: similar new costs from recognized cost guide (with page/version numbers) OR ≥2 bids OR 1 bid + 1 cost guide; physical depreciation applied; functional/external obsolescence applied; land value from sales comparison approach added.
- SCORING:
  - Score 1: Depreciation not applied, wrong replacement, or integrity-questioning defects.
  - Score 2: Only 1 bid, OR no page/version, OR arbitrary depreciation, OR land not from sales comparison, OR not applied at all.
  - Score 3: Recognized cost guide (≥2 bids or 1 bid + cost guide) + page/version listed + depreciation table used + obsolescence applied + land from sales comparison.
  - Score 4: All of 3 + more cost sources than minimum.""",

        "Reconciliation": """- CRITICAL PREREQUISITE: Reconciliation is ONLY done when MORE THAN ONE valuation approach was used (Sales Comparison + Income + Cost Approach). Otherwise → N/A.
- IMPORTANT: Reconciliation (this category) is NOT the same as 'Reconciliation of Unit Value' (which reconciles comparable sales WITHIN a single approach). 'Reconciliation of Unit Value' is part of the Sales Comparison Approach.
- Cost guide usage for improvements (fencing, etc.) does NOT count as using the Cost Approach. It's part of Cost to Cure or Improvements valuation.
- Check methodology for explicit statement of approaches used. Count only formal valuation approaches.
- SCORING:
  - N/A: Only one valuation approach used (single approach common in state summation reports).
  - Score 1: Only provides final value or fails to reconcile at all.
  - Score 2: Final value with limited explanation.
  - Score 3: Evaluated strengths/weaknesses of each approach based on quality and quantity of data; weighted approaches appropriately to derive final value.""",

        "The Acquisition - Land": """- Locate 'THE ACQUISITION' or 'ACQUISITION - LAND' section.
- Extract: fee acquisitions, underlying fee, easements (with percentage applied), TCEs (with rental rate), access/abutter's rights, excess fee parcels.
- Cross-check subparcel numbers and sizes against appraisal map.
- Highway easements: valued at fee − $1.00 (streets & highways code).
- TCE rates: must be market-derived OR comparative risk analysis — NOT arbitrary.
- Easement percentages: proportional to severity (10% nominal, 95% severe).

- RATIONALIZATION CHECK (STRICT — LITERAL REASONING REQUIRED):
  A percentage is 'rationalized in the narrative' ONLY IF a written sentence explains WHY that specific percentage was chosen.

  MANDATORY RATIONALIZATION KEYWORDS (must appear within the same sentence/paragraph as the percentage):
    - 'because'
    - 'due to'
    - 'based on'
    - 'reflects'
    - 'since'
    - 'as a result of'
    - 'reasoning'
    - 'derived from'
    - 'supported by'
    - 'rationale'
    - 'given that'
    - 'in light of'

  EXAMPLES of RATIONALIZED (accept as Score 3):
    - 'The 25% was applied BECAUSE the easement restricts the owner's use for ingress/egress.'
    - 'A risk-based percentage of 10% was used BASED ON industry standards for temporary construction easements.'
    - 'The 30% REFLECTS the partial diminution of value DUE TO the easement's interference with current farming operations.'

  EXAMPLES of NOT RATIONALIZED (Score 2 — model has been over-scoring these):
    - 'The TCE will be valued based on a rental rate of 10% per year and extend for 35 months.' ← This states what but NOT why 10% was chosen.
    - 'Parcel 36674-3 will replace the existing utility easement and a value of 50% of fee will be assigned.' ← States the percentage but NO reasoning.
    - 'Easement value: 25%' ← Simple listing.
    - Table showing percentages without narrative explanation.

  TEST: For every percentage in the acquisition (TCE rate, easement %, etc.), search the narrative for a rationalization keyword NEAR that percentage. If NONE of the percentages have rationalization keywords → Score 2.

  If there ARE NO easements or TCEs in this acquisition (fee-only acquisition) → rationalization check does NOT apply; score based on other criteria.

- SCORE 4 MARKET-DERIVED CRITERIA (strict):
  Requires EXPLICIT mention of market sources like:
    - 'Comparable sales analysis showed...'
    - 'Broker survey indicated...'
    - 'Property manager interviews revealed...'
    - 'Market data from X percent...'
  Simply stating a percentage with generic rationale ≠ Score 4. Must cite market source.

- SCORING (strict hierarchy):
  - Score 1: Math errors or missing subparcels or wildly unreliable values/percentages.
  - Score 2: All subparcels present, seemingly valued correctly, BUT no written rationalization for percentages (just listed, not explained). If easements/TCEs present without rationale → Score 2.
  - Score 3: All subparcels match appraisal map + underlying fee captured at $1/subparcel + TCE rental rates with risk-based percentage rationalized in narrative + easements with percentage of fee rationalized in narrative.
  - Score 4: All of 3 + percentages are explicitly MARKET-DERIVED with cited source (sales/managers/brokers).

- OUTPUT REQUIREMENT: If Score 3+, quote the rationalization sentence. If Score 4, quote the market source reference.""",

        "Improvements": """- Locate IMPROVEMENTS section.
- ANTI-HALLUCINATION: Before claiming line items are missing, LIST all improvement line items that DO appear. Quote the actual improvements table/list.
- If report explicitly states 'no improvements impacted' or 'There are no improvements impacted' → valid Score 3 with $0 value.
- Cost guide sources require page numbers and version numbers.
- No personal property should be paid.
- Improvements with no value must still be listed at $0 for Score 4.
- Cross-check with After Analysis: Improvement value + damage value should not exceed RCN.
- SCORING:
  - Score 1: Major math errors, no sourcing, missing improvements, OR more improvements listed than impacted.
  - Score 2: Like 3 but minor math errors or missing some value sources. All impacted improvements addressed, no arbitrary additions.
  - Score 3: Either 'no improvements impacted' stated, OR all impacted improvements listed with values and sources (page/version for cost guides).
  - Score 4: All of 3 + includes $0 line items for impacted improvements with no value.""",

        "After Analysis (if required)": """- CLIENT CLARIFICATION: All partial acquisitions need the after condition analyzed. Extent can be brief (abbreviated) or extensive (full) depending on complexity.
- FIRST: detect acquisition type. Check RW 7-9 'Part' checkbox, or Introduction for 'partial acquisition' / 'partial fee acquisition' wording, or 'Full Acquisition' language.
- If FULL acquisition with no remainder → N/A.
- If PARTIAL acquisition → After Analysis IS required. Search for section titled: 'After Analysis', 'Remainder', 'Damages and Benefits', 'Remainder — Damages and Benefits', 'After Condition', or similar addressing the after-condition.
- The section name does NOT have to be literally 'After Analysis' — 'Remainder - Damages and Benefits' CAN satisfy this.
- Abbreviated method required elements: (1) method justified, (2) only minor improvements for damages/curative (3) no major damages or parking loss, (4) no access rights acquired.
- Full analysis required when: significant damages, parking loss paid, or access rights being acquired. Requires: parcel description, HABU, approaches to value, RW 7-12 with Line A-G math, damages ≤ property value.
- SCORING:
  - N/A: Full acquisition, no remainder.
  - Score 1: Partial acquisition but NO after-condition analysis found anywhere.
  - Score 3: Abbreviated (method justified + only minor damages + no parking loss) OR Full (parcel description + HABU + approaches + RW 7-12 with correct math + damages ≤ property value).""",

        "Cost to Cure": """- CLIENT CLARIFICATION: If no curative damages used → N/A. 'No damages' is valid evidence, not a deficiency.
- Search for statements: 'no damages', 'no curative damages', 'damages not substantiated', 'Total Damages: $0.00', 'Curable Damage Item: None', 'no cost to cure needed'.
- If such statement found → N/A (or Score 3 if the report is abbreviated and explicitly includes 'no damages' as the after analysis conclusion).
- If curative damages ARE present, verify calculation method: cost guide with page/version OR bid checked with cost guide OR multiple bids.
- SCORING:
  - N/A: Report confirms no curative damages (no cost to cure needed).
  - Score 3: Curative items justified (mitigate severance damage OR abbreviated minor damage rationalized) + calculated via cost guide with page/version, bid + cost guide, or multiple bids.""",

        "Construction Contract Work": """- CCW is a damage payment form. If CCW is used to reestablish access, damage for loss of access should NOT also be paid in after analysis.
- If report confirms 'no CCW' or 'no Construction Contract Work needed' → valid Score 3.
- CRITICAL COMMENT LOGIC: When 'no CCW' path is taken, the comment should CONFIRM adequacy ('Report confirms no CCW is needed, meeting rubric requirement') — NOT imply something is missing.
- SCORING:
  - Score 3: Statement confirming no damage warranting CCW, OR damages previously established in after analysis + CCW estimates from design + PM and ES.""",

        "Summary of Just Compensation": """- Locate 'SUMMARY OF JUST COMPENSATION' or 'Summary of the Basis for Just Compensation' section.
- SCORING:
  - Score 3: Summary of methods used + how damages were determined/not substantiated + benefits (or lack thereof) + CCW addressed.""",

        "Comparable Summary Page": """- This is a DATA-ONLY LISTING page — no analysis required. Do NOT penalize for lack of analysis.
- Required data should match RW 7-11/7-11A forms.
- SCORING:
  - Score 3: Lists all comparables with sales date, zoning, size, land value data, improvements value data, total price. For cap rates: sales date, size, building size, sales price, NOI, capitalization rate.""",

        "Comparable Map Sheet": """- CLIENT CLARIFICATION: Parcel borders should be OUTLINED on the map. Sometimes zoomed out far enough they appear as dots — visual OCR limitation.
- EVIDENCE ACCURACY: If parcels ARE outlined but in wrong colors (not red/orange/green) → state 'outlined but miscolored' NOT 'not outlined'. Score 2.
- Required: subject outlined in red, sales in orange, listings in green, north arrow present.
- SCORING:
  - Score 1: No map or inaccurate map.
  - Score 2: Contains everything in 3 BUT north arrow missing OR miscolored properties.
  - Score 3: Map showing subject relative to comparables + north arrow + subject red / sales orange / listings green.
  - Score 4: All of 3 + size and shape of parcels shown.""",

        "Comparable Data Sheets": """- REQUIRED FORMS: RW 7-11 or RW 7-11A for every comparable (sale, listing, or rental).

- STRICT LITERAL TEXT REQUIREMENT (HARD RULE for Score 3+):
  The document MUST contain the EXACT literal string 'RW 7-11' or 'RW 7-11A' somewhere in the comparable data sheets.
  Search for these patterns:
    - 'RW 7-11'
    - 'RW 07-11'
    - 'RW 7-11A'
    - 'RW 07-11A'
    - 'Form RW 7-11'
    - '(RW 7-11)'

  If the EXACT literal 'RW 7-11' or 'RW 7-11A' is NOT found in the comparable data section → MAX Score 2.
  Custom labels like:
    - 'Comparable Data Sheet'
    - 'Sales Comparable Data'
    - 'COMPARABLE NO. 1'
    - 'Data Sheet for Sale #1'
  These are NOT RW 7-11 forms, even if they contain similar information. → MAX Score 2.

- CLIENT-CONFIRMED EXAMPLES:
  - Parcels 36668, 36674, 38355: All use CUSTOM data sheets without the literal 'RW 7-11' or 'RW 7-11A' string → All score 2 (not 3+).

- Concurring statement required if inspected by another appraiser not on certificate.

- SCORING (strict hierarchy):
  - Score 1: One or more comparables missing any data sheet at all.
  - Score 2: Data sheets exist BUT not explicitly 'RW 7-11' or 'RW 7-11A' (custom forms) OR concurring statement missing OR inspected by non-certified appraiser.
  - Score 3: Every comparable has a LITERAL 'RW 7-11' or 'RW 7-11A' form + concurring statement if verified by others. May have minor info errors.
  - Score 4: All of 3 + no errors.

- OUTPUT REQUIREMENT: In evidence, quote the literal form reference text found (or state 'Custom data sheets — no RW 7-11 literal text found').""",

        "Appraisal Maps": """- DO NOT confuse with Comparable Map Sheet.
- Locate the official state/department Right of Way Appraisal Map (not the Comparable Data Map with aerial photos/dots).
- Cross-check subparcels and rights with RW 7-9.
- SCORING:
  - Score 1: Missing any mapping.
  - Score 3: Contains appraisal maps showing entire proposed acquisition.
  - Score 5: Both appraisal map(s) AND index map present.""",

        "Appraisal Terms": """- Locate 'APPRAISAL TERMS' or 'DEFINITIONS' section (often in an appendix).

- DEFAULT-TO-SCORE-5 RULE (IMPORTANT):
  If an Appraisal Terms/Definitions section EXISTS and contains the standard real-estate appraisal terms (Fair Market Value, Highest and Best Use, Easement, Fee Simple, Larger Parcel, Remainder, Benefit to Remainder, Damage to Remainder, Temporary Easement, etc.) → Default to Score 5 unless specific outdated sources are found.
  Do NOT default to Score 3 out of conservatism — Score 3 requires you to IDENTIFY specific outdated source citations.

- OUTDATED SOURCE IDENTIFICATION (required for Score 3):
  To justify Score 3 instead of 5, you MUST find explicit evidence of:
    - Citations to outdated publications (e.g., 'The Dictionary of Real Estate Appraisal, 3rd Edition' when 7th edition exists)
    - Outdated statutes or code references (e.g., referencing repealed sections)
    - Terms with clearly obsolete definitions
  If you cannot identify a specific outdated citation → Score 5, NOT Score 3.

- CLIENT-CONFIRMED EXAMPLES:
  All 3 parcels (36668, 36674, 38355): Standard Appraisal Terms section with Fair Market Value, HABU, Easement, Fee Simple definitions. No outdated citations identified → Score 5.

- SCORING:
  - Score 1: Appraisal Terms section missing entirely, OR section exists but missing required definitions (Fair Market Value, HABU, Easement, Fee Simple).
  - Score 3: Present with SPECIFIC outdated sources identified (must cite what is outdated).
  - Score 5: Present with all standard appraisal terms and NO identifiable outdated citations. ← DEFAULT SCORE for standard reports.

- OUTPUT REQUIREMENT: For Score 3, list the specific outdated citations. For Score 5, confirm standard terms are present.""",

        "Delegations": """- CRITICAL: This category has the SAME cross-reference requirement as Certificate of Appraiser. If Certificate of Appraiser = Score 1 (missing cert), Delegations MUST also = Score 1.

STEP 1 — IDENTIFY DELEGATION STRUCTURE:
Extract from Title Page:
  - Appraiser signers with roles (R/W Agent, Range-A, Range-B, Associate R/W Agent)
  - Approving signers (Senior Right of Way Agent, Chief, Division Chief)
  - Verifier (Calculations verified by)

STEP 2 — CALTRANS HIERARCHY RULES (apply strictly):
  (a) Minimum to perform an acquisition appraisal = Associate R/W Agent, OR Range-A/Range-B R/W Agent co-signed by an Associate (or higher).
  (b) Anyone signing as 'R/W Agent', 'Range-A', or 'Range-B' (NOT Associate) REQUIRES a cosigning Associate or Senior who ALSO has their own Certificate of Appraiser.
  (c) Approving Senior cannot also be an appraiser on the same report.
  (d) Approval delegation: noncomplex under $25K → Senior approves. Complex or ≥$25K → Office Chief of Appraisals or Division Chief.
  (e) HQ vs District: Check delegation matrix (HQ Approved Parcels or District Approved Parcels count).

STEP 3 — CROSS-REFERENCE APPRAISERS TO CERTIFICATES:
For every appraiser on Title Page, verify they have a signature on the Certificate of Appraiser page (same structural extraction as Certificate of Appraiser category).
If any appraiser is MISSING a Certificate → delegation violation → Score 1.

STEP 4 — EXAMPLE FAILURE (Parcel 36668):
Title Page has: Blake Starr (Range B, R/W Agent) + Jason Ybarra (Associate R/W Agent, co-signing).
Certificate section has: ONLY Blake Starr.
Ybarra is listed as Associate co-signer but has NO certificate → DELEGATION VIOLATION → Score 1.

# ANTI-HALLUCINATION HARD RULE:
Do NOT assume the delegation is correct just because signatures exist. Verify every appraiser has their own certificate.

OCR LIMITATION: Ignore illegible signatures — if the signature block is physically filled with a name, count it as signed.

SCORING:
  - Score 1: Does not follow correct delegations, OR missing correct signatures, OR R/W Agent without Associate co-sign + certificate, OR approving Senior also acting as appraiser.
  - Score 5: Correct delegations with no deviation + all required signatures + every appraiser has their own certificate.

OUTPUT REQUIREMENT: In your evidence field, explicitly confirm whether every Title Page appraiser has a certificate. If not, list the missing ones.""",

        "COS & HMDD": """- This category checks for TWO required documents in the appraisal report:
  (1) Hazardous Materials Disclosure Document (HMDD) — also called Environmental Disclosure
  (2) Certificate of Sufficiency (COS)

- WHAT TO EXTRACT for HMDD:
  - Search for headings like 'HAZARDOUS MATERIALS DISCLOSURE DOCUMENT', 'HMDD', 'Environmental Disclosure', 'Hazardous Waste Disclosure'.
  - Verify the parcel number from this report appears on the HMDD.
  - Check if hazardous waste is being acquired. If yes, verify it is valued per RW Manual requirements for hazardous waste.

- WHAT TO EXTRACT for Certificate of Sufficiency:
  - Search for 'CERTIFICATE OF SUFFICIENCY', 'COS', 'Sufficiency Certificate'.
  - Verify the parcel number from this report appears on the COS.

- SCORING (binary — only Score 1 or Score 5):
  - Score 1: HMDD missing OR HMDD doesn't include the parcel number OR COS missing OR COS doesn't include the parcel number OR hazardous waste acquired without proper RW Manual valuation.
  - Score 5: Both documents present, both include the parcel number, and any hazardous waste is properly valued.

- OUTPUT REQUIREMENT: In evidence, list (a) HMDD present yes/no with parcel number match, (b) COS present yes/no with parcel number match, (c) hazardous waste flagged yes/no. If anything is missing, explicitly state which.""",

        "Diary, Notice of Decision to Appraise & Loss of Business Goodwill": """- This category checks for THREE required documents in the appraisal report:
  (1) RW Diary — appraiser's diary/log of work performed
  (2) Notice of Decision to Appraise Letter — copy of the notice sent to the property owner
  (3) Loss of Business Goodwill Letter — REQUIRED ONLY if a business operates on the subject property

- WHAT TO EXTRACT for RW Diary:
  - Search for 'RW DIARY', 'R/W Diary', 'Diary', 'Appraiser Diary', 'Appraisal Diary'.

- WHAT TO EXTRACT for Notice of Decision to Appraise:
  - Search for 'NOTICE OF DECISION TO APPRAISE', 'Notice of Decision', 'Decision to Appraise Letter', 'Notice of Intent to Appraise'.

- WHAT TO EXTRACT for Loss of Business Goodwill (CONDITIONAL):
  - First determine if a business operates on the subject. Keywords: 'business', 'commercial operation', 'tenant', 'retail operating', 'commercial use', 'income-producing'.
  - If NO business operates on the subject → Loss of Business Goodwill letter is NOT required (skip this check).
  - If a business operates → search for 'LOSS OF BUSINESS GOODWILL', 'Goodwill Letter', 'Business Goodwill'.

- SCORING (binary — only Score 1 or Score 5):
  - Score 1: RW Diary missing OR Notice of Decision to Appraise letter copy missing OR (if a business operates) Loss of Business Goodwill letter missing.
  - Score 5: All required documents present (Diary + Notice always required; Goodwill letter required only if a business operates).

- OUTPUT REQUIREMENT: In evidence, list (a) Diary present yes/no, (b) Notice of Decision present yes/no, (c) does a business operate on subject yes/no, (d) if business operates, is Goodwill letter present yes/no. State the exact missing items if any.""",
    }

    return rules.get(category_name, """- PHYSICALLY LOCATE the section in the document.
- READ THE ENTIRE SECTION.
- Extract specific evidence (quote exact text with page #).
- Verify against rubric requirements.
- Score based only on physically located evidence.
- If evidence NOT FOUND → write 'NOT FOUND' and assign lower score (1-2).""")


def build_chunk_prompt(chunk_categories: Dict[str, Dict[str, str]]) -> Tuple[str, str]:
    """Build system and user prompts for a chunk of categories."""

    rubric_rules = ""
    category_names = list(chunk_categories.keys())

    for category, criteria in chunk_categories.items():
        rubric_rules += f"\n## {category}\n"
        for score, description in criteria.items():
            if description:
                rubric_rules += f"- Score {score}: {description}\n"
            else:
                rubric_rules += f"- Score {score}: (not specified in rubric - do NOT award this score)\n"

    extraction_rules = ""
    for cat in category_names:
        extraction_rules += f"\n### {cat}\n"
        extraction_rules += get_extraction_rules(cat)

    system_prompt = f"""You are a forensic document analyst for Caltrans Right of Way appraisals.
Your job is to EXTRACT and VERIFY facts from the document - NOT to assume or infer.

# CORE ANTI-HALLUCINATION RULES

1. If you cannot find evidence, write "NOT FOUND" - do NOT invent content
2. Use EXACT QUOTES - no paraphrasing
3. A score level is ONLY valid if its rubric criteria explicitly exists. If the rubric says "(not specified in rubric - do NOT award this score)", you CANNOT give that score.
4. Evidence text must match extraction — if extraction says NOT FOUND, evidence must say "not found" or "missing"
5. Names on title page ≠ certificates. Must see actual signed certificate.
6. "Outlined" means parcel boundary shapes traced. Colored boxes/labels can count if client-acceptable.
7. "RW lines denoted" requires explicit text: "existing right of way line", "state's right of way line", or "current right of way line". Easement lines and subparcel outlines do NOT count.
8. Cost Approach ≠ Cost to Cure. Cost guide usage in Improvements/Cost to Cure does NOT count as Cost Approach.

# N/A LOGIC — USE "N/A" (not a numeric score) WHEN:

- HABU Improved: property is unimproved/vacant (no building).
- HABU Reconciliation: only HABU Vacant was done (HABU Improved = N/A).
- Income Approach (If used): methodology states not used.
- Cost Approach (If Used): no formal Cost Approach section + methodology doesn't mention it.
- Reconciliation: only ONE valuation approach used (single-approach reports).
- Cost to Cure: report confirms no damages.
- After Analysis (if required): full acquisition with no remainder.

# CROSS-CATEGORY DEPENDENCIES

1. Before scoring HABU Improved: determine if property has a building. If unimproved → N/A.
2. Before scoring HABU Reconciliation: check HABU Improved status. If N/A → HABU Reconciliation = N/A.
3. Before scoring Reconciliation: count valuation approaches in methodology. If 1 → N/A.
4. Before scoring Cost Approach: check methodology for formal use. Cost guide for fencing ≠ Cost Approach.
5. Before scoring After Analysis: detect acquisition type (RW 7-9 Part checkbox, Introduction).
6. For Certificate of Appraiser + Delegations: cross-reference Title Page appraisers vs Certificate section names.

# CATEGORY-SPECIFIC EXTRACTION REQUIREMENTS
{extraction_rules}

# RUBRIC RULES FOR THIS CHUNK
{rubric_rules}

# OUTPUT FORMAT - JSON ARRAY (CRITICAL)

Output ONLY a JSON array. No markdown code fences. No text before or after. Exactly one object per category:

[
  {{
    "category": "{category_names[0]}",
    "score": 4,
    "criteria_met": "quote from rubric for the score awarded",
    "evidence": "exact quote from document with page number",
    "status": "✅ Pass",
    "comments": "brief factual explanation"
  }},
  ...
]

# STATUS RULES
- "✅ Pass" for Score 4-5
- "⚠️ Warning" for Score 3
- "❌ Fail" for Score 1-2
- "⚪ N/A" for N/A categories

# SCORING RULES
- Score based ONLY on extracted evidence
- For N/A: set "score" to the string "N/A" (not a number)
- For categories where max achievable score is 3 (e.g., Introduction, Parcel Description, Certificate of Appraiser): do NOT award Score 4 or 5 even if criteria seem exceeded.
- For blank rubric levels (e.g., Delegations Scores 2-4, Title Page Score 4): you CANNOT award these scores. Choose the next valid score.
- Be STRICT: your job is to find faults, not excuse them.
"""

    category_list = "\n".join(f"- {cat}" for cat in category_names)

    user_prompt = f"""Evaluate ONLY these {len(category_names)} categories:

{category_list}

For EACH category:
1. Apply the category-specific extraction requirements
2. Check cross-category dependencies (is this an N/A category?)
3. Extract specific evidence (exact quote with page #)
4. Verify against rubric (respect blank score levels)
5. Assign score based on evidence

Output ONLY the JSON array:"""

    return system_prompt, user_prompt


def parse_chunk_results(response_content: str, expected_categories: List[str]) -> List[EvaluationResult]:
    """Parse JSON results from a chunk response with EXACT-MATCH category mapping."""

    results = []
    content = response_content.strip()

    # Strip markdown code fences
    if content.startswith("```json"):
        content = content[7:]
    if content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()

    try:
        data = json.loads(content)

        if not isinstance(data, list):
            print(f"  Warning: Expected JSON array, got {type(data)}")
            return results

        for item in data:
            try:
                if not isinstance(item, dict):
                    continue

                raw_category = item.get('category', '').strip()

                # FIX FOR CATEGORY MAPPING BUG:
                # 1. Try EXACT match first
                # 2. Only fall back to fuzzy match if no exact match found
                mapped_category = None

                # Exact match
                for valid_cat in VALID_CATEGORIES:
                    if valid_cat == raw_category:
                        mapped_category = valid_cat
                        break

                # Exact match (case-insensitive) — prefer this over substring match
                if not mapped_category:
                    for valid_cat in VALID_CATEGORIES:
                        if valid_cat.lower() == raw_category.lower():
                            mapped_category = valid_cat
                            break

                # Only if still no match, do careful substring match
                # (prefer the LONGEST matching category to avoid Reconciliation→HABU Reconciliation bug)
                if not mapped_category:
                    candidates = []
                    for valid_cat in VALID_CATEGORIES:
                        if valid_cat.lower() in raw_category.lower() or raw_category.lower() in valid_cat.lower():
                            candidates.append(valid_cat)
                    if candidates:
                        # Prefer the one that matches the expected categories for this chunk
                        expected_candidates = [c for c in candidates if c in expected_categories]
                        if expected_candidates:
                            # Prefer longest exact-prefix match
                            mapped_category = max(expected_candidates, key=len)
                        else:
                            mapped_category = max(candidates, key=len)

                if not mapped_category:
                    print(f"  Warning: Could not map category '{raw_category}'")
                    continue

                # Extract score — handle N/A
                score_raw = item.get('score', '3')
                if isinstance(score_raw, str):
                    if 'N/A' in score_raw.upper() or score_raw.strip() == '-1':
                        score = -1
                    else:
                        score_match = re.search(r'(\d)', score_raw)
                        score = int(score_match.group(1)) if score_match else 3
                elif isinstance(score_raw, (int, float)):
                    score = int(score_raw) if score_raw >= 0 else -1
                else:
                    score = 3

                criteria_met = str(item.get('criteria_met', 'Not specified')).strip()
                evidence = str(item.get('evidence', 'No evidence')).strip()
                status = str(item.get('status', '❌ Fail')).strip()
                comments = str(item.get('comments', '')).strip()

                evidence = re.sub(r'\s+', ' ', evidence)

                results.append(EvaluationResult(
                    category=mapped_category,
                    score=score,
                    criteria_met=criteria_met,
                    evidence=evidence,
                    status=status,
                    comments=comments
                ))

            except Exception as e:
                print(f"  Warning: Error parsing item: {e}")
                continue

        print(f"  Parsed {len(results)} categories from JSON")

    except json.JSONDecodeError as e:
        print(f"  Warning: Could not parse JSON: {e}")
        print(f"  Response preview: {content[:300]}...")

    return results


def deduplicate_results(results: List[EvaluationResult]) -> List[EvaluationResult]:
    """Remove duplicate categories, keeping the first occurrence."""
    seen = set()
    deduped = []
    for r in results:
        if r.category not in seen:
            seen.add(r.category)
            deduped.append(r)
        else:
            print(f"  ⚠️ Duplicate category '{r.category}' dropped")
    return deduped


def fill_missing_categories(results: List[EvaluationResult], all_categories: List[str]) -> List[EvaluationResult]:
    """Ensure all rubric categories are in results. Add placeholders for any missing."""
    present = {r.category for r in results}
    for cat in all_categories:
        if cat not in present:
            print(f"  ⚠️ Missing category '{cat}' - adding placeholder")
            results.append(EvaluationResult(
                category=cat,
                score=0,
                criteria_met="Evaluation not returned",
                evidence="API response did not include this category",
                status="❌ Error",
                comments="Category missing from model response - manual review required"
            ))
    return results


def enforce_consistency(results: List[EvaluationResult]) -> List[EvaluationResult]:
    """
    Post-processing consistency checks.

    Rule 1: If Certificate of Appraiser = Score 1 (missing cert), Delegations must also = Score 1.
            Both stem from the same cross-reference failure.
    Rule 2: If HABU Improved = N/A, HABU Reconciliation must also = N/A.
    Rule 3: If HABU Improved is scored 1-5 (property is improved), HABU Reconciliation cannot be N/A if HABU Vacant was also done.
    """
    by_cat = {r.category: r for r in results}

    # Rule 1: Certificate ↔ Delegations linkage
    cert = by_cat.get("Certificate of Appraiser")
    deleg = by_cat.get("Delegations")
    if cert and deleg and cert.score == 1 and deleg.score != 1:
        print(f"  ⚠️ Consistency fix: Certificate=1 but Delegations={deleg.score}. Forcing Delegations=1.")
        deleg.score = 1
        deleg.status = "❌ Fail"
        deleg.criteria_met = "Report does not follow correct delegations or does not contain correct signatures."
        deleg.comments = (
            f"Enforced by consistency check: Certificate of Appraiser scored 1 (missing certificate). "
            f"A missing certificate is a delegation violation. Original model comment: {deleg.comments}"
        )

    # Rule 2: HABU Improved → HABU Reconciliation linkage
    habi = by_cat.get("HABU Improved")
    habr = by_cat.get("HABU Reconciliation")
    if habi and habr and habi.score == -1 and habr.score != -1:
        print(f"  ⚠️ Consistency fix: HABU Improved=N/A but HABU Reconciliation={habr.score}. Forcing N/A.")
        habr.score = -1
        habr.status = "⚪ N/A"
        habr.criteria_met = "HABU Reconciliation is only done when a HABU improved was performed. Otherwise report N/A."
        habr.comments = (
            f"Enforced by consistency check: HABU Improved is N/A (property not improved with a building), "
            f"so HABU Reconciliation is automatically N/A."
        )

    # Rule 3: HABU Vacant Score 4/5 requires explicit most likely buyer
    # If the model's own comments admit buyer is not stated, force downgrade to 3
    habu_vacant = by_cat.get("HABU Vacant")
    if habu_vacant and habu_vacant.score >= 4:
        combined_text = f"{habu_vacant.comments} {habu_vacant.evidence}".lower()
        buyer_missing_signals = [
            "most likely buyer is not explicitly stated",
            "most likely buyer is implied",
            "most likely buyer not explicitly",
            "buyer is not explicitly",
            "buyer is implied",
            "buyer is not stated",
        ]
        if any(signal in combined_text for signal in buyer_missing_signals):
            print(f"  ⚠️ Consistency fix: HABU Vacant scored {habu_vacant.score} but comments admit most likely buyer not stated. Forcing Score 3.")
            habu_vacant.score = 3
            habu_vacant.status = "⚠️ Warning"
            habu_vacant.criteria_met = "Contains the dictionary of real estate definition of HABU. Analyzes the zoning, general plan, CCRs, and other restrictions or probable uses of the parcels legal use; then has an analysis on the parcels topography, size, and other physical characteristics for the remaining legal uses; then has an analysis based on market demand on the remaining uses that are financially feasible; and finally a statement of which use is maximally productive and why."
            habu_vacant.comments = (
                f"Enforced by consistency check: Score 4/5 requires an EXPLICIT most likely buyer statement. "
                f"Original comments indicated this was missing or only implied, which fails the Score 4 prerequisite. "
                f"Downgraded to Score 3 (concludes maximally productive use but no explicit buyer identification)."
            )

    return results


def validate_document_with_gpt(extracted_text: str, rubric_categories: Dict[str, Any]) -> Tuple[str, List[EvaluationResult]]:
    """
    Validate the extracted document text against ALL rubric categories using chunked GPT calls.

    Returns:
        Tuple of (Markdown table string, List of EvaluationResult objects)
    """

    all_results = []

    # Group related categories into the same chunk so GPT sees them together.
    # This improves consistency on cross-referenced categories (Certificate ↔ Delegations,
    # HABU Improved ↔ HABU Reconciliation ↔ HABU Vacant, etc.)
    DELEGATION_GROUP = ["Title Page", "Certificate of Appraiser", "Senior Review Certificate", "Delegations"]
    HABU_GROUP = ["HABU Vacant", "HABU Improved", "HABU Reconciliation"]
    APPROACHES_GROUP = ["Methodology", "Sales Comparison Approach (If used)", "Income Approach (If used)", "Cost Approach (If Used)", "Reconciliation"]
    ACQUISITION_GROUP = ["The Acquisition - Land", "Improvements", "After Analysis (if required)", "Cost to Cure", "Construction Contract Work"]
    DOCUMENTS_GROUP = ["COS & HMDD", "Diary, Notice of Decision to Appraise & Loss of Business Goodwill"]  # NEW required-document checks

    # Reorder: dependency groups first, then remaining categories
    categories_list = list(rubric_categories.items())
    category_dict = dict(categories_list)

    ordered_keys = []
    for group in [DELEGATION_GROUP, HABU_GROUP, APPROACHES_GROUP, ACQUISITION_GROUP, DOCUMENTS_GROUP]:
        for cat in group:
            if cat in category_dict and cat not in ordered_keys:
                ordered_keys.append(cat)
    # Add remaining categories
    for cat in category_dict.keys():
        if cat not in ordered_keys:
            ordered_keys.append(cat)

    categories_list = [(k, category_dict[k]) for k in ordered_keys]
    total_chunks = (len(categories_list) + CHUNK_SIZE - 1) // CHUNK_SIZE

    print(f"\n{'='*70}")
    print(f"Processing {len(categories_list)} categories in {total_chunks} chunks of {CHUNK_SIZE}")
    print(f"Model: {GPT_MODEL}")
    print(f"Chunking strategy: dependency-grouped (Title/Certificate/Delegations together, HABU together, Approaches together)")
    print(f"{'='*70}")

    for chunk_idx in range(0, len(categories_list), CHUNK_SIZE):
        chunk_categories = dict(categories_list[chunk_idx:chunk_idx + CHUNK_SIZE])
        chunk_num = (chunk_idx // CHUNK_SIZE) + 1
        chunk_cats = list(chunk_categories.keys())

        print(f"\n{'='*70}")
        print(f"Chunk {chunk_num}/{total_chunks}: {', '.join(chunk_cats)}")
        print(f"{'='*70}")

        system_prompt, user_prompt = build_chunk_prompt(chunk_categories)

        full_user_prompt = f"""RIGHT OF WAY DOCUMENT TEXT (Landing AI OCR Extracted):
{'='*80}

{extracted_text[:150000]}

{'='*80}

{user_prompt}"""

        try:
            print(f"  Calling {GPT_MODEL}...")
            response = client.chat.completions.create(
                model=GPT_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": full_user_prompt}
                ],
                temperature=0.0,
                max_tokens=8000,
                presence_penalty=0,
                frequency_penalty=0
            )

            result = response.choices[0].message.content
            print(f"  ✓ Received {len(result)} characters")

            chunk_results = parse_chunk_results(result, chunk_cats)
            print(f"  ✓ Parsed {len(chunk_results)} categories")

            # Fill missing within chunk with placeholders (retry logic could go here)
            if len(chunk_results) < len(chunk_cats):
                print(f"  ⚠️ Expected {len(chunk_cats)} but got {len(chunk_results)}. Retrying once...")
                try:
                    retry = client.chat.completions.create(
                        model=GPT_MODEL,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": full_user_prompt}
                        ],
                        temperature=0.0,
                        max_tokens=8000,
                    )
                    retry_result = retry.choices[0].message.content
                    retry_results = parse_chunk_results(retry_result, chunk_cats)
                    if len(retry_results) > len(chunk_results):
                        chunk_results = retry_results
                except Exception as e:
                    print(f"  Retry failed: {e}")

                existing = {r.category for r in chunk_results}
                for cat in chunk_cats:
                    if cat not in existing:
                        chunk_results.append(EvaluationResult(
                            category=cat,
                            score=0,
                            criteria_met="Evaluation failed",
                            evidence="No response from model",
                            status="❌ Error",
                            comments="API did not return result for this category after retry"
                        ))

            all_results.extend(chunk_results)

        except Exception as e:
            print(f"  ✗ Error processing chunk: {e}")
            for category in chunk_categories.keys():
                all_results.append(EvaluationResult(
                    category=category,
                    score=0,
                    criteria_met="Error during evaluation",
                    evidence=f"Failed to process: {str(e)}",
                    status="❌ Error",
                    comments="API call failed"
                ))

    # Deduplicate + fill missing + enforce cross-category consistency
    all_results = deduplicate_results(all_results)
    all_results = fill_missing_categories(all_results, list(rubric_categories.keys()))
    all_results = enforce_consistency(all_results)

    # Keep rubric order
    category_order = {cat: idx for idx, cat in enumerate(rubric_categories.keys())}
    all_results.sort(key=lambda r: category_order.get(r.category, 999))

    # Build markdown table
    table_rows = []
    for r in all_results:
        score_display = "N/A" if r.score == -1 else str(r.score)
        table_rows.append(f"| {r.category} | {score_display} | {r.criteria_met} | {r.evidence} | {r.status} | {r.comments} |")

    final_table = """| Category | Score | Criteria Met | Evidence | Status | Comments |
|----------|-------|--------------|----------|--------|----------|
""" + "\n".join(table_rows)

    print(f"\n{'='*70}")
    print(f"Completed: {len(all_results)}/{len(rubric_categories)} categories evaluated")
    print(f"{'='*70}")

    return final_table, all_results


# =============================================================================
# VISION FALLBACK FOR MAP-BASED CATEGORIES
# =============================================================================

def render_pdf_pages_as_images(pdf_bytes: bytes, page_range: Tuple[int, int], dpi: int = 150) -> List[str]:
    """
    Render specified PDF pages as base64-encoded PNG images.
    Returns list of data URLs (data:image/png;base64,...) ready for OpenAI vision API.
    """
    try:
        import fitz  # pymupdf
    except ImportError:
        print("  ⚠️ pymupdf not installed — cannot render PDF images for vision fallback")
        return []

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        total_pages = len(doc)
        start_page = max(0, page_range[0] - 1)  # Convert 1-indexed to 0-indexed
        end_page = min(total_pages, page_range[1])

        data_urls = []
        zoom = dpi / 72.0  # pymupdf default is 72 DPI
        matrix = fitz.Matrix(zoom, zoom)

        for page_num in range(start_page, end_page):
            page = doc[page_num]
            pix = page.get_pixmap(matrix=matrix)
            png_bytes = pix.tobytes("png")
            b64 = base64.b64encode(png_bytes).decode("utf-8")
            data_urls.append(f"data:image/png;base64,{b64}")

        doc.close()
        print(f"  ✓ Rendered pages {page_range[0]}-{page_range[1]} ({len(data_urls)} images)")
        return data_urls
    except Exception as e:
        print(f"  ⚠️ Failed to render PDF pages: {e}")
        return []


def get_vision_prompt_for_category(category: str) -> Tuple[str, Tuple[int, int]]:
    """
    Returns (vision_prompt, page_range_to_render) for a specific map-based category.
    Page ranges are typical locations in Caltrans ROW appraisal reports.
    """
    prompts = {
        "Subject Assessor Map": (
            """You are analyzing PDF page images from a Caltrans Right of Way appraisal report.

TASK: Locate and score the SUBJECT ASSESSOR MAP section.

WHAT A SUBJECT ASSESSOR MAP LOOKS LIKE:
- It is a parcel map from the County Tax Assessor's office (also called "Assessor's Parcel Map" or "Assessor's Plat").
- Shows multiple neighboring parcels drawn as polygons with parcel numbers (e.g., "36", "40", "72Ac").
- Reference labels like "Assessor's Map Bk. 6 Pg. 27" or "Book X, Page Y" at the bottom/corner.
- The SUBJECT property is highlighted/outlined/colored differently from surrounding parcels.
- Typically appears early in the report (pages 4-8) BUT may also appear in appendix (pages 25-35).

NOT to be confused with:
- Aerial/satellite photos (those are Subject Photos or Comparable Map Sheets)
- Engineering R/W Appraisal Maps (those are on the last pages, show acquisition details with parcel numbers like 36674-1)
- Comparable parcel assessor maps (these show a COMPARABLE property, not the subject — labels will match comparable sale addresses, not subject APN)

SCORING CRITERIA:
- Score 1: No Subject Assessor Map anywhere in the pages provided.
- Score 2: Assessor map exists but subject is NOT outlined.
- Score 3: Subject outlined but the color is clearly NOT red (e.g., blue, yellow, green).
- Score 4: Subject outlined in RED but NO caption explaining the map.
- Score 5: Subject outlined in RED AND has a caption explaining the map.

INSTRUCTIONS:
1. Examine EACH page image thoroughly.
2. Look for a tax-assessor-style parcel map (polygonal parcel boundaries with parcel numbers).
3. Verify it's the SUBJECT's assessor map, not a comparable's.
4. Check outlining + color + caption.
5. If no assessor map exists in any of these pages → Score 1, but state which pages you examined.

Respond with ONLY a JSON object (no markdown, no explanation):
{
  "score": <1-5>,
  "evidence": "Page X shows a tax assessor parcel map with subject parcel outlined in [color]. Caption says: '[exact text]'. OR 'No subject assessor map found in pages examined: [list].'",
  "comments": "Brief explanation of the score."
}""",
            (1, 12)  # Render pages 1-12 for comprehensive assessor map search
        ),
        "Subject Photos": (
            """You are analyzing PDF page images from a Caltrans Right of Way appraisal report.

TASK: Locate and score the SUBJECT PHOTOS section.

Subject Photos are ground-level photographs of the subject property, usually with captions describing direction, date, and any markings on the photos.

SCORING CRITERIA:
- Score 1: No photos of the subject at all.
- Score 2: Has at least 1 photo but no dates AND no RW lines denoted, OR missing photos of impacted substantial improvements.
- Score 3: Sufficient photos with dates and photographer, but captions do NOT mention the proposed acquisition.
- Score 4: Sufficient photos + captions mention BOTH direction AND proposed acquisition, but RW lines NOT denoted in captions.
- Score 5: All of Score 4 + captions explicitly reference 'existing right of way line', 'state's right of way line', 'current right of way line', or similar RW terminology.

CRITICAL RULES:
- 'utility easement' line ≠ RW line (does not count for Score 5).
- 'subparcel outline' ≠ RW line (does not count for Score 5).
- Must find explicit RW terminology in captions for Score 5.

Respond with ONLY a JSON object:
{
  "score": <1-5>,
  "evidence": "Page X-Y contain N photos. Caption examples: '...'. Dates present/absent. RW lines denoted: yes/no.",
  "comments": "Brief explanation."
}""",
            (4, 12)  # Photos usually on pages 4-12
        ),
        "Comparable Map Sheet": (
            """You are analyzing PDF page images from a Caltrans Right of Way appraisal report.

TASK: Locate and score the COMPARABLE MAP SHEET (the aerial/satellite map showing subject property relative to comparable sales).

SCORING CRITERIA:
- Score 1: No comparable map, or map is inaccurate.
- Score 2: Contains everything in Score 3 BUT north arrow is missing OR properties are miscolored (wrong colors).
- Score 3: Map shows subject relative to comparables + has north arrow + subject outlined in RED, sales in ORANGE, listings in GREEN.
- Score 4: All of Score 3 + parcel sizes and shapes are shown (not just point markers).

CRITICAL:
- Parcels OUTLINED = parcel boundary shapes traced on the map.
- Parcels marked with DOTS/PINS/BOXES/LABELS = NOT outlined (but acceptable as a form of identification).
- Wrong colors (e.g., colored boxes instead of red/orange/green) → Score 2.
- Correct colors + outlined + north arrow → Score 3.

Respond with ONLY a JSON object:
{
  "score": <1-5>,
  "evidence": "Page X shows an aerial map. Marking method: [dots/outlines/boxes]. Colors: subject=[color], sales=[color]. North arrow: present/absent.",
  "comments": "Brief explanation."
}""",
            (25, 35)  # Comparable map typically in appendix, pages 25-35
        ),
        "Appraisal Maps": (
            """You are analyzing PDF page images from a Caltrans Right of Way appraisal report.

TASK: Locate and score the APPRAISAL MAPS section (the official state/department Right of Way Appraisal Map — NOT the comparable data map).

SCORING CRITERIA:
- Score 1: No appraisal map at all.
- Score 3: Contains an appraisal map showing the entire proposed acquisition area.
- Score 5: Contains BOTH an appraisal map(s) AND an index map. The appraisal map shows the entire proposed acquisition.

CRITICAL:
- This is the engineering-style Right of Way Appraisal Map (usually at the very end of the report, last 1-3 pages).
- Do NOT confuse with the Comparable Data Map (which is a different rubric category).
- Look for 'APPRAISAL MAP', 'R/W APPRAISAL MAP', or 'RIGHT OF WAY APPRAISAL MAP' title.

Respond with ONLY a JSON object:
{
  "score": <1 | 3 | 5>,
  "evidence": "Page X contains the R/W Appraisal Map. Shows acquisition: yes/no. Index map present: yes/no.",
  "comments": "Brief explanation."
}""",
            (30, 50)  # Appraisal maps usually last pages
        ),
    }
    return prompts.get(category, (None, None))


def evaluate_with_vision(pdf_bytes: bytes, category: str) -> Optional[EvaluationResult]:
    """
    Use GPT-4o Vision to evaluate a map-based category by analyzing PDF page images directly.
    Returns EvaluationResult or None if vision unavailable.
    """
    vision_prompt, page_range = get_vision_prompt_for_category(category)
    if not vision_prompt or not page_range:
        return None

    print(f"  🔍 Vision fallback activated for '{category}' (pages {page_range[0]}-{page_range[1]})")

    # Render PDF pages as images
    image_urls = render_pdf_pages_as_images(pdf_bytes, page_range, dpi=150)
    if not image_urls:
        return None

    # Build vision message with all images
    content = [{"type": "text", "text": vision_prompt}]
    for url in image_urls:
        content.append({"type": "image_url", "image_url": {"url": url, "detail": "high"}})

    try:
        print(f"  Calling {VISION_MODEL} Vision with {len(image_urls)} page images...")
        response = client.chat.completions.create(
            model=VISION_MODEL,
            messages=[{"role": "user", "content": content}],
            temperature=0.0,
            max_tokens=1500,
        )
        result_text = response.choices[0].message.content.strip()

        # Strip markdown fences if present
        if result_text.startswith("```json"):
            result_text = result_text[7:]
        if result_text.startswith("```"):
            result_text = result_text[3:]
        if result_text.endswith("```"):
            result_text = result_text[:-3]
        result_text = result_text.strip()

        data = json.loads(result_text)
        score = data.get("score", 1)
        if isinstance(score, str) and "N/A" in score.upper():
            score = -1
        elif isinstance(score, str):
            score_match = re.search(r"(\d)", score)
            score = int(score_match.group(1)) if score_match else 1
        else:
            score = int(score)

        # Determine status
        if score == -1:
            status = "⚪ N/A"
        elif score >= 4:
            status = "✅ Pass"
        elif score == 3:
            status = "⚠️ Warning"
        else:
            status = "❌ Fail"

        print(f"  ✓ Vision scored '{category}' as {score}")
        return EvaluationResult(
            category=category,
            score=score,
            criteria_met=f"Rubric Score {score} criteria (determined by vision analysis)",
            evidence=f"[VISION FALLBACK] {data.get('evidence', 'See vision analysis')}",
            status=status,
            comments=f"[Vision Fallback] {data.get('comments', 'Vision-based evaluation.')}"
        )
    except Exception as e:
        print(f"  ⚠️ Vision fallback failed for '{category}': {e}")
        return None


def apply_vision_fallback(
    results: List[EvaluationResult],
    pdf_bytes: Optional[bytes]
) -> List[EvaluationResult]:
    """
    For map-based categories that scored 1 (NOT FOUND) via OCR, retry with vision model.
    If vision returns a higher score with evidence, replace the result.
    """
    if not pdf_bytes:
        print("\n  ⚠️ No PDF bytes available — skipping vision fallback")
        return results

    print(f"\n{'='*70}")
    print(f"Vision Fallback Stage — checking map-based categories with Score 1")
    print(f"{'='*70}")

    candidates = []
    for r in results:
        if r.category in VISION_FALLBACK_CATEGORIES and r.score == 1:
            candidates.append(r)

    if not candidates:
        print("  No candidates for vision fallback (all map categories scored > 1)")
        return results

    print(f"  Candidates for vision fallback: {[r.category for r in candidates]}")

    for candidate in candidates:
        vision_result = evaluate_with_vision(pdf_bytes, candidate.category)
        if vision_result and vision_result.score > candidate.score:
            # Replace the result
            for i, r in enumerate(results):
                if r.category == candidate.category:
                    results[i] = vision_result
                    print(f"  ✅ '{candidate.category}': OCR Score 1 → Vision Score {vision_result.score}")
                    break
        elif vision_result:
            print(f"  ℹ️ '{candidate.category}': Vision confirmed Score {vision_result.score} (no change)")
            # Still use vision result for better evidence
            for i, r in enumerate(results):
                if r.category == candidate.category:
                    results[i] = vision_result
                    break

    return results


# =============================================================================
# MAIN VALIDATION REPORT
# =============================================================================

def generate_validation_report(pdf_bytes: bytes, pdf_filename: str) -> Tuple[str, List[EvaluationResult]]:
    """Main function to generate a validation report for a ROW document."""
    print(f"\n{'#'*70}")
    print(f"# Starting Landing AI ROW Document Validation (v3 — with Vision Fallback)")
    print(f"# Text model: {GPT_MODEL}")
    print(f"# Vision fallback model: {VISION_MODEL}")
    print(f"{'#'*70}")

    print(f"\n{'#'*70}")
    print(f"# Step 1: Finding Landing AI OCR Output")
    print(f"{'#'*70}")
    landing_ai_md_path = find_landing_ai_output_for_pdf(pdf_filename, pdf_bytes)

    if not landing_ai_md_path:
        return "❌ Error: No Landing AI OCR output found for this PDF.", []

    print(f"\n{'#'*70}")
    print(f"# Step 2: Extracting Text from {landing_ai_md_path}")
    print(f"{'#'*70}")
    extracted_text = extract_text_from_landing_ai_md(landing_ai_md_path)

    if not extracted_text:
        return "❌ Error: Failed to extract text from the Landing AI OCR output file.", []

    print(f"✓ Extracted {len(extracted_text):,} characters")

    print(f"\n{'#'*70}")
    print(f"# Step 3: Loading Rubric Schema")
    print(f"{'#'*70}")
    rubric_schema = load_rubric_schema()

    if not rubric_schema:
        return "❌ Error: Failed to load rubric schema.", []

    print(f"✓ Loaded {len(rubric_schema)} rubric categories")

    print(f"\n{'#'*70}")
    print(f"# Step 4: AI Validation with {GPT_MODEL} (Chunked Processing, {CHUNK_SIZE} per chunk)")
    print(f"{'#'*70}")
    validation_result, evaluation_results = validate_document_with_gpt(extracted_text, rubric_schema)

    # Step 5: Apply vision fallback for map-based Score 1 results
    print(f"\n{'#'*70}")
    print(f"# Step 5: Vision Fallback for Map-Based Categories")
    print(f"{'#'*70}")
    evaluation_results = apply_vision_fallback(evaluation_results, pdf_bytes)

    # Rebuild final table with updated results
    table_rows = []
    for r in evaluation_results:
        score_display = "N/A" if r.score == -1 else str(r.score)
        table_rows.append(f"| {r.category} | {score_display} | {r.criteria_met} | {r.evidence} | {r.status} | {r.comments} |")

    final_table = """| Category | Score | Criteria Met | Evidence | Status | Comments |
|----------|-------|--------------|----------|--------|----------|
""" + "\n".join(table_rows)

    return final_table, evaluation_results


def run_landing_ai_row_evaluation(uploaded_file) -> Tuple[str, List[EvaluationResult]]:
    """Entry point for Landing AI ROW evaluation from Streamlit app."""
    pdf_bytes = uploaded_file.getvalue()
    pdf_filename = uploaded_file.name
    print(f"\n{'#'*70}")
    print(f"# Received PDF: {pdf_filename} ({len(pdf_bytes):,} bytes)")
    print(f"{'#'*70}")

    return generate_validation_report(pdf_bytes, pdf_filename)


def create_excel_download_buffer(evaluation_results: List[EvaluationResult]):
    """Create Excel file in memory for download."""
    import pandas as pd
    from io import BytesIO

    data = [
        {
            'Category': result.category,
            'Score': 'N/A' if result.score == -1 else result.score,
            'Criteria Met': result.criteria_met,
            'Evidence': result.evidence,
            'Status': result.status,
            'Comments': result.comments
        }
        for result in evaluation_results
    ]

    df = pd.DataFrame(data)

    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='ROW Evaluation')

    buffer.seek(0)
    return buffer


if __name__ == "__main__":
    print("Landing AI Right of Way Evaluation Module v2")
    print(f"Using GPT Model: {GPT_MODEL}")
    print(f"Chunk Size: {CHUNK_SIZE} categories per API call")
