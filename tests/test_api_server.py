import tempfile
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
                "_source_id": "1",
                "info_id": "INFO-1",
                "Title": "西安市医保政策",
                "SourceURL": "https://example.com/1",
                "AuditTime": "2026-05-20",
                "areaname": "陕西省-西安市",
                "insurancetypename": "城镇职工",
                "Content": "<p>保障病种范围：类风湿性关节炎，报销比例80%</p>",
            }
        ]

        def provider(keyword="", selected_ids=None, limit=50, offset=0):
            selected = set(selected_ids or [])
            rows = records
            if selected:
                rows = [record for record in rows if str(record["_source_id"]) in selected or record["SourceURL"] in selected]
            if keyword:
                rows = [record for record in rows if keyword in record["Title"]]
            return rows[offset : offset + limit]

        def runner(selected_ids, mode, no_ocr, no_llm):
            output = output_dir / "商业补充保险抽取结果.xlsx"
            write_extraction_workbook(
                [{"info_id": "INFO-1", "地区名称": "陕西省-西安市", "病种名称": "类风湿性关节炎"}],
                output,
                template_path=output_dir / "missing.xlsx",
                field_mapping=load_field_mapping(None),
            )
            return output

        app = create_app(record_provider=provider, extract_runner=runner, output_dir=output_dir, log_dir=output_dir / "logs")
        return TestClient(app)

    def test_health_config_articles_extract_and_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(Path(tmp))

            self.assertEqual(client.get("/api/health").json(), {"ok": True})
            status = client.get("/api/config/status").json()
            self.assertIn("database_configured", status)
            self.assertNotIn("DATABASE_URL", str(status))
            self.assertNotIn("sk-", str(status))

            articles = client.get("/api/articles?keyword=医保&limit=10").json()
            self.assertEqual(articles["total"], 1)
            self.assertEqual(articles["items"][0]["id"], "1")
            self.assertNotIn("Content", articles["items"][0])

            extract = client.post("/api/extract", json={"selected_ids": ["1"], "mode": "merge", "no_ocr": True}).json()
            self.assertEqual(extract["status"], "success")
            self.assertTrue(extract["download_url"].startswith("/api/download/"))
            self.assertIn("%", extract["download_url"])
            self.assertNotIn(str(Path(tmp)), str(extract))

            download = client.get(extract["download_url"])
            self.assertEqual(download.status_code, 200)
            self.assertIn("spreadsheetml", download.headers["content-type"])

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
            payload = response.json()

            self.assertEqual(response.status_code, 500)
            self.assertEqual(response.headers["content-type"].split(";")[0], "application/json")
            self.assertEqual(payload["error_type"], "ExtractFailed")
            self.assertNotIn("abc", str(payload))
            self.assertNotIn("sk-test-token", str(payload))


if __name__ == "__main__":
    unittest.main()
