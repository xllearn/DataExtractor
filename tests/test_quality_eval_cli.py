import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _write_workbook(path, rows):
    from excel_writer import write_extraction_workbook
    from field_mapping import load_field_mapping

    write_extraction_workbook(rows, path, Path(path).parent / "missing.xlsx", load_field_mapping(None))


def _matching_quality_rows():
    from quality_metrics import CORE_FIELDS

    return [{field: f"match-{index}" for index, field in enumerate(CORE_FIELDS, start=1)}]


def _write_matching_workbooks(tmp_path):
    generated = tmp_path / "generated.xlsx"
    manual = tmp_path / "manual.xlsx"
    rows = _matching_quality_rows()
    _write_workbook(generated, rows)
    _write_workbook(manual, rows)
    return generated, manual


def _run_quality_eval_cli(*args):
    return subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "quality_eval.py"), *map(str, args)],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


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


def test_quality_eval_cli_keeps_positional_arguments_with_legacy_output_flags(tmp_path):
    generated, manual = _write_matching_workbooks(tmp_path)
    output = tmp_path / "legacy-report.xlsx"
    json_output = tmp_path / "legacy-report.json"

    completed = _run_quality_eval_cli(generated, manual, "--output-xlsx", output, "--output-json", json_output)

    assert completed.returncode == 0, completed.stderr
    assert output.exists()
    assert json_output.exists()
    assert '"passed": true' in completed.stdout


def test_quality_eval_cli_accepts_named_arguments_and_output_aliases(tmp_path):
    generated, manual = _write_matching_workbooks(tmp_path)
    output = tmp_path / "named-report.xlsx"
    json_output = tmp_path / "named-report.json"

    completed = _run_quality_eval_cli(
        "--generated",
        generated,
        "--manual",
        manual,
        "--output",
        output,
        "--json-output",
        json_output,
    )

    assert completed.returncode == 0, completed.stderr
    assert output.exists()
    assert json_output.exists()
    assert '"passed": true' in completed.stdout


def test_quality_eval_cli_named_inputs_override_positionals(tmp_path):
    generated, manual = _write_matching_workbooks(tmp_path)
    output = tmp_path / "override-report.xlsx"
    json_output = tmp_path / "override-report.json"

    completed = _run_quality_eval_cli(
        tmp_path / "missing-generated.xlsx",
        tmp_path / "missing-manual.xlsx",
        "--generated",
        generated,
        "--manual",
        manual,
        "--output",
        output,
        "--json-output",
        json_output,
    )

    assert completed.returncode == 0, completed.stderr
    assert output.exists()
    assert json_output.exists()


def test_quality_eval_cli_reports_clear_error_when_manual_is_missing(tmp_path):
    generated, _manual = _write_matching_workbooks(tmp_path)
    output = tmp_path / "missing-manual-report.xlsx"

    completed = _run_quality_eval_cli("--generated", generated, "--output", output)

    assert completed.returncode != 0
    assert "manual" in completed.stderr.lower()
    assert "required" in completed.stderr.lower()
    assert not output.exists()
