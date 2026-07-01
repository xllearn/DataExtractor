import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from config import PROJECT_ROOT, LlmConfigError, apply_llm_config, build_arg_parser, load_settings
from config_loader import ConfigError, load_db_config, parse_selected_ids, validate_db_config_ready
from confidence import IMAGE_TABLE_RISK_MESSAGE, evaluate_rows, mark_ocr_failed
from db import fetch_records
from db_reader import DbReaderError, fetch_configured_records
from excel_writer import build_merge_output_path, build_single_output_path, write_extraction_workbook
from field_mapping import FieldMapping, FieldMappingError, load_field_mapping
from html_parser import parse_html_content
from image_ocr import get_ocr_status, process_image_ocr
from input_xlsx import read_records_from_xlsx
from json_utils import normalize_llm_rows
from keyword_utils import expand_keyword_groups
from llm_extractor import LlmExtractionResult, extract_with_llm, llm_result_to_field_evidence
from llm_client import LLMClient
from prompts import build_extract_prompt
from prompts_v2 import build_extract_prompt_v2
from record_fusion import fuse_record_sources
from rule_extractor import extract_key_value_records
from security_utils import mask_sensitive_text
from table_extractor import extract_table_records, load_table_mapping
from utils import append_jsonl, ensure_dir, today_yyyymmdd


def resolve_effective_limit(args_limit: int | None, settings, db_config=None, configured_db_enabled: bool = False) -> int:
    if args_limit is not None:
        return int(args_limit)
    if configured_db_enabled and db_config is not None:
        return int(db_config.query.default_limit)
    return int(settings.default_limit)


def validate_keyword_supported(keyword: str, configured_db_enabled: bool) -> None:
    if keyword and not configured_db_enabled:
        raise ValueError("--keyword 需要启用 config/db_config.yml 配置化数据库读取；旧 db.py 模式暂不支持关键词检索")


def resolve_runtime_flags(dry_run: bool, no_llm: bool, no_ocr: bool, no_excel: bool) -> Dict[str, bool]:
    return {
        "no_llm": bool(no_llm or dry_run),
        "no_ocr": bool(no_ocr or dry_run or no_llm),
        "no_excel": bool(no_excel or dry_run),
    }


def should_stop_processing(record_error_count: int, max_record_errors: int, fail_fast: bool) -> bool:
    if fail_fast and record_error_count > 0:
        return True
    return record_error_count >= max_record_errors


def validate_strict_runtime_config(db_config, input_xlsx: str) -> None:
    if input_xlsx:
        return
    if not db_config.exists or not db_config.database_url:
        raise ValueError("strict-config 模式要求配置 DATABASE_URL，且不能回退旧 db.py 流程")
    validate_db_config_ready(db_config)


def save_intermediate_result(logs_dir: Path, record_index: int, source_id: str, info_id: str, payload: Dict[str, Any]) -> Path:
    intermediate_dir = ensure_dir(logs_dir / "intermediate")
    safe_id = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in (info_id or source_id or str(record_index)))[:60]
    path = intermediate_dir / f"{record_index:04d}_{safe_id or 'record'}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, default=str, indent=2), encoding="utf-8")
    return path


def log_rule_result(result, logs_dir: Path, record_index: int, rule_phase: str, logger: logging.Logger) -> None:
    for error in result.errors:
        append_jsonl(logs_dir / "rule_extract_errors.jsonl", {"record_index": record_index, "rule_phase": rule_phase, **error})
    logger.info("%s 抽取记录数: %s, evidence=%s, errors=%s", rule_phase, len(result.records), len(result.field_evidence), len(result.errors))


def _with_context(items: List[Dict[str, Any]], record_index: int, attempt: str) -> List[Dict[str, Any]]:
    return [{**item, "record_index": record_index, "attempt": attempt} for item in items]


def _append_jsonl_many(path: Path, items: List[Dict[str, Any]]) -> None:
    for item in items:
        append_jsonl(path, item)


def _empty_metadata() -> Dict[str, List[Dict[str, Any]]]:
    return {
        "collection_logs": [],
        "field_evidence": [],
        "conflict_evidence": [],
        "extract_evaluations": [],
        "failed_records": [],
    }


def load_external_ocr_inputs(text_file: str = "", json_file: str = "") -> tuple[str, Dict[str, str]]:
    text = ""
    mapping: Dict[str, str] = {}
    if text_file:
        path = resolve_input_path(text_file)
        text = path.read_text(encoding="utf-8")
    if json_file:
        path = resolve_input_path(json_file)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("--ocr-json-file 必须是 JSON object")
        mapping = {str(key): str(value) for key, value in payload.items() if str(value).strip()}
    return text, mapping


def external_ocr_for_record(record: Dict[str, Any], global_text: str, mapping: Dict[str, str]) -> str:
    keys = [
        str(record.get("_source_id") or ""),
        str(record.get("SourceURL") or ""),
        str(record.get("info_id") or ""),
        str((record.get("_direct_fields") or {}).get("info_id") or ""),
    ]
    for key in keys:
        if key and key in mapping:
            return mapping[key]
    return global_text


def _score_from_evals(evaluations: List[Dict[str, Any]]) -> int:
    scores = [int(item.get("confidence_score", 0)) for item in evaluations]
    return min(scores) if scores else 0


def choose_final_attempt(initial_score: int, retry_score: int, retry_parse_error: str, retry_rows: List[Dict[str, Any]]) -> str:
    if retry_parse_error or not retry_rows:
        return "initial"
    if retry_score < initial_score - 5:
        return "initial"
    return "ocr_retry"


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
    field_mapping: FieldMapping | None = None,
    llm_format: str = "v2",
    table_mapping=None,
    no_llm: bool = False,
    input_mode: str = "",
    save_intermediate: bool = False,
    metadata: Dict[str, List[Dict[str, Any]]] | None = None,
    ocr_func=process_image_ocr,
    external_ocr_text: str = "",
    ocr_status: Dict[str, Any] | None = None,
    ocr_skipped_reason: str = "",
) -> List[Dict[str, Any]]:
    metadata = metadata if metadata is not None else _empty_metadata()
    field_mapping = field_mapping or load_field_mapping(None)
    logger = logger or logging.getLogger("db_to_excel_extractor")
    parsed = parse_html_content(record.get("Content"), image_base_url, logger)
    logger.info("图片数量: %s", len(parsed.image_urls))
    logger.info("首轮抽取不启用OCR")
    source_id = str(record.get("_source_id") or record.get("SourceURL") or record_index)
    info_id = str(record.get("info_id") or (record.get("_direct_fields") or {}).get("info_id") or "")
    ocr_status = ocr_status or get_ocr_status()
    external_ocr_text = str(external_ocr_text or "").strip()
    external_ocr_used = bool(external_ocr_text)
    external_ocr_evidence = []
    if external_ocr_used:
        external_ocr_evidence.append(
            {
                "source_id": source_id,
                "info_id": info_id,
                "field": "备注",
                "value": external_ocr_text[:300],
                "evidence": "external_ocr_text",
                "confidence": 0.7,
                "source": "external_ocr_text",
                "rule_name": "external_ocr_text",
            }
        )
    table_result = extract_table_records(record.get("Content") or "", parsed.tables_text, source_id=source_id, info_id=info_id, config=table_mapping, field_mapping=field_mapping)
    rule_text = "\n".join(part for part in [parsed.clean_text, external_ocr_text] if part)
    text_rule_result = extract_key_value_records(rule_text, source_id=source_id, info_id=info_id, field_mapping=field_mapping)
    log_rule_result(table_result, logs_dir, record_index, "table_rule", logger)
    log_rule_result(text_rule_result, logs_dir, record_index, "text_rule", logger)
    field_evidence = [*table_result.field_evidence, *text_rule_result.field_evidence, *external_ocr_evidence]

    initial_llm_result = extract_once_detail(
        record, record_index, llm_client, logs_dir, today, parsed.clean_text, parsed.tables_text, external_ocr_text, len(parsed.image_urls),
        "initial", debug, logger, field_mapping, llm_format, table_result.records, text_rule_result.records, field_evidence, no_llm=no_llm
    )
    initial_llm_evidence = llm_result_to_field_evidence(initial_llm_result, source_id, info_id, attempt="initial") if not no_llm else []
    initial_fusion = fuse_record_sources(
        record,
        table_result.records,
        text_rule_result.records,
        initial_llm_result.records,
        table_result.field_evidence,
        text_rule_result.field_evidence,
        initial_llm_evidence,
        field_mapping,
    )
    initial_rows = initial_fusion.records
    initial_field_evidence = _with_context([*initial_fusion.field_evidence, *external_ocr_evidence], record_index, "initial")
    initial_conflicts = _with_context(initial_fusion.conflict_evidence, record_index, "initial")
    _append_jsonl_many(logs_dir / "field_evidence.jsonl", initial_field_evidence)
    _append_jsonl_many(logs_dir / "rule_extract_errors.jsonl", _with_context([*table_result.errors, *text_rule_result.errors], record_index, "initial"))
    _append_jsonl_many(logs_dir / "conflict_evidence.jsonl", initial_conflicts)
    initial_evals = evaluate_rows(
        initial_rows,
        record,
        parsed.clean_text,
        parsed.tables_text,
        external_ocr_text,
        image_count=len(parsed.image_urls),
        ocr_attempted=external_ocr_used,
    )
    initial_eval_payloads = log_eval_entries(initial_evals, logs_dir, record_index, record, "initial", debug, logger)

    retry_eval = min(initial_evals, key=lambda item: item["confidence_score"]) if initial_evals else None
    ocr_wanted = bool(retry_eval and retry_eval["should_retry_with_ocr"] and parsed.image_urls and not no_llm and not external_ocr_used)
    should_retry = bool(ocr_wanted and ocr_enabled)
    if not should_retry:
        if retry_eval and retry_eval["should_retry_with_ocr"] and not ocr_enabled:
            logger.info("置信度建议OCR重跑，但OCR已关闭")
        skipped_reason = ""
        if ocr_wanted and not ocr_enabled:
            skipped_reason = ocr_skipped_reason or ("OCR依赖不可用" if not ocr_status.get("available") else "OCR未启用")
        review_reason_parts = []
        if no_llm:
            review_reason_parts.append("no_llm 模式下跳过 LLM/OCR")
        if initial_fusion.review_reason:
            review_reason_parts.append(initial_fusion.review_reason)
        if ocr_wanted and not ocr_enabled:
            review_reason_parts.append(IMAGE_TABLE_RISK_MESSAGE)
        if external_ocr_used:
            review_reason_parts.append("使用了外部 OCR 文本")
        metadata["field_evidence"].extend(initial_field_evidence)
        metadata["conflict_evidence"].extend(initial_conflicts)
        metadata["extract_evaluations"].extend(initial_eval_payloads)
        metadata["collection_logs"].append(
            {
                "source_id": source_id,
                "info_id": info_id,
                "title": record.get("Title"),
                "source_url": record.get("SourceURL"),
                "status": "success",
                "attempt": "initial",
                "input_mode": input_mode,
                "ocr_available": bool(ocr_status.get("available")),
                "ocr_status_reason": ocr_status.get("reason", ""),
                "ocr_triggered": ocr_wanted,
                "ocr_trigger_reason": retry_eval.get("ocr_trigger_reason") if retry_eval else "",
                "ocr_skipped_reason": skipped_reason,
                "image_count": len(parsed.image_urls),
                "ocr_success_count": 0,
                "ocr_failure_count": 0,
                "ocr_failure_reason": "",
                "external_ocr_used": external_ocr_used,
                "llm_format": "none" if no_llm else llm_format,
                "llm_parse_success": not bool(initial_llm_result.parse_error),
                "need_manual_review": bool(initial_fusion.need_manual_review or (ocr_wanted and not ocr_enabled)),
                "review_reason": "；".join(part for part in review_reason_parts if part),
                "output_rows": len(initial_rows),
                "error": "",
                "initial_confidence_score": _score_from_evals(initial_evals),
                "ocr_retry_confidence_score": "",
                "ocr_improved": False,
                "final_attempt": "initial",
            }
        )
        if save_intermediate:
            save_intermediate_result(
                logs_dir,
                record_index,
                source_id,
                info_id,
                {
                    "parsed_text": parsed.clean_text,
                    "tables_text": parsed.tables_text,
                    "external_ocr_text": external_ocr_text,
                    "table_rule_records": table_result.records,
                    "text_rule_records": text_rule_result.records,
                    "llm_raw_output": initial_llm_result.raw_output,
                    "fused_records": initial_rows,
                    "evaluations": initial_evals,
                },
            )
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
        failed_eval_payloads = log_eval_entries(failed_evals, logs_dir, record_index, record, "ocr_failed", debug, logger)
        metadata["field_evidence"].extend(initial_field_evidence)
        metadata["conflict_evidence"].extend(initial_conflicts)
        metadata["extract_evaluations"].extend([*initial_eval_payloads, *failed_eval_payloads])
        metadata["collection_logs"].append(
            {
                "source_id": source_id,
                "info_id": info_id,
                "title": record.get("Title"),
                "source_url": record.get("SourceURL"),
                "status": "success",
                "attempt": "initial",
                "input_mode": input_mode,
                "ocr_available": bool(ocr_status.get("available")),
                "ocr_status_reason": ocr_status.get("reason", ""),
                "ocr_triggered": True,
                "ocr_trigger_reason": retry_eval["ocr_trigger_reason"] if retry_eval else "",
                "ocr_skipped_reason": "",
                "image_count": len(parsed.image_urls),
                "ocr_success_count": ocr_summary.success_count,
                "ocr_failure_count": ocr_summary.failure_count,
                "ocr_failure_reason": f"成功{ocr_summary.success_count}张，失败{ocr_summary.failure_count}张",
                "external_ocr_used": external_ocr_used,
                "llm_format": llm_format,
                "llm_parse_success": not bool(initial_llm_result.parse_error),
                "need_manual_review": True,
                "review_reason": f"OCR 全部失败，保留首轮融合结果；{IMAGE_TABLE_RISK_MESSAGE}",
                "output_rows": len(initial_rows),
                "error": "",
                "initial_confidence_score": _score_from_evals(initial_evals),
                "ocr_retry_confidence_score": "",
                "ocr_improved": False,
                "final_attempt": "initial",
            }
        )
        if save_intermediate:
            save_intermediate_result(
                logs_dir,
                record_index,
                source_id,
                info_id,
                {
                    "parsed_text": parsed.clean_text,
                    "tables_text": parsed.tables_text,
                    "table_rule_records": table_result.records,
                    "text_rule_records": text_rule_result.records,
                    "llm_raw_output": initial_llm_result.raw_output,
                    "fused_records": initial_rows,
                    "evaluations": initial_evals,
                    "ocr_failure_count": ocr_summary.failure_count,
                },
            )
        return initial_rows

    retry_llm_result = extract_once_detail(
        record, record_index, llm_client, logs_dir, today, parsed.clean_text, parsed.tables_text, ocr_summary.text, len(parsed.image_urls),
        "ocr_retry", debug, logger, field_mapping, llm_format, table_result.records, text_rule_result.records, field_evidence, no_llm=False
    )
    retry_llm_evidence = llm_result_to_field_evidence(retry_llm_result, source_id, info_id, attempt="ocr_retry")
    retry_fusion = fuse_record_sources(
        record,
        table_result.records,
        text_rule_result.records,
        retry_llm_result.records,
        table_result.field_evidence,
        text_rule_result.field_evidence,
        retry_llm_evidence,
        field_mapping,
    )
    retry_rows = retry_fusion.records
    retry_evals = evaluate_rows(
        retry_rows,
        record,
        parsed.clean_text,
        parsed.tables_text,
        ocr_summary.text,
        image_count=len(parsed.image_urls),
        ocr_attempted=True,
    )
    retry_eval_payloads = log_eval_entries(retry_evals, logs_dir, record_index, record, "ocr_retry", debug, logger)
    retry_score = _score_from_evals(retry_evals)
    initial_score = _score_from_evals(initial_evals)
    final_attempt = choose_final_attempt(initial_score, retry_score, retry_llm_result.parse_error, retry_rows)
    final_rows = retry_rows if final_attempt == "ocr_retry" else initial_rows
    final_fusion = retry_fusion if final_attempt == "ocr_retry" else initial_fusion
    retry_field_evidence = _with_context(retry_fusion.field_evidence, record_index, "ocr_retry")
    retry_conflicts = _with_context(retry_fusion.conflict_evidence, record_index, "ocr_retry")
    _append_jsonl_many(logs_dir / "field_evidence.jsonl", retry_field_evidence)
    _append_jsonl_many(logs_dir / "conflict_evidence.jsonl", retry_conflicts)
    metadata["field_evidence"].extend([*initial_field_evidence, *retry_field_evidence])
    metadata["conflict_evidence"].extend([*initial_conflicts, *retry_conflicts])
    metadata["extract_evaluations"].extend([*initial_eval_payloads, *retry_eval_payloads])
    metadata["collection_logs"].append(
        {
            "source_id": source_id,
            "info_id": info_id,
            "title": record.get("Title"),
            "source_url": record.get("SourceURL"),
            "status": "success",
            "attempt": final_attempt,
            "input_mode": input_mode,
            "ocr_available": bool(ocr_status.get("available")),
            "ocr_status_reason": ocr_status.get("reason", ""),
            "ocr_triggered": True,
            "ocr_trigger_reason": retry_eval["ocr_trigger_reason"] if retry_eval else "",
            "ocr_skipped_reason": "",
            "image_count": len(parsed.image_urls),
            "ocr_success_count": ocr_summary.success_count,
            "ocr_failure_count": ocr_summary.failure_count,
            "ocr_failure_reason": f"成功{ocr_summary.success_count}张，失败{ocr_summary.failure_count}张" if ocr_summary.failure_count else "",
            "external_ocr_used": external_ocr_used,
            "llm_format": llm_format,
            "llm_parse_success": not bool(retry_llm_result.parse_error),
            "need_manual_review": final_fusion.need_manual_review,
            "review_reason": final_fusion.review_reason,
            "output_rows": len(final_rows),
            "error": "",
            "initial_confidence_score": initial_score,
            "ocr_retry_confidence_score": retry_score,
            "ocr_improved": retry_score > initial_score,
            "final_attempt": final_attempt,
        }
    )
    logger.info("OCR 前 confidence_score=%s, OCR 后 confidence_score=%s, improved=%s, final_attempt=%s", initial_score, retry_score, retry_score > initial_score, final_attempt)
    if save_intermediate:
        save_intermediate_result(
            logs_dir,
            record_index,
            source_id,
            info_id,
            {
                "parsed_text": parsed.clean_text,
                "tables_text": parsed.tables_text,
                "table_rule_records": table_result.records,
                "text_rule_records": text_rule_result.records,
                "llm_raw_output": retry_llm_result.raw_output,
                "fused_records": final_rows,
                "evaluations": [*initial_evals, *retry_evals],
            },
        )
    return final_rows


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
    field_mapping: FieldMapping | None = None,
    llm_format: str = "v2",
    table_rule_records: List[Dict[str, Any]] | None = None,
    text_rule_records: List[Dict[str, Any]] | None = None,
    field_evidence: List[Dict[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    return extract_once_detail(
        record,
        record_index,
        llm_client,
        logs_dir,
        today,
        clean_text,
        tables_text,
        image_ocr_text,
        image_count,
        attempt,
        debug,
        logger,
        field_mapping,
        llm_format,
        table_rule_records,
        text_rule_records,
        field_evidence,
    ).records


def extract_once_detail(
    record: Dict[str, Any],
    record_index: int,
    llm_client: LLMClient | None,
    logs_dir: Path,
    today: str,
    clean_text: str,
    tables_text: str,
    image_ocr_text: str,
    image_count: int,
    attempt: str,
    debug: bool,
    logger: logging.Logger,
    field_mapping: FieldMapping | None = None,
    llm_format: str = "v2",
    table_rule_records: List[Dict[str, Any]] | None = None,
    text_rule_records: List[Dict[str, Any]] | None = None,
    field_evidence: List[Dict[str, Any]] | None = None,
    no_llm: bool = False,
) -> LlmExtractionResult:
    field_mapping = field_mapping or load_field_mapping(None)
    if no_llm:
        logger.info("no_llm=true, 跳过大模型调用, attempt=%s", attempt)
        return LlmExtractionResult(records=[], need_manual_review=False, review_reason="", raw_output="")
    if llm_format == "legacy":
        prompt = build_extract_prompt(record, clean_text, tables_text, image_ocr_text, today, field_mapping=field_mapping)
    else:
        prompt = build_extract_prompt_v2(
            record,
            clean_text,
            tables_text,
            image_ocr_text,
            today,
            field_mapping=field_mapping,
            table_rule_records=table_rule_records,
            text_rule_records=text_rule_records,
            field_evidence=field_evidence,
        )
    try:
        if llm_format == "legacy":
            raw_output = llm_client.extract(prompt)
            rows = normalize_llm_rows(raw_output, record, today, logs_dir, field_mapping=field_mapping)
            result = LlmExtractionResult(records=rows, raw_output=raw_output)
            logger.info("llm_format=legacy parse_success=true need_manual_review=false review_reason=")
        else:
            result = extract_with_llm(llm_client, prompt, record, today, logs_dir, field_mapping)
            rows = result.records
            logger.info(
                "llm_format=v2 parse_success=%s need_manual_review=%s review_reason=%s",
                not bool(result.parse_error),
                result.need_manual_review,
                result.review_reason,
            )
        logger.info("大模型调用是否成功: true, attempt=%s", attempt)
    except Exception as llm_exc:
        raw_output = "[]"
        masked_error = mask_sensitive_text(str(llm_exc))
        logger.error("大模型调用是否成功: false, attempt=%s, error=%s", attempt, masked_error)
        append_jsonl(
            logs_dir / "failed_records.jsonl",
            {
                "phase": "llm",
                "attempt": attempt,
                "record_index": record_index,
                "Title": record.get("Title"),
                "SourceURL": record.get("SourceURL"),
                "error": masked_error,
            },
        )

        rows = normalize_llm_rows(raw_output, record, today, logs_dir, field_mapping=field_mapping)
        result = LlmExtractionResult(records=rows, raw_output=raw_output, parse_error=masked_error, need_manual_review=True, review_reason=masked_error)
        logger.info("llm_format=%s parse_success=false need_manual_review=true review_reason=%s", llm_format, masked_error)
    logger.info("模型返回行数: %s, attempt=%s", len(rows), attempt)
    if debug:
        logger.debug("抽取上下文: attempt=%s image_count=%s ocr_text_length=%s", attempt, image_count, len(image_ocr_text or ""))
    return result


def log_eval_entries(
    evaluations: List[Dict[str, Any]],
    logs_dir: Path,
    record_index: int,
    record: Dict[str, Any],
    attempt: str,
    debug: bool,
    logger: logging.Logger,
) -> List[Dict[str, Any]]:
    payloads: List[Dict[str, Any]] = []
    for row_index, evaluation in enumerate(evaluations, start=1):
        payload = {
            "record_index": record_index,
            "row_index": row_index,
            "attempt": attempt,
            "Title": record.get("Title"),
            "SourceURL": record.get("SourceURL"),
            **evaluation,
        }
        payloads.append(payload)
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
    return payloads


def main() -> int:
    settings = load_settings()
    parser = build_arg_parser(settings)
    args = parser.parse_args()

    logs_dir = Path(args.log_dir)
    if not logs_dir.is_absolute():
        logs_dir = PROJECT_ROOT / logs_dir
    temp_images_dir = PROJECT_ROOT / "temp_images"
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = PROJECT_ROOT / output_dir
    template_path = PROJECT_ROOT / "templates" / "template.xlsx"
    today = today_yyyymmdd()

    logger = setup_logging(logs_dir, args.debug)
    logger.info("程序启动参数: %s", vars(args))
    try:
        settings = apply_llm_config(settings, args.llm_config)
    except LlmConfigError as exc:
        logger.error("LLM 配置错误: %s", exc)
        append_jsonl(logs_dir / "failed_records.jsonl", {"phase": "llm_config", "error": str(exc)})
        return 1
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
        append_jsonl(logs_dir / "failed_records.jsonl", {"phase": "external_ocr", "error": masked_error})
        return 1

    try:
        field_mapping = load_field_mapping(args.field_config)
        logger.info("字段配置加载完成: headers=%s", len(field_mapping.headers))
    except FieldMappingError as exc:
        logger.error("字段配置错误: %s", exc)
        append_jsonl(logs_dir / "failed_records.jsonl", {"phase": "field_config", "error": str(exc)})
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
        append_jsonl(logs_dir / "failed_records.jsonl", {"phase": "read_input", "error": masked_error})
        return 1

    llm_client = None if runtime_flags["no_llm"] else LLMClient(settings)
    ocr_enabled = settings.ocr_enabled and not runtime_flags["no_ocr"] and bool(ocr_status.get("available"))
    all_rows: List[Dict[str, Any]] = []
    all_metadata = _empty_metadata()
    output_paths: List[Path] = []
    record_error_count = 0
    started_at = time.time()

    for index, record in enumerate(records, start=1):
        try:
            logger.info("当前处理第 %s 条 / %s", index, len(records))
            logger.info("Title: %s", record.get("Title"))
            logger.info("SourceURL: %s", record.get("SourceURL"))

            record_metadata = _empty_metadata()
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
                save_intermediate=args.save_intermediate,
                metadata=record_metadata,
                external_ocr_text=external_ocr_for_record(record, external_ocr_text, external_ocr_mapping),
                ocr_status=ocr_status,
                ocr_skipped_reason=ocr_skipped_reason,
            )

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
                    )
                except Exception as exc:
                    masked_error = mask_sensitive_text(str(exc))
                    logger.error("Excel 写入失败: %s", masked_error)
                    append_jsonl(
                        logs_dir / "failed_records.jsonl",
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
                    return 1
                logger.info("Excel 输出路径: %s", output_path)
                output_paths.append(output_path)
            else:
                all_rows.extend(rows)
                for key in all_metadata:
                    all_metadata[key].extend(record_metadata[key])
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
            append_jsonl(logs_dir / "failed_records.jsonl", failed_payload)
            all_metadata["failed_records"].append(failed_payload)
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
            )
        except Exception as exc:
            masked_error = mask_sensitive_text(str(exc))
            logger.error("Excel 写入失败: %s", masked_error)
            append_jsonl(logs_dir / "failed_records.jsonl", {"phase": "excel_write", "error": masked_error})
            return 1
        logger.info("Excel 输出路径: %s", output_path)
        output_paths.append(output_path)

    elapsed = time.time() - started_at
    logger.info("任务结束，输出文件数: %s, 耗时秒: %.2f, 平均每条秒: %.2f, 单条失败数: %s", len(output_paths), elapsed, elapsed / max(len(records), 1), record_error_count)
    for path in output_paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
