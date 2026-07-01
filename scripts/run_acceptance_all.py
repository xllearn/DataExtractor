import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_image_import_test import run_image_import_test
from scripts.run_real_db_smoke import run_real_db_case
from scripts.test_result_utils import desktop_result_dir, python_executable, run_command, write_json


def _run_step(name: str, command: list[str], result_dir: Path, timeout: int = 1800) -> dict:
    run = run_command(command, PROJECT_ROOT, result_dir / "commands" / f"{name}.log", timeout=timeout)
    return {"name": name, "returncode": run["returncode"], "passed": run["returncode"] == 0, "log_path": run["log_path"]}


def _write_markdown(result_dir: Path, report: dict) -> Path:
    path = result_dir / "ACCEPTANCE_STAGE_13_15.md"
    lines = [
        "# DataExtractor Stage 13-15 Acceptance",
        "",
        f"- result_dir: `{result_dir}`",
        f"- overall_passed: `{report['overall_passed']}`",
        "",
        "## Commands",
    ]
    for item in report["commands"]:
        lines.append(f"- {item['name']}: passed={item['passed']}, returncode={item['returncode']}, log={item['log_path']}")
    image_import = report["image_import"]
    lines.extend(
        [
            "",
            "## AI Generated Data",
            f"- passed: `{report['ai_generated']['passed']}`",
            "",
            "## Real Database",
            f"- smoke passed: `{report['real_db_smoke']['passed']}`",
            f"- 20 rows passed: `{report['real_db_20']['passed']}`",
            "",
            "## Image Import",
            f"- passed: `{image_import.get('passed')}`",
            f"- skipped: `{image_import.get('skipped', False)}`",
            f"- reason: `{image_import.get('reason', '')}`",
            f"- overall_similarity: `{image_import.get('compare', {}).get('overall_similarity', 0)}`",
            f"- core_field_similarity: `{image_import.get('compare', {}).get('core_field_similarity', 0)}`",
            "",
            "## Frontend API",
            "- Covered by `tests.test_api_server` in unittest/pytest.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _skipped_image_import(reason: str) -> dict:
    return {"passed": True, "skipped": True, "reason": reason, "compare": {"overall_similarity": 0, "core_field_similarity": 0}}


def run_acceptance(
    result_dir: Path,
    skip_real_db: bool = False,
    skip_image_import: bool = False,
    image: str = "",
    manual_excel: str = "",
    image_import_table: str = "image_import_articles",
) -> dict:
    result_dir.mkdir(parents=True, exist_ok=True)
    compile_exclude = r"(^|[\\/])(\.git|\.pytest_cache|\.venv|\.venv_ocr|__pycache__|logs|outputs|temp_images|db_to_excel_extractor|tmp_ai_debug)([\\/]|$)"
    commands = [
        _run_step("unittest", [python_executable(), "-m", "unittest", "discover", "-s", "tests", "-v"], result_dir, timeout=1800),
        _run_step("pytest", [python_executable(), "-m", "pytest", "-q"], result_dir, timeout=1800),
        _run_step("compileall", [python_executable(), "-m", "compileall", "-x", compile_exclude, "."], result_dir, timeout=1800),
        _run_step("ai_generated", [python_executable(), "-m", "unittest", "tests.test_ai_generated_cases", "-v"], result_dir, timeout=900),
        _run_step("api_server", [python_executable(), "-m", "unittest", "tests.test_api_server", "-v"], result_dir, timeout=900),
    ]
    real_smoke = {"passed": False, "skipped": True}
    real_20 = {"passed": False, "skipped": True}
    if not skip_real_db:
        real_smoke = run_real_db_case(3, result_dir, "real_db_smoke", "logs/real_db_20/db_config.runtime.yml", "logs/real_db_20/selected_ids.txt", no_ocr=True)
        real_20 = run_real_db_case(20, result_dir, "real_db_20", "logs/real_db_20/db_config.runtime.yml", "logs/real_db_20/selected_ids.txt", no_ocr=True)
    image_import = _skipped_image_import("skip_image_import enabled")
    if not skip_image_import:
        if not image or not manual_excel:
            image_import = _skipped_image_import("image/manual_excel not provided")
        elif not Path(image).exists() or not Path(manual_excel).exists():
            image_import = _skipped_image_import("image or manual_excel file not found")
        else:
            image_import = run_image_import_test(result_dir, image, manual_excel, image_import_table, "")
    report = {
        "result_dir": str(result_dir),
        "commands": commands,
        "ai_generated": commands[3],
        "real_db_smoke": real_smoke,
        "real_db_20": real_20,
        "image_import": image_import,
    }
    report["overall_passed"] = all(item["passed"] for item in commands) and real_smoke.get("passed") and real_20.get("passed") and image_import.get("passed")
    write_json(result_dir / "acceptance_stage_13_15.json", report)
    markdown = _write_markdown(result_dir, report)
    report["markdown_report"] = str(markdown)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="运行阶段 13-15 综合验收")
    parser.add_argument("--result-dir", default="")
    parser.add_argument("--skip-real-db", action="store_true")
    parser.add_argument("--skip-image-import", action="store_true")
    parser.add_argument("--image", default="")
    parser.add_argument("--manual-excel", default="")
    parser.add_argument("--image-import-table", default="image_import_articles")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result_dir = Path(args.result_dir) if args.result_dir else desktop_result_dir()
    report = run_acceptance(
        result_dir,
        skip_real_db=args.skip_real_db,
        skip_image_import=args.skip_image_import,
        image=args.image,
        manual_excel=args.manual_excel,
        image_import_table=args.image_import_table,
    )
    print(json.dumps({"result_dir": report["result_dir"], "overall_passed": report["overall_passed"]}, ensure_ascii=False))
    return 0 if report["overall_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
