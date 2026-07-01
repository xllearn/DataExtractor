import unittest
from pathlib import Path

import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class PersonTypeQualityTests(unittest.TestCase):
    def test_rule_person_type_age_ranges_are_redirected(self):
        from rule_extractor import extract_key_value_records

        for value in ["6-65周岁", "18-70岁", "出生满30天-65周岁"]:
            with self.subTest(value=value):
                result = extract_key_value_records(f"人员类型：{value}")
                self.assertEqual(result.records[0]["人员类型"], "")
                self.assertTrue(value in result.records[0]["备注"] or value.replace("出生满", "") in result.records[0]["备注"])

    def test_valid_text_rule_person_type_wins_over_llm_age_range(self):
        from field_mapping import load_field_mapping
        from record_fusion import fuse_record_sources

        result = fuse_record_sources(
            record={},
            table_records=[],
            text_rule_records=[{"人员类型": "参保职工"}],
            llm_records=[{"人员类型": "6-65周岁"}],
            table_evidence=[],
            text_rule_evidence=[],
            llm_evidence=[],
            field_mapping=load_field_mapping(None),
        )

        self.assertEqual(result.records[0]["人员类型"], "参保职工")
        self.assertIn("6-65周岁", result.records[0]["备注"])

    def test_valid_llm_person_type_wins_over_text_rule_age_range(self):
        from field_mapping import load_field_mapping
        from record_fusion import fuse_record_sources

        result = fuse_record_sources(
            record={},
            table_records=[],
            text_rule_records=[{"人员类型": "6-65周岁"}],
            llm_records=[{"人员类型": "被保险人"}],
            table_evidence=[],
            text_rule_evidence=[],
            llm_evidence=[],
            field_mapping=load_field_mapping(None),
        )

        self.assertEqual(result.records[0]["人员类型"], "被保险人")
        self.assertIn("6-65周岁", result.records[0]["备注"])


if __name__ == "__main__":
    unittest.main()
