import argparse
import os
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Optional

import yaml

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - dependency is installed in normal use
    load_dotenv = None


PROJECT_ROOT = Path(__file__).resolve().parent
ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class LlmConfigError(ValueError):
    pass


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        return ENV_PATTERN.sub(lambda match: os.getenv(match.group(1), ""), value)
    if isinstance(value, dict):
        return {key: _expand_env(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    return value


@dataclass
class Settings:
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    db_table: str
    llm_provider: str
    llm_api_key: str
    llm_base_url: str
    llm_model: str
    ocr_enabled: bool
    image_base_url: str
    output_dir: Path
    default_mode: str
    default_limit: int
    default_offset: int
    project_root: Path = PROJECT_ROOT


def str_to_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def load_settings(env_path: Optional[Path] = None) -> Settings:
    env_file = env_path or PROJECT_ROOT / ".env"
    if load_dotenv is not None:
        load_dotenv(env_file, encoding="utf-8-sig", interpolate=False)

    return Settings(
        db_host=os.getenv("DB_HOST", "127.0.0.1"),
        db_port=int(os.getenv("DB_PORT", "3306")),
        db_name=os.getenv("DB_NAME", ""),
        db_user=os.getenv("DB_USER", ""),
        db_password=os.getenv("DB_PASSWORD", ""),
        db_table=os.getenv("DB_TABLE", ""),
        llm_provider=os.getenv("LLM_PROVIDER", "deepseek"),
        llm_api_key=os.getenv("LLM_API_KEY", ""),
        llm_base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com"),
        llm_model=os.getenv("LLM_MODEL", "deepseek-chat"),
        ocr_enabled=str_to_bool(os.getenv("OCR_ENABLED"), True),
        image_base_url=os.getenv("IMAGE_BASE_URL", ""),
        output_dir=Path(os.getenv("OUTPUT_DIR", "outputs")),
        default_mode=os.getenv("DEFAULT_MODE", "single"),
        default_limit=int(os.getenv("DEFAULT_LIMIT", "1")),
        default_offset=int(os.getenv("DEFAULT_OFFSET", "0")),
    )


def apply_llm_config(settings: Settings, path: str | Path | None) -> Settings:
    config_path = Path(path) if path else PROJECT_ROOT / "config" / "llm_config.yml"
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path
    if not config_path.exists():
        return settings
    try:
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise LlmConfigError(f"LLM 配置 YAML 解析失败: {exc}") from exc
    if not isinstance(payload, dict):
        raise LlmConfigError("LLM 配置必须是 YAML 对象")
    payload = _expand_env(payload)
    return replace(
        settings,
        llm_provider=str(payload.get("provider") or settings.llm_provider),
        llm_api_key=str(payload.get("api_key") or settings.llm_api_key),
        llm_base_url=str(payload.get("base_url") or settings.llm_base_url),
        llm_model=str(payload.get("model") or settings.llm_model),
    )


def build_arg_parser(settings: Settings) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="从 MySQL 或调试 Excel 抽取政策文章结构化数据")
    parser.add_argument("--mode", choices=["single", "merge"], default=settings.default_mode)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--offset", type=int, default=settings.default_offset)
    parser.add_argument("--where", default="")
    parser.add_argument("--config", default="config/db_config.yml")
    parser.add_argument("--field-config", default="config/field_mapping.yml")
    parser.add_argument("--keyword", default="")
    parser.add_argument("--keyword-mode", choices=["or", "and"], default="")
    parser.add_argument("--selected-ids", default="")
    parser.add_argument("--llm-format", choices=["v2", "legacy"], default="v2")
    parser.add_argument("--llm-config", default="config/llm_config.yml")
    parser.add_argument("--table-config", default="config/table_mapping.yml")
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--input-xlsx", default="")
    parser.add_argument("--output-dir", default=str(settings.output_dir))
    parser.add_argument("--log-dir", default="logs")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-record-errors", type=int, default=20)
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--strict-config", action="store_true")
    parser.add_argument("--no-excel", action="store_true")
    parser.add_argument("--save-intermediate", action="store_true")
    parser.add_argument("--no-ocr", action="store_true")
    parser.add_argument("--ocr-text-file", default="")
    parser.add_argument("--ocr-json-file", default="")
    parser.add_argument("--debug", action="store_true")
    return parser
