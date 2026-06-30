import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.test_result_utils import latest_xlsx, python_executable, run_command, selected_ids_from_file, validate_output_workbook, write_json


def run_real_db_case(count: int, result_dir: Path, name: str, config: str, selected_ids_file: str, no_ocr: bool = True) -> dict:
    output_dir = result_dir / name / "outputs"
    log_dir = result_dir / name / "logs"
    selected_ids = selected_ids_from_file(PROJECT_ROOT / selected_ids_file, count)
    command = [
        python_executable(),
        str(PROJECT_ROOT / "main.py"),
        "--config",
        config,
        "--field-config",
        "config/field_mapping.yml",
        "--table-config",
        "config/table_mapping.yml",
        "--llm-config",
        "config/llm_config.yml",
        "--selected-ids",
        selected_ids,
        "--mode",
        "merge",
        "--limit",
        str(count),
        "--output-dir",
        str(output_dir),
        "--log-dir",
        str(log_dir),
        "--save-intermediate",
    ]
    if no_ocr:
        command.append("--no-ocr")
    run = run_command(command, PROJECT_ROOT, result_dir / name / "command.log", timeout=1800)
    validation = {}
    if run["returncode"] == 0:
        validation = validate_output_workbook(latest_xlsx(output_dir))
    log_text = (result_dir / name / "command.log").read_text(encoding="utf-8") if (result_dir / name / "command.log").exists() else ""
    report = {
        "name": name,
        "count": count,
        "run": run,
        "validation": validation,
        "passed": bool(
            run["returncode"] == 0
            and validation.get("sheet_count") == 6
            and validation.get("fixed_26_headers")
            and not validation.get("known_bad_disease_hits")
            and not validation.get("generic_disease_hits")
            and "429" not in log_text
        ),
    }
    write_json(result_dir / name / "report.json", report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="运行真实数据库 3 条 smoke 测试")
    parser.add_argument("--result-dir", required=True)
    parser.add_argument("--config", default="logs/real_db_20/db_config.runtime.yml")
    parser.add_argument("--selected-ids-file", default="logs/real_db_20/selected_ids.txt")
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--with-ocr", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = run_real_db_case(args.count, Path(args.result_dir), "real_db_smoke", args.config, args.selected_ids_file, no_ocr=not args.with_ocr)
    print(f"passed={report['passed']}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
