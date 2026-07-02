import json
import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class ApiServerTests(unittest.TestCase):
    def _client(self, output_dir: Path):
        from api_server import create_app
        from excel_writer import write_extraction_workbook
        from field_mapping import load_field_mapping

        records = [
            {
                "_source_id": str(index),
                "info_id": f"INFO-{index}",
                "Title": f"西安市医保政策 {index}",
                "SourceURL": f"https://example.com/{index}",
                "AuditTime": "2026-05-20",
                "areaname": "陕西省-西安市",
                "insurancetypename": "城镇职工",
                "Content": "<p>保障病种范围：类风湿性关节炎，报销比例80%</p>",
            }
            for index in range(1, 26)
        ]

        def provider(keyword="", selected_ids=None, limit=50, offset=0):
            selected = set(selected_ids or [])
            rows = records
            if selected:
                rows = [record for record in rows if str(record["_source_id"]) in selected or record["SourceURL"] in selected]
            if keyword:
                rows = [record for record in rows if keyword in record["Title"]]
            return {"items": rows[offset : offset + limit], "total": len(rows)}

        def runner(selected_ids, mode, no_ocr, no_llm, external_ocr_text=""):
            output = output_dir / "商业补充保险抽取结果.xlsx"
            write_extraction_workbook(
                [{"info_id": "INFO-1", "地区名称": "陕西省-西安市", "病种名称": "类风湿性关节炎", "备注": external_ocr_text or "--"}],
                output,
                template_path=output_dir / "missing.xlsx",
                field_mapping=load_field_mapping(None),
            )
            return output

        app = create_app(record_provider=provider, extract_runner=runner, output_dir=output_dir, log_dir=output_dir / "logs")
        return TestClient(app)

    def _wait_job(self, client: TestClient, job_id: str) -> dict:
        payload = {}
        for _ in range(30):
            response = client.get(f"/api/jobs/{job_id}")
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            if payload["status"] in {"success", "failed"}:
                return payload
            time.sleep(0.05)
        self.fail(f"job did not finish: {payload}")

    def test_health_config_articles_extract_and_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(Path(tmp))

            self.assertEqual(client.get("/api/health").json(), {"ok": True})
            status = client.get("/api/config/status").json()
            self.assertIn("database_configured", status)
            self.assertNotIn("DATABASE_URL", str(status))
            self.assertNotIn("sk-", str(status))

            articles = client.get("/api/articles?keyword=医保&limit=10").json()
            self.assertEqual(articles["total"], 25)
            self.assertEqual(articles["limit"], 10)
            self.assertEqual(articles["offset"], 0)
            self.assertEqual(articles["page"], 1)
            self.assertEqual(articles["page_size"], 10)
            self.assertEqual(articles["total_pages"], 3)
            self.assertTrue(articles["has_next"])
            self.assertFalse(articles["has_prev"])
            self.assertEqual(articles["items"][0]["id"], "1")
            self.assertNotIn("Content", articles["items"][0])

            extract = client.post("/api/extract", json={"selected_ids": ["1"], "mode": "merge", "no_ocr": True}).json()
            self.assertEqual(extract["status"], "queued")
            self.assertTrue(extract["job_id"])
            self.assertEqual(extract["status_url"], f"/api/jobs/{extract['job_id']}")
            self.assertEqual(extract["result_page"], f"/web/result.html?job_id={extract['job_id']}")
            self.assertNotIn(str(Path(tmp)), str(extract))

            job = self._wait_job(client, extract["job_id"])
            self.assertEqual(job["status"], "success")
            self.assertEqual(job["selected_ids"], ["1"])
            self.assertTrue(job["download_url"].startswith("/api/download/"))
            self.assertIn("%", job["download_url"])
            self.assertTrue(job["preview_url"].endswith("/preview"))
            metadata_path = Path(tmp) / "jobs" / f"{extract['job_id']}.json"
            raw_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(raw_metadata["selected_ids"], ["1"])

            preview = client.get(job["preview_url"])
            self.assertEqual(preview.status_code, 200)
            preview_payload = preview.json()
            self.assertEqual(preview_payload["sheet"], "结果数据")
            self.assertEqual(len(preview_payload["headers"]), 26)
            self.assertLessEqual(preview_payload["row_count"], 100)

            download = client.get(job["download_url"])
            self.assertEqual(download.status_code, 200)
            self.assertIn("spreadsheetml", download.headers["content-type"])

    def test_version_endpoint_reports_current_backend_features_without_secrets(self):
        from api_server import WEB_APP_VERSION

        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(Path(tmp))

            response = client.get("/api/version")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["web_app_version"], WEB_APP_VERSION)
        self.assertRegex(payload["git_commit"], r"^[0-9a-f]{7,40}$|^unknown$")
        self.assertTrue(payload["project_root"])
        self.assertTrue(payload["cwd"])
        self.assertEqual(
            payload["api_features"],
            {
                "job_mode": True,
                "job_metadata_persistence": True,
                "pagination_count": True,
                "ocr_status": True,
            },
        )
        self.assertNotIn("sk-", str(payload))
        self.assertNotIn("DATABASE_URL", str(payload))
        self.assertNotIn("password", str(payload).lower())

    def test_articles_pagination_second_page_and_selected_total(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(Path(tmp))

            first = client.get("/api/articles?keyword=医保&limit=10&offset=0").json()
            second = client.get("/api/articles?keyword=医保&limit=10&offset=10").json()
            selected = client.get("/api/articles?selected_ids=1,3,5&limit=2&offset=0").json()

            self.assertEqual(first["total"], 25)
            self.assertEqual(first["total_pages"], 3)
            self.assertEqual(first["items"][0]["id"], "1")
            self.assertEqual(second["page"], 2)
            self.assertTrue(second["has_prev"])
            self.assertEqual(second["items"][0]["id"], "11")
            self.assertEqual(selected["total"], 3)
            self.assertEqual(len(selected["items"]), 2)

    def test_articles_never_returns_items_with_zero_total(self):
        from api_server import create_app

        def provider(**_kwargs):
            return {
                "items": [
                    {
                        "_source_id": "row-11",
                        "Title": "分页兜底测试",
                        "SourceURL": "https://example.com/row-11",
                    }
                ],
                "total": 0,
            }

        with tempfile.TemporaryDirectory() as tmp:
            client = TestClient(create_app(record_provider=provider, output_dir=Path(tmp) / "out", log_dir=Path(tmp) / "logs"))

            payload = client.get("/api/articles?limit=10&offset=10").json()

        self.assertEqual(payload["page"], 2)
        self.assertEqual(payload["total"], 11)
        self.assertEqual(payload["total_pages"], 2)
        self.assertTrue(payload["has_prev"])
        self.assertFalse(payload["has_next"])

    def test_articles_total_is_full_count_not_current_page_length(self):
        from api_server import create_app

        records = [
            {
                "_source_id": str(index),
                "Title": f"分页测试 {index}",
                "SourceURL": f"https://example.com/page/{index}",
                "AuditTime": "2026-05-20",
            }
            for index in range(1, 121)
        ]

        def provider(keyword="", selected_ids=None, limit=50, offset=0):
            rows = records
            if keyword:
                rows = [record for record in rows if keyword in record["Title"]]
            if selected_ids:
                selected = set(selected_ids)
                rows = [record for record in rows if record["_source_id"] in selected]
            return {"items": rows[offset : offset + limit], "total": len(rows)}

        with tempfile.TemporaryDirectory() as tmp:
            client = TestClient(create_app(record_provider=provider, output_dir=Path(tmp) / "out", log_dir=Path(tmp) / "logs"))

            page = client.get("/api/articles?limit=50&offset=50").json()

        self.assertEqual(page["total"], 120)
        self.assertEqual(len(page["items"]), 50)
        self.assertEqual(page["page"], 2)
        self.assertEqual(page["total_pages"], 3)
        self.assertTrue(page["has_next"])
        self.assertTrue(page["has_prev"])

    def test_job_preview_rejects_unknown_and_unfinished_jobs(self):
        from api_server import create_app

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)

            def slow_runner(*_args, **_kwargs):
                time.sleep(0.3)
                return output_dir / "missing.xlsx"

            client = TestClient(create_app(record_provider=lambda **_: {"items": [], "total": 0}, extract_runner=slow_runner, output_dir=output_dir))

            missing = client.get("/api/jobs/nope")
            self.assertEqual(missing.status_code, 404)
            self.assertEqual(missing.headers["content-type"].split(";")[0], "application/json")
            self.assertIn("任务不存在或已过期", missing.text)

            file_name_job = client.get("/api/jobs/商业补充保险抽取结果_20260701_111750")
            self.assertEqual(file_name_job.status_code, 404)
            self.assertEqual(file_name_job.headers["content-type"].split(";")[0], "application/json")
            self.assertIn("任务不存在或已过期", file_name_job.text)

            created = client.post("/api/extract", json={"selected_ids": ["1"]}).json()
            preview = client.get(f"/api/jobs/{created['job_id']}/preview")
            self.assertEqual(preview.status_code, 400)
            self.assertEqual(preview.headers["content-type"].split(";")[0], "application/json")

    def test_successful_job_metadata_survives_app_recreation(self):
        from api_server import create_app

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            client = self._client(output_dir)

            created = client.post("/api/extract", json={"selected_ids": ["1"], "mode": "merge", "no_ocr": True}).json()
            job_id = created["job_id"]
            self.assertTrue(job_id.startswith("job_"))
            self.assertRegex(job_id, r"^job_\d{8}_\d{6}_[0-9a-f]{8}$")
            self.assertNotIn("商业补充保险抽取结果", job_id)

            job = self._wait_job(client, job_id)
            self.assertEqual(job["status"], "success")

            metadata_path = output_dir / "jobs" / f"{job_id}.json"
            self.assertTrue(metadata_path.exists())
            self.assertNotIn(str(output_dir), metadata_path.read_text(encoding="utf-8"))

            recreated = TestClient(create_app(record_provider=lambda **_: {"items": [], "total": 0}, output_dir=output_dir, log_dir=output_dir / "logs"))
            restored = recreated.get(f"/api/jobs/{job_id}")
            self.assertEqual(restored.status_code, 200)
            restored_payload = restored.json()
            self.assertEqual(restored_payload["status"], "success")
            self.assertTrue(restored_payload["download_url"].startswith("/api/download/"))
            self.assertNotIn(str(output_dir), str(restored_payload))

            preview = recreated.get(f"/api/jobs/{job_id}/preview")
            self.assertEqual(preview.status_code, 200)
            self.assertEqual(len(preview.json()["headers"]), 26)

    def test_extract_defaults_to_service_path_and_lists_jobs(self):
        from api_server import create_app
        from excel_writer import write_extraction_workbook
        from field_mapping import load_field_mapping
        from services.extraction_service import ExtractionResult

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            calls = []

            class FakeService:
                def run(self, request):
                    calls.append(request)
                    output = output_dir / "service_result.xlsx"
                    logs = output_dir / "logs" / "service"
                    logs.mkdir(parents=True, exist_ok=True)
                    summary = logs / "summary.json"
                    write_extraction_workbook(
                        [{"info_id": "INFO-SVC"}],
                        output,
                        template_path=output_dir / "missing.xlsx",
                        field_mapping=load_field_mapping(None),
                    )
                    summary.write_text(json.dumps({"run_id": "run_service_1"}) + "\n", encoding="utf-8")
                    return ExtractionResult(
                        run_id="run_service_1",
                        input_mode="configured-db",
                        selected_ids=list(request.selected_ids),
                        keyword="DATABASE_URL=mysql+pymysql://user:secret@127.0.0.1/db password=abc sk-test-token",
                        total_records=1,
                        output_rows=1,
                        failed_record_count=0,
                        output_excel_path=output,
                        summary_path=summary,
                        log_dir=logs,
                    )

            client = TestClient(
                create_app(
                    extraction_service=FakeService(),
                    output_dir=output_dir,
                    log_dir=output_dir / "logs",
                )
            )

            created = client.post("/api/extract", json={"selected_ids": ["svc-1"], "mode": "merge", "no_ocr": True}).json()
            job = self._wait_job(client, created["job_id"])
            listed = client.get("/api/jobs").json()
            preview = client.get(job["preview_url"])
            metadata_path = output_dir / "jobs" / f"{created['job_id']}.json"
            raw_metadata = metadata_path.read_text(encoding="utf-8")
            raw_payload = json.loads(raw_metadata)

            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0].selected_ids, ["svc-1"])
            self.assertEqual(calls[0].mode, "merge")
            self.assertEqual(job["status"], "success")
            self.assertEqual(job["run_id"], "run_service_1")
            self.assertEqual(job["input_mode"], "configured-db")
            self.assertTrue(job["started_at"])
            self.assertEqual(job["selected_ids"], ["svc-1"])
            self.assertTrue(raw_payload["started_at"])
            self.assertEqual(raw_payload["selected_ids"], ["svc-1"])
            self.assertEqual(listed["total"], 1)
            self.assertEqual(listed["items"][0]["job_id"], created["job_id"])
            self.assertEqual(listed["items"][0]["run_id"], "run_service_1")
            self.assertNotIn(str(output_dir), str(job))
            self.assertNotIn(str(output_dir), str(listed))
            self.assertNotIn(str(output_dir), raw_metadata)
            self.assertNotIn("DATABASE_URL", raw_metadata)
            self.assertNotIn("mysql+pymysql://user:secret", raw_metadata)
            self.assertNotIn("secret", raw_metadata)
            self.assertNotIn("abc", raw_metadata)
            self.assertNotIn("sk-test-token", raw_metadata)
            self.assertEqual(preview.status_code, 200)
            self.assertEqual(len(preview.json()["headers"]), 26)

    def test_extract_validates_selection_and_download_rejects_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(Path(tmp))

            empty = client.post("/api/extract", json={"selected_ids": []})
            too_many = client.post("/api/extract", json={"selected_ids": [str(i) for i in range(51)]})
            traversal = client.get("/api/download/..%2F.env")

            self.assertEqual(empty.status_code, 400)
            self.assertIn("selected_ids", empty.text)
            self.assertEqual(too_many.status_code, 400)
            self.assertEqual(traversal.status_code, 400)

    def test_config_status_reports_safe_to_query_without_secrets(self):
        from api_server import create_app

        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "db_config.yml"
            config_path.write_text(
                """
database:
  url: "mysql+pymysql://user:secret@127.0.0.1:3306/db?charset=utf8mb4"
source:
  table: ""
""",
                encoding="utf-8",
            )
            client = TestClient(create_app(config_path=str(config_path), output_dir=Path(tmp) / "out", log_dir=Path(tmp) / "logs"))

            response = client.get("/api/config/status")
            payload = response.json()

            self.assertEqual(response.status_code, 200)
            self.assertFalse(payload["database_configured"])
            self.assertFalse(payload["safe_to_query"])
            self.assertIn("database_status_reason", payload)
            self.assertIn("config_path", payload)
            self.assertNotIn("secret", str(payload))
            self.assertNotIn("mysql+pymysql://user:secret", str(payload))

    def test_articles_database_not_configured_returns_json_error(self):
        from api_server import create_app

        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "db_config.yml"
            config_path.write_text(
                """
database:
  url: ""
source:
  table: ""
""",
                encoding="utf-8",
            )
            client = TestClient(
                create_app(config_path=str(config_path), output_dir=Path(tmp) / "out", log_dir=Path(tmp) / "logs"),
                raise_server_exceptions=False,
            )

            response = client.get("/api/articles?keyword=test")
            payload = response.json()

            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.headers["content-type"].split(";")[0], "application/json")
            self.assertEqual(payload["error_type"], "DatabaseNotConfigured")
            self.assertIn("detail", payload)

    def test_articles_provider_exception_returns_masked_json(self):
        from api_server import create_app

        def provider(**_kwargs):
            raise RuntimeError("DATABASE_URL=mysql+pymysql://user:secret@127.0.0.1/db password=abc sk-test-token")

        with tempfile.TemporaryDirectory() as tmp:
            client = TestClient(
                create_app(record_provider=provider, output_dir=Path(tmp) / "out", log_dir=Path(tmp) / "logs"),
                raise_server_exceptions=False,
            )

            response = client.get("/api/articles?keyword=test")
            payload = response.json()

            self.assertEqual(response.status_code, 500)
            self.assertEqual(response.headers["content-type"].split(";")[0], "application/json")
            self.assertEqual(payload["error_type"], "RuntimeError")
            self.assertNotIn("secret", str(payload))
            self.assertNotIn("abc", str(payload))
            self.assertNotIn("sk-test-token", str(payload))

    def test_extract_runner_exception_returns_masked_json(self):
        from api_server import create_app

        def runner(*_args, **_kwargs):
            raise RuntimeError("extract failed password=abc sk-test-token")

        with tempfile.TemporaryDirectory() as tmp:
            client = TestClient(
                create_app(extract_runner=runner, output_dir=Path(tmp) / "out", log_dir=Path(tmp) / "logs"),
                raise_server_exceptions=False,
            )

            response = client.post("/api/extract", json={"selected_ids": ["1"], "mode": "merge"})
            created = response.json()
            payload = self._wait_job(client, created["job_id"])

            self.assertEqual(response.status_code, 200)
            self.assertEqual(payload["status"], "failed")
            self.assertNotIn("abc", str(payload))
            self.assertNotIn("sk-test-token", str(payload))


if __name__ == "__main__":
    unittest.main()
