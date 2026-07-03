import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Sequence


@dataclass
class TableClassification:
    table_type: str
    confidence: float
    confidence_level: str
    positive_signals: List[str] = field(default_factory=list)
    negative_signals: List[str] = field(default_factory=list)
    reason: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "table_type": self.table_type,
            "confidence": round(self.confidence, 6),
            "confidence_level": self.confidence_level,
            "positive_signals": "; ".join(self.positive_signals),
            "negative_signals": "; ".join(self.negative_signals),
            "reason": self.reason,
        }


def confidence_level(confidence: float) -> str:
    if confidence >= 0.75:
        return "high"
    if confidence >= 0.45:
        return "medium"
    return "low"


def classify_table(
    *,
    headers: Sequence[Any] | None = None,
    caption: Any = "",
    rows: Sequence[Sequence[Any]] | None = None,
    row_texts: Sequence[Any] | None = None,
) -> TableClassification:
    headers = [str(item or "") for item in (headers or [])]
    row_texts = [str(item or "") for item in (row_texts or [])]
    if rows:
        row_texts.extend(" ".join(str(cell or "") for cell in row) for row in rows)
    caption_text = str(caption or "")
    all_text = " ".join([caption_text, *headers, *row_texts])
    header_text = " ".join(headers)

    noise_scores = _noise_scores(header_text, caption_text, all_text)
    best_noise_type, best_noise_score, best_noise_signals = max(noise_scores, key=lambda item: item[1])
    treatment_score, treatment_signals = _treatment_score(header_text, caption_text, all_text)
    premium_score, premium_signals = _premium_score(header_text, caption_text, all_text)

    if best_noise_score >= 0.75:
        return _classification(
            best_noise_type,
            best_noise_score,
            positive=[],
            negative=best_noise_signals,
            reason="obvious noise table signals outrank treatment-like cells",
        )

    if treatment_score >= 0.75:
        table_type = "coverage_table" if _contains_any(all_text, COVERAGE_KEYWORDS) else "treatment_table"
        return _classification(
            table_type,
            treatment_score,
            positive=treatment_signals,
            negative=best_noise_signals if best_noise_score >= 0.45 else [],
            reason="benefit/treatment signals with amount or ratio and context",
        )

    if premium_score >= 0.75:
        return _classification(
            "premium_table",
            premium_score,
            positive=premium_signals,
            negative=best_noise_signals if best_noise_score >= 0.45 else [],
            reason="premium or price signals with amount",
        )

    if best_noise_score >= 0.45:
        return _classification(
            best_noise_type,
            best_noise_score,
            positive=treatment_signals,
            negative=best_noise_signals,
            reason="medium confidence noise table",
        )

    if treatment_score >= 0.45:
        return _classification(
            "unknown_table",
            treatment_score,
            positive=treatment_signals,
            negative=[],
            reason="mixed or incomplete treatment signals; keep as candidate",
        )

    return _classification(
        "unknown_table",
        max(treatment_score, premium_score, best_noise_score, 0.2),
        positive=treatment_signals + premium_signals,
        negative=best_noise_signals,
        reason="no strong table type signals",
    )


def classify_normalized_table(table: Any) -> TableClassification:
    rows = [[getattr(cell, "text", "") for cell in row] for row in getattr(table, "rows", []) or []]
    return classify_table(
        headers=list(getattr(table, "headers", []) or []),
        caption=getattr(table, "caption", ""),
        rows=rows,
    )


def table_classification_row(source: Dict[str, Any], table: Any, classification: TableClassification) -> Dict[str, Any]:
    row_count = len(getattr(table, "rows", []) or [])
    payload = {
        "source_id": source.get("source_id", ""),
        "info_id": source.get("info_id", ""),
        "title": source.get("title", ""),
        "table_index": getattr(table, "table_index", ""),
        "headers": " | ".join(str(item) for item in (getattr(table, "headers", []) or [])),
        "caption": getattr(table, "caption", ""),
        "row_count": row_count,
    }
    payload.update(classification.as_dict())
    return payload


def _classification(
    table_type: str,
    confidence: float,
    *,
    positive: Sequence[str],
    negative: Sequence[str],
    reason: str,
) -> TableClassification:
    confidence = max(0.0, min(1.0, float(confidence)))
    return TableClassification(
        table_type=table_type,
        confidence=confidence,
        confidence_level=confidence_level(confidence),
        positive_signals=list(dict.fromkeys(str(item) for item in positive if item)),
        negative_signals=list(dict.fromkeys(str(item) for item in negative if item)),
        reason=reason,
    )


def _contains_any(text: str, keywords: Iterable[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _hits(text: str, keywords: Iterable[str]) -> List[str]:
    return [keyword for keyword in keywords if keyword in text]


def _has_amount_or_ratio(text: str) -> bool:
    return bool(
        re.search(r"\d+(?:\.\d+)?\s*[%％]", text)
        or re.search(r"\d+(?:\.\d+)?\s*(?:元|万元|万|人民币)", text)
        or "百分之" in text
    )


def _noise_scores(header_text: str, caption_text: str, all_text: str) -> List[tuple[str, float, List[str]]]:
    definitions = {
        "co_insurer_table": CO_INSURER_KEYWORDS,
        "faq_table": FAQ_KEYWORDS,
        "contact_table": CONTACT_KEYWORDS,
        "directory_table": DIRECTORY_KEYWORDS,
        "timeline_table": TIMELINE_KEYWORDS,
        "marketing_table": MARKETING_KEYWORDS,
    }
    scores: List[tuple[str, float, List[str]]] = []
    header_caption = f"{header_text} {caption_text}"
    for table_type, keywords in definitions.items():
        signals = _hits(all_text, keywords)
        strong_signals = _hits(header_caption, keywords)
        score = 0.0
        if signals:
            score = min(0.95, 0.35 + 0.15 * len(signals) + 0.12 * len(strong_signals))
        if table_type == "faq_table" and re.search(r"(^|\s)[QA问答][：:、\s]", all_text, re.I):
            signals.append("Q/A")
            score = max(score, 0.78)
        scores.append((table_type, score, signals))
    return scores


def _treatment_score(header_text: str, caption_text: str, all_text: str) -> tuple[float, List[str]]:
    signals: List[str] = []
    treatment_hits = _hits(all_text, TREATMENT_KEYWORDS)
    context_hits = _hits(all_text, CONTEXT_KEYWORDS)
    header_hits = _hits(f"{header_text} {caption_text}", TREATMENT_KEYWORDS + CONTEXT_KEYWORDS)
    if treatment_hits:
        signals.extend(f"treatment:{item}" for item in treatment_hits)
    if context_hits:
        signals.extend(f"context:{item}" for item in context_hits)
    if header_hits:
        signals.extend(f"header_or_caption:{item}" for item in header_hits)
    has_amount = _has_amount_or_ratio(all_text)
    if has_amount:
        signals.append("amount_or_ratio")
    score = 0.2
    if treatment_hits:
        score += 0.25
    if has_amount:
        score += 0.25
    if context_hits:
        score += 0.2
    if header_hits:
        score += 0.15
    return min(score, 0.95), signals


def _premium_score(header_text: str, caption_text: str, all_text: str) -> tuple[float, List[str]]:
    signals = _hits(all_text, PREMIUM_KEYWORDS)
    header_hits = _hits(f"{header_text} {caption_text}", PREMIUM_KEYWORDS)
    has_amount = _has_amount_or_ratio(all_text)
    labelled = [f"premium:{item}" for item in signals]
    if header_hits:
        labelled.extend(f"header_or_caption:{item}" for item in header_hits)
    if has_amount:
        labelled.append("amount")
    score = 0.2
    if signals:
        score += 0.35
    if header_hits:
        score += 0.15
    if has_amount:
        score += 0.25
    return min(score, 0.9), labelled


TREATMENT_KEYWORDS = [
    "报销",
    "赔付",
    "给付",
    "免赔",
    "起付",
    "限额",
    "补助",
    "补偿",
    "待遇",
]
COVERAGE_KEYWORDS = [
    "保障责任",
    "保障项目",
    "责任",
    "医疗费用",
    "医保内",
    "医保外",
]
CONTEXT_KEYWORDS = [
    "住院",
    "门诊",
    "特药",
    "药品",
    "医疗费用",
    "医保内",
    "医保外",
    "保障责任",
    "保障项目",
    "责任",
    "人群",
    "人员",
    "医院",
    "病种",
    "疾病",
]
PREMIUM_KEYWORDS = ["保费", "价格", "缴费", "支付金额", "年度保费"]
CO_INSURER_KEYWORDS = ["保险公司", "承保公司", "共保体", "服务电话", "客服电话", "承保机构"]
FAQ_KEYWORDS = ["常见问题", "问题", "答案", "问：", "答：", "Q：", "A：", "Q:", "A:"]
CONTACT_KEYWORDS = ["电话", "热线", "二维码", "公众号", "客服", "地址", "联系方式", "联系"]
DIRECTORY_KEYWORDS = ["目录", "章节", "页码", "序号"]
TIMELINE_KEYWORDS = ["时间", "阶段", "投保时间", "等待期", "生效时间"]
MARKETING_KEYWORDS = ["产品亮点", "保障特色", "为什么买", "适合人群", "投保入口", "扫码", "链接"]
