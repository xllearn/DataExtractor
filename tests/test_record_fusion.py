import unittest
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class RecordFusionTests(unittest.TestCase):
    def test_priority_direct_table_text_llm_and_llm_supplements_missing_fields(self):
        from field_mapping import load_field_mapping
        from record_fusion import fuse_record_sources

        result = fuse_record_sources(
            record={"_direct_fields": {"地区名称": "数据库地区"}},
            table_records=[{"地区名称": "表格地区", "报销比例": "80%"}],
            text_rule_records=[{"报销比例": "70%", "起付标准": "500元"}],
            llm_records=[{"报销比例": "60%", "起付标准": "300元", "补助限额": "15万元"}],
            table_evidence=[],
            text_rule_evidence=[],
            llm_evidence=[],
            field_mapping=load_field_mapping(None),
        )

        row = result.records[0]
        self.assertEqual(row["地区名称"], "数据库地区")
        self.assertEqual(row["报销比例"], "80%")
        self.assertEqual(row["起付标准"], "500元")
        self.assertEqual(row["补助限额"], "15万元")
        self.assertTrue(any(item["source"] == "database_direct" for item in result.field_evidence))

    def test_table_and_llm_conflict_keeps_table_and_marks_review(self):
        from field_mapping import load_field_mapping
        from record_fusion import fuse_record_sources

        result = fuse_record_sources(
            record={},
            table_records=[{"报销比例": "80%"}],
            text_rule_records=[],
            llm_records=[{"报销比例": "70%"}],
            table_evidence=[],
            text_rule_evidence=[],
            llm_evidence=[],
            field_mapping=load_field_mapping(None),
        )

        self.assertEqual(result.records[0]["报销比例"], "80%")
        self.assertTrue(result.need_manual_review)
        self.assertIn("报销比例", result.review_reason)
        self.assertEqual(result.conflict_evidence[0]["field"], "报销比例")
        self.assertEqual(result.conflict_evidence[0]["chosen_value"], "80%")

    def test_uses_llm_records_when_rules_are_empty(self):
        from field_mapping import load_field_mapping
        from record_fusion import fuse_record_sources

        result = fuse_record_sources(
            record={},
            table_records=[],
            text_rule_records=[],
            llm_records=[{"报销比例": "70%"}],
            table_evidence=[],
            text_rule_evidence=[],
            llm_evidence=[],
            field_mapping=load_field_mapping(None),
        )

        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.records[0]["报销比例"], "70%")

    def test_multiline_table_records_and_count_mismatch_review(self):
        from field_mapping import load_field_mapping
        from record_fusion import fuse_record_sources

        result = fuse_record_sources(
            record={},
            table_records=[{"人员类型": "居民", "报销比例": "60%"}, {"人员类型": "职工", "报销比例": "80%"}],
            text_rule_records=[],
            llm_records=[{"补助限额": "15万元"}],
            table_evidence=[],
            text_rule_evidence=[],
            llm_evidence=[],
            field_mapping=load_field_mapping(None),
        )

        self.assertEqual(len(result.records), 2)
        self.assertTrue(result.need_manual_review)
        self.assertIn("数量不一致", result.review_reason)


if __name__ == "__main__":
    unittest.main()
