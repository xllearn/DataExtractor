from io import BytesIO
from pathlib import Path
import tempfile
import time
import unittest

from fastapi.testclient import TestClient

import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class ApiQualityTests(unittest.TestCase):
    def _client(self, output_dir: Path) -> TestClient:
        from api_server import create_app
        from excel_writer import write_extraction_workbook
        from field_mapping import load_field_mapping

        records = [
            {
                "_source_id": "Q1",
                "info_id": "INFO-Q1",
                "Title": "质量评估测试",
                "SourceURL": "https://example.test/quality?token=secret",
                "Content": "<p>报销比例 80%</p>",
            }
        ]

        def provider(keyword="", selected_ids=None, limit=50, offset=0):
            return {"items": records[offset : offset + limit], "total": len(records)}

        def runner(selected_ids, mode, no_ocr, no_llm, external_ocr_text="", prompt_version="v3"):
            output = output_dir / "quality_generated.xlsx"
            write_extraction_workbook(
                [
                    {
                        "info_id": "INFO-Q1",
                        "病种名称": "门诊慢特病",
                        "报销比例": "80%",
                        "起付标准": "100元",
                        "补助限额": "1000元",
                        "人员类型": "职工",
                        "保险类型": "医保",
                        "备注": r"C:\Users\admin\My Project\secret-db.txt token=secret",
                    }
                ],
                output,
                template_path=output_dir / "missing.xlsx",
                field_mapping=load_field_mapping(None),
                field_confidence=[
                    {
                        "row_index": 1,
                        "field": "报销比例",
                        "value": "80%",
                        "confidence": 0.42,
                        "source": "test",
                        "reason": "low confidence",
                    }
                ],
                conflict_evidence=[
                    {
                        "source_id": "Q1",
                        "info_id": "INFO-Q1",
                        "row_index": 1,
                        "field": "报销比例",
                        "rule_value": "80%",
                        "llm_value": "70%",
                        "chosen_value": "80%",
                        "reason": "conflict",
                    }
                ],
            )
            return output

        app = create_app(record_provider=provider, extract_runner=runner, output_dir=output_dir, log_dir=output_dir / "logs")
        return TestClient(app)

    def _manual_xlsx_bytes(self, overrides=None) -> bytes:
        from field_mapping import load_field_mapping
        from openpyxl import Workbook

        mapping = load_field_mapping(None)
        row = {
            "info_id": "INFO-Q1",
            "病种名称": "住院统筹",
            "报销比例": "70%",
            "起付标准": "9999元",
            "补助限额": "",
            "人员类型": "居民",
            "保险类型": "商保",
            "备注": "人工复核值 token=secret",
        }
        row.update(overrides or {})
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "结果数据"
        sheet.append(mapping.headers)
        sheet.append([row.get(header, "") for header in mapping.headers])
        buffer = BytesIO()
        workbook.save(buffer)
        workbook.close()
        return buffer.getvalue()

    def _create_success_job(self, client: TestClient) -> dict:
        response = client.post("/api/extract", json={"selected_ids": ["Q1"], "mode": "merge", "no_ocr": True})
        self.assertEqual(response.status_code, 200)
        job_id = response.json()["job_id"]
        payload = {}
        for _ in range(30):
            status = client.get(f"/api/jobs/{job_id}")
            self.assertEqual(status.status_code, 200)
            payload = status.json()
            if payload["status"] in {"success", "failed"}:
                break
            time.sleep(0.05)
        self.assertEqual(payload["status"], "success")
        return payload

    def test_quality_evaluate_creates_report_summary_and_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            client = self._client(output_dir)
            job = self._create_success_job(client)

            response = client.post(
                "/api/quality/evaluate",
                data={"job_id": job["job_id"]},
                files={
                    "file": (
                        r"..\manual secret.xlsx",
                        self._manual_xlsx_bytes(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
            )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertRegex(payload["report_id"], r"^quality_\d{8}_\d{6}_[0-9a-f]{8}$")
            self.assertLess(payload["overall_similarity"], 1)
            self.assertLess(payload["core_field_similarity"], 1)
            self.assertFalse(payload["passed"])
            self.assertGreaterEqual(len(payload["worst_fields"]), 1)
            self.assertGreaterEqual(len(payload["worst_rows"]), 1)
            self.assertEqual(payload["low_confidence_count"], 1)
            self.assertEqual(payload["conflict_count"], 1)
            self.assertTrue(payload["download_url"].endswith("/download"))
            self.assertNotIn(str(output_dir), str(payload))
            self.assertNotIn("secret", str(payload).lower())
            self.assertTrue((output_dir / "quality" / payload["report_id"] / "manual.xlsx").exists())
            self.assertFalse((output_dir / "quality" / payload["report_id"] / "manual secret.xlsx").exists())

            report = client.get(f"/api/quality/reports/{payload['report_id']}")
            self.assertEqual(report.status_code, 200)
            self.assertEqual(report.json(), payload)
            self.assertNotIn(str(output_dir), str(report.json()))
            self.assertNotIn("secret-db", str(report.json()))

            download = client.get(payload["download_url"])
            self.assertEqual(download.status_code, 200)
            self.assertIn("spreadsheetml", download.headers["content-type"])
            self.assertIn(payload["report_id"], download.headers.get("content-disposition", ""))

    def test_quality_errors_are_json_and_do_not_leak_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            client = self._client(output_dir)

            missing_report = client.get("/api/quality/reports/quality_20990101_000000_deadbeef")
            self.assertEqual(missing_report.status_code, 404)
            self.assertEqual(missing_report.headers["content-type"].split(";")[0], "application/json")
            self.assertEqual(missing_report.json()["error_type"], "QualityReportNotFound")

            traversal = client.get("/api/quality/reports/../secret/download")
            self.assertEqual(traversal.headers["content-type"].split(";")[0], "application/json")

            bad_extension = client.post(
                "/api/quality/evaluate",
                data={"job_id": "job_20990101_000000_deadbeef"},
                files={"file": ("manual.xls", b"not-xlsx", "application/vnd.ms-excel")},
            )
            self.assertEqual(bad_extension.status_code, 400)
            self.assertEqual(bad_extension.json()["error_type"], "ValidationError")

            from services.job_store import JobStore

            queued = JobStore(output_dir).create(
                job_id="job_20990101_000000_deadbeef",
                status="queued",
                message="queued",
                selected_ids=["Q1"],
            )
            not_ready = client.post(
                "/api/quality/evaluate",
                data={"job_id": queued["job_id"]},
                files={"file": ("manual.xlsx", self._manual_xlsx_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            )
            self.assertEqual(not_ready.status_code, 400)
            self.assertEqual(not_ready.json()["error_type"], "JobNotReady")
            self.assertNotIn(str(output_dir), str(not_ready.json()))
            self.assertNotIn("secret", str(not_ready.json()).lower())

    def test_quality_service_safe_text_preserves_urls_and_masks_paths(self):
        from services.quality_service import QualityService

        service = QualityService("C:/tmp/out")

        self.assertEqual(service._safe_text("https://example.test/quality?token=secret"), "https://example.test/quality?token=***")
        masked_path = service._safe_text(r"C:\Users\admin\My Project\secret-db.txt token=secret")
        self.assertEqual(masked_path, "[path]")
        self.assertNotIn("Project", masked_path)
        self.assertNotIn("secret-db", masked_path)
