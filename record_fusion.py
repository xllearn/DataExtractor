from typing import Any, Dict, List, Sequence

from extraction_types import FusionResult
from field_mapping import FieldMapping, apply_direct_fields, normalize_record_fields
from field_cleaners import (
    INTERVAL_FIELD,
    NOTE_FIELD,
    PERSON_TYPE_FIELD,
    age_range_note,
    append_note,
    extract_reimbursement_interval,
    invalid_person_type_note,
    is_age_range,
    normalize_person_type,
)
from record_alignment import align_candidate_records, align_sources
from rule_extractor import is_valid_disease_name, normalize_disease_name


SOURCE_PRIORITY = ["database_direct", "table", "text_rule", "llm"]
DISEASE_FIELD = "病种名称"
GENERIC_REGION_VALUES = {"国家", "全国", "中国"}


def _meaningful(value: Any) -> bool:
    return value not in (None, "", "--")


def _source_id(record: Dict[str, Any]) -> str:
    return str(record.get("_source_id") or record.get("SourceURL") or "")


def _info_id(record: Dict[str, Any]) -> str:
    return str(record.get("info_id") or (record.get("_direct_fields") or {}).get("info_id") or "")


def align_records_by_similarity(base_records: Sequence[Dict[str, Any]], candidate_records: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    aligned, _evidence = align_candidate_records(base_records, candidate_records, "base", "candidate")
    return aligned


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
        if field == "地区名称" and str(value).strip() in GENERIC_REGION_VALUES:
            continue
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
        if field in field_mapping.headers and _meaningful(value) and not (field == "地区名称" and str(value).strip() in GENERIC_REGION_VALUES)
    }


def _mark_chosen(evidence: List[Dict[str, Any]], chosen_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    marked: List[Dict[str, Any]] = []
    chosen_pairs = {(field, str(value)) for row in chosen_rows for field, value in row.items() if _meaningful(value)}
    for item in evidence:
        copied = dict(item)
        copied["chosen"] = (copied.get("field"), str(copied.get("value"))) in chosen_pairs
        marked.append(copied)
    return marked


def _conflict(
    record: Dict[str, Any],
    row_index: int,
    field: str,
    source_a: str,
    value_a: Any,
    source_b: str,
    value_b: Any,
    chosen_source: str,
    chosen_value: Any,
    reason: str,
) -> Dict[str, Any]:
    return {
        "source_id": _source_id(record),
        "info_id": _info_id(record),
        "row_index": row_index,
        "field": field,
        "rule_value": value_a,
        "llm_value": value_b,
        "chosen_value": chosen_value,
        "reason": reason,
        "rule_source": source_a,
        "llm_source": source_b,
        "source_a": source_a,
        "value_a": value_a,
        "source_b": source_b,
        "value_b": value_b,
        "chosen_source": chosen_source,
    }


def _append_redirect_note(chosen: Dict[str, Any], note: str) -> None:
    if note:
        chosen[NOTE_FIELD] = append_note(chosen.get(NOTE_FIELD), note)


def _clean_field_value(
    record: Dict[str, Any],
    row_index: int,
    field: str,
    source: str,
    value: Any,
    chosen: Dict[str, Any],
) -> tuple[bool, Any, List[Dict[str, Any]]]:
    conflicts: List[Dict[str, Any]] = []
    if field == PERSON_TYPE_FIELD:
        normalized = normalize_person_type(value)
        if normalized:
            return True, normalized, conflicts
        note = invalid_person_type_note(value)
        _append_redirect_note(chosen, note)
        conflicts.append(
            _conflict(
                record,
                row_index,
                field,
                source,
                value,
                "cleaner",
                "",
                "cleaner",
                "",
                "人员类型特殊规则：年龄范围或纯数字不是人员类型，已转入备注或清空",
            )
        )
        return False, "", conflicts
    if field == INTERVAL_FIELD:
        if is_age_range(value):
            note = age_range_note(value)
            _append_redirect_note(chosen, note)
            conflicts.append(
                _conflict(
                    record,
                    row_index,
                    field,
                    source,
                    value,
                    "cleaner",
                    "",
                    "cleaner",
                    "",
                    "区间特殊规则：区间只用于报销金额区间，年龄范围已转入备注",
                )
            )
            return False, "", conflicts
        return True, extract_reimbursement_interval(value) or value, conflicts
    return True, value, conflicts


def _sanitize_final_row(
    record: Dict[str, Any],
    row: Dict[str, Any],
    field_mapping: FieldMapping,
    row_index: int,
) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    cleaned = dict(row or {})
    conflicts: List[Dict[str, Any]] = []
    person_value = cleaned.get(PERSON_TYPE_FIELD)
    if _meaningful(person_value) and not normalize_person_type(person_value):
        note = invalid_person_type_note(person_value)
        cleaned[NOTE_FIELD] = append_note(cleaned.get(NOTE_FIELD), note)
        cleaned[PERSON_TYPE_FIELD] = ""
        conflicts.append(
            _conflict(
                record,
                row_index,
                PERSON_TYPE_FIELD,
                "final_row",
                person_value,
                "cleaner",
                "",
                "cleaner",
                "",
                "人员类型特殊规则：最终行中的年龄范围或纯数字已清空",
            )
        )
    interval_value = cleaned.get(INTERVAL_FIELD)
    if _meaningful(interval_value) and is_age_range(interval_value):
        note = age_range_note(interval_value)
        cleaned[NOTE_FIELD] = append_note(cleaned.get(NOTE_FIELD), note)
        cleaned[INTERVAL_FIELD] = ""
        conflicts.append(
            _conflict(
                record,
                row_index,
                INTERVAL_FIELD,
                "final_row",
                interval_value,
                "cleaner",
                "",
                "cleaner",
                "",
                "区间特殊规则：最终行中的年龄范围已转入备注",
            )
        )
    return normalize_record_fields(cleaned, field_mapping), conflicts


def _choose_disease_name(
    record: Dict[str, Any],
    candidates: List[tuple[str, Any]],
    row_index: int,
) -> tuple[str, str, List[Dict[str, Any]]]:
    meaningful_candidates = [(source, str(value).strip()) for source, value in candidates if _meaningful(value)]
    if not meaningful_candidates:
        return "", "", []

    for source, value in meaningful_candidates:
        if source in {"database_direct", "table"}:
            return value, source, []

    text_value = next((value for source, value in meaningful_candidates if source == "text_rule"), "")
    llm_value = next((value for source, value in meaningful_candidates if source == "llm"), "")
    text_normalized = normalize_disease_name(text_value)
    llm_normalized = normalize_disease_name(llm_value)

    conflicts: List[Dict[str, Any]] = []
    if text_value and llm_value:
        if llm_normalized and is_valid_disease_name(llm_value) and (llm_value in text_value or text_normalized == llm_value):
            conflicts.append(
                _conflict(
                    record,
                    row_index,
                    DISEASE_FIELD,
                    "text_rule",
                    text_value,
                    "llm",
                    llm_value,
                    "llm",
                    llm_value,
                    "病种名称特殊规则：LLM值为规则长句中的核心疾病名，优先采用LLM",
                )
            )
            return llm_value, "llm", conflicts
        if not text_normalized and llm_normalized and is_valid_disease_name(llm_value):
            conflicts.append(
                _conflict(
                    record,
                    row_index,
                    DISEASE_FIELD,
                    "text_rule",
                    text_value,
                    "llm",
                    llm_value,
                    "llm",
                    llm_value,
                    "病种名称特殊规则：正文规则值不可信，优先采用有效LLM值",
                )
            )
            return llm_value, "llm", conflicts
        if not text_normalized and not llm_normalized:
            conflicts.append(
                _conflict(
                    record,
                    row_index,
                    DISEASE_FIELD,
                    "text_rule",
                    text_value,
                    "llm",
                    llm_value,
                    "cleared",
                    "",
                    "病种名称规则和LLM均不可信",
                )
            )
            return "", "cleared", conflicts

    if text_normalized:
        if text_value != text_normalized:
            conflicts.append(
                _conflict(
                    record,
                    row_index,
                    DISEASE_FIELD,
                    "text_rule",
                    text_value,
                    "normalizer",
                    text_normalized,
                    "text_rule",
                    text_normalized,
                    "病种名称特殊规则：正文规则长句清洗为核心疾病名",
                )
            )
        return text_normalized, "text_rule", conflicts

    if llm_normalized and is_valid_disease_name(llm_value):
        return llm_value, "llm", conflicts

    source_a, value_a = meaningful_candidates[0]
    source_b, value_b = meaningful_candidates[1] if len(meaningful_candidates) > 1 else ("", "")
    conflicts.append(
        _conflict(
            record,
            row_index,
            DISEASE_FIELD,
            source_a,
            value_a,
            source_b,
            value_b,
            "cleared",
            "",
            "病种名称规则和LLM均不可信",
        )
    )
    return "", "cleared", conflicts


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
            if field == DISEASE_FIELD:
                continue
            keep_value, cleaned_value, clean_conflicts = _clean_field_value(record, row_index, field, source, value, chosen)
            conflicts.extend(clean_conflicts)
            if not keep_value:
                continue
            value = cleaned_value
            if field not in chosen:
                chosen[field] = value
                chosen_source[field] = source
            elif str(chosen[field]) != str(value):
                conflicts.append(
                    _conflict(
                        record,
                        row_index,
                        field,
                        chosen_source[field],
                        chosen[field],
                        source,
                        value,
                        chosen_source[field],
                        chosen[field],
                        f"{chosen_source[field]} 优先于 {source}，保留高优先级值",
                    )
                )

    disease_candidates = [
        (source, normalize_record_fields(row or {}, field_mapping).get(DISEASE_FIELD))
        for source, row in source_rows
    ]
    disease_value, disease_source, disease_conflicts = _choose_disease_name(record, disease_candidates, row_index)
    if _meaningful(disease_value):
        chosen[DISEASE_FIELD] = disease_value
        chosen_source[DISEASE_FIELD] = disease_source
    conflicts.extend(disease_conflicts)

    normalized_chosen = normalize_record_fields(chosen, field_mapping)
    final_row = apply_direct_fields(normalized_chosen, record, field_mapping)
    final_row, final_conflicts = _sanitize_final_row(record, final_row, field_mapping, row_index)
    final_row.update(_source_metadata(source_rows))
    conflicts.extend(final_conflicts)
    return final_row, conflicts


def _source_metadata(source_rows: List[tuple[str, Dict[str, Any]]]) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {}
    for source, row in source_rows:
        if not row:
            continue
        for key, value in row.items():
            if str(key).startswith("_") and value not in (None, "") and key not in metadata:
                metadata[key] = value
        if source and "_extraction_source" not in metadata and any(str(key).startswith("_table_") for key in row):
            metadata["_extraction_source"] = source
    return metadata


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
    base_source, _initial_base = _base_records(table_records, text_rule_records, llm_records)
    base, aligned_sources, row_match_evidence = align_sources(table_records, text_rule_records, llm_records)
    aligned_table = aligned_sources["table"]
    aligned_text = aligned_sources["text_rule"]
    aligned_llm = aligned_sources["llm"]

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
        for reason in [str(item.get("reason", "")) for item in conflicts if item.get("field") == DISEASE_FIELD]:
            if reason and reason not in review_reasons:
                review_reasons.append(reason)
    if (table_records or text_rule_records) and llm_records and len(base) != len(llm_records):
        review_reasons.append("规则记录和 LLM 记录数量不一致，需要人工复核")

    return FusionResult(
        records=fused_rows,
        field_evidence=_mark_chosen(evidence, fused_rows),
        conflict_evidence=conflicts,
        row_match_evidence=row_match_evidence,
        need_manual_review=bool(review_reasons),
        review_reason="；".join(review_reasons),
    )
