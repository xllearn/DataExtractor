from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Sequence

import yaml
from bs4 import BeautifulSoup

from config import PROJECT_ROOT
from extraction_types import RuleExtractionResult
from field_mapping import ALIASES, FieldMapping, load_field_mapping, normalize_record_fields


DEDUP_FIELDS = ["人员类型", "医院类型", "类型", "起付标准", "补助限额", "报销比例"]


@dataclass
class TableMapping:
    header_aliases: Dict[str, List[str]] = field(default_factory=lambda: {key: list(value) for key, value in ALIASES.items()})
    source: str = "table_rule"
    confidence: float = 0.85

    @property
    def alias_to_header(self) -> Dict[str, str]:
        mapping: Dict[str, str] = {}
        for header, aliases in self.header_aliases.items():
            mapping[header] = header
            for alias in aliases:
                mapping[alias] = header
        return mapping


def load_table_mapping(path: str | Path | None = None) -> TableMapping:
    config_path = Path(path) if path else PROJECT_ROOT / "config" / "table_mapping.yml"
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path
    if not config_path.exists():
        return TableMapping()
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    aliases = {key: list(value) for key, value in ALIASES.items()}
    for header, values in (payload.get("header_aliases") or {}).items():
        aliases[str(header)] = [str(value) for value in values or []]
    defaults = payload.get("defaults") or {}
    return TableMapping(
        header_aliases=aliases,
        source=str(defaults.get("source", "table_rule")),
        confidence=float(defaults.get("confidence", 0.85)),
    )


def _clean_cell(value: Any) -> str:
    return " ".join(str(value or "").split())


def _evidence(source_id: str, info_id: str, field: str, value: str, evidence: str, confidence: float, source: str, rule_name: str) -> Dict[str, Any]:
    return {
        "source_id": source_id,
        "info_id": info_id,
        "field": field,
        "value": value,
        "evidence": evidence,
        "confidence": confidence,
        "source": source,
        "rule_name": rule_name,
    }


def _rows_from_html_table(table) -> List[List[str]]:
    rows: List[List[str]] = []
    for tr in table.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        values = [_clean_cell(cell.get_text(" ", strip=True)) for cell in cells]
        if any(values):
            rows.append(values)
    return rows


def _rows_from_markdown(text: str) -> List[List[List[str]]]:
    tables: List[List[List[str]]] = []
    current: List[List[str]] = []
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [_clean_cell(part) for part in stripped.strip("|").split("|")]
            if cells and not all(set(cell) <= {"-", ":", " "} for cell in cells):
                current.append(cells)
        elif current:
            if len(current) >= 2:
                tables.append(current)
            current = []
    if len(current) >= 2:
        tables.append(current)
    return tables


def _rows_from_delimited_text(text: str) -> List[List[List[str]]]:
    lines = [_clean_cell(line) for line in str(text or "").splitlines() if _clean_cell(line)]
    tables: List[List[List[str]]] = []
    for index, line in enumerate(lines[:-1]):
        if "\t" in line:
            header = [_clean_cell(part) for part in line.split("\t")]
            body = [_clean_cell(part) for part in lines[index + 1].split("\t")]
            if len(header) > 1 and len(body) == len(header):
                tables.append([header, body])
    return tables


def _extract_from_rows(
    table_rows: Sequence[Sequence[str]],
    source_id: str,
    info_id: str,
    table_mapping: TableMapping,
    field_mapping: FieldMapping,
    rule_name: str,
) -> RuleExtractionResult:
    result = RuleExtractionResult()
    if len(table_rows) < 2:
        return result
    headers = [_clean_cell(cell) for cell in table_rows[0]]
    alias_to_header = {**table_mapping.alias_to_header, **field_mapping.alias_to_header}

    for row_number, values in enumerate(table_rows[1:], start=2):
        if not any(values):
            continue
        record: Dict[str, Any] = {}
        extra_notes: List[str] = []
        for index, raw_header in enumerate(headers):
            value = _clean_cell(values[index] if index < len(values) else "")
            if not value:
                continue
            target = raw_header if raw_header in field_mapping.headers else alias_to_header.get(raw_header)
            if target and target in field_mapping.headers:
                record[target] = value
                result.field_evidence.append(
                    _evidence(
                        source_id,
                        info_id,
                        target,
                        value,
                        f"表格第{row_number}行：{raw_header}={value}",
                        table_mapping.confidence,
                        "table",
                        rule_name,
                    )
                )
            else:
                extra_notes.append(f"{raw_header}={value}")
        if extra_notes:
            record["备注"] = "；".join(extra_notes)
        if record:
            result.records.append(normalize_record_fields(record, field_mapping))
    return result


def _merge_results(results: Sequence[RuleExtractionResult]) -> RuleExtractionResult:
    merged = RuleExtractionResult()
    seen_records = set()
    seen_evidence = set()
    for result in results:
        for record in result.records:
            key = tuple(str(record.get(field, "")) for field in DEDUP_FIELDS)
            if key not in seen_records:
                merged.records.append(record)
                seen_records.add(key)
        for evidence in result.field_evidence:
            key = (
                evidence.get("source_id", ""),
                evidence.get("info_id", ""),
                evidence.get("field", ""),
                evidence.get("value", ""),
                evidence.get("evidence", ""),
            )
            if key not in seen_evidence:
                merged.field_evidence.append(evidence)
                seen_evidence.add(key)
        merged.errors.extend(result.errors)
    return merged


def extract_tables_from_html(
    html: str,
    source_id: str = "",
    info_id: str = "",
    config: TableMapping | None = None,
    field_mapping: FieldMapping | None = None,
) -> RuleExtractionResult:
    table_mapping = config or load_table_mapping(None)
    field_mapping = field_mapping or load_field_mapping(None)
    try:
        soup = BeautifulSoup(html or "", "html.parser")
        results = [
            _extract_from_rows(_rows_from_html_table(table), source_id, info_id, table_mapping, field_mapping, "html_table_header_alias")
            for table in soup.find_all("table")
        ]
        return _merge_results(results)
    except Exception as exc:
        return RuleExtractionResult(errors=[{"source": "table", "rule_name": "html_table_header_alias", "error": str(exc)}])


def extract_tables_from_text(
    text: str,
    source_id: str = "",
    info_id: str = "",
    config: TableMapping | None = None,
    field_mapping: FieldMapping | None = None,
) -> RuleExtractionResult:
    table_mapping = config or load_table_mapping(None)
    field_mapping = field_mapping or load_field_mapping(None)
    try:
        tables = _rows_from_markdown(text) + _rows_from_delimited_text(text)
        results = [
            _extract_from_rows(rows, source_id, info_id, table_mapping, field_mapping, "text_table_header_alias")
            for rows in tables
        ]
        return _merge_results(results)
    except Exception as exc:
        return RuleExtractionResult(errors=[{"source": "table", "rule_name": "text_table_header_alias", "error": str(exc)}])


def extract_table_records(
    html: str,
    text: str = "",
    source_id: str = "",
    info_id: str = "",
    config: TableMapping | None = None,
    field_mapping: FieldMapping | None = None,
) -> RuleExtractionResult:
    return _merge_results(
        [
            extract_tables_from_html(html, source_id=source_id, info_id=info_id, config=config, field_mapping=field_mapping),
            extract_tables_from_text(text, source_id=source_id, info_id=info_id, config=config, field_mapping=field_mapping),
        ]
    )
