import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence

from field_mapping import FieldMapping, load_field_mapping, normalize_record_fields
from table_classifier import confidence_level
from utils import EXCEL_HEADERS


METADATA_FIELDS = {
    EXCEL_HEADERS[0],
    EXCEL_HEADERS[1],
    EXCEL_HEADERS[2],
    EXCEL_HEADERS[3],
    EXCEL_HEADERS[9],
    EXCEL_HEADERS[20],
    EXCEL_HEADERS[21],
    EXCEL_HEADERS[22],
    EXCEL_HEADERS[23],
    EXCEL_HEADERS[24],
    EXCEL_HEADERS[25],
}
CONTENT_CORE_FIELDS = {
    EXCEL_HEADERS[6],
    EXCEL_HEADERS[7],
    EXCEL_HEADERS[8],
    EXCEL_HEADERS[10],
    EXCEL_HEADERS[11],
    EXCEL_HEADERS[12],
    EXCEL_HEADERS[13],
    EXCEL_HEADERS[14],
    EXCEL_HEADERS[15],
}
TREATMENT_FIELDS = {EXCEL_HEADERS[16], EXCEL_HEADERS[17], EXCEL_HEADERS[18]}
OBVIOUS_NOISE_TABLE_TYPES = {
    "co_insurer_table",
    "faq_table",
    "contact_table",
    "directory_table",
    "timeline_table",
    "marketing_table",
}
LOW_VALUE_TARGET = "low_value"
MAIN_TARGET = "main"
CANDIDATE_TARGET = "candidate"
EMPTY_VALUES = {"", "--", "none", "null", "nan"}


@dataclass
class RowQualityResult:
    metadata_nonblank_count: int
    content_core_nonblank_count: int
    treatment_nonblank_count: int
    has_amount_or_ratio: bool
    has_treatment_context: bool
    has_treatment_context_source: str
    table_type: str
    table_confidence: float
    table_confidence_level: str
    row_quality_level: str
    row_quality_reason: str
    target_sheet: str
    should_enter_main_result: bool
    mapped_values_json: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "metadata_nonblank_count": self.metadata_nonblank_count,
            "content_core_nonblank_count": self.content_core_nonblank_count,
            "treatment_nonblank_count": self.treatment_nonblank_count,
            "has_amount_or_ratio": self.has_amount_or_ratio,
            "has_treatment_context": self.has_treatment_context,
            "has_treatment_context_source": self.has_treatment_context_source,
            "table_type": self.table_type,
            "table_confidence": round(self.table_confidence, 6),
            "table_confidence_level": self.table_confidence_level,
            "row_quality_level": self.row_quality_level,
            "row_quality_reason": self.row_quality_reason,
            "target_sheet": self.target_sheet,
            "should_enter_main_result": self.should_enter_main_result,
            "mapped_values_json": self.mapped_values_json,
        }


def evaluate_row_quality(
    row: Dict[str, Any],
    *,
    field_mapping: FieldMapping | None = None,
) -> RowQualityResult:
    field_mapping = field_mapping or load_field_mapping(None)
    mapped = normalize_record_fields(row, field_mapping)
    metadata_nonblank_count = _count_nonblank(mapped, METADATA_FIELDS)
    content_core_nonblank_count = _count_nonblank(mapped, CONTENT_CORE_FIELDS)
    treatment_nonblank_count = _count_nonblank(mapped, TREATMENT_FIELDS)
    row_text = _row_text(row, mapped)
    has_amount_or_ratio = _has_amount_or_ratio(row_text)
    context_sources = _treatment_context_sources(row, mapped, row_text)
    has_treatment_context = bool(context_sources)
    context_source = ",".join(context_sources) if context_sources else "none"
    table_type = str(row.get("_table_type") or "unknown_table")
    table_confidence = _float(row.get("_table_confidence"), default=1.0 if not _is_table_row(row) else 0.2)
    table_confidence_level = str(row.get("_table_confidence_level") or confidence_level(table_confidence))
    target_sheet, quality_level, reason = _target_for_row(
        is_table_row=_is_table_row(row),
        table_type=table_type,
        table_confidence=table_confidence,
        treatment_nonblank_count=treatment_nonblank_count,
        content_core_nonblank_count=content_core_nonblank_count,
        has_treatment_context=has_treatment_context,
    )
    return RowQualityResult(
        metadata_nonblank_count=metadata_nonblank_count,
        content_core_nonblank_count=content_core_nonblank_count,
        treatment_nonblank_count=treatment_nonblank_count,
        has_amount_or_ratio=has_amount_or_ratio,
        has_treatment_context=has_treatment_context,
        has_treatment_context_source=context_source,
        table_type=table_type,
        table_confidence=table_confidence,
        table_confidence_level=table_confidence_level,
        row_quality_level=quality_level,
        row_quality_reason=reason,
        target_sheet=target_sheet,
        should_enter_main_result=target_sheet == MAIN_TARGET,
        mapped_values_json=json.dumps(mapped, ensure_ascii=False, default=str, sort_keys=True),
    )


def split_rows_by_quality(
    rows: Sequence[Dict[str, Any]],
    *,
    record: Dict[str, Any],
    field_mapping: FieldMapping | None = None,
) -> Dict[str, List[Dict[str, Any]]]:
    field_mapping = field_mapping or load_field_mapping(None)
    source = _record_source(record)
    main_rows: List[Dict[str, Any]] = []
    candidate_rows: List[Dict[str, Any]] = []
    low_value_rows: List[Dict[str, Any]] = []
    result_index_rows: List[Dict[str, Any]] = []
    row_quality_rows: List[Dict[str, Any]] = []

    target_counters = {MAIN_TARGET: 0, CANDIDATE_TARGET: 0, LOW_VALUE_TARGET: 0}
    for original_index, row in enumerate(rows or [], start=1):
        quality = evaluate_row_quality(row, field_mapping=field_mapping)
        mapped = normalize_record_fields(row, field_mapping)
        enriched = {
            **row,
            **quality.as_dict(),
        }
        row_quality_rows.append(
            {
                **source,
                "original_row_index": original_index,
                "table_index": row.get("_table_index", ""),
                "row_index": row.get("_row_index", original_index),
                **quality.as_dict(),
            }
        )
        target_counters[quality.target_sheet] += 1
        target_row_index = target_counters[quality.target_sheet]
        result_index_rows.append(_result_index_row(source, row, quality, target_row_index))
        if quality.target_sheet == MAIN_TARGET:
            main_rows.append({**mapped, **_quality_internal_meta(enriched)})
        elif quality.target_sheet == CANDIDATE_TARGET:
            candidate_rows.append(_candidate_row(mapped, source, row, quality))
        else:
            low_value_rows.append(_low_value_row(mapped, source, row, quality))

    return {
        "main_rows": main_rows,
        "candidate_rows": candidate_rows,
        "low_value_rows": low_value_rows,
        "result_index_rows": result_index_rows,
        "row_quality_rows": row_quality_rows,
    }


def build_row_quality_summary(metadata: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    row_quality_rows = list(metadata.get("row_quality_rows") or [])
    main_result_rows = sum(1 for row in row_quality_rows if row.get("target_sheet") == MAIN_TARGET)
    candidate_result_rows = sum(1 for row in row_quality_rows if row.get("target_sheet") == CANDIDATE_TARGET)
    low_value_table_rows = sum(1 for row in row_quality_rows if row.get("target_sheet") == LOW_VALUE_TARGET)
    useful_main_rows = sum(
        1
        for row in row_quality_rows
        if row.get("target_sheet") == MAIN_TARGET
        and int(row.get("treatment_nonblank_count") or 0) >= 1
        and (int(row.get("content_core_nonblank_count") or 0) >= 1 or bool(row.get("has_treatment_context")))
    )
    total_split_rows = main_result_rows + candidate_result_rows + low_value_table_rows
    manual_review_rows_before = total_split_rows * len(EXCEL_HEADERS)
    manual_review_rows_after = len(metadata.get("review_rows") or [])
    return {
        "main_result_rows": main_result_rows,
        "candidate_result_rows": candidate_result_rows,
        "low_value_table_rows": low_value_table_rows,
        "useful_main_rows": useful_main_rows,
        "useful_rows_ratio": useful_main_rows / max(main_result_rows, 1),
        "row_noise_ratio": low_value_table_rows / max(total_split_rows, 1),
        "top_noisy_records": _top_noisy_records(row_quality_rows),
        "manual_review_rows_before": manual_review_rows_before,
        "manual_review_rows_after": manual_review_rows_after,
    }


def _target_for_row(
    *,
    is_table_row: bool,
    table_type: str,
    table_confidence: float,
    treatment_nonblank_count: int,
    content_core_nonblank_count: int,
    has_treatment_context: bool,
) -> tuple[str, str, str]:
    if table_type in OBVIOUS_NOISE_TABLE_TYPES:
        return LOW_VALUE_TARGET, "low", f"obvious noise table: {table_type}"
    has_treatment_signal = treatment_nonblank_count >= 1 or has_treatment_context
    if table_type == "unknown_table" and is_table_row:
        if (
            treatment_nonblank_count >= 1
            and has_treatment_context
            and content_core_nonblank_count >= 1
            and table_confidence >= 0.45
        ):
            return MAIN_TARGET, "high", "unknown table met strict treatment/context/core criteria"
        if has_treatment_signal:
            return CANDIDATE_TARGET, "medium", "unknown table kept for manual candidate review"
        return LOW_VALUE_TARGET, "low", "unknown table without treatment signal"
    if (
        treatment_nonblank_count >= 1
        and (content_core_nonblank_count >= 1 or has_treatment_context)
        and (not is_table_row or table_confidence >= 0.45)
    ):
        return MAIN_TARGET, "high", "treatment field plus core/context evidence"
    if has_treatment_signal:
        return CANDIDATE_TARGET, "medium", "has treatment field or treatment context but not enough for main"
    return LOW_VALUE_TARGET, "low", "no treatment field or treatment context"


def _quality_internal_meta(row: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in row.items() if str(key).startswith("_")}


def _record_source(record: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "source_id": record.get("_source_id") or record.get("SourceURL") or "",
        "info_id": record.get("info_id") or (record.get("_direct_fields") or {}).get("info_id") or "",
        "title": record.get("Title") or record.get("title") or "",
        "source_url": record.get("SourceURL") or record.get("source_url") or "",
    }


def _candidate_row(mapped: Dict[str, Any], source: Dict[str, Any], row: Dict[str, Any], quality: RowQualityResult) -> Dict[str, Any]:
    return {
        **mapped,
        "row_quality_level": quality.row_quality_level,
        "row_quality_reason": quality.row_quality_reason,
        "has_treatment_context": quality.has_treatment_context,
        "has_treatment_context_source": quality.has_treatment_context_source,
        "table_type": quality.table_type,
        "table_confidence": round(quality.table_confidence, 6),
        "table_confidence_level": quality.table_confidence_level,
        **source,
        "mapped_values_json": quality.mapped_values_json,
    }


def _low_value_row(mapped: Dict[str, Any], source: Dict[str, Any], row: Dict[str, Any], quality: RowQualityResult) -> Dict[str, Any]:
    return {
        **source,
        "table_index": row.get("_table_index", ""),
        "row_index": row.get("_row_index", ""),
        "table_type": quality.table_type,
        "table_confidence": round(quality.table_confidence, 6),
        "table_confidence_level": quality.table_confidence_level,
        "headers": row.get("_headers", ""),
        "row_text": row.get("_row_text", _row_text(row, mapped)),
        "mapped_values_json": quality.mapped_values_json,
        "reason": quality.row_quality_reason,
    }


def _result_index_row(source: Dict[str, Any], row: Dict[str, Any], quality: RowQualityResult, target_row_index: int) -> Dict[str, Any]:
    return {
        "result_row_index": target_row_index,
        **source,
        "extraction_source": row.get("_extraction_source", row.get("_source", "")),
        "table_index": row.get("_table_index", ""),
        "row_index": row.get("_row_index", ""),
        "table_type": quality.table_type,
        "table_confidence": round(quality.table_confidence, 6),
        "table_confidence_level": quality.table_confidence_level,
        "row_quality_level": quality.row_quality_level,
        "row_quality_reason": quality.row_quality_reason,
        "has_treatment_context_source": quality.has_treatment_context_source,
        "target_sheet": quality.target_sheet,
    }


def _top_noisy_records(row_quality_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[tuple[str, str], Dict[str, Any]] = {}
    for row in row_quality_rows:
        key = (str(row.get("source_id") or ""), str(row.get("info_id") or ""))
        item = grouped.setdefault(
            key,
            {
                "source_id": row.get("source_id", ""),
                "info_id": row.get("info_id", ""),
                "title": row.get("title", ""),
                "main_rows": 0,
                "candidate_rows": 0,
                "low_value_rows": 0,
                "reasons": {},
            },
        )
        target = row.get("target_sheet")
        if target == MAIN_TARGET:
            item["main_rows"] += 1
        elif target == CANDIDATE_TARGET:
            item["candidate_rows"] += 1
        elif target == LOW_VALUE_TARGET:
            item["low_value_rows"] += 1
            reason = str(row.get("table_type") or row.get("row_quality_reason") or "")
            item["reasons"][reason] = item["reasons"].get(reason, 0) + 1
    noisy = sorted(grouped.values(), key=lambda item: item["low_value_rows"], reverse=True)
    result = []
    for item in noisy[:10]:
        reasons = sorted(item.pop("reasons").items(), key=lambda pair: pair[1], reverse=True)
        item["reason"] = "/".join(reason for reason, _count in reasons[:3])
        result.append(item)
    return result


def _count_nonblank(row: Dict[str, Any], fields: set[str]) -> int:
    return sum(1 for field in fields if _nonblank(row.get(field)))


def _nonblank(value: Any) -> bool:
    return str(value or "").strip().lower() not in EMPTY_VALUES


def _is_table_row(row: Dict[str, Any]) -> bool:
    return _nonblank(row.get("_table_index")) or str(row.get("_extraction_source") or "") == "table"


def _float(value: Any, default: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except Exception:
        return default


def _row_text(row: Dict[str, Any], mapped: Dict[str, Any]) -> str:
    parts = [
        str(row.get("_row_text") or ""),
        str(row.get("_headers") or ""),
        str(row.get("_caption") or ""),
    ]
    parts.extend(str(mapped.get(field) or "") for field in EXCEL_HEADERS)
    return " ".join(part for part in parts if part)


def _has_amount_or_ratio(text: str) -> bool:
    return bool(
        re.search(r"\d+(?:\.\d+)?\s*[%％]", str(text or ""))
        or re.search(r"\d+(?:\.\d+)?\s*(?:元|万元|万|人民币)", str(text or ""))
        or "百分之" in str(text or "")
    )


def _treatment_context_sources(row: Dict[str, Any], mapped: Dict[str, Any], row_text: str) -> List[str]:
    sources: List[str] = []
    if _count_nonblank(mapped, CONTENT_CORE_FIELDS) >= 1:
        sources.append("field")
    checks = [
        ("header", row.get("_headers") or row.get("_header_path") or ""),
        ("caption", row.get("_caption") or ""),
        ("parent_title", row.get("_parent_title") or ""),
        ("nearby_text", row.get("_nearby_text") or row_text),
    ]
    for source, text in checks:
        if _contains_context(text):
            sources.append(source)
    return list(dict.fromkeys(sources))


def _contains_context(text: Any) -> bool:
    value = str(text or "")
    return any(keyword in value for keyword in TREATMENT_CONTEXT_KEYWORDS)


TREATMENT_CONTEXT_KEYWORDS = [
    "住院",
    "门诊",
    "特药",
    "药品",
    "医疗费用",
    "医保内",
    "医保外",
    "保障责任",
    "保障项目",
    "责任",
    "人群",
    "人员",
    "医院",
    "病种",
    "疾病",
    "赔付",
    "报销",
    "给付",
    "补偿",
    "待遇",
    "免赔",
    "起付",
    "限额",
]
