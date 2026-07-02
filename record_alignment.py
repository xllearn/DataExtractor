import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import yaml

from config import PROJECT_ROOT
from utils import EXCEL_HEADERS


MATCH_FIELDS = [
    "info_id",
    EXCEL_HEADERS[7],
    EXCEL_HEADERS[8],
    EXCEL_HEADERS[9],
    EXCEL_HEADERS[10],
    EXCEL_HEADERS[11],
    EXCEL_HEADERS[6],
    EXCEL_HEADERS[12],
    EXCEL_HEADERS[13],
    EXCEL_HEADERS[14],
    EXCEL_HEADERS[15],
    EXCEL_HEADERS[16],
    EXCEL_HEADERS[17],
    EXCEL_HEADERS[18],
]
EMPTY_VALUES = {"", "--", "none", "null", "nan"}
DEFAULT_MIN_SIMILARITY = 0.55
DEFAULT_STRONG_SIMILARITY = 0.82


@dataclass(frozen=True)
class AlignmentThresholds:
    min_similarity: float = DEFAULT_MIN_SIMILARITY
    strong_similarity: float = DEFAULT_STRONG_SIMILARITY


def load_alignment_thresholds(path: str | Path | None = None) -> AlignmentThresholds:
    config_path = Path(path) if path else PROJECT_ROOT / "config" / "quality_thresholds.yml"
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path
    if not config_path.exists():
        return AlignmentThresholds()

    payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    alignment = payload.get("alignment") or {}
    min_similarity = float(alignment.get("min_similarity", DEFAULT_MIN_SIMILARITY))
    strong_similarity = float(alignment.get("strong_similarity", DEFAULT_STRONG_SIMILARITY))
    return AlignmentThresholds(min_similarity=max(min_similarity, 0.5), strong_similarity=strong_similarity)


def _resolve_thresholds(
    threshold: float | None = None,
    min_similarity: float | None = None,
    strong_similarity: float | None = None,
) -> AlignmentThresholds:
    defaults = load_alignment_thresholds()
    resolved_min = threshold if threshold is not None else min_similarity
    return AlignmentThresholds(
        min_similarity=max(float(resolved_min if resolved_min is not None else defaults.min_similarity), 0.5),
        strong_similarity=float(strong_similarity if strong_similarity is not None else defaults.strong_similarity),
    )


def _match_level(score: float, thresholds: AlignmentThresholds) -> str:
    if score >= thresholds.strong_similarity:
        return "strong"
    if score >= thresholds.min_similarity:
        return "weak"
    return "below_threshold"


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
    strong_similarity: float = DEFAULT_STRONG_SIMILARITY,
) -> Tuple[float, List[str]]:
    scores: List[float] = []
    matched_fields: List[str] = []
    for field in fields:
        if not _meaningful(base.get(field)) or not _meaningful(candidate.get(field)):
            continue
        score = _field_similarity(base.get(field), candidate.get(field))
        scores.append(score)
        if score >= strong_similarity:
            matched_fields.append(field)
    if not scores:
        return 0.0, []
    return sum(scores) / len(scores), matched_fields


def align_candidate_records(
    base_records: Sequence[Dict[str, Any]],
    candidate_records: Sequence[Dict[str, Any]],
    source_a: str,
    source_b: str,
    threshold: float | None = None,
    min_similarity: float | None = None,
    strong_similarity: float | None = None,
    fields: Sequence[str] = MATCH_FIELDS,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    thresholds = _resolve_thresholds(threshold, min_similarity, strong_similarity)
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
            score, matched_fields = record_similarity(base, candidate, fields, thresholds.strong_similarity)
            if score > best_score:
                best_index = candidate_index
                best_score = score
                best_matched = matched_fields
        level = _match_level(best_score, thresholds)
        if best_index is not None and best_score >= thresholds.min_similarity:
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
                "match_level": level,
                "needs_review": level != "strong",
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
    threshold: float | None = None,
    min_similarity: float | None = None,
    strong_similarity: float | None = None,
) -> tuple[List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]], List[Dict[str, Any]]]:
    thresholds = _resolve_thresholds(threshold, min_similarity, strong_similarity)
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
            similarity, matched_fields = record_similarity(base[0], records[0], strong_similarity=thresholds.strong_similarity)
            level = _match_level(similarity, thresholds)
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
                    "match_level": level,
                    "needs_review": level != "strong",
                    "candidate_index": 1,
                }
            ]
        else:
            source_aligned, source_evidence = align_candidate_records(
                base,
                records,
                base_source,
                source,
                min_similarity=thresholds.min_similarity,
                strong_similarity=thresholds.strong_similarity,
            )
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
                    "match_level": "strong" if source == base_source else "below_threshold",
                    "needs_review": source != base_source,
                    "candidate_index": candidate_index + 1,
                }
            )

    return base, aligned, evidence
