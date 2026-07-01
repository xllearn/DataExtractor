import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class OcrStatusAndImageRiskTests(unittest.TestCase):
    def test_config_status_reports_ocr_unavailable_reason(self):
        from api_server import create_app

        with patch(
            "api_server.get_ocr_status",
            return_value={"available": False, "reason": "未安装 paddleocr/paddlepaddle 或 OCR 初始化失败", "engine": "none"},
        ):
            with tempfile.TemporaryDirectory() as tmp:
                client = TestClient(create_app(record_provider=lambda **_: {"items": [], "total": 0}, output_dir=Path(tmp)))
                payload = client.get("/api/config/status").json()

        self.assertFalse(payload["ocr_available"])
        self.assertIn("ocr_status_reason", payload)
        self.assertIn("OCR", payload["ocr_status_reason"])
        self.assertNotIn("sk-", str(payload))

    def test_image_table_risk_message_when_images_without_table_or_ocr(self):
        from confidence import calculate_ocr_risk_score

        _score, reason = calculate_ocr_risk_score(
            clean_text="短正文",
            tables_text="",
            image_ocr_text="",
            image_count=2,
            ocr_attempted=False,
        )

        self.assertIn("图片表格未识别", reason)
        self.assertIn("保障责任", reason)

    def test_external_ocr_text_is_in_prompt_and_field_evidence(self):
        from field_mapping import load_field_mapping
        from main import extract_record_rows
        from table_extractor import load_table_mapping

        class FakeClient:
            def __init__(self):
                self.prompt = ""

            def extract(self, prompt):
                self.prompt = prompt
                return '{"records":[{"报销比例":"免赔额100元，给付比例80%","补助限额":"100000"}],"need_manual_review":false}'

        record = {
            "Title": "普惠门诊保·如意版2025 保障详情",
            "SourceURL": "https://mp.weixin.qq.com/s/7meXk1OSTtr9-GTFxFX4HQ",
            "Content": '<p>正文很短</p><img src="https://example.com/table.jpg" />',
        }
        with tempfile.TemporaryDirectory() as tmp:
            metadata = {
                "collection_logs": [],
                "field_evidence": [],
                "conflict_evidence": [],
                "extract_evaluations": [],
                "failed_records": [],
            }
            client = FakeClient()
            rows = extract_record_rows(
                record=record,
                record_index=1,
                llm_client=client,
                logs_dir=Path(tmp),
                temp_images_dir=Path(tmp) / "images",
                today="20260701",
                image_base_url="",
                ocr_enabled=False,
                debug=False,
                logger=None,
                field_mapping=load_field_mapping(None),
                table_mapping=load_table_mapping(None),
                metadata=metadata,
                external_ocr_text="投保年龄：6-65周岁\n意外门诊急诊费用补偿 100000 免赔额100元 给付比例80%",
                ocr_status={"available": False, "reason": "OCR依赖不可用", "engine": "none"},
            )

        self.assertEqual(rows[0]["报销比例"], "免赔额100元，给付比例80%")
        self.assertIn("6-65周岁", rows[0]["备注"])
        self.assertIn("意外门诊急诊费用补偿", client.prompt)
        self.assertTrue(any(item.get("source") == "external_ocr_text" for item in metadata["field_evidence"]))
        self.assertTrue(metadata["collection_logs"][0]["external_ocr_used"])


if __name__ == "__main__":
    unittest.main()
