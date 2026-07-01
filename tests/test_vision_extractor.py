import json
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class VisionExtractorTests(unittest.TestCase):
    def test_vision_json_records_and_evidence_are_normalized(self):
        from vision_extractor import extract_image_table_with_vision

        class FakeVisionClient:
            model = "fake-vl"

            def extract_image_table(self, image, prompt_context=""):
                return json.dumps(
                    {
                        "tables_text": "意外门诊急诊费用补偿 100000 免赔额100元 给付比例80%",
                        "records": [
                            {
                                "类型": "意外门诊急诊费用补偿",
                                "补助限额": "100000元",
                                "起付标准": "免赔额100元",
                                "报销比例": "80%",
                            }
                        ],
                        "evidence": {"报销比例": "图片表格：给付比例80%"},
                    },
                    ensure_ascii=False,
                )

        result = extract_image_table_with_vision(
            ["https://example.com/table.jpg"],
            {"SourceURL": "https://example.com/article", "info_id": "INFO-1"},
            "上下文",
            FakeVisionClient(),
        )

        self.assertEqual(result.success_count, 1)
        self.assertEqual(result.failure_count, 0)
        self.assertEqual(result.records[0]["报销比例"], "80%")
        self.assertIn("意外门诊急诊费用补偿", result.text)
        self.assertTrue(any(item["source"] == "vision_llm" for item in result.field_evidence))

    def test_vision_failure_is_recorded_per_image_without_raising(self):
        from vision_extractor import extract_image_table_with_vision

        class FakeVisionClient:
            def __init__(self):
                self.calls = 0

            def extract_image_table(self, image, prompt_context=""):
                self.calls += 1
                if self.calls == 1:
                    return '{"records":[{"类型":"猝死","补助限额":"200000元"}],"tables_text":"猝死 200000"}'
                raise RuntimeError("provider does not support image_url")

        result = extract_image_table_with_vision(["a.jpg", "b.jpg"], {}, "", FakeVisionClient())

        self.assertEqual(result.success_count, 1)
        self.assertEqual(result.failure_count, 1)
        self.assertEqual(result.records[0]["类型"], "猝死")
        self.assertIn("image_url", result.errors[0])
        self.assertIn("does not support", result.errors[0]["error"])


if __name__ == "__main__":
    unittest.main()
