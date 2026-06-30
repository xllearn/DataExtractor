import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from excel_compare import compare_excel_files
from scripts.test_result_utils import write_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="对比真实数据生成 Excel 与人工 Excel")
    parser.add_argument("--generated", required=True)
    parser.add_argument("--manual", required=True)
    parser.add_argument("--output-xlsx", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--overall-threshold", type=float, default=0.85)
    parser.add_argument("--core-threshold", type=float, default=0.90)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = compare_excel_files(args.generated, args.manual, output_xlsx=args.output_xlsx, output_json=args.output_json)
    result["passed"] = result["overall_similarity"] >= args.overall_threshold and result["core_field_similarity"] >= args.core_threshold
    write_json(Path(args.output_json), result)
    print(f"overall_similarity={result['overall_similarity']:.6f}")
    print(f"core_field_similarity={result['core_field_similarity']:.6f}")
    print(f"passed={result['passed']}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
