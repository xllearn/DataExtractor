import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_APP_VERSION = "20260701_image_table"


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
        self.assertIn("externalOcrInput", index_source)
        self.assertIn("external_ocr_text", app_source)
        self.assertIn("payload.result_page", app_source)
        self.assertNotIn("payload.result_page ||", app_source)
        self.assertNotIn("encodeURIComponent(payload.job_id)", app_source)

    def test_frontend_guards_stale_scripts_and_pagination_fallback(self):
        app_source = (PROJECT_ROOT / "web" / "app.js").read_text(encoding="utf-8")
        index_source = (PROJECT_ROOT / "web" / "index.html").read_text(encoding="utf-8")
        result_source = (PROJECT_ROOT / "web" / "result.js").read_text(encoding="utf-8")
        result_html_source = (PROJECT_ROOT / "web" / "result.html").read_text(encoding="utf-8")

        self.assertIn(f"/web/app.js?v={WEB_APP_VERSION}", index_source)
        self.assertIn(f"/web/result.js?v={WEB_APP_VERSION}", result_html_source)
        self.assertIn(WEB_APP_VERSION, app_source)
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
        self.assertIn("任务不存在或已过期", source)
        self.assertIn("任务编号格式不正确", source)
        self.assertIn('jobId.startsWith("job_")', source)
        self.assertIn("error.status === 404", source)

    def test_frontend_uses_workbench_layout_components(self):
        index_source = (PROJECT_ROOT / "web" / "index.html").read_text(encoding="utf-8")
        style_source = (PROJECT_ROOT / "web" / "style.css").read_text(encoding="utf-8")

        self.assertIn('class="app-shell"', index_source)
        self.assertIn('class="status-chip', index_source)
        self.assertIn('class="command-panel"', index_source)
        self.assertIn('class="ocr-panel"', index_source)
        self.assertIn("<details", index_source)
        self.assertIn('class="selection-panel"', index_source)
        self.assertIn('class="table-card"', index_source)
        self.assertIn('class="pagination-bar"', index_source)
        self.assertIn(".status-chip", style_source)
        self.assertIn(".command-panel", style_source)
        self.assertIn(".table-card", style_source)

    def test_result_preview_keeps_headers_readable(self):
        result_html_source = (PROJECT_ROOT / "web" / "result.html").read_text(encoding="utf-8")
        style_source = (PROJECT_ROOT / "web" / "style.css").read_text(encoding="utf-8")

        self.assertIn('class="result-summary"', result_html_source)
        self.assertIn('id="previewMeta"', result_html_source)
        self.assertIn('class="preview-table"', result_html_source)
        self.assertIn(".preview-table", style_source)
        self.assertIn("white-space: nowrap", style_source)
        self.assertIn("position: sticky", style_source)
        self.assertIn("min-width:", style_source)


if __name__ == "__main__":
    unittest.main()
