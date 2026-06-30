from typing import Any, Dict, List, Sequence

from extraction_types import FusionResult
from field_mapping import FieldMapping, apply_direct_fields, normalize_record_fields


SOURCE_PRIORITY = ["database_direct", "table", "text_rule", "llm"]


def _meaningful(value: Any) -> bool:
    return value not in (None, "", "--")


def _source_id(record: Dict[str, Any]) -> str:
    return str(record.get("_source_id") or record.get("SourceURL") or "")


def _info_id(record: Dict[str, Any]) -> str:
    return str(record.get("info_id") or (record.get("_direct_fields") or {}).get("info_id") or "")


def align_records_by_similarity(base_records: Sequence[Dict[str, Any]], candidate_records: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [candidate_records[index] if index < len(candidate_records) else {} for index in range(len(base_records))]


def _base_records(table_records: List[Dict[str, Any]], text_rule_records: List[Dict[str, Any]], llm_records: List[Dict[str, Any]]) -> tuple[str, List[Dict[str, Any]]]:
    if table_records:
        return "table", list(table_records)
    if text_rule_records:
        return "text_rule", list(text_rule_records)
    if llm_records:
        return "llm", list(llm_records)
    return "default", [{}]


def _direct_field_evidence(record: Dict[str, Any], field_mapping: FieldMapping) -> List[Dict[str, Any]]:
    evidence: List[Dict[str, Any]] = []
    for field, value in (record.get("_direct_fields") or {}).items():
        if field in field_mapping.headers and _meaningful(value):
            evidence.append(
                {
                    "source_id": _source_id(record),
                    "info_id": _info_id(record),
                    "field": field,
                    "value": value,
                    "evidence": f"direct_field_columns: {field}={value}",
                    "confidence": 1.0,
                    "source": "database_direct",
                    "rule_name": "direct_field_columns",
                }
            )
    return evidence


def _direct_row(record: Dict[str, Any], field_mapping: FieldMapping) -> Dict[str, Any]:
    return {
        field: value
        for field, value in (record.get("_direct_fields") or {}).items()
        if field in field_mapping.headers and _meaningful(value)
    }


def _mark_chosen(evidence: List[Dict[str, Any]], chosen_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    marked: List[Dict[str, Any]] = []
    chosen_pairs = {(field, str(value)) for row in chosen_rows for field, value in row.items() if _meaningful(value)}
    for item in evidence:
        copied = dict(item)
        copied["chosen"] = (copied.get("field"), str(copied.get("value"))) in chosen_pairs
        marked.append(copied)
    return marked


def _merge_row(
    record: Dict[str, Any],
    source_rows: List[tuple[str, Dict[str, Any]]],
    field_mapping: FieldMapping,
    row_index: int,
) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    chosen: Dict[str, Any] = {}
    chosen_source: Dict[str, str] = {}
    conflicts: List[Dict[str, Any]] = []

    for source, row in source_rows:
        normalized = normalize_record_fields(row or {}, field_mapping)
        for field in field_mapping.headers:
            value = normalized.get(field)
            if not _meaningful(value):
                continue
            if field not in chosen:
                chosen[field] = value
                chosen_source[field] = source
            elif str(chosen[field]) != str(value):
                conflicts.append(
                    {
                        "source_id": _source_id(record),
                        "info_id": _info_id(record),
                        "row_index": row_index,
                        "field": field,
                        "rule_value": chosen[field],
                        "llm_value": value,
                        "chosen_value": chosen[field],
                        "reason": f"{chosen_source[field]} 优先于 {source}，保留高优先级值",
                        "rule_source": chosen_source[field],
                        "llm_source": source,
                        "source_a": chosen_source[field],
                        "value_a": chosen[field],
                        "source_b": source,
                        "value_b": value,
                        "chosen_source": chosen_source[field],
                    }
                )

    normalized_chosen = normalize_record_fields(chosen, field_mapping)
    return apply_direct_fields(normalized_chosen, record, field_mapping), conflicts


def fuse_record_sources(
    record: Dict[str, Any],
    table_records: List[Dict[str, Any]],
    text_rule_records: List[Dict[str, Any]],
    llm_records: List[Dict[str, Any]],
    table_evidence: List[Dict[str, Any]],
    text_rule_evidence: List[Dict[str, Any]],
    llm_evidence: List[Dict[str, Any]],
    field_mapping: FieldMapping,
) -> FusionResult:
    base_source, base = _base_records(table_records, text_rule_records, llm_records)
    if llm_records and len(llm_records) > len(base):
        base = [*base, *llm_records[len(base) :]]

    aligned_table = align_records_by_similarity(base, table_records)
    aligned_text = align_records_by_similarity(base, text_rule_records)
    aligned_llm = align_records_by_similarity(base, llm_records)

    fused_rows: List[Dict[str, Any]] = []
    conflicts: List[Dict[str, Any]] = []
    for index, _base_row in enumerate(base):
        source_rows = [
            ("database_direct", _direct_row(record, field_mapping)),
            ("table", aligned_table[index] if index < len(aligned_table) else {}),
            ("text_rule", aligned_text[index] if index < len(aligned_text) else {}),
            ("llm", aligned_llm[index] if index < len(aligned_llm) else {}),
        ]
        if base_source == "llm":
            source_rows = [("database_direct", _direct_row(record, field_mapping)), ("llm", aligned_llm[index] if index < len(aligned_llm) else {})]
        row, row_conflicts = _merge_row(record, source_rows, field_mapping, index + 1)
        fused_rows.append(row)
        conflicts.extend(row_conflicts)

    evidence = [
        *_direct_field_evidence(record, field_mapping),
        *table_evidence,
        *text_rule_evidence,
        *llm_evidence,
    ]
    review_reasons: List[str] = []
    if conflicts:
        details = "、".join(
            f"{item['field']}({item['source_a']}={item['value_a']}, {item['source_b']}={item['value_b']})"
            for item in conflicts
        )
        review_reasons.append(f"不同来源字段存在冲突：{details}")
    if (table_records or text_rule_records) and llm_records and len(base) != len(llm_records):
        review_reasons.append("规则记录和 LLM 记录数量不一致，需要人工复核")

    return FusionResult(
        records=fused_rows,
        field_evidence=_mark_chosen(evidence, fused_rows),
        conflict_evidence=conflicts,
        need_manual_review=bool(review_reasons),
        review_reason="；".join(review_reasons),
    )
