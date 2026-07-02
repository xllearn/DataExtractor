import logging
import sys
from pathlib import Path
from typing import Any, Dict, List

from config import LlmConfigError, apply_llm_config, build_arg_parser, load_settings
from config_loader import ConfigError, load_db_config, parse_selected_ids, validate_db_config_ready
from db import fetch_records
from db_reader import DbReaderError, fetch_configured_records
from excel_writer import build_merge_output_path, build_single_output_path, write_extraction_workbook
from field_mapping import FieldMappingError, load_field_mapping
from image_ocr import get_ocr_status
from input_xlsx import read_records_from_xlsx
from keyword_utils import expand_keyword_groups
from llm_client import LLMClient
from pipeline import create_empty_metadata, extract_record_rows
from run_summary import RunSummary
from runtime import (
    external_ocr_for_record,
    load_external_ocr_inputs,
    resolve_effective_limit,
    resolve_input_path,
    resolve_runtime_flags,
    resolve_runtime_paths,
    setup_logging,
    should_stop_processing,
    validate_keyword_supported,
    validate_strict_runtime_config,
)
from security_utils import mask_sensitive_text
from table_extractor import load_table_mapping
from utils import today_yyyymmdd
from vision_client import create_vision_client


def _append_failure(logs_dir: Path, summary: RunSummary, payload: Dict[str, Any]) -> Dict[str, Any]:
    return summary.record_failure(payload)


_empty_metadata = create_empty_metadata


def _metadata_flags(record_metadata: Dict[str, List[Dict[str, Any]]]) -> Dict[str, bool]:
    logs = record_metadata.get("collection_logs", [])
    return {
        "manual_review": any(bool(item.get("need_manual_review")) for item in logs),
        "ocr_triggered": any(bool(item.get("ocr_triggered")) for item in logs),
        "ocr_failed": any(int(item.get("ocr_failure_count") or 0) > 0 for item in logs),
        "llm_parse_failed": any(item.get("llm_parse_success") is False for item in logs),
    }


def _write_summary(summary: RunSummary, logger: logging.Logger | None = None) -> None:
    try:
        payload = summary.write_artifacts()
        if logger:
            logger.info("运行摘要已写入: %s", summary.log_dir / "summary.json")
            logger.info("运行摘要: %s", payload)
    except Exception as exc:
        if logger:
            logger.error("运行摘要写入失败: %s", mask_sensitive_text(str(exc)))


def main() -> int:
    settings = load_settings()
    parser = build_arg_parser(settings)
    args = parser.parse_args()

    logs_dir, output_dir, temp_images_dir, template_path = resolve_runtime_paths(args.output_dir, args.log_dir)
    today = today_yyyymmdd()

    logger = setup_logging(logs_dir, args.debug)
    logger.info("程序启动参数: %s", vars(args))
    summary = RunSummary(input_mode="", total_records=0, log_dir=logs_dir)

    try:
        settings = apply_llm_config(settings, args.llm_config)
    except LlmConfigError as exc:
        logger.error("LLM 配置错误: %s", exc)
        _append_failure(logs_dir, summary, {"phase": "llm_config", "error": str(exc)})
        _write_summary(summary, logger)
        return 1

    try:
        vision_client = create_vision_client(args.llm_config)
        if vision_client is not None and vision_client.is_ready():
            logger.info("vision 模型配置可用: model=%s", vision_client.model)
        elif vision_client is not None:
            logger.info("vision 模型已启用但配置不完整，将跳过 vision 识别")
    except Exception as exc:
        logger.error("vision 配置读取失败: %s", mask_sensitive_text(str(exc)))
        vision_client = None

    runtime_flags = resolve_runtime_flags(args.dry_run, args.no_llm, args.no_ocr, args.no_excel)
    ocr_status = get_ocr_status()
    ocr_skipped_reason = ""
    if runtime_flags["no_ocr"]:
        ocr_skipped_reason = "用户选择跳过 OCR"
    elif not settings.ocr_enabled:
        ocr_skipped_reason = "配置关闭 OCR"
    elif not ocr_status.get("available"):
        ocr_skipped_reason = "OCR依赖不可用"

    try:
        external_ocr_text, external_ocr_mapping = load_external_ocr_inputs(args.ocr_text_file, args.ocr_json_file)
    except Exception as exc:
        masked_error = mask_sensitive_text(str(exc))
        logger.error("外部 OCR 文本读取失败: %s", masked_error)
        _append_failure(logs_dir, summary, {"phase": "external_ocr", "error": masked_error})
        _write_summary(summary, logger)
        return 1

    try:
        field_mapping = load_field_mapping(args.field_config)
        logger.info("字段配置加载完成: headers=%s", len(field_mapping.headers))
    except FieldMappingError as exc:
        logger.error("字段配置错误: %s", exc)
        _append_failure(logs_dir, summary, {"phase": "field_config", "error": str(exc)})
        _write_summary(summary, logger)
        return 1
    table_mapping = load_table_mapping(args.table_config)

    try:
        if args.input_xlsx:
            input_mode = "input-xlsx"
            input_path = resolve_input_path(args.input_xlsx)
            logger.info("当前输入模式: input-xlsx, path=%s", input_path)
            if args.keyword:
                logger.info("input-xlsx 模式忽略数据库关键词检索: keyword=%s", args.keyword)
            effective_limit = resolve_effective_limit(args.limit, settings, configured_db_enabled=False)
            records = read_records_from_xlsx(input_path, limit=effective_limit, offset=args.offset)
        else:
            selected_ids = parse_selected_ids(args.selected_ids)
            db_config = load_db_config(args.config)
            if args.strict_config:
                validate_strict_runtime_config(db_config, args.input_xlsx)
            explicit_config = "--config" in sys.argv
            keyword_groups = expand_keyword_groups(args.keyword)
            keyword_mode = args.keyword_mode or db_config.query.keyword_mode
            if keyword_mode not in {"or", "and"}:
                raise ConfigError("--keyword-mode 只能是 or 或 and")

            if selected_ids and keyword_groups:
                logger.info("--selected-ids 优先于 --keyword，已忽略关键词检索")

            if db_config.use_configured_reader:
                input_mode = "configured-db"
                validate_db_config_ready(db_config)
                effective_limit = resolve_effective_limit(args.limit, settings, db_config, configured_db_enabled=True)
                logger.info("当前输入模式: configured-db, table=%s", db_config.source.table)
                logger.info("有效 limit: %s", effective_limit)
                logger.info(
                    "关键词检索: enabled=%s raw=%s mode=%s groups=%s",
                    bool(keyword_groups and not selected_ids),
                    args.keyword,
                    keyword_mode,
                    keyword_groups if keyword_groups and not selected_ids else [],
                )
                records = fetch_configured_records(
                    db_config,
                    limit=effective_limit,
                    offset=args.offset,
                    selected_ids=selected_ids,
                    keyword_groups=[] if selected_ids else keyword_groups,
                    keyword_mode=keyword_mode,
                )
                logger.info("配置化数据库实际检索记录数: %s", len(records))
            elif explicit_config and db_config.exists:
                input_mode = "configured-db"
                validate_db_config_ready(db_config)
                records = []
            else:
                input_mode = "legacy-db"
                validate_keyword_supported(args.keyword, configured_db_enabled=False)
                effective_limit = resolve_effective_limit(args.limit, settings, configured_db_enabled=False)
                logger.info("当前输入模式: MySQL, table=%s", settings.db_table)
                records = fetch_records(settings, limit=effective_limit, offset=args.offset, where=args.where)
        logger.info("读取到记录数: %s", len(records))
    except (ConfigError, DbReaderError, Exception) as exc:
        masked_error = mask_sensitive_text(str(exc))
        logger.error("读取输入失败: %s", masked_error)
        _append_failure(logs_dir, summary, {"phase": "read_input", "error": masked_error})
        _write_summary(summary, logger)
        return 1

    summary.update_input(input_mode, len(records))
    llm_client = None if runtime_flags["no_llm"] else LLMClient(settings)
    ocr_enabled = settings.ocr_enabled and not runtime_flags["no_ocr"] and bool(ocr_status.get("available"))
    all_rows: List[Dict[str, Any]] = []
    all_metadata = create_empty_metadata()
    output_paths: List[Path] = []
    record_error_count = 0

    for index, record in enumerate(records, start=1):
        try:
            logger.info("当前处理第 %s 条 / %s", index, len(records))
            logger.info("Title: %s", record.get("Title"))
            logger.info("SourceURL: %s", record.get("SourceURL"))

            record_metadata = create_empty_metadata()
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
                field_mapping=field_mapping,
                llm_format=args.llm_format,
                table_mapping=table_mapping,
                no_llm=runtime_flags["no_llm"],
                input_mode=input_mode,
                prompt_version=args.prompt_version,
                save_intermediate=args.save_intermediate,
                metadata=record_metadata,
                external_ocr_text=external_ocr_for_record(record, external_ocr_text, external_ocr_mapping),
                ocr_status=ocr_status,
                ocr_skipped_reason=ocr_skipped_reason,
                vision_client=vision_client,
                run_id=summary.run_id,
            )

            for failed_payload in record_metadata.get("failed_records", []):
                summary.record_failure(failed_payload, count_record_failure=False)

            if args.mode == "single" and not runtime_flags["no_excel"]:
                output_path = build_single_output_path(record, output_dir, args.offset + index)
                try:
                    write_extraction_workbook(
                        rows,
                        output_path,
                        template_path,
                        field_mapping,
                        collection_logs=record_metadata["collection_logs"],
                        field_evidence=record_metadata["field_evidence"],
                        conflict_evidence=record_metadata["conflict_evidence"],
                        extract_evaluations=record_metadata["extract_evaluations"],
                        failed_records=record_metadata["failed_records"],
                        field_confidence=record_metadata["field_confidence"],
                        review_rows=record_metadata["review_rows"],
                        row_match_evidence=record_metadata["row_match_evidence"],
                    )
                except Exception as exc:
                    masked_error = mask_sensitive_text(str(exc))
                    logger.error("Excel 写入失败: %s", masked_error)
                    _append_failure(
                        logs_dir,
                        summary,
                        {
                            "phase": "excel_write",
                            "record_index": index,
                            "source_id": record.get("_source_id"),
                            "info_id": record.get("info_id"),
                            "Title": record.get("Title"),
                            "SourceURL": record.get("SourceURL"),
                            "error": masked_error,
                        },
                    )
                    _write_summary(summary, logger)
                    return 1
                logger.info("Excel 输出路径: %s", output_path)
                output_paths.append(output_path)
                summary.add_output_path(output_path)
            else:
                all_rows.extend(rows)
                for key in all_metadata:
                    all_metadata[key].extend(record_metadata[key])

            summary.record_success(output_rows=len(rows), **_metadata_flags(record_metadata))
        except Exception as exc:
            record_error_count += 1
            masked_error = mask_sensitive_text(str(exc))
            logger.error("单条记录处理失败: %s", masked_error)
            failed_payload = {
                "phase": "process_record",
                "record_index": index,
                "source_id": record.get("_source_id"),
                "info_id": record.get("info_id"),
                "Title": record.get("Title"),
                "SourceURL": record.get("SourceURL"),
                "error": masked_error,
            }
            safe_failed = _append_failure(logs_dir, summary, failed_payload)
            all_metadata["failed_records"].append(safe_failed)
            all_metadata["collection_logs"].append(
                {
                    "source_id": record.get("_source_id"),
                    "info_id": record.get("info_id"),
                    "title": record.get("Title"),
                    "source_url": record.get("SourceURL"),
                    "status": "failed",
                    "attempt": "",
                    "input_mode": input_mode,
                    "llm_format": "none" if runtime_flags["no_llm"] else args.llm_format,
                    "error": masked_error,
                }
            )
            if should_stop_processing(record_error_count, args.max_record_errors, args.fail_fast):
                logger.error("单条记录失败数达到阈值，停止后续处理: errors=%s max=%s fail_fast=%s", record_error_count, args.max_record_errors, args.fail_fast)
                break
            continue

    if args.mode == "merge" and not runtime_flags["no_excel"]:
        output_path = build_merge_output_path(output_dir)
        try:
            write_extraction_workbook(
                all_rows,
                output_path,
                template_path,
                field_mapping,
                collection_logs=all_metadata["collection_logs"],
                field_evidence=all_metadata["field_evidence"],
                conflict_evidence=all_metadata["conflict_evidence"],
                extract_evaluations=all_metadata["extract_evaluations"],
                failed_records=all_metadata["failed_records"],
                field_confidence=all_metadata["field_confidence"],
                review_rows=all_metadata["review_rows"],
                row_match_evidence=all_metadata["row_match_evidence"],
            )
        except Exception as exc:
            masked_error = mask_sensitive_text(str(exc))
            logger.error("Excel 写入失败: %s", masked_error)
            _append_failure(logs_dir, summary, {"phase": "excel_write", "error": masked_error})
            _write_summary(summary, logger)
            return 1
        logger.info("Excel 输出路径: %s", output_path)
        output_paths.append(output_path)
        summary.add_output_path(output_path)

    _write_summary(summary, logger)
    logger.info("任务结束，输出文件数: %s, 单条失败数: %s", len(output_paths), record_error_count)
    for path in output_paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
