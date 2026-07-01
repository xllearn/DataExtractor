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
9. “病种名称”只能填写具体疾病、病种或病症名称，例如：帕金森病、高血压、糖尿病、恶性肿瘤、白血病、罕见病等。
10. 病种名称不要填写包含人物、地名、时间、宣传语、费用说明或普通句子的长文本；如果原文没有明确具体病种，病种名称填空字符串。
11. 不要为了填字段而从宣传语中截取“病”“症”等字；“大病”“既往症”“慢性病”“特殊病”等泛化类别可放入“病种类型”或“备注”，不要直接放入“病种名称”。
12. 不要把“高额医疗费用”“合理自费费用”“医保定点医药机构发生的大病”等费用或场景描述填入病种名称。
13. “人员类型”只填写人群身份或参保类别，例如：职工、居民、城乡居民、城镇职工、参保职工、参保居民、退休人员、在职职工、被保险人、投保人、少儿、成人、老年人、新生儿、学生等。不要把年龄范围填入人员类型。
14. “区间”只用于报销金额区间、费用区间或赔付金额区间；区间只用于报销金额区间，例如：50000元-400000元、0-1000元、5万元以上。不要把年龄范围填入区间。
15. 如果原文只有“6-65周岁”“18-70岁”“28天至60周岁”等年龄范围，人员类型和区间都填空字符串，可在备注中写“年龄区间：6-65周岁”。

病种名称示例：
- 错误：澄迈县的李女士去年帕金森病
- 正确：帕金森病
- 错误：旨在减轻被保险人因患大病
- 正确：空字符串，或将“大病”放入病种类型/备注
- 错误：医保定点医药机构发生的大病
- 正确：空字符串，或将“大病”放入病种类型/备注

人员类型和区间示例：
- 错误：人员类型=6-65周岁
- 正确：人员类型=空字符串；备注=年龄区间：6-65周岁
- 错误：区间=18-70岁
- 正确：区间=空字符串；备注=年龄区间：18-70岁
- 正确：区间=50000元-400000元

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
