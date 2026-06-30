import re
from typing import Any, Dict, List, Tuple

from extraction_types import RuleExtractionResult
from field_mapping import FieldMapping, load_field_mapping, normalize_record_fields


FIELD_ALIASES: Dict[str, List[str]] = {
    "报销比例": ["报销比例", "支付比例", "报付比例", "补偿比例"],
    "起付标准": ["起付标准", "起付线", "起付金额"],
    "补助限额": ["年度最高支付限额", "最高支付限额", "封顶线", "年度限额", "补助限额"],
}

VALUE_PATTERN = r"([0-9]+(?:\.[0-9]+)?\s*(?:%|％|元|万元|万|亿元)?)"


def _evidence(source_id: str, info_id: str, field: str, value: str, evidence: str, confidence: float, rule_name: str) -> Dict[str, Any]:
    return {
        "source_id": source_id,
        "info_id": info_id,
        "field": field,
        "value": value,
        "evidence": evidence,
        "confidence": confidence,
        "source": "text_rule",
        "rule_name": rule_name,
    }


def _field_aliases(field_mapping: FieldMapping) -> Dict[str, List[str]]:
    aliases = {field: list(values) for field, values in FIELD_ALIASES.items()}
    for field, values in field_mapping.aliases.items():
        aliases.setdefault(field, [])
        for value in values:
            if value not in aliases[field]:
                aliases[field].append(value)
    return aliases


def _find_field_values(text: str, field_mapping: FieldMapping) -> List[Tuple[str, str, str]]:
    hits: List[Tuple[str, str, str]] = []
    for field, aliases in _field_aliases(field_mapping).items():
        for alias in aliases:
            pattern = re.compile(rf"({re.escape(alias)}\s*(?:[:：为是]|不超过|不高于)?\s*{VALUE_PATTERN})")
            for match in pattern.finditer(text):
                evidence = match.group(1).strip()
                value = match.group(2).strip()
                hits.append((field, value, evidence))
    return hits


def _find_insurance_type(text: str) -> Tuple[str, str]:
    match = re.search(r"(居民医保|职工医保|城乡居民医保|城镇职工医保|商业补充保险)", text)
    if not match:
        return "", ""
    return match.group(1), match.group(1)


def _find_context_hints(text: str) -> List[Tuple[str, str, str, str, float]]:
    hints: List[Tuple[str, str, str, str, float]] = []
    context_rules = [
        ("人员类型", r"(参保职工|参保居民|职工|居民)", "context_person_type", 0.65),
        ("医院类型", r"([一二三]级医院|基层医疗机构|定点医疗机构)", "context_hospital_type", 0.7),
        ("类型", r"(门诊慢特病|门诊统筹|住院待遇|特药保障|个人账户)", "context_benefit_type", 0.7),
        ("病种名称", r"([\u4e00-\u9fa5]{2,12}(?:病|症))", "context_disease_name", 0.55),
    ]
    for field, pattern, rule_name, confidence in context_rules:
        match = re.search(pattern, text)
        if match:
            value = match.group(1)
            hints.append((field, value, value, rule_name, confidence))
            if field == "类型" and value == "门诊慢特病":
                hints.append(("标化类型", "门统", value, "context_standard_type", 0.65))
            elif field == "类型" and value == "住院待遇":
                hints.append(("标化类型", "住院", value, "context_standard_type", 0.65))
    return hints


def extract_key_value_records(
    text: str,
    source_id: str = "",
    info_id: str = "",
    field_mapping: FieldMapping | None = None,
) -> RuleExtractionResult:
    result = RuleExtractionResult()
    try:
        field_mapping = field_mapping or load_field_mapping(None)
        source_text = str(text or "")
        record: Dict[str, Any] = {}
        for field, value, evidence_text in _find_field_values(source_text, field_mapping):
            if field not in record:
                record[field] = value
                result.field_evidence.append(_evidence(source_id, info_id, field, value, evidence_text, 0.8, "kv_pattern"))

        insurance_value, insurance_evidence = _find_insurance_type(source_text)
        if insurance_value:
            record["保险类型"] = insurance_value
            result.field_evidence.append(_evidence(source_id, info_id, "保险类型", insurance_value, insurance_evidence, 0.75, "insurance_hint"))

        for field, value, evidence_text, rule_name, confidence in _find_context_hints(source_text):
            if field not in record:
                record[field] = value
                result.field_evidence.append(_evidence(source_id, info_id, field, value, evidence_text, confidence, rule_name))

        if record:
            result.records.append(normalize_record_fields(record, field_mapping))
        return result
    except Exception as exc:
        result.errors.append({"source": "text_rule", "rule_name": "kv_pattern", "error": str(exc)})
        return result
