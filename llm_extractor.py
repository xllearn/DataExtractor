from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from field_mapping import FieldMapping, apply_direct_fields, normalize_record_fields
from json_utils import parse_llm_json, save_failed_llm_output
from utils import apply_default_mappings, create_fallback_row


@dataclass
class LlmExtractionResult:
    records: List[Dict[str, Any]] = field(default_factory=list)
    evidence: Dict[str, Any] = field(default_factory=dict)
    confidence: Dict[str, float] = field(default_factory=dict)
    need_manual_review: bool = False
    review_reason: str = ""
    raw_output: str = ""
    parse_error: str = ""


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on", "是"}
    return bool(value)


def _clamp_confidence(confidence: Any) -> Dict[str, float]:
    if not isinstance(confidence, dict):
        return {}
    result: Dict[str, float] = {}
    for key, value in confidence.items():
        try:
            number = float(value)
        except Exception:
            continue
        result[str(key)] = max(0.0, min(1.0, number))
    return result


def _clamp_number(value: Any, default: float = 0.6) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except Exception:
        return default


def _items_from_parsed(parsed: Any) -> tuple[List[Dict[str, Any]], Dict[str, Any], Dict[str, float], bool, str]:
    if isinstance(parsed, dict) and isinstance(parsed.get("records"), list):
        records = [item for item in parsed["records"] if isinstance(item, dict)]
        evidence = parsed.get("evidence") if isinstance(parsed.get("evidence"), dict) else {}
        confidence = _clamp_confidence(parsed.get("confidence"))
        need_manual_review = _coerce_bool(parsed.get("need_manual_review", False))
        review_reason = str(parsed.get("review_reason", "") or "")
        return records, evidence, confidence, need_manual_review, review_reason
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)], {}, {}, False, ""
    if isinstance(parsed, dict):
        return [parsed], {}, {}, False, ""
    return [], {}, {}, False, ""


def _normalize_items(items: List[Dict[str, Any]], record: Dict[str, Any], today: str, field_mapping: FieldMapping) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for item in items:
        row = normalize_record_fields(item, field_mapping)
        row = apply_default_mappings(row, record, today)
        rows.append(apply_direct_fields(row, record, field_mapping))
    if not rows:
        rows.append(apply_direct_fields(create_fallback_row(record, today), record, field_mapping))
    return rows


def parse_llm_extraction(
    raw_output: str,
    record: Dict[str, Any],
    today: str,
    logs_dir: Path,
    field_mapping: FieldMapping,
) -> LlmExtractionResult:
    raw_text = "" if raw_output is None else str(raw_output)
    try:
        parsed = parse_llm_json(raw_text)
        items, evidence, confidence, need_manual_review, review_reason = _items_from_parsed(parsed)
        return LlmExtractionResult(
            records=_normalize_items(items, record, today, field_mapping),
            evidence=evidence,
            confidence=confidence,
            need_manual_review=need_manual_review,
            review_reason=review_reason,
            raw_output=raw_text,
        )
    except Exception as exc:
        save_failed_llm_output(raw_text, logs_dir)
        return LlmExtractionResult(
            records=[apply_direct_fields(create_fallback_row(record, today), record, field_mapping)],
            raw_output=raw_text,
            parse_error=str(exc),
            need_manual_review=True,
            review_reason=f"LLM JSON 解析失败: {exc}",
        )


def extract_with_llm(
    llm_client,
    prompt: str,
    record: Dict[str, Any],
    today: str,
    logs_dir: Path,
    field_mapping: FieldMapping,
) -> LlmExtractionResult:
    raw_output = llm_client.extract(prompt)
    return parse_llm_extraction(raw_output, record, today, logs_dir, field_mapping)


def llm_result_to_field_evidence(
    llm_result: LlmExtractionResult,
    source_id: str,
    info_id: str,
    attempt: str = "",
) -> List[Dict[str, Any]]:
    evidence_rows: List[Dict[str, Any]] = []
    seen = set()
    for record in llm_result.records:
        for field, value in record.items():
            if value in (None, "", "--"):
                continue
            key = (field, str(value))
            if key in seen:
                continue
            seen.add(key)
            evidence_rows.append(
                {
                    "source_id": source_id,
                    "info_id": info_id,
                    "field": field,
                    "value": value,
                    "evidence": str(llm_result.evidence.get(field, "") if isinstance(llm_result.evidence, dict) else ""),
                    "confidence": _clamp_number(llm_result.confidence.get(field, 0.6) if isinstance(llm_result.confidence, dict) else 0.6),
                    "source": "llm",
                    "rule_name": "llm_v2",
                    "attempt": attempt,
                }
            )
    return evidence_rows
