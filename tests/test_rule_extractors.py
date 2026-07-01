import unittest
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class TableExtractorTests(unittest.TestCase):
    def test_html_table_maps_alias_headers_and_multiple_rows(self):
        from table_extractor import extract_tables_from_html

        html = """
        <table>
          <tr><th>人员类型</th><th>支付比例</th><th>起付线</th><th>最高支付限额</th><th>未映射列</th></tr>
          <tr><td>居民</td><td>60%</td><td>300元</td><td>15万元</td><td>备注一</td></tr>
          <tr><td>职工</td><td>80%</td><td>500元</td><td>20万元</td><td>备注二</td></tr>
        </table>
        """

        result = extract_tables_from_html(html, source_id="123", info_id="A-001")

        self.assertEqual(len(result.records), 2)
        self.assertEqual(result.records[0]["报销比例"], "60%")
        self.assertEqual(result.records[0]["起付标准"], "300元")
        self.assertEqual(result.records[0]["补助限额"], "15万元")
        self.assertIn("未映射列=备注一", result.records[0]["备注"])
        self.assertEqual(result.records[1]["报销比例"], "80%")
        evidence = result.field_evidence[0]
        for key in ["source_id", "info_id", "field", "value", "evidence", "confidence", "source", "rule_name"]:
            self.assertIn(key, evidence)

    def test_markdown_table_extracts_alias_headers(self):
        from table_extractor import extract_tables_from_text

        text = """
| 待遇类型 | 报付比例 |
| --- | --- |
| 门诊统筹 | 70% |
"""

        result = extract_tables_from_text(text, source_id="S", info_id="I")

        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.records[0]["类型"], "门诊统筹")
        self.assertEqual(result.records[0]["报销比例"], "70%")

    def test_table_extractor_uses_passed_field_mapping_aliases(self):
        from field_mapping import FieldMapping
        from table_extractor import extract_tables_from_text
        from utils import EXCEL_HEADERS

        mapping = FieldMapping(headers=list(EXCEL_HEADERS), aliases={"报销比例": ["给付比例"]})
        text = """
| 给付比例 |
| --- |
| 66% |
"""

        result = extract_tables_from_text(text, field_mapping=mapping)

        self.assertEqual(result.records[0]["报销比例"], "66%")

    def test_extract_table_records_deduplicates_html_and_markdown_sources(self):
        from table_extractor import extract_table_records

        html = "<table><tr><th>支付比例</th></tr><tr><td>80%</td></tr></table>"
        markdown = "| 支付比例 |\n| --- |\n| 80% |"

        result = extract_table_records(html, markdown)

        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.records[0]["报销比例"], "80%")

    def test_table_extractor_preserves_rows_that_differ_by_interval(self):
        from table_extractor import extract_tables_from_html

        html = """
        <table>
          <tr><th>人员类型</th><th>区间</th><th>支付比例</th></tr>
          <tr><td>职工</td><td>0-1000元</td><td>80%</td></tr>
          <tr><td>职工</td><td>1000元以上</td><td>80%</td></tr>
        </table>
        """

        result = extract_tables_from_html(html)

        self.assertEqual(len(result.records), 2)
        self.assertEqual(result.records[0]["区间"], "0-1000元")
        self.assertEqual(result.records[1]["区间"], "1000元以上")

    def test_table_extractor_keeps_age_ranges_out_of_person_type_and_interval(self):
        from table_extractor import extract_tables_from_html

        html = """
        <table>
          <tr><th>人员类型</th><th>区间</th><th>支付比例</th></tr>
          <tr><td>6-65周岁</td><td>18-60周岁</td><td>80%</td></tr>
          <tr><td>参保职工</td><td>50000元-400000元</td><td>90%</td></tr>
        </table>
        """

        result = extract_tables_from_html(html)

        self.assertEqual(len(result.records), 2)
        self.assertEqual(result.records[0]["人员类型"], "")
        self.assertEqual(result.records[0]["区间"], "")
        self.assertIn("6-65周岁", result.records[0]["备注"])
        self.assertIn("18-60周岁", result.records[0]["备注"])
        self.assertEqual(result.records[1]["人员类型"], "参保职工")
        self.assertEqual(result.records[1]["区间"], "50000元-400000元")


class TextRuleExtractorTests(unittest.TestCase):
    def test_extracts_common_key_value_patterns(self):
        from rule_extractor import extract_key_value_records

        text = "报销比例：80%\n起付标准为500元\n年度最高支付限额为15万元"

        result = extract_key_value_records(text, source_id="123", info_id="A-001")

        self.assertEqual(result.records[0]["报销比例"], "80%")
        self.assertEqual(result.records[0]["起付标准"], "500元")
        self.assertEqual(result.records[0]["补助限额"], "15万元")
        evidence = result.field_evidence[0]
        for key in ["source_id", "info_id", "field", "value", "evidence", "confidence", "source", "rule_name"]:
            self.assertIn(key, evidence)

    def test_extracts_insurance_hint_and_ratio(self):
        from rule_extractor import extract_key_value_records

        result = extract_key_value_records("居民医保报销比例为60%")

        self.assertEqual(result.records[0]["保险类型"], "居民医保")
        self.assertEqual(result.records[0]["报销比例"], "60%")

    def test_text_rule_extractor_uses_passed_field_mapping_aliases(self):
        from field_mapping import FieldMapping
        from rule_extractor import extract_key_value_records
        from utils import EXCEL_HEADERS

        mapping = FieldMapping(headers=list(EXCEL_HEADERS), aliases={"报销比例": ["给付比例"]})

        result = extract_key_value_records("给付比例为66%", field_mapping=mapping)

        self.assertEqual(result.records[0]["报销比例"], "66%")

    def test_age_range_person_alias_redirects_to_note_not_person_type_or_interval(self):
        from rule_extractor import extract_key_value_records

        result = extract_key_value_records("适用人群：6-65周岁\n报销比例：80%")

        self.assertEqual(result.records[0]["人员类型"], "")
        self.assertEqual(result.records[0]["区间"], "")
        self.assertEqual(result.records[0]["报销比例"], "80%")
        self.assertIn("6-65周岁", result.records[0]["备注"])

    def test_reimbursement_amount_interval_can_fill_interval(self):
        from rule_extractor import extract_key_value_records

        result = extract_key_value_records("报销区间：50000元-400000元\n报销比例：80%")

        self.assertEqual(result.records[0]["区间"], "50000元-400000元")
        self.assertEqual(result.records[0]["报销比例"], "80%")

    def test_rule_extraction_failure_is_captured(self):
        from rule_extractor import extract_key_value_records

        class BadText:
            def __str__(self):
                raise RuntimeError("boom")

        result = extract_key_value_records(BadText())

        self.assertEqual(result.records, [])
        self.assertEqual(len(result.errors), 1)


if __name__ == "__main__":
    unittest.main()
