import json
from typing import Any, Dict

from utils import EXCEL_HEADERS, build_region_name, format_datetime_value


def build_extract_prompt(
    record: Dict[str, Any],
    clean_text: str,
    tables_text: str,
    image_ocr_text: str,
    today: str,
) -> str:
    meta = {
        "Title": record.get("Title"),
        "Source": record.get("Source"),
        "SourceURL": record.get("SourceURL"),
        "AuditTime": format_datetime_value(record.get("AuditTime")),
        "SourceAreaID": record.get("SourceAreaID"),
        "areaname": record.get("areaname"),
        "province": record.get("province"),
        "insurancetypename": record.get("insurancetypename"),
    }
    defaults = {
        "文章时间": format_datetime_value(record.get("AuditTime")),
        "审核日期": today,
        "info_id": "",
        "地区名称": build_region_name(record),
        "相关资讯": "",
        "备注": "--",
        "审核状态0待审核1已审核": 0,
        "执行状态": "执行中",
        "是否需要手动修改执行状态(1是0否)": 0,
        "抽不到字段": "--",
    }

    return f"""你是商业补充医疗保险、医保待遇政策数据结构化抽取助手。

请根据我提供的数据库元信息、网页正文、HTML表格、图片OCR内容，抽取固定 Excel 字段。

你必须遵守以下规则：

1. 只能依据提供的内容抽取。
2. 不允许根据常识、经验或猜测补充。
3. 原文、表格、OCR 都没有明确说明的字段，填写 "--"。
4. 金额、比例、日期必须尽量保留原文格式。
5. 如果一篇文章包含多个待遇类型、保障责任、人员类型、医院类型、就诊情况、费用区间，必须拆成多行。
6. 如果不同条件下起付标准、补助限额、报销比例不同，必须拆成不同记录。
7. 如果相同信息适用于所有拆分行，需要在每一行重复填写，不要留空。
8. 如果文章只是宣传稿、上线提醒、公众号更名、参保提醒，缺少具体待遇标准，也要尽量抽取已有信息，其余字段填 "--"，不要编造待遇。
9. 个人账户计入办法、个人账户使用范围只有原文明确提到时才填写；没有提到则填 "--"。
10. 病种名称不是必须字段。若原文没有具体病种，填 "--"。
11. 类型字段填写原文对应的待遇类型，例如门诊统筹、住院待遇、特药保障、罕见病保障、个人账户、参保信息、其他。
12. 标化类型字段尽量归一化为：门统、住院、特药、罕见病、个人账户、参保、其他。无法判断填 "--"。
13. 保险类型字段优先使用数据库中的 insurancetypename；如果正文明确是城镇职工、城乡居民、商业补充保险等，也可填写更具体类型。
14. 人员类型、医院类型、就诊情况、区间必须根据原文拆分。
15. 输出必须是 JSON 数组。
16. JSON 数组中的每个对象必须包含完整 26 个字段。
17. 字段名必须和 Excel 表头完全一致。
18. 不要输出任何解释文字。

固定 Excel 字段如下：
{json.dumps(EXCEL_HEADERS, ensure_ascii=False, indent=2)}

默认值如下：
{json.dumps(defaults, ensure_ascii=False, indent=2, default=str)}

数据库元信息：
{json.dumps(meta, ensure_ascii=False, indent=2, default=str)}

网页正文 clean_text：
{clean_text or "--"}

HTML 表格 tables_text：
{tables_text or "--"}

图片 OCR 内容 image_ocr_text：
{image_ocr_text or "--"}
"""
