import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from confidence import IMAGE_TABLE_RISK_MESSAGE, evaluate_rows, mark_ocr_failed
from extraction_types import RuleExtractionResult
from field_confidence import build_review_rows, calculate_field_confidence
from field_mapping import FieldMapping, load_field_mapping
from html_parser import parse_html_content
from image_ocr import get_ocr_status, process_image_ocr
from image_table_pipeline import ImageTableContext, collect_image_table_context
from json_utils import normalize_llm_rows
from llm_client import LLMClient
from llm_extractor import LlmExtractionResult, extract_with_llm, llm_result_to_field_evidence
from prompts import build_extract_prompt
from prompt_registry import build_prompt, hash_text
from record_fusion import fuse_record_sources
from rule_extractor import extract_key_value_records
from security_utils import mask_sensitive_text
from table_extractor import extract_table_records
from utils import append_jsonl, ensure_dir


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


def _append_confidence_metadata(
    metadata: Dict[str, List[Dict[str, Any]]],
    rows: List[Dict[str, Any]],
    field_evidence: List[Dict[str, Any]],
    conflicts: List[Dict[str, Any]],
    row_match_evidence: List[Dict[str, Any]] | None = None,
    source_text: str = "",
    table_text: str = "",
) -> None:
    confidence_rows = calculate_field_confidence(
        rows,
        field_evidence,
        conflicts,
        metadata.get("collection_logs", []),
        row_match_evidence=row_match_evidence or [],
        source_text=source_text,
        table_text=table_text,
    )
    review_rows = build_review_rows(
        rows,
        confidence_rows,
        conflicts,
        metadata.get("collection_logs", []),
        row_match_evidence=row_match_evidence or [],
    )
    metadata["field_confidence"].extend(confidence_rows)
    metadata["review_rows"].extend(review_rows)


def create_empty_metadata() -> Dict[str, List[Dict[str, Any]]]:
    return {
        "collection_logs": [],
        "field_evidence": [],
        "conflict_evidence": [],
        "extract_evaluations": [],
        "failed_records": [],
        "field_confidence": [],
        "review_rows": [],
        "row_match_evidence": [],
    }


_empty_metadata = create_empty_metadata


def _merge_rule_results(results: List[RuleExtractionResult]) -> RuleExtractionResult:
    merged = RuleExtractionResult()
    seen_records = set()
    seen_evidence = set()
    for result in results:
        for record in result.records:
            key = tuple((field, str(value)) for field, value in record.items() if value not in (None, "", "--"))
            if key not in seen_records:
                merged.records.append(record)
                seen_records.add(key)
        for evidence in result.field_evidence:
            key = (
                evidence.get("source_id", ""),
                evidence.get("info_id", ""),
                evidence.get("field", ""),
                evidence.get("value", ""),
                evidence.get("evidence", ""),
                evidence.get("source", ""),
            )
            if key not in seen_evidence:
                merged.field_evidence.append(evidence)
                seen_evidence.add(key)
        merged.errors.extend(result.errors)
    return merged


def _format_ocr_summary_failure(summary) -> str:
    base = f"成功{summary.success_count}张，失败{summary.failure_count}张"
    details = []
    for error in getattr(summary, "errors", []) or []:
        image_index = error.get("image_index", "")
        message = error.get("error") or error.get("ocr_error") or error.get("download_error") or ""
        if message:
            details.append(f"图片{image_index}: {message}")
    if details:
        return f"{base}；" + "；".join(details[:3])
    return base if summary.failure_count else ""


def _recognition_log_fields(context: ImageTableContext, ocr_triggered: bool | None = None) -> Dict[str, Any]:
    return {
        "vision_enabled": context.vision_enabled,
        "vision_triggered": context.vision_triggered,
        "vision_success_count": context.vision_success_count,
        "vision_failure_count": context.vision_failure_count,
        "vision_model": context.vision_model,
        "vision_error": context.vision_error,
        "ocr_triggered": context.ocr_triggered if ocr_triggered is None else bool(ocr_triggered),
        "ocr_success_count": context.ocr_success_count,
        "ocr_failure_count": context.ocr_failure_count,
        "ocr_failure_reason": context.ocr_failure_reason,
        "external_ocr_used": context.external_ocr_used,
    }


def _append_image_recognition_errors(logs_dir: Path, record_index: int, errors: List[Dict[str, Any]]) -> None:
    for error in errors:
        append_jsonl(logs_dir / "image_table_recognition_errors.jsonl", {"record_index": record_index, **error})


IMAGE_TABLE_COMMON_TEXT_FIELDS = {"地区名称", "保险类型", "人员类型", "病种类型", "就诊地域", "医院类型", "就诊情况", "备注"}


def _sanitize_text_rules_for_image_table(result: RuleExtractionResult, table_record_count: int, has_image_table_records: bool) -> RuleExtractionResult:
    if not has_image_table_records or table_record_count <= 1:
        return result
    sanitized = RuleExtractionResult(errors=list(result.errors))
    common_records = []
    for record in result.records:
        common = {field: value for field, value in record.items() if field in IMAGE_TABLE_COMMON_TEXT_FIELDS and value not in (None, "", "--")}
        if common:
            common_records.append(common)
    if common_records:
        first_common = common_records[0]
        sanitized.records = [dict(first_common) for _ in range(table_record_count)]
    sanitized.field_evidence = [
        evidence
        for evidence in result.field_evidence
        if evidence.get("field") in IMAGE_TABLE_COMMON_TEXT_FIELDS
    ]
    return sanitized


def _score_from_evals(evaluations: List[Dict[str, Any]]) -> int:
    scores = [int(item.get("confidence_score", 0)) for item in evaluations]
    return min(scores) if scores else 0


def choose_final_attempt(initial_score: int, retry_score: int, retry_parse_error: str, retry_rows: List[Dict[str, Any]]) -> str:
    if retry_parse_error or not retry_rows:
        return "initial"
    if retry_score < initial_score - 5:
        return "initial"
    return "ocr_retry"


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
    prompt_version: str = "v3",
    save_intermediate: bool = False,
    metadata: Dict[str, List[Dict[str, Any]]] | None = None,
    ocr_func=process_image_ocr,
    external_ocr_text: str = "",
    ocr_status: Dict[str, Any] | None = None,
    ocr_skipped_reason: str = "",
    vision_client=None,
    run_id: str = "",
) -> List[Dict[str, Any]]:
    metadata = metadata if metadata is not None else create_empty_metadata()
    for key, value in create_empty_metadata().items():
        metadata.setdefault(key, list(value))
    field_mapping = field_mapping or load_field_mapping(None)
    logger = logger or logging.getLogger("db_to_excel_extractor")
    parsed = parse_html_content(record.get("Content"), image_base_url, logger)
    logger.info("图片数量: %s", len(parsed.image_urls))
    source_id = str(record.get("_source_id") or record.get("SourceURL") or record_index)
    info_id = str(record.get("info_id") or (record.get("_direct_fields") or {}).get("info_id") or "")
    ocr_status = ocr_status or get_ocr_status()
    external_ocr_text = str(external_ocr_text or "").strip()

    image_context = collect_image_table_context(
        parsed=parsed,
        record=record,
        record_index=record_index,
        temp_images_dir=temp_images_dir,
        today=today,
        field_mapping=field_mapping,
        external_ocr_text=external_ocr_text,
        ocr_enabled=ocr_enabled,
        ocr_func=ocr_func,
        vision_client=vision_client,
        no_llm=no_llm,
        logger=logger,
    )
    _append_image_recognition_errors(logs_dir, record_index, image_context.errors)
    image_ocr_text = image_context.text
    external_ocr_used = image_context.external_ocr_used
    if not image_context.recognition_attempted:
        logger.info("首轮未触发图片表格识别")
    elif external_ocr_used:
        logger.info("使用外部 OCR 文本参与首轮抽取")
    elif image_context.vision_triggered:
        logger.info("vision 图片表格识别完成: success=%s failure=%s", image_context.vision_success_count, image_context.vision_failure_count)
    elif image_context.ocr_triggered:
        logger.info("PaddleOCR 图片表格识别完成: success=%s failure=%s", image_context.ocr_success_count, image_context.ocr_failure_count)

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
    html_table_result = extract_table_records(record.get("Content") or "", parsed.tables_text, source_id=source_id, info_id=info_id, config=table_mapping, field_mapping=field_mapping, normalized_tables=parsed.normalized_tables)
    image_table_result = RuleExtractionResult(records=image_context.records, field_evidence=image_context.field_evidence, errors=[])
    table_result = _merge_rule_results([html_table_result, image_table_result])
    rule_text = "\n".join(part for part in [parsed.clean_text, image_ocr_text] if part)
    raw_text_rule_result = extract_key_value_records(rule_text, source_id=source_id, info_id=info_id, field_mapping=field_mapping)
    text_rule_result = _sanitize_text_rules_for_image_table(raw_text_rule_result, len(table_result.records), bool(image_context.records))
    log_rule_result(table_result, logs_dir, record_index, "table_rule", logger)
    log_rule_result(text_rule_result, logs_dir, record_index, "text_rule", logger)
    field_evidence = [*table_result.field_evidence, *text_rule_result.field_evidence, *external_ocr_evidence]

    initial_llm_result = extract_once_detail(
        record, record_index, llm_client, logs_dir, today, parsed.clean_text, parsed.tables_text, image_ocr_text, len(parsed.image_urls),
        "initial", debug, logger, field_mapping, llm_format, table_result.records, text_rule_result.records, field_evidence, no_llm=no_llm, run_id=run_id, failure_collector=metadata["failed_records"], prompt_version=prompt_version
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
    initial_row_match_evidence = _with_context(initial_fusion.row_match_evidence, record_index, "initial")
    _append_jsonl_many(logs_dir / "field_evidence.jsonl", initial_field_evidence)
    _append_jsonl_many(logs_dir / "rule_extract_errors.jsonl", _with_context([*table_result.errors, *text_rule_result.errors], record_index, "initial"))
    _append_jsonl_many(logs_dir / "conflict_evidence.jsonl", initial_conflicts)
    _append_jsonl_many(logs_dir / "row_match_evidence.jsonl", initial_row_match_evidence)
    initial_evals = evaluate_rows(
        initial_rows,
        record,
        parsed.clean_text,
        parsed.tables_text,
        image_ocr_text,
        image_count=len(parsed.image_urls),
        ocr_attempted=image_context.recognition_attempted,
    )
    initial_eval_payloads = log_eval_entries(initial_evals, logs_dir, record_index, record, "initial", debug, logger)

    retry_eval = min(initial_evals, key=lambda item: item["confidence_score"]) if initial_evals else None
    ocr_wanted = bool(retry_eval and retry_eval["should_retry_with_ocr"] and parsed.image_urls and not no_llm and not image_context.recognition_attempted)
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
        if image_context.vision_error:
            review_reason_parts.append(f"vision 识别异常：{image_context.vision_error}")
        if image_context.ocr_failure_reason and image_context.ocr_success_count == 0:
            review_reason_parts.append(f"OCR 识别失败：{image_context.ocr_failure_reason}")
        metadata["field_evidence"].extend(initial_field_evidence)
        metadata["conflict_evidence"].extend(initial_conflicts)
        metadata["row_match_evidence"].extend(initial_row_match_evidence)
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
                **_recognition_log_fields(image_context, ocr_triggered=image_context.ocr_triggered or ocr_wanted),
                "ocr_trigger_reason": retry_eval.get("ocr_trigger_reason") if retry_eval else "",
                "ocr_skipped_reason": skipped_reason,
                "image_count": len(parsed.image_urls),
                "llm_format": "none" if no_llm else llm_format,
                "prompt_version": initial_llm_result.prompt_version,
                "prompt_hash": initial_llm_result.prompt_hash,
                "response_hash": initial_llm_result.response_hash,
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
        _append_confidence_metadata(
            metadata,
            initial_rows,
            initial_field_evidence,
            initial_conflicts,
            initial_row_match_evidence,
            source_text=parsed.clean_text,
            table_text=parsed.tables_text,
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
                    "image_ocr_text": image_ocr_text,
                    "image_table_records": image_context.records,
                    "image_recognition_errors": image_context.errors,
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
    _append_image_recognition_errors(logs_dir, record_index, getattr(ocr_summary, "errors", []) or [])
    retry_ocr_failure_reason = _format_ocr_summary_failure(ocr_summary)

    if ocr_summary.failure_count > 0 and ocr_summary.success_count == 0:
        failed_evals = mark_ocr_failed(initial_evals, retry_ocr_failure_reason or f"成功0张，失败{ocr_summary.failure_count}张")
        failed_eval_payloads = log_eval_entries(failed_evals, logs_dir, record_index, record, "ocr_failed", debug, logger)
        metadata["field_evidence"].extend(initial_field_evidence)
        metadata["conflict_evidence"].extend(initial_conflicts)
        metadata["row_match_evidence"].extend(initial_row_match_evidence)
        metadata["extract_evaluations"].extend([*initial_eval_payloads, *failed_eval_payloads])
        retry_context = ImageTableContext(
            external_ocr_used=external_ocr_used,
            vision_enabled=image_context.vision_enabled,
            vision_model=image_context.vision_model,
            ocr_triggered=True,
            ocr_success_count=ocr_summary.success_count,
            ocr_failure_count=ocr_summary.failure_count,
            ocr_failure_reason=retry_ocr_failure_reason,
        )
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
                **_recognition_log_fields(retry_context, ocr_triggered=True),
                "ocr_trigger_reason": retry_eval["ocr_trigger_reason"] if retry_eval else "",
                "ocr_skipped_reason": "",
                "image_count": len(parsed.image_urls),
                "llm_format": llm_format,
                "prompt_version": initial_llm_result.prompt_version,
                "prompt_hash": initial_llm_result.prompt_hash,
                "response_hash": initial_llm_result.response_hash,
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
        _append_confidence_metadata(
            metadata,
            initial_rows,
            initial_field_evidence,
            initial_conflicts,
            initial_row_match_evidence,
            source_text=parsed.clean_text,
            table_text=parsed.tables_text,
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
                    "ocr_errors": getattr(ocr_summary, "errors", []) or [],
                },
            )
        return initial_rows

    retry_llm_result = extract_once_detail(
        record, record_index, llm_client, logs_dir, today, parsed.clean_text, parsed.tables_text, ocr_summary.text, len(parsed.image_urls),
        "ocr_retry", debug, logger, field_mapping, llm_format, table_result.records, text_rule_result.records, field_evidence, no_llm=False, run_id=run_id, failure_collector=metadata["failed_records"], prompt_version=prompt_version
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
    retry_row_match_evidence = _with_context(retry_fusion.row_match_evidence, record_index, "ocr_retry")
    _append_jsonl_many(logs_dir / "field_evidence.jsonl", retry_field_evidence)
    _append_jsonl_many(logs_dir / "conflict_evidence.jsonl", retry_conflicts)
    _append_jsonl_many(logs_dir / "row_match_evidence.jsonl", retry_row_match_evidence)
    metadata["field_evidence"].extend([*initial_field_evidence, *retry_field_evidence])
    metadata["conflict_evidence"].extend([*initial_conflicts, *retry_conflicts])
    metadata["row_match_evidence"].extend([*initial_row_match_evidence, *retry_row_match_evidence])
    metadata["extract_evaluations"].extend([*initial_eval_payloads, *retry_eval_payloads])
    retry_context = ImageTableContext(
        external_ocr_used=external_ocr_used,
        vision_enabled=image_context.vision_enabled,
        vision_model=image_context.vision_model,
        ocr_triggered=True,
        ocr_success_count=ocr_summary.success_count,
        ocr_failure_count=ocr_summary.failure_count,
        ocr_failure_reason=retry_ocr_failure_reason,
    )
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
            **_recognition_log_fields(retry_context, ocr_triggered=True),
            "ocr_trigger_reason": retry_eval["ocr_trigger_reason"] if retry_eval else "",
            "ocr_skipped_reason": "",
            "image_count": len(parsed.image_urls),
            "llm_format": llm_format,
            "prompt_version": retry_llm_result.prompt_version,
            "prompt_hash": retry_llm_result.prompt_hash,
            "response_hash": retry_llm_result.response_hash,
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
    final_field_evidence = retry_field_evidence if final_attempt == "ocr_retry" else initial_field_evidence
    final_conflicts = retry_conflicts if final_attempt == "ocr_retry" else initial_conflicts
    final_row_match_evidence = retry_row_match_evidence if final_attempt == "ocr_retry" else initial_row_match_evidence
    _append_confidence_metadata(
        metadata,
        final_rows,
        final_field_evidence,
        final_conflicts,
        final_row_match_evidence,
        source_text=parsed.clean_text,
        table_text=parsed.tables_text,
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
                "ocr_errors": getattr(ocr_summary, "errors", []) or [],
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
    prompt_version: str = "v3",
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
        prompt_version=prompt_version,
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
    run_id: str = "",
    failure_collector: List[Dict[str, Any]] | None = None,
    prompt_version: str = "v3",
) -> LlmExtractionResult:
    field_mapping = field_mapping or load_field_mapping(None)
    if no_llm:
        logger.info("no_llm=true, 跳过大模型调用, attempt=%s", attempt)
        return LlmExtractionResult(records=[], need_manual_review=False, review_reason="", raw_output="", prompt_version="none")
    if llm_format == "legacy":
        prompt = build_extract_prompt(record, clean_text, tables_text, image_ocr_text, today, field_mapping=field_mapping)
        effective_prompt_version = "legacy"
        prompt_hash = hash_text(prompt)
    else:
        prompt_payload = build_prompt(
            prompt_version,
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
        prompt = prompt_payload.text
        effective_prompt_version = prompt_payload.version
        prompt_hash = prompt_payload.prompt_hash
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
        failure_payload = {
            "run_id": run_id,
            "phase": "llm",
            "attempt": attempt,
            "record_index": record_index,
            "source_id": record.get("_source_id"),
            "info_id": record.get("info_id") or (record.get("_direct_fields") or {}).get("info_id"),
            "Title": record.get("Title"),
            "SourceURL": record.get("SourceURL"),
            "error": masked_error,
        }
        append_jsonl(logs_dir / "llm_errors.jsonl", failure_payload)
        if failure_collector is not None:
            failure_collector.append(failure_payload)

        rows = normalize_llm_rows(raw_output, record, today, logs_dir, field_mapping=field_mapping)
        result = LlmExtractionResult(records=rows, raw_output=raw_output, parse_error=masked_error, need_manual_review=True, review_reason=masked_error)
        logger.info("llm_format=%s parse_success=false need_manual_review=true review_reason=%s", llm_format, masked_error)
    logger.info("模型返回行数: %s, attempt=%s", len(rows), attempt)
    result.prompt_version = effective_prompt_version
    result.prompt_hash = prompt_hash
    result.response_hash = hash_text(result.raw_output)
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
