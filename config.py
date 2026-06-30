import argparse
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - dependency is installed in normal use
    load_dotenv = None


PROJECT_ROOT = Path(__file__).resolve().parent


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
        load_dotenv(env_file)

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


def build_arg_parser(settings: Settings) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="从 MySQL 或调试 Excel 抽取政策文章结构化数据")
    parser.add_argument("--mode", choices=["single", "merge"], default=settings.default_mode)
    parser.add_argument("--limit", type=int, default=settings.default_limit)
    parser.add_argument("--offset", type=int, default=settings.default_offset)
    parser.add_argument("--where", default="")
    parser.add_argument("--config", default="config/db_config.yml")
    parser.add_argument("--field-config", default="config/field_mapping.yml")
    parser.add_argument("--keyword", default="")
    parser.add_argument("--keyword-mode", choices=["or", "and"], default="")
    parser.add_argument("--selected-ids", default="")
    parser.add_argument("--input-xlsx", default="")
    parser.add_argument("--output-dir", default=str(settings.output_dir))
    parser.add_argument("--no-ocr", action="store_true")
    parser.add_argument("--debug", action="store_true")
    return parser
