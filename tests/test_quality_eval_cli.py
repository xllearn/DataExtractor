from pathlib import Path


def _write_workbook(path, rows):
    from excel_writer import write_extraction_workbook
    from field_mapping import load_field_mapping

    write_extraction_workbook(rows, path, Path(path).parent / "missing.xlsx", load_field_mapping(None))


def test_quality_eval_outputs_xlsx_and_json(tmp_path):
    from quality_eval import run_quality_eval

    generated = tmp_path / "generated.xlsx"
    manual = tmp_path / "manual.xlsx"
    output = tmp_path / "report.xlsx"
    json_output = tmp_path / "report.json"
    _write_workbook(generated, [{"类型": "门诊", "报销比例": "80%"}])
    _write_workbook(manual, [{"类型": "门诊", "报销比例": "80%"}])

    result = run_quality_eval(generated, manual, output, json_output)

    assert output.exists()
    assert json_output.exists()
    assert result["overall_similarity"] >= 0.85
    assert "row_alignment_score" in result
    assert "missing_core_fields" in result
