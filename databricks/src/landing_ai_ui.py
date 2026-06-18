"""
Enhanced UI Component for Landing AI ROW Evaluation

Features:
- Two tabs: Executive Summary and Detailed Findings
- Excel download functionality
- Color-coded scores
- Clean tab switching
"""

import streamlit as st
import pandas as pd
from io import BytesIO
from typing import List, Dict, Any

from .landing_ai_row_eval_chunked import (
    run_landing_ai_row_evaluation,
    EvaluationResult,
    create_excel_download_buffer,
    GPT_MODEL
)


def create_rich_table_html(evaluation_results: List[EvaluationResult]) -> List[Dict]:
    """
    Convert evaluation results to list of dicts for DataFrame (without Status column).
    
    Args:
        evaluation_results: List of EvaluationResult objects
        
    Returns:
        List of dictionaries for pandas DataFrame
    """
    df_data = []
    for result in evaluation_results:
        # Format score display
        if result.score == -1:  # N/A
            score_display = "N/A"
        else:
            score_display = str(result.score)
        
        df_data.append({
            'Category': result.category,
            'Score': score_display,
            'Criteria Met': result.criteria_met,
            'Evidence': result.evidence,
            'Comments': result.comments
        })
    
    return df_data


def create_executive_summary(evaluation_results: List[EvaluationResult]) -> pd.DataFrame:
    """
    Create executive summary with high-level scores by category.
    
    Args:
        evaluation_results: List of EvaluationResult objects
        
    Returns:
        DataFrame with executive summary
    """
    summary_data = []
    
    for result in evaluation_results:
        # Determine status color
        if result.score == -1:
            status = "N/A"
            color = "#808080"
        elif result.score >= 4:
            status = "Pass"
            color = "#28a745"
        elif result.score == 3:
            status = "Warning"
            color = "#ffc107"
        else:
            status = "Fail"
            color = "#dc3545"
        
        summary_data.append({
            'Category': result.category,
            'Score': result.score if result.score != -1 else 'N/A',
            'Status': status,
            'Comments': result.comments
        })
    
    return pd.DataFrame(summary_data)


def create_action_items(evaluation_results: List[EvaluationResult], rubric_schema: Dict[str, Any]) -> pd.DataFrame:
    """
    Generate action items for categories that need correction.
    
    Args:
        evaluation_results: List of EvaluationResult objects
        rubric_schema: Dictionary of rubric categories and their rules
        
    Returns:
        DataFrame with action items
    """
    action_items = []
    
    # Priority mapping based on score
    priority_map = {
        1: "HIGH",
        2: "HIGH", 
        3: "MEDIUM",
        4: "LOW",
        5: "NONE"
    }
    
    # Standard action templates for common issues
    action_templates = {
        "Certificate of Appraiser": "Obtain missing certificate(s) for appraiser(s) listed on Title Page. Ensure all appraisers sign the Certificate of Appraiser section.",
        "Income Approach (If used)": "Document why Income Approach is not applicable, or complete full Income Approach analysis with market data.",
        "Cost Approach (If Used)": "Add page number and version number for cost source (e.g., Marshall & Swift). Verify depreciation calculations.",
        "Comparable Data Sheets": "Replace custom data sheets with official Caltrans RW 7-11 or RW 7-11A forms. Add concurring statement from another appraiser.",
        "Comparable Map Sheet": "Update map to use outlines (red for subject, orange for sales, green for listings) instead of colored dots/pins. Add north arrow.",
        "Subject Assessor Map": "Ensure subject parcel is highlighted in red. Add caption explaining the map.",
        "Subject Photos": "Add more photos with captions. Denote Right of Way lines and acquisition areas on photos. Include dates.",
        "Area Description": "Add employment data, market trends, and current uses. Include census data and population statistics.",
        "Senior Review Certificate": "Update form to current revision. Verify all required signatures are present.",
        "Title Page": "Update form to current revision (REV). Verify all delegation signatures.",
        "RW 7-9": "Update to current form revision. Ensure all line items are complete and mathematically correct.",
        "Scope of Work": "Expand scope to include all required elements: client, users, intended use, value definition, effective dates.",
        "Sales Comparison Approach (If used)": "Add detailed explanation of adjustments and sources. Evaluate strengths/weaknesses of comparables.",
        "Reconciliation": "Provide detailed evaluation of each approach used. Explain why any approach was not used.",
        "The Acquisition - Land": "Provide rationalization for percentages used for easements/TCEs. Include market-derived data.",
        "Improvements": "Add line items for improvements with no value. Verify all impacted improvements are listed.",
        "Delegations": "Verify all required signatures are present and follow correct delegation chain."
    }
    
    for result in evaluation_results:
        category = result.category
        actual_score = result.score
        
        # Skip N/A and perfect scores
        if actual_score == -1 or actual_score == 5:
            continue
        
        # Determine priority
        priority = priority_map.get(actual_score, "MEDIUM")
        
        # Get action item text
        action_text = action_templates.get(category, 
            f"Review {category} and address deficiencies to meet Score 5 requirements.")
        
        # Add specific details from evidence
        if actual_score <= 2:
            # High priority - specific fix needed
            if "NOT FOUND" in result.evidence or "missing" in result.evidence.lower():
                action_text = f"CRITICAL: {action_text} Evidence: {result.evidence[:200]}"
        
        action_items.append({
            'Category': category,
            'Current Score': actual_score,
            'Target Score': 5,
            'Priority': priority,
            'Action Item': action_text,
            'Comments': result.comments
        })
    
    # Sort by priority
    priority_order = {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2}
    action_items.sort(key=lambda x: priority_order.get(x['Priority'], 3))
    
    return pd.DataFrame(action_items)


def create_detailed_findings(evaluation_results: List[EvaluationResult], rubric_schema: Dict[str, Any]) -> pd.DataFrame:
    """
    Create detailed findings with all rubric rules broken down for each category.
    Each rule is scored as 0 or 1 (binary scoring).
    
    Args:
        evaluation_results: List of EvaluationResult objects
        rubric_schema: Dictionary of rubric categories and their rules
        
    Returns:
        DataFrame with detailed findings showing each rubric rule with binary score
    """
    detailed_data = []
    
    for result in evaluation_results:
        category = result.category
        actual_score = result.score
        
        # Get rubric rules for this category
        rubric_rules = rubric_schema.get(category, {})
        
        # Sort rubric rules by score level
        sorted_rules = sorted(rubric_rules.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 0)
        
        # Create a row for each rubric score level
        for score_level, rule_description in sorted_rules:
            # Determine if this rule is met based on the actual score
            try:
                score_int = int(score_level)
                
                # For N/A items
                if actual_score == -1:
                    rule_score = "N/A"
                    status = "⚪"
                    status_full = "N/A"
                    evidence = "Not applicable for this document"
                    comments = result.comments
                # For scored items - check if this rule is satisfied
                # If actual_score >= score_level, this rule is satisfied (1 point)
                elif actual_score >= score_int:
                    rule_score = "1"
                    status = "✓"
                    status_full = "Pass"
                    # Show specific evidence for why this rule passed
                    if actual_score == score_int:
                        # This is the exact score achieved - show main evidence
                        evidence = result.evidence
                        comments = result.comments
                    else:
                        # This rule is below the achieved score - explain why it passed
                        evidence = f"Score {actual_score} achieved, which satisfies Score {score_level} requirement"
                        comments = f"This rule is satisfied because the achieved score ({actual_score}) is higher than {score_level}"
                # This rule is ABOVE the actual score (not satisfied, 0 points)
                else:
                    rule_score = "0"
                    status = "✗"
                    status_full = "Fail"
                    # Show specific evidence for why this rule failed
                    evidence = f"Score {actual_score} achieved, which does not meet Score {score_level} requirement"
                    comments = f"This rule requires Score {score_level} but only Score {actual_score} was achieved"
            except:
                rule_score = "N/A"
                status = "⚪"
                status_full = "N/A"
                evidence = "Unable to evaluate"
                comments = result.comments
            
            detailed_data.append({
                'Category': category,
                'Score Level': f"Score {score_level}",
                'Rubric Rule': rule_description,
                'Rule Score': rule_score,
                'Status': status,
                'Status Full': status_full,
                'Evidence': evidence,
                'Comments': comments
            })
    
    return pd.DataFrame(detailed_data)


def render_landing_ai_evaluation_ui():
    """
    Render the complete Landing AI ROW Evaluation UI with two tabs.
    """
    
    # File uploader is already rendered in app.py, just get it from session
    uploaded_file = st.session_state.get("row_upload")
    
    if uploaded_file is None:
        return
    
    # Load rubric schema for detailed findings
    import json
    import os
    rubric_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "rubric_schema.json")
    try:
        with open(rubric_path, 'r') as f:
            rubric_schema = json.load(f)
    except:
        rubric_schema = {}

    # Check if we already have evaluation results for this file
    file_key = f"row_eval_{uploaded_file.name}"
    
    # Initialize or reset evaluation results if file changed
    if file_key not in st.session_state or st.session_state.get(f"row_eval_filename") != uploaded_file.name:
        # Run evaluation only if file is new or changed
        with st.spinner("Analyzing document..."):
            # Run evaluation
            markdown_result, evaluation_results = run_landing_ai_row_evaluation(uploaded_file)
        
        # Store results in session state
        st.session_state[file_key] = {
            'markdown_result': markdown_result,
            'evaluation_results': evaluation_results
        }
        st.session_state["row_eval_filename"] = uploaded_file.name
        st.session_state["row_eval_completed"] = True
    else:
        # Retrieve cached results
        cached_data = st.session_state[file_key]
        markdown_result = cached_data['markdown_result']
        evaluation_results = cached_data['evaluation_results']
    
    if evaluation_results and "Error" not in str(markdown_result):
        # Create tabs with larger font
        tab1, tab2, tab3 = st.tabs(["EXECUTIVE SUMMARY", "DETAILED FINDINGS", "ACTION ITEMS"])
        
        # TAB 1: Executive Summary
        with tab1:
            st.markdown("### Executive Summary - Right of Way Evaluation")
            
            # Create summary DataFrame
            summary_df = create_executive_summary(evaluation_results)
            
            # Style the dataframe with color-coded status
            def color_status(val):
                if val == 'Pass':
                    return 'background-color: #d4edda; color: #155724'
                elif val == 'Warning':
                    return 'background-color: #fff3cd; color: #856404'
                elif val == 'Fail':
                    return 'background-color: #f8d7da; color: #721c24'
                elif val == 'N/A':
                    return 'background-color: #e2e3e5; color: #383d41'
                return ''
            
            def color_score(val):
                if isinstance(val, int):
                    if val >= 4:
                        return 'background-color: #d4edda; color: #155724'
                    elif val == 3:
                        return 'background-color: #fff3cd; color: #856404'
                    elif val >= 0:
                        return 'background-color: #f8d7da; color: #721c24'
                elif val == 'N/A':
                    return 'background-color: #e2e3e5; color: #383d41'
                return ''
            
            styled_summary = summary_df.style.applymap(color_status, subset=['Status']).applymap(color_score, subset=['Score'])
            st.dataframe(styled_summary, use_container_width=True, height=600)
        
        # TAB 2: Detailed Findings
        with tab2:
            st.markdown("### Detailed Findings - Rubric Rule Breakdown")
            
            # Create detailed DataFrame with rubric breakdown
            detailed_df = create_detailed_findings(evaluation_results, rubric_schema)
            
            # Display detailed findings with formatting
            def color_detailed_status(val):
                if val == '✓':
                    return 'background-color: #d4edda; color: #155724'
                elif val == '✗':
                    return 'background-color: #f8d7da; color: #721c24'
                elif val == '⚪':
                    return 'background-color: #e2e3e5; color: #383d41'
                return ''
            
            def color_rule_score(val):
                if val == '1':
                    return 'background-color: #d4edda; color: #155724'
                elif val == '0':
                    return 'background-color: #f8d7da; color: #721c24'
                elif val == 'N/A':
                    return 'background-color: #e2e3e5; color: #383d41'
                return ''
            
            styled_detailed = detailed_df.style.applymap(color_detailed_status, subset=['Status']).applymap(color_rule_score, subset=['Rule Score'])
            st.dataframe(styled_detailed, use_container_width=True, height=700)
        
        # TAB 3: Action Items
        with tab3:
            st.markdown("### Action Items - Corrective Actions Required")
            
            # Create action items DataFrame
            action_df = create_action_items(evaluation_results, rubric_schema)
            
            if len(action_df) > 0:
                # Style by priority
                def color_priority(val):
                    if val == 'HIGH':
                        return 'background-color: #f8d7da; color: #721c24; font-weight: bold'
                    elif val == 'MEDIUM':
                        return 'background-color: #fff3cd; color: #856404'
                    elif val == 'LOW':
                        return 'background-color: #d4edda; color: #155724'
                    return ''
                
                styled_actions = action_df.style.applymap(color_priority, subset=['Priority'])
                st.dataframe(styled_actions, use_container_width=True, height=700)
            else:
                st.success("No action items! All categories scored 5 or are N/A.")
        
        # Single Excel download button (centered) at the bottom
        st.markdown("---")
        col1, col2, col3 = st.columns([3, 2, 3])
        with col2:
            # Create Excel with three sheets
            import pandas as pd
            from io import BytesIO
            
            excel_buffer = BytesIO()
            with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                # Sheet 1: Executive Summary
                summary_df = create_executive_summary(evaluation_results)
                summary_df.to_excel(writer, sheet_name='Executive Summary', index=False)
                
                # Sheet 2: Detailed Findings
                detailed_df = create_detailed_findings(evaluation_results, rubric_schema)
                detailed_df.to_excel(writer, sheet_name='Detailed Findings', index=False)
                
                # Sheet 3: Action Items
                action_df = create_action_items(evaluation_results, rubric_schema)
                if len(action_df) > 0:
                    action_df.to_excel(writer, sheet_name='Action Items', index=False)
            
            excel_buffer.seek(0)
            
            st.download_button(
                label="Download Report",
                data=excel_buffer,
                file_name=f"ROW_Evaluation_{uploaded_file.name.replace('.pdf', '')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key="download_excel_btn"
            )
    else:
        st.error(f"Error: {markdown_result}")


def landing_ai_row_ui(app_option: str):
    """
    Wrapper function for compatibility with existing app structure.
    
    Args:
        app_option: App option string (unused, for compatibility)
    """
    render_landing_ai_evaluation_ui()


if __name__ == "__main__":
    # Test the UI component
    st.set_page_config(page_title="Landing AI ROW Evaluation", layout="wide")
    render_landing_ai_evaluation_ui()
