import json
import tempfile
import unittest
from pathlib import Path

import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class AiGeneratedCasesTests(unittest.TestCase):
    def test_generated_cases_flow_matches_baseline_thresholds(self):
        from excel_compare import compare_excel_files
        from excel_writer import write_extraction_workbook
        from field_mapping import load_field_mapping
        from main import _empty_metadata, extract_record_rows

        class FakeLLM:
            def extract(self, prompt):
                case_id = ""
                for item in ["AI-001", "AI-002", "AI-003", "AI-004", "AI-005", "AI-006", "AI-007", "AI-008", "AI-009", "AI-010"]:
                    if item in prompt:
                        case_id = item
                        break
                payload = {
                    "records": [
                        {
                            "info_id": case_id,
                            "地区名称": "测试省-测试市",
                            "保险类型": "城镇职工",
                            "病种名称": "类风湿性关节炎" if case_id in {"AI-001", "AI-002"} else "",
                            "类型": "门诊慢特病" if case_id in {"AI-001", "AI-002"} else "住院待遇",
                            "报销比例": "80%" if case_id != "AI-006" else "70%",
                            "起付标准": "200元",
                            "补助限额": "15万元",
                        }
                    ],
                    "evidence": {"报销比例": "模拟数据"},
                    "confidence": {"报销比例": 0.9},
                    "need_manual_review": False,
                    "review_reason": "",
                }
                return json.dumps(payload, ensure_ascii=False)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            mapping = load_field_mapping(None)
            records = json.loads((Path("samples") / "ai_generated" / "cases.json").read_text(encoding="utf-8"))
            all_rows = []
            all_metadata = _empty_metadata()
            for index, record in enumerate(records, start=1):
                record = dict(record)
                record["_direct_fields"] = {
                    "info_id": record.get("info_id", ""),
                    "地区名称": record.get("areaname", ""),
                    "保险类型": record.get("insurancetypename", ""),
                }
                metadata = _empty_metadata()
                rows = extract_record_rows(
                    record=record,
                    record_index=index,
                    llm_client=FakeLLM(),
                    logs_dir=tmp_path / "logs",
                    temp_images_dir=tmp_path / "images",
                    today="20260630",
                    image_base_url="",
                    ocr_enabled=False,
                    debug=False,
                    logger=None,
                    field_mapping=mapping,
                    no_llm=False,
                    input_mode="ai-generated",
                    metadata=metadata,
                )
                all_rows.extend(rows)
                for key in all_metadata:
                    all_metadata[key].extend(metadata[key])

            generated = tmp_path / "generated.xlsx"
            manual = tmp_path / "manual.xlsx"
            write_extraction_workbook(all_rows, generated, tmp_path / "missing.xlsx", mapping, **all_metadata)
            baseline_rows = json.loads((Path("samples") / "ai_generated" / "baseline.json").read_text(encoding="utf-8"))
            write_extraction_workbook(baseline_rows, manual, tmp_path / "missing.xlsx", mapping)

            result = compare_excel_files(generated, manual, output_json=tmp_path / "compare.json")

        self.assertGreaterEqual(result["overall_similarity"], 0.85)
        self.assertGreaterEqual(result["core_field_similarity"], 0.90)


if __name__ == "__main__":
    unittest.main()
