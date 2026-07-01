import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


SAMPLE_OCR_TEXT = """普惠门诊保·如意版(2025)
保障期间 1年
投保年龄 6-65周岁
保费 188元/年/人
保障项目 累计保险金额 等待期、免赔额、给付比例
意外身故及伤残保险金 200000 详见保险条款约定
航空意外身故及伤残保险金 1000000 详见保险条款约定
火车意外身故及伤残保险金 1000000 详见保险条款约定
轮船意外身故及伤残保险金 1000000 详见保险条款约定
意外骨折和脱臼 30000 详见保险条款约定
意外住院津贴保险金 18000 等待期0天，每次免赔日数0天，每次最高给付津贴日数90天，每份每日津贴给付标准100元，总给付日数180天
重疾住院津贴保险金 18000 等待期30天，每次免赔日数0天，每次最高给付津贴日数90天，每份每日津贴给付标准100元，总给付日数180天
在线问诊药品费用医疗保险金 10000 疾病等待期7天，意外等待期0天，每次事故免赔额0元，每次给付限额500元，每月最高给付次数2次，累计最高给付次数20次，给付比例70%
猝死 200000 等待期30天
意外门诊急诊费用补偿 100000 免赔额100元，给付比例80%
免责条款：高血压、糖尿病、慢性肝炎不承担给付责任。"""


class OcrFallbackTests(unittest.TestCase):
    def test_sample_ocr_text_parses_multiple_benefit_rows(self):
        from field_mapping import load_field_mapping
        from ocr_table_parser import extract_benefit_table_records_from_ocr_text

        result = extract_benefit_table_records_from_ocr_text(
            SAMPLE_OCR_TEXT,
            source_id="https://mp.weixin.qq.com/s/7meXk1OSTtr9-GTFxFX4HQ",
            info_id="INFO-1",
            field_mapping=load_field_mapping(None),
            source="external_ocr_text",
        )

        self.assertGreaterEqual(len(result.records), 10)
        by_type = {row["类型"]: row for row in result.records}
        self.assertEqual(by_type["意外门诊急诊费用补偿"]["补助限额"], "100000元")
        self.assertEqual(by_type["意外门诊急诊费用补偿"]["起付标准"], "免赔额100元")
        self.assertEqual(by_type["意外门诊急诊费用补偿"]["报销比例"], "80%")
        self.assertEqual(by_type["在线问诊药品费用医疗保险金"]["补助限额"], "10000元")
        self.assertEqual(by_type["在线问诊药品费用医疗保险金"]["报销比例"], "70%")
        self.assertNotIn("6-65周岁", by_type["意外门诊急诊费用补偿"]["人员类型"])
        self.assertEqual(by_type["意外门诊急诊费用补偿"]["病种名称"], "")
        self.assertTrue(any(item.get("source") == "external_ocr_text" for item in result.field_evidence))

    def test_external_ocr_text_flow_outputs_multiple_rows_without_llm(self):
        from field_mapping import load_field_mapping
        from main import _empty_metadata, extract_record_rows
        from table_extractor import load_table_mapping

        class FailingLLM:
            def extract(self, prompt):
                raise AssertionError("LLM should be skipped")

        record = {
            "Title": "普惠门诊保·如意版2025 保障详情",
            "SourceURL": "https://mp.weixin.qq.com/s/7meXk1OSTtr9-GTFxFX4HQ",
            "AuditTime": "2025-05-21 20:00:00",
            "province": "湖南省",
            "areaname": "湖南省",
            "insurancetypename": "商业补充保险",
            "Content": '<p>中国大陆籍人士可投保，详见保障图。</p><img src="https://example.com/table.jpg" />',
        }
        with tempfile.TemporaryDirectory() as tmp:
            metadata = _empty_metadata()
            rows = extract_record_rows(
                record=record,
                record_index=1,
                llm_client=FailingLLM(),
                logs_dir=Path(tmp),
                temp_images_dir=Path(tmp) / "images",
                today="20260701",
                image_base_url="",
                ocr_enabled=False,
                debug=False,
                logger=None,
                field_mapping=load_field_mapping(None),
                table_mapping=load_table_mapping(None),
                no_llm=True,
                metadata=metadata,
                external_ocr_text=SAMPLE_OCR_TEXT,
                ocr_status={"available": False, "reason": "OCR依赖不可用", "engine": "none"},
            )

        self.assertGreaterEqual(len(rows), 10)
        by_type = {row["类型"]: row for row in rows}
        self.assertNotEqual(by_type["意外身故及伤残保险金"]["起付标准"], "0元")
        self.assertEqual(by_type["意外门诊急诊费用补偿"]["地区名称"], "湖南省")
        self.assertEqual(by_type["意外门诊急诊费用补偿"]["人员类型"], "中国大陆籍人士")
        self.assertEqual(by_type["意外门诊急诊费用补偿"]["补助限额"], "100000元")
        self.assertEqual(by_type["意外门诊急诊费用补偿"]["起付标准"], "免赔额100元")
        self.assertEqual(by_type["意外门诊急诊费用补偿"]["报销比例"], "80%")
        self.assertEqual(by_type["在线问诊药品费用医疗保险金"]["报销比例"], "70%")
        self.assertIn("6-65周岁", by_type["猝死"]["备注"])
        self.assertEqual(by_type["猝死"]["病种名称"], "")
        self.assertNotEqual(by_type["猝死"]["人员类型"], "6-65周岁")
        self.assertTrue(metadata["collection_logs"][0]["external_ocr_used"])
        self.assertTrue(any(item.get("source") == "external_ocr_text" for item in metadata["field_evidence"]))


if __name__ == "__main__":
    unittest.main()
