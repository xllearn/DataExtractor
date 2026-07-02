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
REVIEW_THRESHOLD = 0.7
REVIEW_STATUSES = {"pending", "confirmed"}


def _meaningful(value: Any) -> bool:
    return str(value or "").strip().lower() not in EMPTY_VALUES


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except Exception:
        return None


def _truthy_false(value: Any) -> bool:
    return value is False or str(value).strip().lower() in {"false", "0", "no"}


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


def _row_match_row_matches(item: Dict[str, Any], row_index: int) -> bool:
    item_row = item.get("row_a") or item.get("output_row_index") or item.get("final_row_index") or item.get("row_index")
    if item_row in (None, ""):
        return True
    try:
        return int(item_row) == row_index
    except Exception:
        return False


def _attempt_matches(item: Dict[str, Any], attempt: str) -> bool:
    item_attempt = str(item.get("attempt") or "").strip()
    return not attempt or not item_attempt or item_attempt == attempt


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


def _latest_log(collection_logs: Sequence[Dict[str, Any]] | None) -> Dict[str, Any]:
    logs = [item for item in (collection_logs or []) if isinstance(item, dict)]
    return logs[-1] if logs else {}


def _log_attempt(log: Dict[str, Any]) -> str:
    return str(log.get("final_attempt") or log.get("attempt") or "").strip()


def _log_adjustments(log: Dict[str, Any]) -> List[tuple[float, str]]:
    adjustments: List[tuple[float, str]] = []
    if _as_int(log.get("ocr_failure_count")) > 0 or str(log.get("ocr_failure_reason") or "").strip():
        adjustments.append((-0.10, "OCR failed"))
    if "llm_parse_success" in log and _truthy_false(log.get("llm_parse_success")):
        adjustments.append((-0.20, "LLM parse failed"))

    initial_score = _as_float(log.get("initial_confidence_score"))
    retry_score = _as_float(log.get("ocr_retry_confidence_score"))
    if initial_score is not None and retry_score is not None and retry_score < initial_score:
        adjustments.append((-0.10, "OCR retry confidence down"))

    review_reason = str(log.get("review_reason") or "")
    if (
        "数量不一致" in review_reason
        or "row count mismatch" in review_reason.lower()
        or bool(log.get("row_count_mismatch"))
    ):
        adjustments.append((-0.10, "row count mismatch"))
    return adjustments


def _table_coordinates_found(evidences: Sequence[Dict[str, Any]]) -> bool:
    for item in evidences:
        has_table = item.get("table_index") not in (None, "")
        has_col = item.get("col_index") not in (None, "")
        if has_table and has_col:
            return True
    return False


def _llm_evidence_found(evidences: Sequence[Dict[str, Any]], source_text: str, table_text: str) -> bool:
    combined = f"{source_text or ''}\n{table_text or ''}"
    if not combined.strip():
        return False
    for item in evidences:
        if str(item.get("source") or "").lower() != "llm":
            continue
        candidates = [item.get("evidence"), item.get("cell_text"), item.get("value")]
        for candidate in candidates:
            text = str(candidate or "").strip()
            if text and text in combined:
                return True
    return False


def _review_status(field: str, row: Dict[str, Any], evidences: Sequence[Dict[str, Any]], log: Dict[str, Any]) -> str:
    candidates: List[Any] = [
        row.get("_review_status"),
        row.get("review_status"),
        row.get(f"{field}_review_status"),
        log.get("review_status"),
    ]
    field_statuses = row.get("_field_review_status") or row.get("_field_review_statuses") or {}
    if isinstance(field_statuses, dict):
        candidates.append(field_statuses.get(field))
    candidates.extend(item.get("review_status") for item in evidences)

    for candidate in candidates:
        status = str(candidate or "").strip().lower()
        if status == "confirmed":
            return "confirmed"
    for candidate in candidates:
        status = str(candidate or "").strip().lower()
        if status in REVIEW_STATUSES:
            return status
    return "pending"


def _row_match_info(
    row_index: int,
    attempt: str,
    row_match_evidence: Sequence[Dict[str, Any]] | None,
) -> tuple[str, bool, List[str]]:
    matches = [
        item
        for item in (row_match_evidence or [])
        if _row_match_row_matches(item, row_index) and _attempt_matches(item, attempt)
    ]
    if not matches:
        return "", False, []

    severity = {"below_threshold": 2, "weak": 1, "strong": 0}
    selected = max(matches, key=lambda item: severity.get(str(item.get("match_level") or ""), 1))
    level = str(selected.get("match_level") or "").strip()
    needs_review = any(bool(item.get("needs_review")) for item in matches) or bool(level and level != "strong")
    reasons = ["weak row match"] if needs_review and level != "strong" else []
    return level, needs_review, reasons


def _confidence_for(
    value: Any,
    evidences: List[Dict[str, Any]],
    conflicts: List[Dict[str, Any]],
    field: str,
    log_adjustments: Sequence[tuple[float, str]],
    match_level: str,
    row_needs_review: bool,
    review_status: str,
    source_text: str,
    table_text: str,
) -> tuple[float, str, bool]:
    sources = [str(item.get("source") or "") for item in evidences if item.get("source")]
    source_set = set(sources)
    base = max((SOURCE_BASE.get(source, 0.6) for source in sources), default=0.58)
    score = base
    reasons: List[str] = []

    if not _meaningful(value):
        if field in CORE_FIELDS:
            score -= 0.20
            reasons.append("core field empty")
        else:
            score = 0.55
            reasons.append("field empty")

    if len(source_set) > 1:
        score += 0.10
        reasons.append("multi-source")
    if _table_coordinates_found(evidences):
        score += 0.05
        reasons.append("table coordinates")
    if _llm_evidence_found(evidences, source_text, table_text):
        score += 0.05
        reasons.append("LLM evidence found in source/table text")
    if review_status == "confirmed":
        score += 0.20
        reasons.append("human confirmed")

    if conflicts:
        score -= min(0.35, len(conflicts) * 0.18)
        reasons.append("存在冲突")
    for delta, reason in log_adjustments:
        score += delta
        reasons.append(reason)
    if row_needs_review and match_level != "strong":
        score -= 0.10
        reasons.append("weak row match")

    score = max(0.0, min(1.0, score))
    reason_text = "；".join(dict.fromkeys(part for part in reasons if part))
    if not reason_text:
        reason_text = "single-source evidence" if sources else "no evidence"

    needs_review = (
        review_status != "confirmed"
        and (
            score < REVIEW_THRESHOLD
            or bool(conflicts)
            or (field in CORE_FIELDS and not _meaningful(value))
            or bool(row_needs_review)
            or bool(log_adjustments)
        )
    )
    return score, reason_text, needs_review


def calculate_field_confidence(
    rows: Sequence[Dict[str, Any]],
    evidence: Sequence[Dict[str, Any]],
    conflicts: Sequence[Dict[str, Any]],
    collection_logs: Sequence[Dict[str, Any]] | None = None,
    row_match_evidence: Sequence[Dict[str, Any]] | None = None,
    source_text: str = "",
    table_text: str = "",
) -> List[Dict[str, Any]]:
    confidence_rows: List[Dict[str, Any]] = []
    log = _latest_log(collection_logs)
    attempt = _log_attempt(log)
    log_adjustments = _log_adjustments(log)

    for row_index, row in enumerate(rows, start=1):
        fields = list(dict.fromkeys([*row.keys(), *CORE_FIELDS]))
        match_level, row_needs_review, _row_match_reasons = _row_match_info(row_index, attempt, row_match_evidence)
        for field in fields:
            value = row.get(field, "")
            evidences = _matching_evidence(field, value, row_index, evidence)
            field_conflicts = _matching_conflicts(field, row_index, conflicts)
            status = _review_status(field, row, evidences, log)
            score, reason, needs_review = _confidence_for(
                value,
                evidences,
                field_conflicts,
                field,
                log_adjustments,
                match_level,
                row_needs_review,
                status,
                source_text,
                table_text,
            )
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
                    "match_level": match_level,
                    "needs_review": needs_review,
                    "attempt": attempt,
                    "review_status": status,
                    "reason": reason,
                    "evidence": " | ".join(str(item.get("evidence") or "") for item in evidences if item.get("evidence")),
                    "evidence_ids": ",".join(str(item.get("evidence_id") or "") for item in evidences if item.get("evidence_id")),
                }
            )
    return confidence_rows


def _suggested_action(missing_core: bool, low_confidence: bool, has_conflict: bool, weak_match: bool, reason: str) -> str:
    if missing_core or low_confidence:
        return "补充或确认字段"
    if has_conflict:
        return "确认冲突取值"
    if weak_match:
        return "核对行匹配"
    if "OCR failed" in reason or "LLM parse failed" in reason:
        return "重新抽取或人工确认"
    return "人工确认"


def build_review_rows(
    rows: Sequence[Dict[str, Any]],
    confidence_rows: Sequence[Dict[str, Any]],
    conflicts: Sequence[Dict[str, Any]],
    collection_logs: Sequence[Dict[str, Any]] | None = None,
    row_match_evidence: Sequence[Dict[str, Any]] | None = None,
    low_confidence_threshold: float = REVIEW_THRESHOLD,
) -> List[Dict[str, Any]]:
    review_rows: List[Dict[str, Any]] = []
    log = _latest_log(collection_logs)
    attempt = _log_attempt(log)
    conflict_keys = {(int(item.get("row_index") or 1), item.get("field")) for item in conflicts}
    conflict_reasons = {
        (int(item.get("row_index") or 1), item.get("field")): str(item.get("reason") or "")
        for item in conflicts
    }

    for item in confidence_rows:
        row_index = int(item.get("row_index") or 1)
        field = item.get("field")
        confidence = float(item.get("confidence") or 0)
        status = str(item.get("review_status") or "pending").strip().lower() or "pending"
        if status == "confirmed":
            continue

        match_level = str(item.get("match_level") or "").strip()
        row_needs_review = bool(item.get("needs_review"))
        if not match_level and row_match_evidence:
            match_level, row_needs_review, _ = _row_match_info(row_index, attempt, row_match_evidence)
        weak_match = row_needs_review and match_level != "strong"
        low_confidence = confidence < low_confidence_threshold
        conflict_key = (row_index, field)
        has_conflict = conflict_key in conflict_keys
        missing_core = field in CORE_FIELDS and not _meaningful(item.get("value"))
        log_failure = any(reason in str(item.get("reason") or "") for reason in ("OCR failed", "LLM parse failed"))

        if not (low_confidence or has_conflict or missing_core or weak_match or log_failure or bool(item.get("needs_review"))):
            continue

        reason_parts = []
        if item.get("reason"):
            reason_parts.append(str(item.get("reason")))
        if has_conflict:
            reason_parts.append(conflict_reasons.get(conflict_key, "冲突"))

        reason = "；".join(dict.fromkeys(part for part in reason_parts if part))
        current_value = item.get("value", "")
        review_rows.append(
            {
                "source_id": log.get("source_id", ""),
                "info_id": log.get("info_id", ""),
                "title": log.get("title", ""),
                "source_url": log.get("source_url", ""),
                "row_index": row_index,
                "field": field,
                "current_value": current_value,
                "value": current_value,
                "confidence": confidence,
                "reason": reason,
                "evidence": item.get("evidence", ""),
                "evidence_id": item.get("evidence_ids", ""),
                "attempt": item.get("attempt") or attempt,
                "review_status": status if status in REVIEW_STATUSES else "pending",
                "reviewed_value": "",
                "review_comment": "",
                "suggested_action": _suggested_action(missing_core, low_confidence, has_conflict, weak_match, reason),
            }
        )
    return review_rows
