from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import yaml

from config import PROJECT_ROOT
from utils import EXCEL_HEADERS


class FieldMappingError(ValueError):
    pass


DEFAULTS: Dict[str, Any] = {
    "info_id": "",
    "相关资讯": "",
    "备注": "--",
    "审核状态0待审核1已审核": 0,
    "执行状态": "执行中",
    "是否需要手动修改执行状态(1是0否)": 0,
}
GENERIC_REGION_VALUES = {"国家", "全国", "中国"}

ALIASES: Dict[str, List[str]] = {
    "报销比例": ["支付比例", "报付比例", "补偿比例", "赔付比例"],
    "起付标准": ["起付线", "起付金额", "免赔额"],
    "补助限额": ["最高支付限额", "封顶线", "年度限额", "保障额度"],
    "人员类型": ["适用人群", "参保人员", "参保人群"],
    "医院类型": ["医疗机构", "医院等级", "定点医疗机构"],
    "保险类型": ["险种", "医保类型", "参保险种"],
    "病种名称": ["疾病名称", "特定病种", "保障病种", "纳入病种", "病种范围"],
    "区间": ["报销区间", "费用区间", "医疗费用区间", "赔付区间", "金额区间"],
}


@dataclass
class FieldMapping:
    headers: List[str] = field(default_factory=lambda: list(EXCEL_HEADERS))
    defaults: Dict[str, Any] = field(default_factory=lambda: dict(DEFAULTS))
    aliases: Dict[str, List[str]] = field(default_factory=lambda: {key: list(value) for key, value in ALIASES.items()})

    @property
    def alias_to_header(self) -> Dict[str, str]:
        mapping: Dict[str, str] = {}
        for header, aliases in self.aliases.items():
            for alias in aliases:
                mapping[alias] = header
        return mapping


def _validate_headers(headers: Iterable[str]) -> List[str]:
    headers = [str(header) for header in headers]
    if headers != EXCEL_HEADERS:
        raise FieldMappingError("headers 必须与固定 26 列完全一致，且顺序不能变化")
    if len(set(headers)) != len(headers):
        raise FieldMappingError("headers 存在重复字段")
    return headers


def load_field_mapping(path: str | Path | None) -> FieldMapping:
    config_path: Optional[Path]
    if path is None:
        config_path = None
    else:
        config_path = Path(path)
        if not config_path.is_absolute():
            config_path = PROJECT_ROOT / config_path

    if config_path is None or not config_path.exists():
        return FieldMapping()

    try:
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise FieldMappingError(f"字段配置 YAML 解析失败: {exc}") from exc
    if not isinstance(payload, dict):
        raise FieldMappingError("字段配置必须是 YAML 对象")

    headers = _validate_headers(payload.get("headers", []))
    defaults = dict(DEFAULTS)
    defaults.update(payload.get("defaults") or {})
    aliases = {key: list(value) for key, value in ALIASES.items()}
    for header, values in (payload.get("aliases") or {}).items():
        aliases[str(header)] = [str(value) for value in values or []]
    return FieldMapping(headers=headers, defaults=defaults, aliases=aliases)


def _safe_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return f"{value.year}/{value.month}/{value.day}"
    return str(value)


def normalize_record_fields(row: Dict[str, Any], field_mapping: FieldMapping) -> Dict[str, Any]:
    alias_to_header = field_mapping.alias_to_header
    merged: Dict[str, Any] = {}
    for key, value in (row or {}).items():
        target = key if key in field_mapping.headers else alias_to_header.get(key)
        if target and target in field_mapping.headers and target not in merged:
            merged[target] = value

    normalized: Dict[str, Any] = {}
    for header in field_mapping.headers:
        value = merged.get(header)
        if value is None or value == "":
            value = field_mapping.defaults.get(header, "")
        normalized[header] = _safe_value(value)
    return normalized


def apply_direct_fields(row: Dict[str, Any], record: Dict[str, Any], field_mapping: FieldMapping) -> Dict[str, Any]:
    merged = dict(row or {})
    for header, value in (record.get("_direct_fields") or {}).items():
        if header == "地区名称" and str(value).strip() in GENERIC_REGION_VALUES:
            continue
        if header in field_mapping.headers and value not in (None, ""):
            merged[header] = value
    return normalize_record_fields(merged, field_mapping)


def normalize_records_fields(rows: List[Dict[str, Any]], field_mapping: FieldMapping) -> List[Dict[str, Any]]:
    return [normalize_record_fields(row, field_mapping) for row in rows]
