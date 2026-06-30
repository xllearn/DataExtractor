import tempfile
import unittest
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class NoLlmFlowTests(unittest.TestCase):
    def test_no_llm_skips_client_and_uses_rules_and_direct_fields(self):
        from field_mapping import load_field_mapping
        from main import _empty_metadata, extract_record_rows

        class FailingLLM:
            def extract(self, prompt):
                raise AssertionError("LLM should not be called")

        record = {
            "Title": "规则抽取",
            "SourceURL": "https://example.com/a",
            "Content": "<table><tr><th>支付比例</th></tr><tr><td>80%</td></tr></table>",
            "_direct_fields": {"info_id": "A-001", "地区名称": "山东省"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            metadata = _empty_metadata()
            rows = extract_record_rows(
                record=record,
                record_index=1,
                llm_client=FailingLLM(),
                logs_dir=Path(tmp),
                temp_images_dir=Path(tmp) / "images",
                today="20260630",
                image_base_url="",
                ocr_enabled=True,
                debug=False,
                logger=None,
                field_mapping=load_field_mapping(None),
                no_llm=True,
                input_mode="input-xlsx",
                metadata=metadata,
            )

        self.assertEqual(rows[0]["报销比例"], "80%")
        self.assertEqual(rows[0]["info_id"], "A-001")
        self.assertEqual(rows[0]["地区名称"], "山东省")
        self.assertEqual(metadata["collection_logs"][0]["llm_format"], "none")
        self.assertEqual(metadata["collection_logs"][0]["input_mode"], "input-xlsx")
        self.assertFalse(metadata["collection_logs"][0]["ocr_triggered"])
        self.assertIn("跳过 LLM/OCR", metadata["collection_logs"][0]["review_reason"])
        self.assertTrue(metadata["field_evidence"])


if __name__ == "__main__":
    unittest.main()
