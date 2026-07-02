from typing import Any, Dict, List, Sequence


CORE_FIELDS = ["病种名称", "报销比例", "起付标准", "补助限额", "人员类型", "保险类型", "类型"]
SOURCE_BASE = {
    "database_direct": 0.98,
    "table": 0.86,
    "text_rule": 0.76,
    "external_ocr_text": 0.68,
    "llm": 0.64,
}
EMPTY_VALUES = {"", "--", "none", "null", "nan"}


def _meaningful(value: Any) -> bool:
    return str(value or "").strip().lower() not in EMPTY_VALUES


def _row_matches(item: Dict[str, Any], row_index: int) -> bool:
    item_row = item.get("output_row_index") or item.get("final_row_index")
    if item_row in (None, ""):
        return True
    try:
        return int(item_row) == row_index
    except Exception:
        return False


def _conflict_row_matches(item: Dict[str, Any], row_index: int) -> bool:
    item_row = item.get("output_row_index") or item.get("final_row_index") or item.get("row_index")
    if item_row in (None, ""):
        return True
    try:
        return int(item_row) == row_index
    except Exception:
        return False


def _matching_evidence(field: str, value: Any, row_index: int, evidence: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    value_text = str(value or "")
    return [
        item
        for item in evidence
        if item.get("field") == field
        and _row_matches(item, row_index)
        and (not value_text or not item.get("value") or str(item.get("value")) == value_text)
    ]


def _matching_conflicts(field: str, row_index: int, conflicts: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [item for item in conflicts if item.get("field") == field and _conflict_row_matches(item, row_index)]


def _confidence_for(value: Any, evidences: List[Dict[str, Any]], conflicts: List[Dict[str, Any]], field: str) -> tuple[float, str]:
    if not _meaningful(value):
        reason = "核心字段缺失" if field in CORE_FIELDS else "字段为空"
        return (0.4 if field in CORE_FIELDS else 0.55), reason

    sources = [str(item.get("source") or "") for item in evidences if item.get("source")]
    base = max((SOURCE_BASE.get(source, 0.6) for source in sources), default=0.58)
    score = base + min(0.12, max(0, len(set(sources)) - 1) * 0.06)
    if any(item.get("table_index") and item.get("col_index") for item in evidences):
        score += 0.04
    if conflicts:
        score -= min(0.35, len(conflicts) * 0.18)
    score = max(0.0, min(0.99, score))

    reasons: List[str] = []
    if len(set(sources)) > 1:
        reasons.append("多来源一致")
    if any(item.get("table_index") and item.get("col_index") for item in evidences):
        reasons.append("表格坐标证据明确")
    if conflicts:
        reasons.append("存在冲突")
    if not reasons:
        reasons.append("单来源证据")
    return score, "；".join(reasons)


def calculate_field_confidence(
    rows: Sequence[Dict[str, Any]],
    evidence: Sequence[Dict[str, Any]],
    conflicts: Sequence[Dict[str, Any]],
    collection_logs: Sequence[Dict[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    confidence_rows: List[Dict[str, Any]] = []
    for row_index, row in enumerate(rows, start=1):
        fields = list(dict.fromkeys([*row.keys(), *CORE_FIELDS]))
        for field in fields:
            value = row.get(field, "")
            evidences = _matching_evidence(field, value, row_index, evidence)
            field_conflicts = _matching_conflicts(field, row_index, conflicts)
            score, reason = _confidence_for(value, evidences, field_conflicts, field)
            sources = sorted({str(item.get("source") or "") for item in evidences if item.get("source")})
            confidence_rows.append(
                {
                    "row_index": row_index,
                    "field": field,
                    "value": value,
                    "confidence": round(score, 4),
                    "source": ",".join(sources),
                    "evidence_count": len(evidences),
                    "conflict_count": len(field_conflicts),
                    "reason": reason,
                    "evidence": " | ".join(str(item.get("evidence") or "") for item in evidences if item.get("evidence")),
                    "evidence_ids": ",".join(str(item.get("evidence_id") or "") for item in evidences if item.get("evidence_id")),
                }
            )
    return confidence_rows


def build_review_rows(
    rows: Sequence[Dict[str, Any]],
    confidence_rows: Sequence[Dict[str, Any]],
    conflicts: Sequence[Dict[str, Any]],
    collection_logs: Sequence[Dict[str, Any]] | None = None,
    low_confidence_threshold: float = 0.7,
) -> List[Dict[str, Any]]:
    review_rows: List[Dict[str, Any]] = []
    log = (collection_logs or [{}])[0] if collection_logs is not None else {}
    conflict_keys = {(int(item.get("row_index") or 1), item.get("field")) for item in conflicts}
    conflict_reasons = {
        (int(item.get("row_index") or 1), item.get("field")): str(item.get("reason") or "")
        for item in conflicts
    }
    for item in confidence_rows:
        row_index = int(item.get("row_index") or 1)
        field = item.get("field")
        confidence = float(item.get("confidence") or 0)
        low_confidence = confidence < low_confidence_threshold
        conflict_key = (row_index, field)
        has_conflict = conflict_key in conflict_keys
        missing_core = field in CORE_FIELDS and not _meaningful(item.get("value"))
        if not (low_confidence or has_conflict or missing_core):
            continue
        reason_parts = []
        if item.get("reason"):
            reason_parts.append(str(item.get("reason")))
        if has_conflict:
            reason_parts.append(conflict_reasons.get(conflict_key, "冲突"))
        review_rows.append(
            {
                "row_index": row_index,
                "field": field,
                "value": item.get("value", ""),
                "confidence": confidence,
                "reason": "；".join(part for part in reason_parts if part),
                "suggested_action": "补充或确认字段" if missing_core or low_confidence else "确认冲突取值",
                "title": log.get("title", ""),
                "source_url": log.get("source_url", ""),
                "evidence": item.get("evidence", ""),
            }
        )
    return review_rows
