import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    load_dotenv = None

from config import PROJECT_ROOT


class ConfigError(ValueError):
    pass


@dataclass
class SourceConfig:
    table: str = ""
    id_column: str = ""
    info_id_column: str = ""
    title_column: str = ""
    html_column: str = ""
    text_column: str = ""
    article_time_column: str = ""
    audit_time_column: str = ""
    region_column: str = ""
    source_url_column: str = ""
    related_info_column: str = ""
    insurance_type_column: str = ""


@dataclass
class QueryConfig:
    default_limit: int = 50
    keyword_mode: str = "or"


@dataclass
class DbConfig:
    exists: bool = False
    database_url: str = ""
    source: SourceConfig = field(default_factory=SourceConfig)
    query: QueryConfig = field(default_factory=QueryConfig)
    direct_field_columns: Dict[str, str] = field(default_factory=dict)
    path: Optional[Path] = None

    @property
    def use_configured_reader(self) -> bool:
        return bool(self.exists and self.database_url and self.source.table)


ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def parse_selected_ids(value: str | None) -> List[str]:
    if not value:
        return []
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _load_dotenv_once() -> None:
    if load_dotenv is not None:
        load_dotenv(PROJECT_ROOT / ".env", encoding="utf-8-sig", interpolate=False)


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        return ENV_PATTERN.sub(lambda match: os.getenv(match.group(1), ""), value)
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    if isinstance(value, dict):
        return {key: _expand_env(item) for key, item in value.items()}
    return value


def _as_mapping(value: Any, name: str) -> Dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{name} 必须是 YAML 对象")
    return value


def load_db_config(path: str | Path | None, require_ready: bool = False) -> DbConfig:
    _load_dotenv_once()
    config_path = Path(path) if path else PROJECT_ROOT / "config" / "db_config.yml"
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path
    if not config_path.exists():
        return DbConfig(exists=False, path=config_path)

    try:
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"数据库配置 YAML 解析失败: {exc}") from exc
    payload = _expand_env(_as_mapping(payload, "数据库配置"))

    database = _as_mapping(payload.get("database"), "database")
    source_payload = _as_mapping(payload.get("source"), "source")
    query_payload = _as_mapping(payload.get("query"), "query")
    direct_field_columns = {
        str(key): "" if value is None else str(value).strip()
        for key, value in _as_mapping(payload.get("direct_field_columns"), "direct_field_columns").items()
    }

    source = SourceConfig(**{field_name: str(source_payload.get(field_name, "") or "").strip() for field_name in SourceConfig.__dataclass_fields__})
    keyword_mode = str(query_payload.get("keyword_mode", "or") or "or").strip().lower()
    if keyword_mode not in {"or", "and"}:
        raise ConfigError("query.keyword_mode 只能是 or 或 and")
    query = QueryConfig(
        default_limit=int(query_payload.get("default_limit", 50) or 50),
        keyword_mode=keyword_mode,
    )
    config = DbConfig(
        exists=True,
        database_url=str(database.get("url", "") or "").strip(),
        source=source,
        query=query,
        direct_field_columns=direct_field_columns,
        path=config_path,
    )
    if require_ready:
        validate_db_config_ready(config)
    return config


def validate_db_config_ready(config: DbConfig) -> None:
    if not config.database_url:
        raise ConfigError("database.url 不能为空；可使用 ${DATABASE_URL} 从环境变量读取")
    if not config.source.table:
        raise ConfigError("source.table 不能为空")
    if not (config.source.html_column or config.source.text_column):
        raise ConfigError("source.html_column 或 source.text_column 至少需要配置一个")
