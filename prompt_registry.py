import hashlib
from dataclasses import dataclass
from typing import Any, Dict, List

from field_mapping import FieldMapping
from prompts_v2 import build_extract_prompt_v2


DEFAULT_PROMPT_VERSION = "v3"
SUPPORTED_PROMPT_VERSIONS = {"v2", "v3"}


@dataclass(frozen=True)
class PromptPayload:
    version: str
    text: str
    prompt_hash: str
    format: str = "json_object"


def hash_text(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:16]


def build_prompt(
    version: str,
    record: Dict[str, Any],
    clean_text: str,
    tables_text: str,
    image_ocr_text: str,
    today: str,
    field_mapping: FieldMapping | None = None,
    table_rule_records: List[Dict[str, Any]] | None = None,
    text_rule_records: List[Dict[str, Any]] | None = None,
    field_evidence: List[Dict[str, Any]] | None = None,
) -> PromptPayload:
    normalized_version = (version or DEFAULT_PROMPT_VERSION).strip().lower()
    if normalized_version not in SUPPORTED_PROMPT_VERSIONS:
        raise ValueError(f"unsupported prompt version: {version}")
    text = build_extract_prompt_v2(
        record,
        clean_text,
        tables_text,
        image_ocr_text,
        today,
        field_mapping=field_mapping,
        table_rule_records=table_rule_records,
        text_rule_records=text_rule_records,
        field_evidence=field_evidence,
    )
    if normalized_version == "v3":
        text = (
            text
            + "\n\nPROMPT_VERSION=v3\n"
            + "不要编造字段；所有字段必须来自数据库元信息、正文、HTML 表格、图片 OCR 或已有规则证据。\n"
            + "必须返回 JSON object，且顶层只允许 records、evidence、confidence、need_manual_review、review_reason。\n"
            + "对于表格字段，优先使用带 table_index/row_index/col_index/header_path 的规则证据；无法确认时降低 confidence 并说明 review_reason。\n"
            + "当多行待遇表存在时，按类型、人员类型、医院类型、区间、起付标准、补助限额、报销比例等关键字段保持行级对应，不要按输出顺序硬配。\n"
        )
    return PromptPayload(version=normalized_version, text=text, prompt_hash=hash_text(text))
