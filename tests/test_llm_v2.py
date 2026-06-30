import json
import tempfile
import unittest
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class LlmV2ParsingTests(unittest.TestCase):
    def test_parse_standard_v2_object(self):
        from field_mapping import load_field_mapping
        from llm_extractor import parse_llm_extraction

        raw = json.dumps(
            {
                "records": [{"报销比例": "80%", "多余": "x"}],
                "evidence": {"报销比例": "原文"},
                "confidence": {"报销比例": 1.5, "起付标准": -0.2},
                "need_manual_review": "true",
                "review_reason": 123,
            },
            ensure_ascii=False,
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = parse_llm_extraction(raw, {"_direct_fields": {"info_id": "A-001"}}, "20260630", Path(tmp), load_field_mapping(None))

        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.records[0]["报销比例"], "80%")
        self.assertEqual(result.records[0]["info_id"], "A-001")
        self.assertNotIn("多余", result.records[0])
        self.assertEqual(result.confidence["报销比例"], 1.0)
        self.assertEqual(result.confidence["起付标准"], 0.0)
        self.assertIs(result.need_manual_review, True)
        self.assertEqual(result.review_reason, "123")
        self.assertEqual(result.parse_error, "")

    def test_parse_legacy_array_and_single_object(self):
        from field_mapping import load_field_mapping
        from llm_extractor import parse_llm_extraction

        mapping = load_field_mapping(None)
        with tempfile.TemporaryDirectory() as tmp:
            array_result = parse_llm_extraction('[{"支付比例":"70%"}]', {}, "20260630", Path(tmp), mapping)
            object_result = parse_llm_extraction('{"支付比例":"60%"}', {}, "20260630", Path(tmp), mapping)

        self.assertEqual(array_result.records[0]["报销比例"], "70%")
        self.assertEqual(object_result.records[0]["报销比例"], "60%")

    def test_invalid_json_saves_raw_output_and_fallback_applies_direct_fields(self):
        from field_mapping import load_field_mapping
        from llm_extractor import parse_llm_extraction

        with tempfile.TemporaryDirectory() as tmp:
            result = parse_llm_extraction(
                "not json",
                {"AuditTime": "2026-01-02", "_direct_fields": {"info_id": "A-002", "地区名称": "青岛市"}},
                "20260630",
                Path(tmp),
                load_field_mapping(None),
            )

            failed_files = list((Path(tmp) / "failed_llm_outputs").glob("*.txt"))

        self.assertEqual(result.records[0]["info_id"], "A-002")
        self.assertEqual(result.records[0]["地区名称"], "青岛市")
        self.assertTrue(result.parse_error)
        self.assertEqual(len(failed_files), 1)

    def test_extract_with_llm_uses_client_and_returns_raw_output(self):
        from field_mapping import load_field_mapping
        from llm_extractor import extract_with_llm

        class FakeClient:
            def extract(self, prompt):
                self.prompt = prompt
                return '{"records":[{"报销比例":"88%"}],"need_manual_review":false}'

        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient()
            result = extract_with_llm(client, "prompt text", {}, "20260630", Path(tmp), load_field_mapping(None))

        self.assertEqual(client.prompt, "prompt text")
        self.assertEqual(result.records[0]["报销比例"], "88%")
        self.assertIn("records", result.raw_output)


if __name__ == "__main__":
    unittest.main()
