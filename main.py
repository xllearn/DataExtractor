import logging
import sys
from pathlib import Path
from typing import Any, Dict, List

from config import PROJECT_ROOT, build_arg_parser, load_settings
from confidence import evaluate_rows, mark_ocr_failed
from db import fetch_records
from excel_writer import build_merge_output_path, build_single_output_path, write_rows_to_workbook
from html_parser import parse_html_content
from image_ocr import process_image_ocr
from input_xlsx import read_records_from_xlsx
from json_utils import normalize_llm_rows
from llm_client import LLMClient
from prompts import build_extract_prompt
from utils import append_jsonl, ensure_dir, today_yyyymmdd


def resolve_input_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    candidates = [Path.cwd() / path, PROJECT_ROOT / path, PROJECT_ROOT.parent / path]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return PROJECT_ROOT / path


def setup_logging(logs_dir: Path, debug: bool = False) -> logging.Logger:
    ensure_dir(logs_dir)
    logger = logging.getLogger("db_to_excel_extractor")
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    file_handler = logging.FileHandler(logs_dir / "run.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.addHandler(console_handler)
    return logger


def extract_record_rows(
    record: Dict[str, Any],
    record_index: int,
    llm_client: LLMClient,
    logs_dir: Path,
    temp_images_dir: Path,
    today: str,
    image_base_url: str,
    ocr_enabled: bool,
    debug: bool,
    logger: logging.Logger | None,
    ocr_func=process_image_ocr,
) -> List[Dict[str, Any]]:
    logger = logger or logging.getLogger("db_to_excel_extractor")
    parsed = parse_html_content(record.get("Content"), image_base_url, logger)
    logger.info("图片数量: %s", len(parsed.image_urls))
    logger.info("首轮抽取不启用OCR")

    initial_rows = extract_once(
        record=record,
        record_index=record_index,
        llm_client=llm_client,
        logs_dir=logs_dir,
        today=today,
        clean_text=parsed.clean_text,
        tables_text=parsed.tables_text,
        image_ocr_text="",
        image_count=len(parsed.image_urls),
        attempt="initial",
        debug=debug,
        logger=logger,
    )
    initial_evals = evaluate_rows(
        initial_rows,
        record,
        parsed.clean_text,
        parsed.tables_text,
        "",
        image_count=len(parsed.image_urls),
        ocr_attempted=False,
    )
    log_eval_entries(initial_evals, logs_dir, record_index, record, "initial", debug, logger)

    retry_eval = min(initial_evals, key=lambda item: item["confidence_score"]) if initial_evals else None
    should_retry = bool(retry_eval and retry_eval["should_retry_with_ocr"] and ocr_enabled and parsed.image_urls)
    if not should_retry:
        if retry_eval and retry_eval["should_retry_with_ocr"] and not ocr_enabled:
            logger.info("置信度建议OCR重跑，但OCR已关闭")
        return initial_rows

    logger.info("低置信度触发OCR重跑: %s", retry_eval["ocr_trigger_reason"])
    ocr_summary = ocr_func(
        parsed.image_urls,
        temp_images_dir,
        record_index=record_index,
        enabled=True,
        logger=logger,
    )
    logger.info("OCR 成功数量: %s", ocr_summary.success_count)
    logger.info("OCR 失败数量: %s", ocr_summary.failure_count)

    if ocr_summary.failure_count > 0 and ocr_summary.success_count == 0:
        failed_evals = mark_ocr_failed(initial_evals, f"成功0张，失败{ocr_summary.failure_count}张")
        log_eval_entries(failed_evals, logs_dir, record_index, record, "ocr_failed", debug, logger)
        return initial_rows

    retry_rows = extract_once(
        record=record,
        record_index=record_index,
        llm_client=llm_client,
        logs_dir=logs_dir,
        today=today,
        clean_text=parsed.clean_text,
        tables_text=parsed.tables_text,
        image_ocr_text=ocr_summary.text,
        image_count=len(parsed.image_urls),
        attempt="ocr_retry",
        debug=debug,
        logger=logger,
    )
    retry_evals = evaluate_rows(
        retry_rows,
        record,
        parsed.clean_text,
        parsed.tables_text,
        ocr_summary.text,
        image_count=len(parsed.image_urls),
        ocr_attempted=True,
    )
    log_eval_entries(retry_evals, logs_dir, record_index, record, "ocr_retry", debug, logger)
    return retry_rows


def extract_once(
    record: Dict[str, Any],
    record_index: int,
    llm_client: LLMClient,
    logs_dir: Path,
    today: str,
    clean_text: str,
    tables_text: str,
    image_ocr_text: str,
    image_count: int,
    attempt: str,
    debug: bool,
    logger: logging.Logger,
) -> List[Dict[str, Any]]:
    prompt = build_extract_prompt(record, clean_text, tables_text, image_ocr_text, today)
    try:
        raw_output = llm_client.extract(prompt)
        logger.info("大模型调用是否成功: true, attempt=%s", attempt)
    except Exception as llm_exc:
        raw_output = "[]"
        logger.exception("大模型调用是否成功: false, attempt=%s, error=%s", attempt, llm_exc)
        append_jsonl(
            logs_dir / "failed_records.jsonl",
            {
                "phase": "llm",
                "attempt": attempt,
                "record_index": record_index,
                "Title": record.get("Title"),
                "SourceURL": record.get("SourceURL"),
                "error": str(llm_exc),
            },
        )

    rows = normalize_llm_rows(raw_output, record, today, logs_dir)
    logger.info("模型返回行数: %s, attempt=%s", len(rows), attempt)
    if debug:
        logger.debug("抽取上下文: attempt=%s image_count=%s ocr_text_length=%s", attempt, image_count, len(image_ocr_text or ""))
    return rows


def log_eval_entries(
    evaluations: List[Dict[str, Any]],
    logs_dir: Path,
    record_index: int,
    record: Dict[str, Any],
    attempt: str,
    debug: bool,
    logger: logging.Logger,
) -> None:
    for row_index, evaluation in enumerate(evaluations, start=1):
        payload = {
            "record_index": record_index,
            "row_index": row_index,
            "attempt": attempt,
            "Title": record.get("Title"),
            "SourceURL": record.get("SourceURL"),
            **evaluation,
        }
        append_jsonl(logs_dir / "extract_eval.jsonl", payload)
        logger.info(
            "抽取置信度: attempt=%s row=%s score=%s level=%s retry=%s",
            attempt,
            row_index,
            evaluation["confidence_score"],
            evaluation["confidence_level"],
            evaluation["should_retry_with_ocr"],
        )
        if debug:
            logger.debug("抽取评估详情: %s", payload)


def main() -> int:
    settings = load_settings()
    parser = build_arg_parser(settings)
    args = parser.parse_args()

    logs_dir = PROJECT_ROOT / "logs"
    temp_images_dir = PROJECT_ROOT / "temp_images"
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = PROJECT_ROOT / output_dir
    template_path = PROJECT_ROOT / "templates" / "template.xlsx"
    today = today_yyyymmdd()

    logger = setup_logging(logs_dir, args.debug)
    logger.info("程序启动参数: %s", vars(args))

    try:
        if args.input_xlsx:
            input_path = resolve_input_path(args.input_xlsx)
            logger.info("当前输入模式: input-xlsx, path=%s", input_path)
            records = read_records_from_xlsx(input_path, limit=args.limit, offset=args.offset)
        else:
            logger.info("当前输入模式: MySQL, table=%s", settings.db_table)
            records = fetch_records(settings, limit=args.limit, offset=args.offset, where=args.where)
        logger.info("读取到记录数: %s", len(records))
    except Exception as exc:
        logger.exception("读取输入失败: %s", exc)
        append_jsonl(logs_dir / "failed_records.jsonl", {"phase": "read_input", "error": str(exc)})
        return 1

    llm_client = LLMClient(settings)
    ocr_enabled = settings.ocr_enabled and not args.no_ocr
    all_rows: List[Dict[str, Any]] = []
    output_paths: List[Path] = []

    for index, record in enumerate(records, start=1):
        try:
            logger.info("当前处理第 %s 条 / %s", index, len(records))
            logger.info("Title: %s", record.get("Title"))
            logger.info("SourceURL: %s", record.get("SourceURL"))

            rows = extract_record_rows(
                record=record,
                record_index=args.offset + index,
                llm_client=llm_client,
                logs_dir=logs_dir,
                temp_images_dir=temp_images_dir,
                today=today,
                image_base_url=settings.image_base_url,
                ocr_enabled=ocr_enabled,
                debug=args.debug,
                logger=logger,
            )

            if args.mode == "single":
                output_path = build_single_output_path(record, output_dir, args.offset + index)
                write_rows_to_workbook(rows, output_path, template_path)
                logger.info("Excel 输出路径: %s", output_path)
                output_paths.append(output_path)
            else:
                all_rows.extend(rows)
        except Exception as exc:
            logger.exception("单条记录处理失败: %s", exc)
            append_jsonl(
                logs_dir / "failed_records.jsonl",
                {
                    "phase": "process_record",
                    "record_index": index,
                    "Title": record.get("Title"),
                    "SourceURL": record.get("SourceURL"),
                    "error": str(exc),
                },
            )
            continue

    if args.mode == "merge":
        output_path = build_merge_output_path(output_dir)
        write_rows_to_workbook(all_rows, output_path, template_path)
        logger.info("Excel 输出路径: %s", output_path)
        output_paths.append(output_path)

    logger.info("任务结束，输出文件数: %s", len(output_paths))
    for path in output_paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
