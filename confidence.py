import re
from typing import Any, Dict, Iterable, List

from utils import EMPTY_VALUE, EXCEL_HEADERS, is_empty


EVAL_FIELDS = [
    "confidence_score",
    "confidence_level",
    "confidence_reason",
    "should_retry_with_ocr",
    "ocr_trigger_reason",
    "evidence_score",
    "key_field_score",
    "ocr_risk_score",
]

DEFAULT_EVIDENCE_EXCLUDE = {
    "文章时间",
    "审核日期",
    "info_id",
    "备注",
    "相关资讯",
    "审核状态0待审核1已审核",
    "执行状态",
    "开始执行时间",
    "结束时间",
    "是否需要手动修改执行状态(1是0否)",
}

KEY_FIELD_CUES = [
    ("起付标准", ["起付", "免赔"]),
    ("补助限额", ["限额", "保额", "最高", "封顶", "保障额度"]),
    ("报销比例", ["报销", "赔付", "支付比例", "比例"]),
    ("人员类型", ["人群", "参保人", "职工", "居民", "退休", "适用人群"]),
    ("病种名称", ["病种", "特药", "药品", "疾病"]),
    ("类型", ["保障", "待遇", "责任", "住院", "门诊", "特药"]),
]


def evaluate_rows(
    rows: List[Dict[str, Any]],
    record: Dict[str, Any],
    clean_text: str,
    tables_text: str,
    image_ocr_text: str,
    image_count: int,
    ocr_attempted: bool,
) -> List[Dict[str, Any]]:
    source_text = "\n".join([clean_text or "", tables_text or "", image_ocr_text or ""])
    return [
        evaluate_row(row, record, source_text, clean_text or "", tables_text or "", image_ocr_text or "", image_count, ocr_attempted)
        for row in rows
    ]


def evaluate_row(
    row: Dict[str, Any],
    record: Dict[str, Any],
    source_text: str,
    clean_text: str,
    tables_text: str,
    image_ocr_text: str,
    image_count: int,
    ocr_attempted: bool,
) -> Dict[str, Any]:
    evidence_score, evidence_reason = calculate_evidence_score(row, source_text, record)
    key_field_score, key_reason = calculate_key_field_score(row, source_text, record)
    ocr_risk_score, ocr_reason = calculate_ocr_risk_score(clean_text, tables_text, image_ocr_text, image_count, ocr_attempted)

    confidence_score = round(evidence_score * 0.5 + key_field_score * 0.3 + ocr_risk_score * 0.2)
    confidence_score = max(0, min(100, int(confidence_score)))
    confidence_level = "high" if confidence_score >= 85 else "medium" if confidence_score >= 70 else "low"

    should_retry = confidence_score < 70 and ocr_risk_score < 80
    trigger_reason = ocr_reason if should_retry else EMPTY_VALUE
    reason_parts = [part for part in [evidence_reason, key_reason, ocr_reason if ocr_risk_score < 80 else ""] if part]

    return {
        "confidence_score": confidence_score,
        "confidence_level": confidence_level,
        "confidence_reason": "；".join(reason_parts) or "核心字段和证据一致性较好",
        "should_retry_with_ocr": bool(should_retry),
        "ocr_trigger_reason": trigger_reason,
        "evidence_score": evidence_score,
        "key_field_score": key_field_score,
        "ocr_risk_score": ocr_risk_score,
    }


def calculate_evidence_score(row: Dict[str, Any], source_text: str, record: Dict[str, Any]) -> tuple[int, str]:
    candidates = []
    for header in EXCEL_HEADERS:
        if header in DEFAULT_EVIDENCE_EXCLUDE:
            continue
        value = row.get(header)
        if is_meaningful_value(value):
            candidates.append((header, str(value)))

    if not candidates:
        return 85, "文章可抽取信息较少，未按字段覆盖率扣分"

    matched = 0
    missing = []
    for header, value in candidates:
        if value_has_evidence(header, value, source_text, record):
            matched += 1
        else:
            missing.append(header)

    ratio = matched / len(candidates)
    score = int(40 + ratio * 60)
    if not missing:
        return 100, "已抽取字段基本能在文本或元信息中找到依据"
    return score, f"{'、'.join(missing[:4])} 未找到直接文本依据"


def calculate_key_field_score(row: Dict[str, Any], source_text: str, record: Dict[str, Any]) -> tuple[int, str]:
    missing = []
    total_checks = 0
    cue_checks = 0

    metadata_checks = [
        ("地区名称", bool(record.get("province") or record.get("areaname"))),
        ("保险类型", bool(record.get("insurancetypename"))),
        ("文章时间", bool(record.get("AuditTime"))),
    ]
    for header, expected in metadata_checks:
        if expected:
            total_checks += 1
            if not is_meaningful_value(row.get(header)):
                missing.append(header)

    for header, cues in KEY_FIELD_CUES:
        if any(cue in source_text for cue in cues):
            total_checks += 1
            cue_checks += 1
            if header == "病种名称" and is_meaningful_value(row.get("病种类型")):
                continue
            if not is_meaningful_value(row.get(header)):
                missing.append(header)

    if total_checks == 0:
        return 85, "正文未出现明显待遇标准线索"
    if not missing:
        if cue_checks == 0:
            return 85, "正文未出现明显待遇标准线索"
        return 100, "业务核心字段与文本线索匹配"

    ratio = 1 - len(missing) / total_checks
    score = int(45 + max(0, ratio) * 55)
    return score, f"核心字段缺少：{'、'.join(missing[:5])}"


def calculate_ocr_risk_score(
    clean_text: str,
    tables_text: str,
    image_ocr_text: str,
    image_count: int,
    ocr_attempted: bool,
) -> tuple[int, str]:
    text_length = len(strip_space(clean_text))
    has_table_text = bool(strip_space(tables_text))
    has_ocr_text = bool(strip_space(image_ocr_text))

    if image_count <= 0:
        return 100, "未发现图片，OCR风险低"

    score = 85
    reasons = [f"发现{image_count}张图片"]
    if not ocr_attempted:
        score -= 35
        reasons.append("首轮未识别图片")
    if text_length < 300:
        score -= 35
        reasons.append("正文较短")
    elif text_length < 800:
        score -= 10
        reasons.append("正文信息量有限")
    if not has_table_text:
        score -= 15
        reasons.append("未提取到HTML表格")
    if image_count >= 3:
        score -= 10
        reasons.append("图片数量较多")
    if has_ocr_text:
        score += 25
        reasons.append("已有OCR文本")

    score = max(0, min(100, score))
    return score, "、".join(reasons)


def mark_ocr_failed(evaluations: Iterable[Dict[str, Any]], reason: str) -> List[Dict[str, Any]]:
    marked = []
    for item in evaluations:
        updated = dict(item)
        extra = f"OCR失败，保留首轮结果：{reason}"
        updated["confidence_reason"] = f"{updated.get('confidence_reason') or EMPTY_VALUE}；{extra}"
        updated["should_retry_with_ocr"] = False
        updated["ocr_trigger_reason"] = extra
        marked.append(updated)
    return marked


def is_meaningful_value(value: Any) -> bool:
    if is_empty(value):
        return False
    return str(value).strip() != EMPTY_VALUE


def value_has_evidence(header: str, value: str, source_text: str, record: Dict[str, Any]) -> bool:
    if normalized_contains(source_text, value):
        return True
    if header == "地区名称":
        return any(normalized_contains(value, str(record.get(key) or "")) for key in ("province", "areaname"))
    if header == "保险类型":
        return normalized_contains(value, str(record.get("insurancetypename") or ""))
    return False


def normalized_contains(container: str, value: str) -> bool:
    needle = normalize_for_match(value)
    haystack = normalize_for_match(container)
    if not needle:
        return False
    if needle in haystack:
        return True
    if len(needle) > 8:
        return needle[:8] in haystack
    return False


def normalize_for_match(text: str) -> str:
    return re.sub(r"[\s,，。；;：:、|/\\（）()\[\]【】<>《》\"'“”‘’\-_]+", "", str(text).lower())


def strip_space(text: str) -> str:
    return re.sub(r"\s+", "", text or "")
