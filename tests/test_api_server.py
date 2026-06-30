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
            output = output_dir / "web_result.xlsx"
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


if __name__ == "__main__":
    unittest.main()
