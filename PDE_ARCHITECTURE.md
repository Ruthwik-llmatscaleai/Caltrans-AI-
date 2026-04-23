# Project Delivery Evaluator (PDE) — System Architecture

## 1. Executive Summary & Goal
The **Project Delivery Evaluator (PDE)** is an AI-powered SaaS application designed to help state transportation departments (specifically modeled around Caltrans procedures) select the optimal project delivery method. Delivery methods include Design-Bid-Build, Design-Build, CM/GC, Progressive Design-Build, etc.

**The core problem:** Project managers write lengthy "Nomination Fact Sheets" and manually map project constraints (budget, schedule, innovation needs, right-of-way risks) against a massive rubric to pick a delivery method. This is tedious, subjective, and prone to error.

**The solution:** PDE ingests unstructured project documents (PDFs, DOCX), uses Large Language Models (LLMs) to perform a first-pass evaluation against a standard 25-question evaluation rubric, maps the answers to an affinity matrix, and recommends the best delivery method. Most importantly, it includes an interactive **Human-in-the-Feedback-Loop (HIFL)** architecture, allowing the system to learn from human corrections ("Institutional Memory") without requiring a heavy backend database.

## 2. Core Architectural Pillars

### 2.1. Stateless Cloud Run Design
PDE is built via Streamlit and deployed on stateless cloud infrastructure (e.g., Google Cloud Run). 
*   **No Database:** For prototype speed, security, and multi-tenant safety, there is no persistent database.
*   **File-Backed State:** All state is handled within the Streamlit session. Persistence between sessions occurs strictly via the user uploading/downloading state files (`.pdf`/`.docx` for project scope, and `pde_rules.json` for AI memory).

### 2.2. The LLM Evaluation Pipeline (`project_delivery_evaluator.py`)
1.  **Extraction Setup:** The system extracts raw text from the uploaded project fact sheets.
2.  **Rubric Evaluation:** A system prompt containing a 6-category, 25-question rubric is sent to the LLM (typically GPT-4o or similar high-capacity reasoner).
3.  **JSON Response:** The LLM returns structured JSON containing its chosen rating (`A`, `B`, or `C`), the exact quote/evidence supporting the rating, and a confidence score for each of the 25 questions.
4.  **Matrix Scoring:** The 25 ratings are run through a hardcoded weighted matrix (`calculate_method_scores`). Each delivery method has different strengths, so an `A` on schedule risk benefits Design-Build more than Design-Bid-Build.
5.  **Recommendation Reasoning:** Instead of passing the entire document back to the LLM to write a summary, a secondary lightweight LLM call (`gpt-4o-mini`) uses *only the extracted quote snippets* for the top-ranking method to generate a 2-sentence plain-English justification, saving massive amounts of tokens.

## 3. Human-in-the-Feedback-Loop (HIFL) & Continuous Learning
The most distinguished feature of the PDE is its ability to learn from human disagreement. As users review the AI's first-pass ratings, they can override them.

### The 4-Step HIFL Wizard Workflow
The UI operates via a state machine (`wizard_step` 1-4) to prevent context overload.

#### Step 1: Review & Override
*   Users see the AI's rating and the specific paragraph of evidence it cited.
*   If the AI is wrong, the user changes the rating and is **required** to type a rationale (e.g., "The document actually says Right of Way is fully acquired in section 4, not pending.").
*   This is staged as a "Draft Rule".

#### Step 2: Validation Audit (Optional)
*   The system can perform a self-audit, calculating an `Agreement Rate` between the AI and the Human.
*   It categorizes mismatches into Minor vs. Major and detects if the human's overrides were severe enough to change the ultimate delivery method recommendation.

#### Step 3: Security Review (LLM Adjudicator)
*   *The Problem:* We want the AI to learn from the human, but we cannot blindly trust user input. A user might try to force a specific delivery method by maliciously altering rules or writing garbage rationales.
*   *The Solution:* An independent LLM call (the **Adjudicator**) acts as a security gateway. It reviews the human's override rationale against Caltrans policy.
*   If the rationale makes sense contextually, it is "approved."
*   If the rationale is illogical or seems manipulative, the Adjudicator flags it, issues a "Concern," and demands the user "Defend" the correction in a single-turn defense loop.
*   *Fail-Open Design:* If the Adjudicator API times out or fails, laws of prototyping dictate that the user is not blocked; the rule is marked "offline" and approved.

#### Step 4: Institutional Memory Synthesis & Export
*   Once rules are approved, they must become long-term memory.
*   The system takes the newly approved rules and merges them with the previously uploaded `pde_rules.json`.
*   *Abstractive Compression:* To prevent prompt bloat over years of use, an LLM compressor function (`synthesize_rulebook`) groups related rules by their rubric Question ID. If it finds 5 rules that all basically say "If the text mentions SB-1 funding, rating is A", it synthesizes them into one concise master rule.

## 4. Reporting & Export Generation
The final step is generating deliverables that project managers can take to formal committee meetings.
*   **Dual Download:** The user downloads the generated `pde_rules.json` (to feed back into the tool next time) and the official `Excel Delivery Evaluation Report`.
*   **Template-Driven Excel:** Using `openpyxl`, the system reads an empty styled `.xls` template and injects the evaluation data.
*   **Structure:** It builds an Executive Summary sheet and creates dedicated tabs for *each* delivery method, detailing how that method scored on all 25 questions, complete with the human overrides and the AI's supporting text evidence.

## 5. Development Details & Intuition
If you are an LLM or developer inheriting this codebase, understand these core tenets:
1.  **Token Economy:** Full documents are read *once* in `run_delivery_evaluation`. After that, we only pass small text fragments (like `source_reasoning`) to subsequent LLM steps (Validation, Reasoning Generation, Adjudicator) to keep it fast and cheap.
2.  **State Management:** Because Streamlit reruns the script top-to-bottom on every button click, heavy operations (LLM calls, Excel generation) are heavily guarded by `if "key" not in st.session_state` checks. Do not break these locks.
3.  **HIFL is King:** The entire architecture is built around the human. The AI is a co-pilot that does the heavy reading; the human performs the critical thinking and strategy definition. The system's job is simply to capture the human's intelligence robustly.
