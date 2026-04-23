# Project Delivery Evaluator (PDE) — V2 Workflow Guide

This document outlines the standard workflows for project evaluation using the PDE V2 system, covering both initial District assessment and the Human-in-the-Feedback-Loop (HIFL) review process.

---

## 1. District Role: Initial Project Assessment

The **District Role** is responsible for the baseline evaluation of a project. 
1. **Document Upload**: The user uploads the project nomination documents (e.g., Fact Sheets).
2. **Automated Extraction**: The AI engine analyzes the documents against the project rubric.
3. **Draft Results**: The system generates an initial scoring set and identifies "Missing Context" areas where the document evidence is incomplete.

---

## 2. HIFL Role: Expert Review & Quality Assurance

The **HIFL Role** follows a structured 3-phase process to verify and refine the AI's findings. This ensures the final recommendation is official and human-verified.

### **Phase 1: Review and Correction**
The reviewer verifies each question by comparing the AI’s results against the full rubric descriptions (A, B, or C). 
- **Lookup**: The system displays the exact criteria for the specific question being reviewed.
- **Override**: If the AI’s rating is incorrect, the reviewer selects the accurate option and provides a brief rationale. 
- **Commit**: Corrections are staged in a queue for final analysis.

### **Phase 2: Validation Audit**
The system performs a secondary comparison between the updated human ratings and the AI’s original evidence.
- **Integrity Check**: It flags major differences, particularly when the AI was highly confident in its original reading. 
- **Neutral Reference**: The reviewer can see the exact document text the AI cited, providing a factual check to verify that all overrides align with the project data.

### **Phase 3: Final Export and Reporting**
The system reconciles all verified ratings into the final project dataset.
- **Reporting**: It generates a high-fidelity Excel report where expert human ratings supersede AI predictions.
- **Audit Trail**: Every modification is archived in a permanent JSON audit file (`pde_rules.json`), ensuring a complete and transparent record for project files.
