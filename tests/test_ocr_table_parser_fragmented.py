import unittest
from pathlib import Path

import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class OcrTableParserFragmentedTests(unittest.TestCase):
    def test_reconstructs_fragmented_real_paddleocr_table_lines(self):
        from field_mapping import load_field_mapping
        from ocr_table_parser import extract_benefit_table_records_from_ocr_text

        text = """
普惠门诊保·如意版（2025）
保险期间
投保年龄
保费
1年
6-65周岁
188元/年/人
累计
保障项目
等待期、免赔额、给付比例
保险金额（元）
意外身故及
200000
伤残保险金
航空意外身故
1000000
及伤残保险金
火车意外身故
详见保险条款约定
轮船意外身故
意外骨折和脱臼
30000
等待期0天、每次免赔日数0天、每次最高给
意外住院津贴保险金
18000
付津贴日数90天、每份每日津贴给付标准
100元、总给付日数180天
疾病等待期7天，意外等待期0天，每次事故
在线问诊药品
免赔额0元，每次给付限额500元，每月最高
10000
费用医疗保险金
给付次数2次，累计最高给付次数20次，给
付比例70%
猝死
等待期30天
意外门诊
100000
免赔额100元，给付比例80%
急诊费用补偿
"""

        result = extract_benefit_table_records_from_ocr_text(
            text,
            source_id="sample",
            info_id="sample",
            field_mapping=load_field_mapping(None),
            source="paddleocr",
        )
        rows = {row["类型"]: row for row in result.records}

        self.assertGreaterEqual(len(result.records), 6)
        self.assertEqual(rows["意外身故及伤残保险金"]["补助限额"], "200000元")
        self.assertEqual(rows["航空意外身故及伤残保险金"]["补助限额"], "1000000元")
        self.assertEqual(rows["意外骨折和脱臼"]["补助限额"], "30000元")
        self.assertEqual(rows["在线问诊药品费用医疗保险金"]["补助限额"], "10000元")
        self.assertEqual(rows["在线问诊药品费用医疗保险金"]["起付标准"], "免赔额0元")
        self.assertEqual(rows["在线问诊药品费用医疗保险金"]["报销比例"], "70%")
        self.assertEqual(rows["意外门诊急诊费用补偿"]["起付标准"], "免赔额100元")
        self.assertEqual(rows["意外门诊急诊费用补偿"]["报销比例"], "80%")

    def test_does_not_use_standalone_year_as_benefit_amount(self):
        from field_mapping import load_field_mapping
        from ocr_table_parser import extract_benefit_table_records_from_ocr_text

        text = """
猝死
等待期30天
普惠门诊保·如意版
2025
"""

        result = extract_benefit_table_records_from_ocr_text(
            text,
            field_mapping=load_field_mapping(None),
            source="paddleocr",
        )

        self.assertEqual(result.records, [])


if __name__ == "__main__":
    unittest.main()
