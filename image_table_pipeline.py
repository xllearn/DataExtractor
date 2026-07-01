from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from extraction_types import RuleExtractionResult
from field_mapping import FieldMapping, normalize_record_fields
from image_ocr import OcrSummary
from ocr_table_parser import extract_benefit_table_records_from_ocr_text
from security_utils import mask_sensitive_text
from utils import apply_default_mappings
from vision_extractor import extract_image_table_with_vision


@dataclass
class ImageTableContext:
    text: str = ""
    records: List[Dict[str, Any]] = field(default_factory=list)
    field_evidence: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[Dict[str, Any]] = field(default_factory=list)
    external_ocr_used: bool = False
    vision_enabled: bool = False
    vision_triggered: bool = False
    vision_success_count: int = 0
    vision_failure_count: int = 0
    vision_model: str = ""
    vision_error: str = ""
    ocr_triggered: bool = False
    ocr_success_count: int = 0
    ocr_failure_count: int = 0
    ocr_failure_reason: str = ""

    @property
    def recognition_attempted(self) -> bool:
        return bool(self.external_ocr_used or self.vision_triggered or self.ocr_triggered)


def _has_html_table(tables_text: str) -> bool:
    return bool(str(tables_text or "").strip())


def _empty_summary(image_count: int = 0) -> OcrSummary:
    return OcrSummary(text="", success_count=0, failure_count=image_count)


def _format_ocr_failure_reason(summary: OcrSummary) -> str:
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


def _enrich_records(records: List[Dict[str, Any]], record: Dict[str, Any], today: str, field_mapping: FieldMapping) -> List[Dict[str, Any]]:
    enriched = []
    for row in records:
        note = row.get("备注")
        applied = apply_default_mappings(row, record, today)
        for field, value in row.items():
            if value not in (None, "", "--"):
                applied[field] = value
        if note not in (None, "", "--"):
            applied["备注"] = note
        enriched.append(normalize_record_fields(applied, field_mapping))
    return enriched


def _parse_table_text(
    text: str,
    record: Dict[str, Any],
    today: str,
    field_mapping: FieldMapping,
    source: str,
) -> RuleExtractionResult:
    source_id = str(record.get("_source_id") or record.get("SourceURL") or "")
    info_id = str(record.get("info_id") or (record.get("_direct_fields") or {}).get("info_id") or "")
    result = extract_benefit_table_records_from_ocr_text(
        text,
        source_id=source_id,
        info_id=info_id,
        field_mapping=field_mapping,
        source=source,
    )
    result.records = _enrich_records(result.records, record, today, field_mapping)
    return result


def collect_image_table_context(
    parsed,
    record: Dict[str, Any],
    record_index: int,
    temp_images_dir: Path,
    today: str,
    field_mapping: FieldMapping,
    external_ocr_text: str = "",
    ocr_enabled: bool = False,
    ocr_func=None,
    vision_client=None,
    no_llm: bool = False,
    logger=None,
) -> ImageTableContext:
    context = ImageTableContext()
    context.vision_enabled = bool(vision_client is not None and getattr(vision_client, "is_ready", lambda: True)())
    context.vision_model = str(getattr(vision_client, "model", "") or "")

    image_urls = list(getattr(parsed, "image_urls", []) or [])
    has_images = bool(image_urls)
    has_table = _has_html_table(getattr(parsed, "tables_text", ""))
    external_ocr_text = str(external_ocr_text or "").strip()

    if external_ocr_text:
        context.external_ocr_used = True
        context.text = external_ocr_text
        parsed_result = _parse_table_text(
            "\n".join(part for part in [getattr(parsed, "clean_text", ""), external_ocr_text] if part),
            record,
            today,
            field_mapping,
            "external_ocr_text",
        )
        context.records.extend(parsed_result.records)
        context.field_evidence.extend(parsed_result.field_evidence)
        context.errors.extend(parsed_result.errors)
        return context

    if has_table or not has_images:
        return context

    prompt_context = "\n".join(
        part
        for part in [
            str(record.get("Title") or ""),
            str(record.get("SourceURL") or ""),
            str(getattr(parsed, "clean_text", "") or "")[:2000],
        ]
        if part
    )

    if vision_client is not None and context.vision_enabled and not no_llm:
        context.vision_triggered = True
        if logger:
            logger.info("无 HTML 表格且发现图片，优先调用 vision 模型识别图片表格: model=%s", context.vision_model or "--")
        vision_result = extract_image_table_with_vision(image_urls, record, prompt_context, vision_client)
        context.vision_success_count = vision_result.success_count
        context.vision_failure_count = vision_result.failure_count
        context.errors.extend(vision_result.errors)
        if vision_result.errors:
            context.vision_error = "；".join(str(item.get("error") or "") for item in vision_result.errors if item.get("error"))[:500]
        if vision_result.text.strip() or vision_result.records:
            context.text = vision_result.text
            context.records.extend(_enrich_records(vision_result.records, record, today, field_mapping))
            context.field_evidence.extend(vision_result.field_evidence)
            parsed_result = _parse_table_text(
                "\n".join(part for part in [getattr(parsed, "clean_text", ""), vision_result.text] if part),
                record,
                today,
                field_mapping,
                "vision_llm",
            )
            context.records.extend(parsed_result.records)
            context.field_evidence.extend(parsed_result.field_evidence)
            context.errors.extend(parsed_result.errors)
            return context

    if ocr_enabled and ocr_func is not None:
        context.ocr_triggered = True
        if logger:
            logger.info("vision 不可用或未产出图片表格文本，开始 PaddleOCR 图片识别")
        try:
            summary = ocr_func(image_urls, temp_images_dir, record_index=record_index, enabled=True, logger=logger)
        except Exception as exc:
            summary = _empty_summary(len(image_urls))
            summary.errors.append({"image_index": "", "image_url": "", "error": mask_sensitive_text(str(exc)), "source": "paddleocr"})
        context.ocr_success_count = summary.success_count
        context.ocr_failure_count = summary.failure_count
        context.ocr_failure_reason = _format_ocr_failure_reason(summary)
        context.errors.extend(getattr(summary, "errors", []) or [])
        if summary.success_count > 0 and summary.text.strip():
            context.text = summary.text
            parsed_result = _parse_table_text(
                "\n".join(part for part in [getattr(parsed, "clean_text", ""), summary.text] if part),
                record,
                today,
                field_mapping,
                "paddleocr",
            )
            context.records.extend(parsed_result.records)
            context.field_evidence.extend(parsed_result.field_evidence)
            context.errors.extend(parsed_result.errors)
    return context
