import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_APP_VERSION = "20260702_workbench"


def read_web_file(name: str) -> str:
    return (PROJECT_ROOT / "web" / name).read_text(encoding="utf-8")


class WebAppStaticTests(unittest.TestCase):
    def test_fetch_json_handles_non_json_responses(self):
        source = read_web_file("app.js")

        self.assertIn('headers.get("content-type")', source)
        self.assertIn("response.text()", source)
        self.assertIn("application/json", source)
        self.assertIn("Backend returned non-JSON", source)

    def test_frontend_uses_safe_dom_api(self):
        app_source = read_web_file("app.js")
        result_source = read_web_file("result.js")

        self.assertNotIn(".innerHTML", app_source)
        self.assertNotIn(".innerHTML", result_source)
        self.assertIn("document.createElement", app_source)
        self.assertIn("document.createElement", result_source)
        self.assertIn("textContent", app_source)
        self.assertIn("textContent", result_source)
        self.assertIn("isSafeHttpUrl", app_source)

    def test_database_not_ready_disables_query_actions(self):
        source = read_web_file("app.js")

        self.assertIn("safe_to_query", source)
        self.assertIn("setQueryEnabled", source)
        self.assertIn("searchBtn.disabled", source)
        self.assertIn("extractBtn.disabled", source)

    def test_frontend_contains_pagination_and_result_page_flow(self):
        app_source = read_web_file("app.js")
        index_source = read_web_file("index.html")

        self.assertTrue((PROJECT_ROOT / "web" / "result.html").exists())
        self.assertTrue((PROJECT_ROOT / "web" / "result.js").exists())
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

    def test_frontend_guards_stale_scripts_and_pagination_fallback(self):
        app_source = read_web_file("app.js")
        index_source = read_web_file("index.html")
        result_source = read_web_file("result.js")
        result_html_source = read_web_file("result.html")

        self.assertIn(f"/web/app.js?v={WEB_APP_VERSION}", index_source)
        self.assertIn(f"/web/result.js?v={WEB_APP_VERSION}", result_html_source)
        self.assertIn(WEB_APP_VERSION, app_source)
        self.assertIn(WEB_APP_VERSION, result_source)
        self.assertNotIn("downloadLink", app_source)
        self.assertIn("function normalizePagination", app_source)
        self.assertIn("minimumTotal", app_source)
        self.assertIn("function clearSelection", app_source)
        self.assertIn("setHidden(elements.downloadBtn", result_source)

    def test_frontend_ocr_available_defaults_to_using_ocr(self):
        source = read_web_file("app.js")

        self.assertIn("elements.noOcrInput.checked = false", source)
        self.assertIn("elements.noOcrInput.disabled = false", source)
        self.assertIn("OCR", source)

    def test_index_contains_task3_workbench_sections_and_controls(self):
        index_source = read_web_file("index.html")

        for marker in [
            'id="modeMergeInput"',
            'id="modeSingleInput"',
            '<select id="promptVersionInput">',
            '<option value="v3" selected>v3</option>',
            '<option value="v2">v2</option>',
            'id="currentJobPanel"',
            'id="jobProgressBar"',
            'id="currentTitleText"',
            'id="jobLogTail"',
            'id="jobSummaryPanel"',
            'id="jobHistoryBody"',
            'id="jobDownloadLink"',
            'id="jobPreviewLink"',
            'id="jobCancelBtn"',
        ]:
            self.assertIn(marker, index_source)

    def test_app_js_polls_jobs_and_uses_task_action_endpoints(self):
        source = read_web_file("app.js")

        for marker in [
            'fetchJson("/api/jobs?limit=20")',
            'fetchJson(`/api/jobs/${encodeURIComponent(jobId)}`',
            'fetchJson(`/api/jobs/${encodeURIComponent(jobId)}/logs?tail=80`',
            'fetchJson(`/api/jobs/${encodeURIComponent(jobId)}/summary`',
            'fetch(`/api/jobs/${encodeURIComponent(jobId)}/cancel`',
            'href = `/api/jobs/${encodeURIComponent(jobId)}/download`',
            "function startJobPolling",
            "function stopJobPolling",
            "function loadJobHistory",
            "function renderJobHistory",
            "function renderJobSummary",
            "function cancelCurrentJob",
            "state.pollTimer",
            "state.extracting",
            "elements.extractBtn.disabled",
            "window.setTimeout",
        ]:
            self.assertIn(marker, source)

        self.assertIn("mode: getSelectedMode()", source)
        self.assertIn("prompt_version: elements.promptVersionInput.value.trim()", source)
        self.assertNotIn("window.location.href = payload.result_page", source)

    def test_index_and_app_js_expose_uploaded_xlsx_job_flow(self):
        index_source = read_web_file("index.html")
        app_source = read_web_file("app.js")
        style_source = read_web_file("style.css")

        for marker in [
            'id="uploadXlsxInput"',
            'id="uploadExtractBtn"',
            'accept=".xlsx"',
            'class="upload-panel"',
        ]:
            self.assertIn(marker, index_source)

        for marker in [
            "uploadXlsxInput: document.querySelector",
            "uploadExtractBtn: document.querySelector",
            "function hasUploadFile",
            "async function uploadExtractExcel",
            "new FormData()",
            'formData.append("file", elements.uploadXlsxInput.files[0])',
            'fetchJson("/api/uploads/excel"',
            'fetchJson("/api/extract/uploaded"',
            "upload_id: upload.upload_id",
            "startJobPolling(payload.job_id)",
            "elements.uploadExtractBtn.disabled = state.extracting || !hasUploadFile()",
            'elements.uploadXlsxInput.addEventListener("change"',
        ]:
            self.assertIn(marker, app_source)

        for marker in [
            ".upload-panel",
            ".upload-actions",
            ".file-input-row",
        ]:
            self.assertIn(marker, style_source)

    def test_result_page_contains_task3_job_panels(self):
        result_html_source = read_web_file("result.html")

        for marker in [
            'id="jobProgressBar"',
            'id="currentTitleText"',
            'id="jobLogTail"',
            'id="jobSummaryPanel"',
            'id="cancelBtn"',
            'id="previewStatusText"',
            'id="downloadBtn"',
        ]:
            self.assertIn(marker, result_html_source)

    def test_result_page_calls_task3_job_apis(self):
        source = read_web_file("result.js")

        for marker in [
            "/api/jobs/",
            "/preview",
            "/download",
            "/logs",
            "/summary",
            "/cancel",
            "progress_current",
            "progress_total",
            "current_title",
            'jobId.startsWith("job_")',
            "error.status === 404",
            "任务不存在或已过期",
            "任务编号格式不正确",
        ]:
            self.assertIn(marker, source)

    def test_frontend_uses_workbench_layout_components(self):
        index_source = read_web_file("index.html")
        style_source = read_web_file("style.css")

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

    def test_css_contains_workbench_history_logs_progress_and_mobile_layout(self):
        style_source = read_web_file("style.css")

        for marker in [
            ".workbench-grid",
            ".current-job-panel",
            ".job-progress",
            ".job-log-tail",
            ".summary-panel",
            ".job-history",
            ".history-table",
            "@media (max-width: 900px)",
        ]:
            self.assertIn(marker, style_source)

    def test_result_preview_keeps_headers_readable(self):
        result_html_source = read_web_file("result.html")
        style_source = read_web_file("style.css")

        self.assertIn('class="result-summary"', result_html_source)
        self.assertIn('id="previewMeta"', result_html_source)
        self.assertIn('class="preview-table"', result_html_source)
        self.assertIn(".preview-table", style_source)
        self.assertIn("white-space: nowrap", style_source)
        self.assertIn("position: sticky", style_source)
        self.assertIn("min-width:", style_source)


if __name__ == "__main__":
    unittest.main()
