import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class DiseaseNameRuleTests(unittest.TestCase):
    def test_normalizes_sentence_to_core_disease_name(self):
        from rule_extractor import extract_key_value_records, normalize_disease_name

        self.assertEqual(normalize_disease_name("澄迈县的李女士去年帕金森病加重"), "帕金森病")

        result = extract_key_value_records("澄迈县的李女士去年帕金森病加重")

        self.assertEqual(result.records[0]["病种名称"], "帕金森病")

    def test_rejects_generic_or_sentence_like_disease_names(self):
        from rule_extractor import extract_key_value_records, is_valid_disease_name, normalize_disease_name

        invalid_values = [
            "旨在减轻被保险人因患大病",
            "特药范围以及覆盖的疾病病",
            "了解症",
            "妥妥的花小钱保大病",
            "医保定点医药机构发生的大病",
            "中国居民营养与慢性病",
            "合理自费费用",
            "高额医疗费用",
            "既往症",
            "大病",
            "慢性病",
            "特殊病",
        ]

        for value in invalid_values:
            with self.subTest(value=value):
                self.assertEqual(normalize_disease_name(value), "")
                self.assertFalse(is_valid_disease_name(value))
                result = extract_key_value_records(value)
                disease_name = result.records[0].get("病种名称", "") if result.records else ""
                self.assertEqual(disease_name, "")

    def test_strong_context_extracts_multiple_disease_names(self):
        from rule_extractor import extract_key_value_records

        result = extract_key_value_records("病种范围：帕金森病、恶性肿瘤")

        self.assertEqual(result.records[0]["病种名称"], "帕金森病、恶性肿瘤")

    def test_observed_real_data_long_clauses_are_not_kept_as_disease_names(self):
        from rule_extractor import normalize_disease_name

        self.assertEqual(
            normalize_disease_name("美国国家综合癌、加拿大国立癌、英国癌、欧洲癌、结直肠癌"),
            "结直肠癌",
        )
        self.assertEqual(
            normalize_disease_name("参保群众一旦患了癌、高发肿瘤、种高发肿瘤、罕见病、种高价自费癌"),
            "罕见病",
        )


class DiseaseNameFusionTests(unittest.TestCase):
    def test_llm_core_disease_wins_over_text_rule_sentence(self):
        from field_mapping import load_field_mapping
        from record_fusion import fuse_record_sources

        result = fuse_record_sources(
            record={},
            table_records=[],
            text_rule_records=[{"病种名称": "澄迈县的李女士去年帕金森病"}],
            llm_records=[{"病种名称": "帕金森病"}],
            table_evidence=[],
            text_rule_evidence=[],
            llm_evidence=[],
            field_mapping=load_field_mapping(None),
        )

        self.assertEqual(result.records[0]["病种名称"], "帕金森病")
        self.assertTrue(result.need_manual_review)
        conflict = result.conflict_evidence[0]
        self.assertEqual(conflict["field"], "病种名称")
        self.assertEqual(conflict["source_a"], "text_rule")
        self.assertEqual(conflict["value_a"], "澄迈县的李女士去年帕金森病")
        self.assertEqual(conflict["source_b"], "llm")
        self.assertEqual(conflict["value_b"], "帕金森病")
        self.assertEqual(conflict["chosen_source"], "llm")
        self.assertEqual(conflict["chosen_value"], "帕金森病")
        self.assertIn("核心疾病名", conflict["reason"])

    def test_invalid_text_rule_and_llm_disease_name_is_cleared(self):
        from field_mapping import load_field_mapping
        from record_fusion import fuse_record_sources

        result = fuse_record_sources(
            record={},
            table_records=[],
            text_rule_records=[{"病种名称": "医保定点医药机构发生的大病"}],
            llm_records=[{"病种名称": "大病"}],
            table_evidence=[],
            text_rule_evidence=[],
            llm_evidence=[],
            field_mapping=load_field_mapping(None),
        )

        self.assertEqual(result.records[0]["病种名称"], "")
        self.assertTrue(result.need_manual_review)
        self.assertIn("病种名称规则和LLM均不可信", result.review_reason)
        self.assertEqual(result.conflict_evidence[0]["chosen_source"], "cleared")

    def test_table_explicit_disease_header_still_wins(self):
        from table_extractor import extract_tables_from_html

        html = """
        <table>
          <tr><th>疾病名称</th><th>报销比例</th></tr>
          <tr><td>帕金森病</td><td>80%</td></tr>
        </table>
        """

        result = extract_tables_from_html(html)

        self.assertEqual(result.records[0]["病种名称"], "帕金森病")
        self.assertEqual(result.field_evidence[0]["source"], "table")


class DiseaseNamePromptTests(unittest.TestCase):
    def test_prompt_contains_disease_name_constraints(self):
        from prompts_v2 import build_extract_prompt_v2

        prompt = build_extract_prompt_v2({}, "", "", "", "20260630")

        self.assertIn("病种名称”只能填写具体疾病、病种或病症名称", prompt)
        self.assertIn("错误：澄迈县的李女士去年帕金森病", prompt)
        self.assertIn("正确：帕金森病", prompt)
        self.assertIn("高额医疗费用", prompt)


if __name__ == "__main__":
    unittest.main()
