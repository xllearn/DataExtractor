import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import PROJECT_ROOT
from config_loader import load_db_config
from excel_compare import compare_excel_files
from image_data_loader import load_image_records
from scripts.import_image_data_to_db import import_records_to_db
from scripts.test_result_utils import latest_xlsx, python_executable, run_command, validate_output_workbook, write_json


def _write_runtime_config(path: Path, table: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""database:
  url: "${{DATABASE_URL}}"

source:
  table: "{table}"
  id_column: "SourceURL"
  info_id_column: "SourceURL"
  title_column: "Title"
  html_column: "Content"
  text_column: ""
  article_time_column: ""
  audit_time_column: "AuditTime"
  region_column: "areaname"
  source_url_column: "SourceURL"
  related_info_column: ""
  insurance_type_column: "insurancetypename"

query:
  default_limit: 20
  keyword_mode: "or"

direct_field_columns:
  info_id: "info_id"
  地区名称: "areaname"
  保险类型: "insurancetypename"
""",
        encoding="utf-8",
    )
    return path


def run_image_import_test(result_dir: Path, image: str, manual: str, table: str, batch_id: str) -> dict:
    parsed_json = result_dir / "image_import" / "parsed_image_data.json"
    records = load_image_records(image, transcript_path=manual, output_json=parsed_json, batch_id=batch_id)
    db_config = load_db_config("config/db_config.yml")
    database_url = os.environ.get("DATABASE_URL") or db_config.database_url
    import_dry_run = import_records_to_db(database_url, table, records, dry_run=True, create_table=True)
    import_result = import_records_to_db(database_url, table, records, dry_run=False, create_table=True)
    runtime_config = _write_runtime_config(result_dir / "image_import" / "db_config.image_import.yml", table)
    output_dir = result_dir / "image_import" / "outputs"
    log_dir = result_dir / "image_import" / "logs"
    selected_ids = ",".join(record["SourceURL"] for record in records)
    command = [
        python_executable(),
        str(PROJECT_ROOT / "main.py"),
        "--config",
        str(runtime_config),
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
        "--output-dir",
        str(output_dir),
        "--log-dir",
        str(log_dir),
        "--save-intermediate",
        "--no-ocr",
        "--no-llm",
    ]
    run = run_command(command, PROJECT_ROOT, result_dir / "image_import" / "extract_command.log", timeout=900)
    validation = {}
    compare = {}
    generated = None
    if run["returncode"] == 0:
        generated = latest_xlsx(output_dir)
        validation = validate_output_workbook(generated)
        compare = compare_excel_files(
            generated,
            manual,
            output_xlsx=result_dir / "image_import" / "image_import_compare_report.xlsx",
            output_json=result_dir / "image_import" / "image_import_compare_report.json",
        )
    passed = bool(
        len(records) > 0
        and import_result.get("inserted_count") == len(records)
        and run["returncode"] == 0
        and validation.get("sheet_count") == 6
        and validation.get("fixed_26_headers")
        and compare.get("overall_similarity", 0) >= 0.85
        and compare.get("core_field_similarity", 0) >= 0.90
    )
    report = {
        "parsed_json": str(parsed_json),
        "record_count": len(records),
        "dry_run": import_dry_run,
        "import": import_result,
        "extract_run": run,
        "generated_excel": str(generated) if generated else "",
        "validation": validation,
        "compare": {
            "overall_similarity": compare.get("overall_similarity", 0),
            "core_field_similarity": compare.get("core_field_similarity", 0),
            "report_xlsx": str(result_dir / "image_import" / "image_import_compare_report.xlsx"),
            "report_json": str(result_dir / "image_import" / "image_import_compare_report.json"),
        },
        "passed": passed,
    }
    write_json(result_dir / "image_import" / "report.json", report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="运行图片导入、入库、抽取和人工 Excel 对比测试")
    parser.add_argument("--result-dir", required=True)
    parser.add_argument("--image", default="samples/db/陕西西安.jpeg")
    parser.add_argument("--manual", default="samples/manual/陕西西安.xlsx")
    parser.add_argument("--target-table", default="image_import_articles")
    parser.add_argument("--batch-id", default="")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    batch_id = args.batch_id or f"image_import_{__import__('datetime').datetime.now().strftime('%Y%m%d_%H%M%S')}"
    report = run_image_import_test(Path(args.result_dir), args.image, args.manual, args.target_table, batch_id)
    print(f"overall_similarity={report['compare']['overall_similarity']:.6f}")
    print(f"core_field_similarity={report['compare']['core_field_similarity']:.6f}")
    print(f"passed={report['passed']}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
