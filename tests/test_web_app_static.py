import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class WebAppStaticTests(unittest.TestCase):
    def test_fetch_json_handles_non_json_responses(self):
        source = (PROJECT_ROOT / "web" / "app.js").read_text(encoding="utf-8")

        self.assertIn('headers.get("content-type")', source)
        self.assertIn("response.text()", source)
        self.assertIn("application/json", source)
        self.assertIn("Backend returned non-JSON", source)

    def test_article_rendering_uses_safe_dom_api(self):
        source = (PROJECT_ROOT / "web" / "app.js").read_text(encoding="utf-8")

        self.assertNotIn(".innerHTML", source)
        self.assertIn("document.createElement", source)
        self.assertIn("textContent", source)
        self.assertIn("isSafeHttpUrl", source)

    def test_database_not_ready_disables_query_actions(self):
        source = (PROJECT_ROOT / "web" / "app.js").read_text(encoding="utf-8")

        self.assertIn("safe_to_query", source)
        self.assertIn("setQueryEnabled", source)
        self.assertIn("searchBtn.disabled", source)
        self.assertIn("extractBtn.disabled", source)

    def test_frontend_contains_pagination_and_result_page_flow(self):
        app_source = (PROJECT_ROOT / "web" / "app.js").read_text(encoding="utf-8")
        index_source = (PROJECT_ROOT / "web" / "index.html").read_text(encoding="utf-8")
        result_html = PROJECT_ROOT / "web" / "result.html"
        result_js = PROJECT_ROOT / "web" / "result.js"

        self.assertTrue(result_html.exists())
        self.assertTrue(result_js.exists())
        self.assertIn("currentPage", app_source)
        self.assertIn("pageSize", app_source)
        self.assertIn("totalItems", app_source)
        self.assertIn("prevPageBtn", index_source)
        self.assertIn("nextPageBtn", index_source)
        self.assertIn("clearSelectionBtn", index_source)
        self.assertIn("result.html?job_id=", app_source)

    def test_frontend_guards_stale_scripts_and_pagination_fallback(self):
        app_source = (PROJECT_ROOT / "web" / "app.js").read_text(encoding="utf-8")
        index_source = (PROJECT_ROOT / "web" / "index.html").read_text(encoding="utf-8")
        result_source = (PROJECT_ROOT / "web" / "result.js").read_text(encoding="utf-8")
        result_html_source = (PROJECT_ROOT / "web" / "result.html").read_text(encoding="utf-8")

        self.assertIn('/web/app.js?v=', index_source)
        self.assertIn('/web/result.js?v=', result_html_source)
        self.assertNotIn("downloadLink", app_source)
        self.assertIn("function normalizePagination", app_source)
        self.assertIn("minimumTotal", app_source)
        self.assertIn("function clearSelection", app_source)
        self.assertIn("setHidden(elements.downloadBtn", result_source)

    def test_frontend_ocr_available_defaults_to_using_ocr(self):
        source = (PROJECT_ROOT / "web" / "app.js").read_text(encoding="utf-8")

        self.assertIn("elements.noOcrInput.checked = false", source)
        self.assertIn("elements.noOcrInput.disabled = false", source)
        self.assertIn("OCR 可用", source)

    def test_result_page_calls_job_and_preview_apis(self):
        source = (PROJECT_ROOT / "web" / "result.js").read_text(encoding="utf-8")

        self.assertIn("/api/jobs/", source)
        self.assertIn("/preview", source)
        self.assertIn("download_url", source)
        self.assertIn("textContent", source)


if __name__ == "__main__":
    unittest.main()
