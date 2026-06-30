import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List


EXCEL_HEADERS: List[str] = [
    "文章时间",
    "审核日期",
    "info_id",
    "地区名称",
    "个人账户计入办法",
    "个人账户使用范围",
    "病种名称",
    "类型",
    "标化类型",
    "保险类型",
    "人员类型",
    "病种类型",
    "就诊地域",
    "医院类型",
    "就诊情况",
    "区间",
    "起付标准",
    "补助限额",
    "报销比例",
    "备注",
    "相关资讯",
    "审核状态0待审核1已审核",
    "执行状态",
    "开始执行时间",
    "结束时间",
    "是否需要手动修改执行状态(1是0否)",
]

DB_FIELDS: List[str] = [
    "Title",
    "Source",
    "SourceURL",
    "AuditTime",
    "SourceAreaID",
    "areaname",
    "Content",
    "province",
    "insurancetypename",
]

EMPTY_VALUE = "--"
BLANK_VALUE_HEADERS = {"info_id", "相关资讯"}


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        stripped = value.strip()
        return stripped == "" or stripped.lower() in {"none", "null", "nan"}
    return False


def clean_text_value(value: Any) -> str:
    if is_empty(value):
        return EMPTY_VALUE
    if isinstance(value, (datetime, date)):
        return format_datetime_value(value)
    return str(value).strip()


def format_datetime_value(value: Any) -> str:
    if is_empty(value):
        return EMPTY_VALUE
    if isinstance(value, datetime):
        return f"{value.year}/{value.month}/{value.day}"
    if isinstance(value, date):
        return f"{value.year}/{value.month}/{value.day}"
    text = str(value).strip()
    match = re.search(r"(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})", text)
    if match:
        year, month, day = match.groups()
        return f"{int(year)}/{int(month)}/{int(day)}"
    return text


def format_date_for_filename(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y%m%d")
    if isinstance(value, date):
        return value.strftime("%Y%m%d")
    text = clean_text_value(value)
    if text == EMPTY_VALUE:
        return "unknown"
    match = re.search(r"(\d{4})[-/年.]?(\d{1,2})[-/月.]?(\d{1,2})", text)
    if not match:
        return sanitize_filename(text)[:20] or "unknown"
    year, month, day = match.groups()
    return f"{year}{int(month):02d}{int(day):02d}"


def today_yyyymmdd() -> str:
    return datetime.now().strftime("%Y%m%d")


def build_region_name(record: Dict[str, Any]) -> str:
    province = clean_text_value(record.get("province"))
    area = clean_text_value(record.get("areaname"))
    if province != EMPTY_VALUE and area != EMPTY_VALUE:
        if province == area:
            return province
        return f"{province}-{area}"
    if province != EMPTY_VALUE:
        return province
    if area != EMPTY_VALUE:
        return area
    return EMPTY_VALUE


def create_blank_row() -> Dict[str, Any]:
    return {header: EMPTY_VALUE for header in EXCEL_HEADERS}


def create_fallback_row(record: Dict[str, Any], today: str) -> Dict[str, Any]:
    return apply_default_mappings(create_blank_row(), record, today)


def normalize_cell_value(header: str, value: Any) -> Any:
    if header in BLANK_VALUE_HEADERS:
        if is_empty(value) or value == EMPTY_VALUE:
            return ""
        return value
    if header == "审核状态0待审核1已审核":
        if is_empty(value) or value == EMPTY_VALUE:
            return 0
        return value
    if header == "是否需要手动修改执行状态(1是0否)":
        if is_empty(value) or value == EMPTY_VALUE:
            return 0
        return value
    if is_empty(value):
        return EMPTY_VALUE
    return value


def apply_default_mappings(row: Dict[str, Any], record: Dict[str, Any], today: str) -> Dict[str, Any]:
    normalized = create_blank_row()
    for header in EXCEL_HEADERS:
        normalized[header] = normalize_cell_value(header, row.get(header, EMPTY_VALUE))

    article_time = format_datetime_value(record.get("AuditTime"))
    if article_time != EMPTY_VALUE:
        normalized["文章时间"] = article_time
    normalized["审核日期"] = today
    normalized["info_id"] = ""
    region_name = build_region_name(record)
    if region_name != EMPTY_VALUE:
        normalized["地区名称"] = region_name
    normalized["相关资讯"] = ""
    normalized["审核状态0待审核1已审核"] = 0
    normalized["执行状态"] = "执行中"
    normalized["是否需要手动修改执行状态(1是0否)"] = 0
    normalized["备注"] = EMPTY_VALUE

    insurance = clean_text_value(row.get("保险类型"))
    db_insurance = clean_text_value(record.get("insurancetypename"))
    if insurance == EMPTY_VALUE and db_insurance != EMPTY_VALUE:
        normalized["保险类型"] = db_insurance
    return normalized


def append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
    ensure_dir(path.parent)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def sanitize_filename(value: Any, max_length: int = 120) -> str:
    text = clean_text_value(value)
    if text == EMPTY_VALUE:
        text = "unknown"
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text)
    text = re.sub(r"\s+", "_", text).strip("._ ")
    if not text:
        text = "unknown"
    return text[:max_length]


def build_single_filename(record: Dict[str, Any], sequence: int) -> str:
    parts: Iterable[str] = [
        clean_text_value(record.get("province")),
        clean_text_value(record.get("areaname")),
        clean_text_value(record.get("insurancetypename")),
        format_date_for_filename(record.get("AuditTime")),
        f"{sequence:03d}",
    ]
    cleaned = [sanitize_filename(part, 40) for part in parts if clean_text_value(part) != EMPTY_VALUE]
    return "_".join(cleaned) + ".xlsx"
