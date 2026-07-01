import json
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class ImageDataLoaderTests(unittest.TestCase):
    def test_loads_json_transcript_and_writes_intermediate_records(self):
        from image_data_loader import load_image_records

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            image_path = tmp_path / "sample.jpg"
            image_path.write_bytes(b"fake")
            transcript = tmp_path / "transcript.json"
            transcript.write_text(
                json.dumps(
                    [
                        {
                            "Title": "图片导入测试",
                            "Content": "<p>保障病种范围：类风湿性关节炎</p>",
                            "AuditTime": "2026-05-20",
                            "areaname": "陕西省-西安市",
                            "SourceURL": "image-import://case-1",
                            "insurancetypename": "城镇职工",
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            output_json = tmp_path / "parsed.json"

            records = load_image_records(image_path, transcript_path=transcript, output_json=output_json, batch_id="batch-test")

            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["Title"], "图片导入测试")
            self.assertIn("类风湿性关节炎", records[0]["Content"])
            self.assertEqual(records[0]["_batch_id"], "batch-test")
            saved = json.loads(output_json.read_text(encoding="utf-8"))
            self.assertEqual(saved["record_count"], 1)

    def test_builds_article_record_from_manual_excel_fallback(self):
        from image_data_loader import load_image_records

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            image_path = tmp_path / "sample.jpg"
            image_path.write_bytes(b"fake")
            manual = tmp_path / "manual.xlsx"
            wb = Workbook()
            ws = wb.active
            ws.append(["文章时间", "info_id", "地区名称", "病种名称", "类型", "报销比例", "保险类型"])
            ws.append(["2026-05-20", "M-1", "陕西省-西安市", "类风湿性关节炎", "门诊慢特病", "80%", "城镇职工"])
            wb.save(manual)

            records = load_image_records(image_path, transcript_path=manual, batch_id="batch-xlsx")

            self.assertEqual(len(records), 1)
            self.assertIn("<table>", records[0]["Content"])
            self.assertIn("类风湿性关节炎", records[0]["Content"])
            self.assertEqual(records[0]["AuditTime"], "2026-05-20")
            self.assertEqual(records[0]["areaname"], "陕西省-西安市")


class ImageDataImportTests(unittest.TestCase):
    def test_import_records_to_sqlite_uses_transaction_and_returns_traceable_ids(self):
        from scripts.import_image_data_to_db import import_records_to_db

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "image_import.db"
            database_url = f"sqlite:///{db_path.as_posix()}"
            records = [
                {
                    "Title": "图片导入测试",
                    "Content": "<p>保障病种范围：类风湿性关节炎</p>",
                    "AuditTime": "2026-05-20",
                    "areaname": "陕西省-西安市",
                    "SourceURL": "image-import://case-1",
                    "insurancetypename": "城镇职工",
                    "_batch_id": "batch-test",
                }
            ]

            dry_run = import_records_to_db(database_url, "image_import_articles", records, dry_run=True, create_table=True)
            inserted = import_records_to_db(database_url, "image_import_articles", records, dry_run=False, create_table=True)

            self.assertEqual(dry_run["inserted_count"], 0)
            self.assertEqual(inserted["inserted_count"], 1)
            self.assertEqual(inserted["records"][0]["SourceURL"], "image-import://case-1")
            self.assertEqual(inserted["batch_id"], "batch-test")

    def _minimal_records(self):
        return [
            {
                "Title": "image import test",
                "Content": "<p>policy</p>",
                "AuditTime": "2026-05-20",
                "areaname": "region",
                "SourceURL": "image-import://case-1",
                "insurancetypename": "insurance",
                "_batch_id": "batch-test",
            }
        ]

    def test_image_import_allows_test_table_names_by_default(self):
        from scripts.import_image_data_to_db import import_records_to_db

        with tempfile.TemporaryDirectory() as tmp:
            database_url = f"sqlite:///{(Path(tmp) / 'image_import.db').as_posix()}"

            for table in ("image_import_articles", "test_articles", "articles_test"):
                with self.subTest(table=table):
                    result = import_records_to_db(database_url, table, self._minimal_records(), dry_run=True, create_table=True)
                    self.assertEqual(result["target_table"], table)

    def test_image_import_rejects_non_test_table_without_force(self):
        from scripts.import_image_data_to_db import import_records_to_db

        with tempfile.TemporaryDirectory() as tmp:
            database_url = f"sqlite:///{(Path(tmp) / 'image_import.db').as_posix()}"

            with self.assertRaisesRegex(ValueError, "force-production-table"):
                import_records_to_db(database_url, "prod_articles", self._minimal_records(), dry_run=True, create_table=True)

    def test_image_import_allows_non_test_table_with_force(self):
        from scripts.import_image_data_to_db import import_records_to_db

        with tempfile.TemporaryDirectory() as tmp:
            database_url = f"sqlite:///{(Path(tmp) / 'image_import.db').as_posix()}"

            result = import_records_to_db(
                database_url,
                "prod_articles",
                self._minimal_records(),
                dry_run=True,
                create_table=True,
                force_production_table=True,
            )

            self.assertEqual(result["target_table"], "prod_articles")


if __name__ == "__main__":
    unittest.main()
