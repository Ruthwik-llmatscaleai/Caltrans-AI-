"""
E2E Playwright Tests — Project Delivery Evaluator Full Flow

Tests the complete PDE user journey:
1. Upload nomination fact sheet
2. Select role (District / HQ)
3. Run evaluation
4. Verify recommendation card renders
5. Verify questionnaire table renders
6. Download Excel report
7. Re-run same document → verify Result Store hit (instant response)

Prerequisites:
    - App running at APP_URL (default: http://localhost:8501)
    - Sample PDF at tests/e2e/fixtures/sample_nomination.pdf
    - pip install playwright pytest-playwright
    - playwright install chromium

Run:
    pytest tests/e2e/test_pde_flow.py --headed --base-url http://localhost:8501
"""

import re
import time
import pytest
from playwright.sync_api import Page, expect


# ==============================================================================
# HELPERS
# ==============================================================================

def select_pde_usecase(page: Page):
    """Navigate to the Project Delivery Evaluator V2 use case."""
    # Select "Caltrans" application
    page.get_by_text("Select Application").first.click()
    page.locator("[data-testid='stSelectbox']").first.select_option("Caltrans")

    # Select PDE V2 use case
    page.locator("text=Select the Usecase").click()
    page.get_by_role("option", name="Project Delivery Evaluator V2").click()


def upload_document(page: Page, file_path: str):
    """Upload a nomination fact sheet."""
    file_input = page.locator("[data-testid='stFileUploader'] input[type='file']").first
    file_input.set_input_files(file_path)
    # Wait for upload to complete
    page.wait_for_selector("text=Loaded", timeout=15000)


def select_role(page: Page, role: str = "Headquarters (HQ)"):
    """Select the view perspective."""
    page.get_by_role("radio", name=role).click()


def run_evaluation(page: Page):
    """Click the Evaluate button and wait for results."""
    page.get_by_role("button", name="Evaluate Project").click()
    # Wait for evaluation to complete (may take up to 3 minutes)
    page.wait_for_selector("[data-testid='stMarkdown']", timeout=180000)


# ==============================================================================
# TEST: HQ FULL FLOW
# ==============================================================================

class TestPDEHeadquartersFlow:
    """End-to-end tests for the HQ view of Project Delivery Evaluator."""

    @pytest.fixture(autouse=True)
    def setup(self, page: Page, app_url: str):
        """Load the app before each test."""
        page.goto(app_url, wait_until="networkidle")
        page.wait_for_timeout(2000)

    def test_app_loads(self, page: Page):
        """App loads with the Caltrans header."""
        expect(page.locator("text=CUCP: Transforming Documents")).to_be_visible()

    def test_upload_and_evaluate_hq(self, page: Page, test_pdf_path: str):
        """Upload a doc, select HQ, evaluate, and verify results render."""
        select_pde_usecase(page)
        upload_document(page, test_pdf_path)
        select_role(page, "Headquarters (HQ)")
        run_evaluation(page)

        # Verify recommendation card appears with method name
        rec_card = page.locator("text=Recommended Delivery Method")
        expect(rec_card).to_be_visible(timeout=10000)

        # Verify score is shown (HQ only)
        expect(page.locator("text=pts")).to_be_visible()

        # Verify questionnaire table renders
        expect(page.locator("text=WORKSHEET 1")).to_be_visible()

    def test_hq_shows_points_in_table(self, page: Page, test_pdf_path: str):
        """HQ view should show points in brackets in the questionnaire table."""
        select_pde_usecase(page)
        upload_document(page, test_pdf_path)
        select_role(page, "Headquarters (HQ)")
        run_evaluation(page)

        # Points format: "B (5)" or "A (10)" etc.
        table_content = page.locator(".parity-table").inner_text()
        assert re.search(r"[ABC]\s*\(\d+\)", table_content), "HQ table should show points in brackets"

    def test_hq_multi_method_table(self, page: Page, test_pdf_path: str):
        """HQ view should show the multi-method comparison table."""
        select_pde_usecase(page)
        upload_document(page, test_pdf_path)
        select_role(page, "Headquarters (HQ)")
        run_evaluation(page)

        expect(page.locator("text=All Delivery Methods")).to_be_visible()

    def test_hq_role_locks_after_eval(self, page: Page, test_pdf_path: str):
        """After evaluation, role radio should be disabled."""
        select_pde_usecase(page)
        upload_document(page, test_pdf_path)
        select_role(page, "Headquarters (HQ)")
        run_evaluation(page)

        radio = page.get_by_role("radio", name="District")
        expect(radio).to_be_disabled()

    def test_excel_download_hq(self, page: Page, test_pdf_path: str):
        """HQ wizard Step 3 should offer Excel download."""
        select_pde_usecase(page)
        upload_document(page, test_pdf_path)
        select_role(page, "Headquarters (HQ)")
        run_evaluation(page)

        # Navigate to Step 2 (Validation)
        page.get_by_role("button", name="Next → Validation").click()
        page.wait_for_timeout(1000)

        # Skip audit → Step 3
        page.get_by_role("button", name="Finalize & Export →").click()
        page.wait_for_timeout(2000)

        # Verify download button exists
        expect(page.locator("text=Download Report")).to_be_visible()


# ==============================================================================
# TEST: DISTRICT FULL FLOW
# ==============================================================================

class TestPDEDistrictFlow:
    """End-to-end tests for the District view of Project Delivery Evaluator."""

    @pytest.fixture(autouse=True)
    def setup(self, page: Page, app_url: str):
        """Load the app before each test."""
        page.goto(app_url, wait_until="networkidle")
        page.wait_for_timeout(2000)

    def test_district_no_points(self, page: Page, test_pdf_path: str):
        """District view should NOT show points in the questionnaire table."""
        select_pde_usecase(page)
        upload_document(page, test_pdf_path)
        select_role(page, "District")
        run_evaluation(page)

        # Table should show only letters, no "(X)" pattern
        table_content = page.locator(".parity-table").inner_text()
        assert not re.search(r"[ABC]\s*\(\d+\)", table_content), "District table should NOT show points"

    def test_district_no_multi_method_table(self, page: Page, test_pdf_path: str):
        """District view should NOT show the multi-method comparison table."""
        select_pde_usecase(page)
        upload_document(page, test_pdf_path)
        select_role(page, "District")
        run_evaluation(page)

        expect(page.locator("text=All Delivery Methods")).not_to_be_visible()

    def test_district_recommendation_no_score(self, page: Page, test_pdf_path: str):
        """District recommendation card should show method but no points."""
        select_pde_usecase(page)
        upload_document(page, test_pdf_path)
        select_role(page, "District")
        run_evaluation(page)

        expect(page.locator("text=Recommended Delivery Method")).to_be_visible()
        # Should NOT have "pts" in the recommendation card area
        rec_area = page.locator("div:has-text('Recommended Delivery Method')").first
        rec_text = rec_area.inner_text()
        assert "pts" not in rec_text, "District recommendation should not show points"

    def test_district_excel_download(self, page: Page, test_pdf_path: str):
        """District view should offer direct Excel download."""
        select_pde_usecase(page)
        upload_document(page, test_pdf_path)
        select_role(page, "District")
        run_evaluation(page)

        expect(page.locator("text=Download Report")).to_be_visible()


# ==============================================================================
# TEST: RESULT STORE (Same doc re-run = instant)
# ==============================================================================

class TestResultStore:
    """Test that the Result Store delivers instant responses on re-evaluation."""

    @pytest.fixture(autouse=True)
    def setup(self, page: Page, app_url: str):
        """Load the app before each test."""
        page.goto(app_url, wait_until="networkidle")
        page.wait_for_timeout(2000)

    def test_second_run_is_faster(self, page: Page, test_pdf_path: str):
        """Second evaluation of the same document should be significantly faster."""
        select_pde_usecase(page)
        upload_document(page, test_pdf_path)
        select_role(page, "Headquarters (HQ)")

        # First run — may take 30-180 seconds
        start1 = time.time()
        run_evaluation(page)
        duration1 = time.time() - start1

        # Reset
        page.get_by_role("button", name="Reset (New Project)").click()
        page.wait_for_timeout(2000)

        # Re-upload same document
        select_pde_usecase(page)
        upload_document(page, test_pdf_path)
        select_role(page, "Headquarters (HQ)")

        # Second run — should hit Result Store
        start2 = time.time()
        run_evaluation(page)
        duration2 = time.time() - start2

        # Second run should be at least 5x faster (store hit vs LLM call)
        assert duration2 < duration1 / 3, (
            f"Second run ({duration2:.1f}s) should be much faster than first ({duration1:.1f}s) due to Result Store"
        )
