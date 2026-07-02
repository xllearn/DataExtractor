import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Sequence, Tuple


MATCH_FIELDS = [
    "info_id",
    "类型",
    "标准化类型",
    "保险类型",
    "人员类型",
    "病种类型",
    "病种名称",
    "就诊场景",
    "医院类型",
    "就诊情况",
    "区间",
    "起付标准",
    "补助限额",
    "报销比例",
]
EMPTY_VALUES = {"", "--", "none", "null", "nan"}


def _meaningful(value: Any) -> bool:
    return str(value or "").strip().lower() not in EMPTY_VALUES


def _normalize(value: Any) -> str:
    text = re.sub(r"\s+", "", str(value or "")).strip().lower()
    return "" if text in EMPTY_VALUES else text


def _field_similarity(left: Any, right: Any) -> float:
    left_text = _normalize(left)
    right_text = _normalize(right)
    if not left_text or not right_text:
        return 0.0
    if left_text == right_text:
        return 1.0
    if left_text in right_text or right_text in left_text:
        return 0.9
    return SequenceMatcher(None, left_text, right_text).ratio()


def record_similarity(
    base: Dict[str, Any],
    candidate: Dict[str, Any],
    fields: Sequence[str] = MATCH_FIELDS,
) -> Tuple[float, List[str]]:
    scores: List[float] = []
    matched_fields: List[str] = []
    for field in fields:
        if not _meaningful(base.get(field)) or not _meaningful(candidate.get(field)):
            continue
        score = _field_similarity(base.get(field), candidate.get(field))
        scores.append(score)
        if score >= 0.82:
            matched_fields.append(field)
    if not scores:
        return 0.0, []
    return sum(scores) / len(scores), matched_fields


def align_candidate_records(
    base_records: Sequence[Dict[str, Any]],
    candidate_records: Sequence[Dict[str, Any]],
    source_a: str,
    source_b: str,
    threshold: float = 0.34,
    fields: Sequence[str] = MATCH_FIELDS,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    aligned: List[Dict[str, Any]] = []
    evidence: List[Dict[str, Any]] = []
    used_candidates: set[int] = set()

    for base_index, base in enumerate(base_records):
        best_index = None
        best_score = 0.0
        best_matched: List[str] = []
        for candidate_index, candidate in enumerate(candidate_records):
            if candidate_index in used_candidates:
                continue
            score, matched_fields = record_similarity(base, candidate, fields)
            if score > best_score:
                best_index = candidate_index
                best_score = score
                best_matched = matched_fields
        if best_index is not None and best_score >= threshold:
            used_candidates.add(best_index)
            aligned.append(dict(candidate_records[best_index]))
            reason = "matched"
            row_b: int | str = best_index + 1
        else:
            aligned.append({})
            reason = "below_threshold"
            row_b = ""
        evidence.append(
            {
                "source_a": source_a,
                "source_b": source_b,
                "row_a": base_index + 1,
                "row_b": row_b,
                "similarity": round(best_score, 6),
                "matched_fields": best_matched,
                "reason": reason,
                "candidate_index": best_index + 1 if best_index is not None else "",
            }
        )
    return aligned, evidence


def _base_records(
    table_records: Sequence[Dict[str, Any]],
    text_rule_records: Sequence[Dict[str, Any]],
    llm_records: Sequence[Dict[str, Any]],
) -> tuple[str, List[Dict[str, Any]]]:
    if table_records:
        return "table", [dict(row) for row in table_records]
    if text_rule_records:
        return "text_rule", [dict(row) for row in text_rule_records]
    if llm_records:
        return "llm", [dict(row) for row in llm_records]
    return "default", [{}]


def _used_indices(evidence: Sequence[Dict[str, Any]]) -> set[int]:
    return {int(item["row_b"]) - 1 for item in evidence if item.get("reason") == "matched" and str(item.get("row_b") or "").isdigit()}


def align_sources(
    table_records: Sequence[Dict[str, Any]],
    text_rule_records: Sequence[Dict[str, Any]],
    llm_records: Sequence[Dict[str, Any]],
    threshold: float = 0.34,
) -> tuple[List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]], List[Dict[str, Any]]]:
    base_source, base = _base_records(table_records, text_rule_records, llm_records)
    aligned: Dict[str, List[Dict[str, Any]]] = {
        "table": [dict(row) for row in table_records] if base_source == "table" else [],
        "text_rule": [dict(row) for row in text_rule_records] if base_source == "text_rule" else [],
        "llm": [dict(row) for row in llm_records] if base_source == "llm" else [],
    }
    evidence: List[Dict[str, Any]] = []

    sources = {
        "table": list(table_records),
        "text_rule": list(text_rule_records),
        "llm": list(llm_records),
    }
    used_by_source: Dict[str, set[int]] = {}
    for source, records in sources.items():
        if source == base_source:
            aligned[source] = [dict(row) for row in base]
            used_by_source[source] = set(range(len(base)))
            continue
        if len(base) == 1 and len(records) == 1:
            similarity, matched_fields = record_similarity(base[0], records[0])
            source_aligned = [dict(records[0])]
            source_evidence = [
                {
                    "source_a": base_source,
                    "source_b": source,
                    "row_a": 1,
                    "row_b": 1,
                    "similarity": round(similarity, 6),
                    "matched_fields": matched_fields,
                    "reason": "single_row_default",
                    "candidate_index": 1,
                }
            ]
        else:
            source_aligned, source_evidence = align_candidate_records(base, records, base_source, source, threshold=threshold)
        aligned[source] = source_aligned
        evidence.extend(source_evidence)
        used_by_source[source] = _used_indices(source_evidence)

    for source in ("table", "text_rule", "llm"):
        if len(sources[source]) <= len(base):
            continue
        for candidate_index, candidate in enumerate(sources[source]):
            if candidate_index in used_by_source.get(source, set()):
                continue
            if source == base_source and candidate_index < len(base):
                continue
            append_index = len(base) + 1
            base.append(dict(candidate))
            for aligned_source in aligned:
                aligned[aligned_source].append(dict(candidate) if aligned_source == source else {})
            evidence.append(
                {
                    "source_a": base_source,
                    "source_b": source,
                    "row_a": append_index,
                    "row_b": candidate_index + 1,
                    "similarity": 1.0 if source == base_source else 0.0,
                    "matched_fields": [],
                    "reason": "extra_candidate_appended",
                    "candidate_index": candidate_index + 1,
                }
            )

    return base, aligned, evidence
