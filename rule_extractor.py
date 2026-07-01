import re
from typing import Any, Dict, List, Tuple

from extraction_types import RuleExtractionResult
from field_mapping import FieldMapping, load_field_mapping, normalize_record_fields
from field_cleaners import (
    INTERVAL_FIELD,
    NOTE_FIELD,
    PERSON_TYPE_FIELD,
    age_range_note,
    append_note,
    extract_age_range,
    extract_reimbursement_interval,
    invalid_person_type_note,
    normalize_person_type,
)


FIELD_ALIASES: Dict[str, List[str]] = {
    "报销比例": ["报销比例", "支付比例", "报付比例", "补偿比例"],
    "起付标准": ["起付标准", "起付线", "起付金额"],
    "补助限额": ["年度最高支付限额", "最高支付限额", "封顶线", "年度限额", "补助限额"],
    "病种名称": ["病种名称", "疾病名称", "特定病种", "保障病种", "纳入病种", "病种范围"],
    "人员类型": ["人员类型", "适用人群", "参保人员", "参保人群"],
    "区间": ["区间", "报销区间", "费用区间", "医疗费用区间", "赔付区间", "金额区间"],
}

VALUE_PATTERN = r"([0-9]+(?:\.[0-9]+)?\s*(?:%|％|元|万元|万|亿元)?)"
DISEASE_FIELD = "病种名称"
AGE_CONTEXT_ALIASES = ["投保年龄", "参保年龄", "承保年龄", "年龄范围"]
GENERIC_DISEASE_TERMS = {"大病", "既往症", "慢性病", "特殊病", "疾病病", "了解症"}
INVALID_DISEASE_MARKERS = [
    "旨在",
    "减轻",
    "保障",
    "覆盖",
    "范围",
    "了解",
    "花小钱",
    "保大病",
    "发生的",
    "费用",
    "医疗费用",
    "基金支付",
    "保险金",
    "报销",
    "赔付",
    "定点医药机构",
]
INVALID_DISEASE_SEGMENT_MARKERS = [
    "美国",
    "加拿大",
    "英国",
    "欧洲",
    "国家",
    "国立",
    "国际",
    "通行",
    "针对",
    "分类",
    "协会",
    "参保",
    "群众",
    "一旦",
    "高发",
    "高价",
    "自费",
    "费用",
    "医疗",
    "基础",
    "主要表现",
    "一组",
]
NEGATIVE_DISEASE_CONTEXT_MARKERS = [
    "免责",
    "责任免除",
    "投保须知",
    "健康告知",
    "既往症",
    "不能投保",
    "不可投保",
    "除外责任",
    "不承担",
    "不予赔付",
]
DISEASE_CORE_PATTERNS = [
    r"类风湿性关节炎",
    r"慢性阻塞性肺疾病",
    r"阿尔茨海默病",
    r"系统性红斑狼疮",
    r"再生障碍性贫血",
    r"精神分裂症",
    r"肾功能衰竭",
    r"心力衰竭",
    r"帕金森病",
    r"高血压",
    r"糖尿病",
    r"恶性肿瘤",
    r"白血病",
    r"罕见病",
    r"冠心病",
    r"脑卒中",
    r"尿毒症",
    r"[\u4e00-\u9fff]{1,10}关节炎",
    r"[\u4e00-\u9fff]{1,10}肾炎",
    r"[\u4e00-\u9fff]{1,10}肝炎",
    r"[\u4e00-\u9fff]{1,10}肺炎",
    r"[\u4e00-\u9fff]{1,10}脑炎",
    r"[\u4e00-\u9fff]{1,10}贫血",
    r"[\u4e00-\u9fff]{1,10}硬化",
    r"[\u4e00-\u9fff]{1,10}梗死",
    r"[\u4e00-\u9fff]{1,10}卒中",
    r"[\u4e00-\u9fff]{1,10}哮喘",
    r"[\u4e00-\u9fff]{1,10}癫痫",
    r"[\u4e00-\u9fff]{1,10}抑郁症",
    r"[\u4e00-\u9fff]{1,10}衰竭",
    r"[\u4e00-\u9fff]{1,8}综合征",
    r"[\u4e00-\u9fff]{1,8}癌",
    r"[\u4e00-\u9fff]{1,8}瘤",
]
DISEASE_CORE_RE = re.compile("|".join(f"(?:{pattern})" for pattern in DISEASE_CORE_PATTERNS))
DISEASE_SPLIT_RE = re.compile(r"[、,，/；;和及与]")


def _clean_disease_segment(value: str) -> str:
    text = re.sub(r"\s+", "", str(value or ""))
    return text.strip("：:，,。；;、（）()[]【】\"'“”‘’")


def _unique_join(values: List[str]) -> str:
    unique: List[str] = []
    for value in values:
        if value and value not in unique:
            unique.append(value)
    return "、".join(unique)


def _clean_core_candidate(value: str) -> str:
    candidate = _clean_disease_segment(value)
    for token in ["的", "为", "对", "按", "等", "或"]:
        if token in candidate:
            candidate = candidate.split(token)[-1]
    for token in ["患了", "患有", "确诊"]:
        if token in candidate:
            candidate = candidate.split(token)[-1]
    if len(candidate) < 2 or candidate in GENERIC_DISEASE_TERMS:
        return ""
    return candidate


def normalize_disease_name(value: str) -> str:
    text = _clean_disease_segment(value)
    if not text:
        return ""
    if any(marker in text for marker in NEGATIVE_DISEASE_CONTEXT_MARKERS):
        return ""

    normalized_parts: List[str] = []
    for segment in [part for part in DISEASE_SPLIT_RE.split(text) if part]:
        segment = _clean_disease_segment(segment)
        if not segment or segment in GENERIC_DISEASE_TERMS:
            continue
        if any(marker in segment for marker in INVALID_DISEASE_SEGMENT_MARKERS):
            continue
        matches = [match.group(0) for match in DISEASE_CORE_RE.finditer(segment)]
        if matches:
            normalized_parts.extend(candidate for candidate in (_clean_core_candidate(match) for match in matches) if candidate)
            continue
        if any(marker in segment for marker in INVALID_DISEASE_MARKERS):
            continue
        if len(segment) <= 15 and segment not in GENERIC_DISEASE_TERMS and DISEASE_CORE_RE.fullmatch(segment):
            normalized_parts.append(segment)
    return _unique_join(normalized_parts)


def is_valid_disease_name(value: str) -> bool:
    text = _clean_disease_segment(value)
    if not text:
        return False
    normalized = normalize_disease_name(text)
    return bool(normalized) and normalized == text and len(text) <= 30


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


def _find_field_values(text: str, field_mapping: FieldMapping) -> List[Tuple[str, str, str, str]]:
    hits: List[Tuple[str, str, str, str]] = []
    for alias in AGE_CONTEXT_ALIASES:
        pattern = re.compile(rf"({re.escape(alias)}\s*(?:[:：为是])\s*([^\n。；;，,、|]+))")
        for match in pattern.finditer(text):
            evidence = match.group(1).strip()
            value = match.group(2).strip()
            age_range = extract_age_range(value)
            if age_range:
                hits.append((NOTE_FIELD, f"{alias}：{age_range}", evidence, "age_context_redirect_to_note"))
    for field, aliases in _field_aliases(field_mapping).items():
        if field == DISEASE_FIELD:
            continue
        for alias in aliases:
            if field == PERSON_TYPE_FIELD:
                pattern = re.compile(rf"({re.escape(alias)}\s*(?:[:：为是])\s*([^\n。；;，,、|]+))")
                for match in pattern.finditer(text):
                    evidence = match.group(1).strip()
                    value = match.group(2).strip()
                    person_type = normalize_person_type(value)
                    if person_type:
                        hits.append((field, person_type, evidence, "person_type_text_pattern"))
                        continue
                    note = invalid_person_type_note(value)
                    if note:
                        hits.append((NOTE_FIELD, note, evidence, "age_range_redirect_to_note"))
                continue
            if field == INTERVAL_FIELD:
                pattern = re.compile(rf"({re.escape(alias)}\s*(?:[:：为是])\s*([^\n。；;，,、|]+))")
                for match in pattern.finditer(text):
                    evidence = match.group(1).strip()
                    value = match.group(2).strip()
                    interval = extract_reimbursement_interval(value)
                    if interval:
                        hits.append((field, interval, evidence, "reimbursement_interval_pattern"))
                        continue
                    note = age_range_note(value)
                    if note:
                        hits.append((NOTE_FIELD, note, evidence, "age_range_redirect_to_note"))
                continue
            pattern = re.compile(rf"({re.escape(alias)}\s*(?:[:：为是]|不超过|不高于)?\s*{VALUE_PATTERN})")
            for match in pattern.finditer(text):
                evidence = match.group(1).strip()
                value = match.group(2).strip()
                hits.append((field, value, evidence, "kv_pattern"))
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


def _find_disease_names(text: str, field_mapping: FieldMapping) -> List[Tuple[str, str, str, str, float]]:
    aliases = _field_aliases(field_mapping).get(DISEASE_FIELD, [DISEASE_FIELD])
    alias_pattern = "|".join(re.escape(alias) for alias in aliases)
    strong_pattern = re.compile(rf"((?:{alias_pattern})\s*[:：为是]\s*([^\n。；;]+))")
    for match in strong_pattern.finditer(text):
        normalized = normalize_disease_name(match.group(2))
        if normalized:
            return [(DISEASE_FIELD, normalized, match.group(1).strip(), "disease_name_strong_context", 0.82)]

    if any(marker in text for marker in NEGATIVE_DISEASE_CONTEXT_MARKERS):
        return []

    normalized = normalize_disease_name(text)
    if normalized:
        return [(DISEASE_FIELD, normalized, normalized, "disease_name_weak_core", 0.58)]
    return []


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
        for field, value, evidence_text, rule_name in _find_field_values(source_text, field_mapping):
            if field == NOTE_FIELD:
                record[field] = append_note(record.get(field), value)
                result.field_evidence.append(_evidence(source_id, info_id, field, value, evidence_text, 0.8, rule_name))
            elif field not in record:
                record[field] = value
                result.field_evidence.append(_evidence(source_id, info_id, field, value, evidence_text, 0.8, rule_name))

        for field, value, evidence_text, rule_name, confidence in _find_disease_names(source_text, field_mapping):
            if field not in record:
                record[field] = value
                result.field_evidence.append(_evidence(source_id, info_id, field, value, evidence_text, confidence, rule_name))

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
