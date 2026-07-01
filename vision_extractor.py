from dataclasses import dataclass, field
from typing import Any, Dict, List

from field_mapping import normalize_record_fields, load_field_mapping
from json_utils import parse_llm_json
from security_utils import mask_sensitive_text


@dataclass
class VisionExtractionResult:
    text: str = ""
    records: List[Dict[str, Any]] = field(default_factory=list)
    field_evidence: List[Dict[str, Any]] = field(default_factory=list)
    raw_output: str = ""
    success_count: int = 0
    failure_count: int = 0
    errors: List[Dict[str, Any]] = field(default_factory=list)


def _source_id(record: Dict[str, Any]) -> str:
    return str(record.get("_source_id") or record.get("SourceURL") or "")


def _info_id(record: Dict[str, Any]) -> str:
    return str(record.get("info_id") or (record.get("_direct_fields") or {}).get("info_id") or "")


def _coerce_payload(raw_output: str) -> Dict[str, Any]:
    parsed = parse_llm_json(raw_output)
    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, list):
        return {"records": [item for item in parsed if isinstance(item, dict)], "tables_text": raw_output, "evidence": {}}
    return {"records": [], "tables_text": raw_output, "evidence": {}}


def _field_evidence(record: Dict[str, Any], rows: List[Dict[str, Any]], evidence: Any) -> List[Dict[str, Any]]:
    source_id = _source_id(record)
    info_id = _info_id(record)
    evidence_map = evidence if isinstance(evidence, dict) else {}
    items: List[Dict[str, Any]] = []
    seen = set()
    for row in rows:
        for field, value in row.items():
            if value in (None, "", "--"):
                continue
            key = (field, str(value))
            if key in seen:
                continue
            seen.add(key)
            items.append(
                {
                    "source_id": source_id,
                    "info_id": info_id,
                    "field": field,
                    "value": value,
                    "evidence": str(evidence_map.get(field, "")),
                    "confidence": 0.78,
                    "source": "vision_llm",
                    "rule_name": "vision_image_table",
                }
            )
    return items


def extract_image_table_with_vision(
    image_urls: List[str],
    record: Dict[str, Any],
    prompt_context: str,
    vision_client,
) -> VisionExtractionResult:
    result = VisionExtractionResult()
    field_mapping = load_field_mapping(None)
    for image_index, image_url in enumerate(image_urls or [], start=1):
        try:
            raw_output = vision_client.extract_image_table(image_url, prompt_context=prompt_context)
            payload = _coerce_payload(raw_output)
            records = [
                normalize_record_fields(item, field_mapping)
                for item in payload.get("records", [])
                if isinstance(item, dict)
            ]
            tables_text = str(payload.get("tables_text") or raw_output or "")
            result.raw_output = "\n\n".join(part for part in [result.raw_output, raw_output] if part)
            result.text = "\n\n".join(part for part in [result.text, tables_text] if part)
            result.records.extend(records)
            result.field_evidence.extend(_field_evidence(record, records, payload.get("evidence")))
            result.success_count += 1
        except Exception as exc:
            result.failure_count += 1
            result.errors.append(
                {
                    "image_index": image_index,
                    "image_url": image_url,
                    "error": mask_sensitive_text(str(exc)),
                    "source": "vision_llm",
                }
            )
    return result
