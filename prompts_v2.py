import json
from typing import Any, Dict, List

from field_mapping import FieldMapping, load_field_mapping
from prompts import build_extract_prompt
from utils import build_region_name, format_datetime_value


def build_extract_prompt_v2(
    record: Dict[str, Any],
    clean_text: str,
    tables_text: str,
    image_ocr_text: str,
    today: str,
    field_mapping: FieldMapping | None = None,
    table_rule_records: List[Dict[str, Any]] | None = None,
    text_rule_records: List[Dict[str, Any]] | None = None,
    field_evidence: List[Dict[str, Any]] | None = None,
) -> str:
    field_mapping = field_mapping or load_field_mapping(None)
    meta = {
        "Title": record.get("Title"),
        "Source": record.get("Source"),
        "SourceURL": record.get("SourceURL"),
        "AuditTime": format_datetime_value(record.get("AuditTime")),
        "SourceAreaID": record.get("SourceAreaID"),
        "areaname": record.get("areaname"),
        "province": record.get("province"),
        "insurancetypename": record.get("insurancetypename"),
        "地区名称": build_region_name(record),
    }
    skeleton = {header: "" for header in field_mapping.headers}
    return f"""你是商业补充医疗保险、医保待遇政策数据结构化抽取助手。

请只依据提供的数据库元信息、网页正文、HTML表格、图片OCR内容以及规则抽取参考，抽取固定 26 列字段。不要编造。

必须返回严格 JSON object，根节点格式如下：
{json.dumps({"records": [skeleton], "evidence": {}, "confidence": {}, "need_manual_review": False, "review_reason": ""}, ensure_ascii=False, indent=2)}

规则：
1. 根节点必须是 object。
2. records 必须是 list。
3. records 中每条记录只能包含固定 26 列字段，多余字段不要输出。
4. 缺失字段填空字符串、"--" 或默认值。
5. evidence 是字段到原文证据片段的 object。
6. confidence 是字段到 0-1 数值的 object。
7. need_manual_review 必须是 boolean。
8. 如果规则抽取参考与正文冲突，以正文、表格、OCR 原始内容为准。

固定 26 列字段：
{json.dumps(field_mapping.headers, ensure_ascii=False, indent=2)}

数据库元信息：
{json.dumps(meta, ensure_ascii=False, indent=2, default=str)}

表格规则抽取参考：
{json.dumps(table_rule_records or [], ensure_ascii=False, indent=2, default=str)}

正文规则抽取参考：
{json.dumps(text_rule_records or [], ensure_ascii=False, indent=2, default=str)}

已有字段证据：
{json.dumps(field_evidence or [], ensure_ascii=False, indent=2, default=str)}

网页正文 clean_text：
{clean_text or "--"}

HTML 表格 tables_text：
{tables_text or "--"}

图片 OCR 内容 image_ocr_text：
{image_ocr_text or "--"}
"""


def build_legacy_extract_prompt(*args, **kwargs) -> str:
    return build_extract_prompt(*args, **kwargs)
