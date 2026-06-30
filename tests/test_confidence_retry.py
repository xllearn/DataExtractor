import json
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class ConfidenceScoringTests(unittest.TestCase):
    def test_sparse_article_without_images_is_not_penalized_by_field_coverage(self):
        from confidence import evaluate_rows
        from utils import create_fallback_row

        record = {
            "Title": "更名提醒",
            "AuditTime": "2025-05-20",
            "province": "山东省",
            "areaname": "德州市",
            "insurancetypename": "商业补充保险",
        }
        rows = [create_fallback_row(record, "20260602")]

        evals = evaluate_rows(
            rows,
            record,
            clean_text="德州惠民保即将上线，具体保障待遇请以后续公告为准。",
            tables_text="",
            image_ocr_text="",
            image_count=0,
            ocr_attempted=False,
        )

        self.assertEqual(len(evals), 1)
        self.assertGreaterEqual(evals[0]["confidence_score"], 70)
        self.assertIn(evals[0]["confidence_level"], {"medium", "high"})
        self.assertFalse(evals[0]["should_retry_with_ocr"])
        self.assertEqual(evals[0]["ocr_trigger_reason"], "--")

    def test_images_and_low_evidence_trigger_ocr_retry(self):
        from confidence import evaluate_rows
        from utils import create_fallback_row

        record = {"Title": "待遇图解", "AuditTime": "2025-05-20"}
        rows = [create_fallback_row(record, "20260602")]

        evals = evaluate_rows(
            rows,
            record,
            clean_text="详见下图。",
            tables_text="",
            image_ocr_text="",
            image_count=3,
            ocr_attempted=False,
        )

        self.assertLess(evals[0]["confidence_score"], 70)
        self.assertLess(evals[0]["ocr_risk_score"], 80)
        self.assertTrue(evals[0]["should_retry_with_ocr"])
        self.assertNotEqual(evals[0]["ocr_trigger_reason"], "--")


class RetryFlowTests(unittest.TestCase):
    def test_low_confidence_first_pass_retries_with_ocr_and_logs_eval(self):
        from image_ocr import OcrSummary
        from main import extract_record_rows
        from utils import EXCEL_HEADERS

        class FakeLLM:
            def __init__(self):
                self.prompts = []

            def extract(self, prompt):
                self.prompts.append(prompt)
                if len(self.prompts) == 1:
                    return json.dumps([{"类型": "其他"}], ensure_ascii=False)
                return json.dumps(
                    [
                        {
                            "类型": "住院待遇",
                            "起付标准": "1万元",
                            "补助限额": "100万元",
                            "报销比例": "80%",
                            "人员类型": "普通参保人",
                        }
                    ],
                    ensure_ascii=False,
                )

        ocr_calls = []

        def fake_ocr(image_urls, temp_dir, record_index, enabled=True, logger=None):
            ocr_calls.append((list(image_urls), enabled))
            return OcrSummary(
                text="【图片OCR-1】\n住院待遇 起付标准1万元 补助限额100万元 报销比例80% 普通参保人",
                success_count=1,
                failure_count=0,
            )

        record = {
            "Title": "待遇图解",
            "AuditTime": "2025-05-20",
            "Content": '<p>详见下图。</p><img src="https://example.com/a.jpg" />',
            "province": "山东省",
            "areaname": "德州市",
            "insurancetypename": "商业补充保险",
        }

        with tempfile.TemporaryDirectory() as tmp:
            fake_llm = FakeLLM()
            rows = extract_record_rows(
                record=record,
                record_index=1,
                llm_client=fake_llm,
                logs_dir=Path(tmp),
                temp_images_dir=Path(tmp) / "images",
                today="20260602",
                image_base_url="",
                ocr_enabled=True,
                debug=True,
                logger=None,
                ocr_func=fake_ocr,
            )

            self.assertEqual(len(ocr_calls), 1)
            self.assertEqual(len(fake_llm.prompts), 2)
            self.assertNotIn("图片OCR-1", fake_llm.prompts[0])
            self.assertIn("图片OCR-1", fake_llm.prompts[1])
            self.assertEqual(rows[0]["报销比例"], "80%")
            self.assertEqual(list(rows[0].keys()), EXCEL_HEADERS)

            eval_path = Path(tmp) / "extract_eval.jsonl"
            payloads = [json.loads(line) for line in eval_path.read_text(encoding="utf-8").splitlines()]
            self.assertGreaterEqual(len(payloads), 2)
            self.assertIn("confidence_score", payloads[0])
            self.assertTrue(payloads[0]["should_retry_with_ocr"])
            self.assertIn("ocr_retry", {payload["attempt"] for payload in payloads})


if __name__ == "__main__":
    unittest.main()
