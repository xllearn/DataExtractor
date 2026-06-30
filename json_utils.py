import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from field_mapping import FieldMapping, load_field_mapping, normalize_record_fields
from utils import EXCEL_HEADERS, apply_default_mappings, create_fallback_row, ensure_dir


def normalize_llm_rows(
    raw_output: Any,
    record: Dict[str, Any],
    today: str,
    logs_dir: Path,
    field_mapping: FieldMapping | None = None,
) -> List[Dict[str, Any]]:
    field_mapping = field_mapping or load_field_mapping(None)
    try:
        parsed = parse_llm_json(raw_output)
    except Exception:
        save_failed_llm_output(raw_output, logs_dir)
        return [normalize_record_fields(create_fallback_row(record, today), field_mapping)]

    if isinstance(parsed, dict):
        items = [parsed]
    elif isinstance(parsed, list):
        items = parsed
    else:
        save_failed_llm_output(raw_output, logs_dir)
        return [create_fallback_row(record, today)]

    rows: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        row = normalize_record_fields(item, field_mapping)
        row = apply_default_mappings(row, record, today)
        for header, value in (record.get("_direct_fields") or {}).items():
            if header in EXCEL_HEADERS and value not in (None, ""):
                row[header] = value
        rows.append(normalize_record_fields(row, field_mapping))

    if not rows:
        rows.append(normalize_record_fields(create_fallback_row(record, today), field_mapping))
    return rows


def parse_llm_json(raw_output: Any) -> Any:
    text = "" if raw_output is None else str(raw_output).strip()
    text = strip_markdown_code_block(text)
    candidate = extract_json_candidate(text)
    return json.loads(candidate)


def strip_markdown_code_block(text: str) -> str:
    stripped = text.strip()
    match = re.fullmatch(r"```(?:json|JSON)?\s*(.*?)\s*```", stripped, flags=re.DOTALL)
    if match:
        return match.group(1).strip()
    return stripped.replace("```json", "").replace("```JSON", "").replace("```", "").strip()


def extract_json_candidate(text: str) -> str:
    array_start = text.find("[")
    object_start = text.find("{")
    if array_start == -1 and object_start == -1:
        raise ValueError("No JSON array or object found")

    if array_start != -1 and (object_start == -1 or array_start < object_start):
        return _extract_balanced(text, array_start, "[", "]")
    return _extract_balanced(text, object_start, "{", "}")


def _extract_balanced(text: str, start: int, open_char: str, close_char: str) -> str:
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise ValueError("JSON is not balanced")


def save_failed_llm_output(raw_output: Any, logs_dir: Path) -> Path:
    failed_dir = ensure_dir(logs_dir / "failed_llm_outputs")
    path = failed_dir / f"failed_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.txt"
    path.write_text("" if raw_output is None else str(raw_output), encoding="utf-8")
    return path
