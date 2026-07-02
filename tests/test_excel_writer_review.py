from pathlib import Path


def test_workbook_writes_review_confidence_and_row_match_sheets(tmp_path):
    from excel_writer import write_extraction_workbook
    from field_mapping import load_field_mapping
    from openpyxl import load_workbook

    out = tmp_path / "out.xlsx"
    write_extraction_workbook(
        [{"类型": "门诊", "报销比例": "80%"}],
        out,
        Path(tmp_path) / "missing.xlsx",
        load_field_mapping(None),
        field_confidence=[{"row_index": 1, "field": "报销比例", "confidence": 0.95, "reason": "表格坐标证据明确"}],
        review_rows=[{"row_index": 1, "field": "类型", "confidence": 0.4, "reason": "低置信"}],
        row_match_evidence=[{"source_a": "table", "source_b": "llm", "row_a": 1, "row_b": 2, "similarity": 0.8}],
    )

    wb = load_workbook(out)
    assert "结果数据" in wb.sheetnames
    assert "字段置信度" in wb.sheetnames
    assert "人工复核" in wb.sheetnames
    assert "行匹配证据" in wb.sheetnames
    assert [cell.value for cell in wb["结果数据"][1]][:3] == ["文章时间", "审核日期", "info_id"]
