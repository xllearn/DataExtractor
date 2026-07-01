import re
from typing import Any, Dict, List

from extraction_types import RuleExtractionResult
from field_cleaners import append_note
from field_mapping import FieldMapping, load_field_mapping, normalize_record_fields


BENEFIT_NAMES = [
    "意外身故及伤残保险金",
    "航空意外身故及伤残保险金",
    "火车意外身故及伤残保险金",
    "轮船意外身故及伤残保险金",
    "意外骨折和脱臼",
    "意外住院津贴保险金",
    "重疾住院津贴保险金",
    "在线问诊药品费用医疗保险金",
    "猝死",
    "意外门诊急诊费用补偿",
]

AMOUNT_RE = re.compile(r"(\d+(?:\.\d+)?\s*(?:元|万元|万|亿元)?)")
RATIO_RE = re.compile(r"(?:给付比例|报销比例|赔付比例)\s*([0-9]+(?:\.[0-9]+)?\s*[%％])")
DEDUCTIBLE_RE = re.compile(r"((?:每次事故)?免赔额\s*\d+(?:\.\d+)?\s*元)")
WAITING_RE = re.compile(r"(等待期\s*\d+\s*天)")
PERIOD_RE = re.compile(r"保障期间\s*[:：]?\s*([^\n，,；;]+)")
AGE_RE = re.compile(r"投保年龄\s*[:：]?\s*([^\n，,；;]+)")
PREMIUM_RE = re.compile(r"保费\s*[:：]?\s*([0-9]+(?:\.\d+)?\s*元/年/人)")
INSURANCE_RE = re.compile(r"(普惠门诊保\s*[·・]?\s*如意版\s*[（(]?\s*2025\s*[）)]?)")
PERSON_RE = re.compile(r"(中国大陆籍人士|中国大陆居民|中国大陆公民|被保险人|投保人)")
PROVINCE_RE = re.compile(
    r"(北京市|天津市|上海市|重庆市|河北省|山西省|辽宁省|吉林省|黑龙江省|江苏省|浙江省|安徽省|福建省|江西省|山东省|河南省|湖北省|湖南省|广东省|海南省|四川省|贵州省|云南省|陕西省|甘肃省|青海省|台湾省|内蒙古自治区|广西壮族自治区|西藏自治区|宁夏回族自治区|新疆维吾尔自治区|香港特别行政区|澳门特别行政区)"
)


def _clean_text(value: Any) -> str:
    return re.sub(r"[ \t\u3000]+", " ", str(value or "")).strip()


def _normalize_amount(value: str) -> str:
    text = re.sub(r"\s+", "", value or "")
    if not text:
        return ""
    if re.search(r"(元|万元|万|亿元)$", text):
        return text
    return f"{text}元"


def _normalize_insurance(value: str) -> str:
    text = re.sub(r"\s+", "", value or "")
    text = text.replace("（", "(").replace("）", ")")
    text = text.replace("(2025)", "2025")
    return text


def _find_common_context(text: str) -> Dict[str, str]:
    context: Dict[str, str] = {}
    insurance_match = INSURANCE_RE.search(text)
    if insurance_match:
        context["保险类型"] = _normalize_insurance(insurance_match.group(1))

    note_parts: List[str] = []
    period_match = PERIOD_RE.search(text)
    if period_match:
        note_parts.append(f"保障期间：{_clean_text(period_match.group(1))}")
    age_match = AGE_RE.search(text)
    if age_match:
        note_parts.append(f"投保年龄：{_clean_text(age_match.group(1))}")
    premium_match = PREMIUM_RE.search(text)
    if premium_match:
        note_parts.append(f"保费：{_clean_text(premium_match.group(1))}")
    if note_parts:
        context["备注"] = "；".join(note_parts)

    province_match = PROVINCE_RE.search(text)
    if province_match:
        context["地区名称"] = province_match.group(1)

    mainland_match = re.search(r"(中国大陆籍人士|中国大陆居民|中国大陆公民)", text)
    person_match = mainland_match or PERSON_RE.search(text)
    if person_match and person_match.group(1) not in {"投保人", "被保险人"} and "周岁" not in person_match.group(1):
        context["人员类型"] = person_match.group(1)
    return context


def _match_benefit_line(line: str) -> tuple[str, str, str] | None:
    clean_line = _clean_text(line)
    if not clean_line:
        return None
    for name in BENEFIT_NAMES:
        if not clean_line.startswith(name):
            continue
        tail = _clean_text(clean_line[len(name) :])
        amount_match = AMOUNT_RE.search(tail)
        if not amount_match:
            return None
        amount = _normalize_amount(amount_match.group(1))
        detail = _clean_text(tail[amount_match.end() :])
        return name, amount, detail
    return None


def _evidence(
    source_id: str,
    info_id: str,
    field: str,
    value: str,
    evidence: str,
    source: str,
    rule_name: str,
    confidence: float = 0.86,
) -> Dict[str, Any]:
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


def extract_benefit_table_records_from_ocr_text(
    text: str,
    source_id: str = "",
    info_id: str = "",
    field_mapping: FieldMapping | None = None,
    source: str = "image_ocr_text",
) -> RuleExtractionResult:
    result = RuleExtractionResult()
    source_text = str(text or "")
    if not source_text.strip():
        return result

    field_mapping = field_mapping or load_field_mapping(None)
    common = _find_common_context(source_text)
    for raw_line in source_text.splitlines():
        matched = _match_benefit_line(raw_line)
        if not matched:
            continue
        benefit_name, amount, detail = matched
        record: Dict[str, Any] = {
            "类型": benefit_name,
            "补助限额": amount,
            "病种名称": "",
        }
        if common.get("保险类型"):
            record["保险类型"] = common["保险类型"]
        if common.get("地区名称"):
            record["地区名称"] = common["地区名称"]
        if common.get("人员类型"):
            record["人员类型"] = common["人员类型"]

        note = common.get("备注", "")
        deductible_match = DEDUCTIBLE_RE.search(detail)
        if deductible_match:
            record["起付标准"] = re.sub(r"\s+", "", deductible_match.group(1))
        ratio_match = RATIO_RE.search(detail)
        if ratio_match:
            record["报销比例"] = ratio_match.group(1).replace("％", "%").replace(" ", "")
        waiting_match = WAITING_RE.search(detail)
        if waiting_match:
            note = append_note(note, re.sub(r"\s+", "", waiting_match.group(1)))
        if detail:
            note = append_note(note, detail)
        if note:
            record["备注"] = note

        result.records.append(normalize_record_fields(record, field_mapping))
        line_evidence = _clean_text(raw_line)
        for field in ["类型", "补助限额", "保险类型", "人员类型", "起付标准", "报销比例", "备注"]:
            value = str(record.get(field) or "").strip()
            if not value:
                continue
            result.field_evidence.append(_evidence(source_id, info_id, field, value, line_evidence, source, "benefit_image_table"))

    return result
