import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_real_db_smoke import run_real_db_case


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="运行真实数据库 20 条测试")
    parser.add_argument("--result-dir", required=True)
    parser.add_argument("--config", default="logs/real_db_20/db_config.runtime.yml")
    parser.add_argument("--selected-ids-file", default="logs/real_db_20/selected_ids.txt")
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--with-ocr", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = run_real_db_case(args.count, Path(args.result_dir), "real_db_20", args.config, args.selected_ids_file, no_ocr=not args.with_ocr)
    print(f"passed={report['passed']}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
