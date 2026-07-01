import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List

from config import PROJECT_ROOT
from config_loader import validate_db_config_ready
from utils import ensure_dir


def resolve_effective_limit(args_limit: int | None, settings, db_config=None, configured_db_enabled: bool = False) -> int:
    if args_limit is not None:
        return int(args_limit)
    if configured_db_enabled and db_config is not None:
        return int(db_config.query.default_limit)
    return int(settings.default_limit)


def validate_keyword_supported(keyword: str, configured_db_enabled: bool) -> None:
    if keyword and not configured_db_enabled:
        raise ValueError("--keyword 需要启用 config/db_config.yml 配置化数据库读取；旧 db.py 模式暂不支持关键词检索")


def resolve_runtime_flags(dry_run: bool, no_llm: bool, no_ocr: bool, no_excel: bool) -> Dict[str, bool]:
    return {
        "no_llm": bool(no_llm or dry_run),
        "no_ocr": bool(no_ocr or dry_run or no_llm),
        "no_excel": bool(no_excel or dry_run),
    }


def should_stop_processing(record_error_count: int, max_record_errors: int, fail_fast: bool) -> bool:
    if fail_fast and record_error_count > 0:
        return True
    return record_error_count >= max_record_errors


def validate_strict_runtime_config(db_config, input_xlsx: str) -> None:
    if input_xlsx:
        return
    if not db_config.exists or not db_config.database_url:
        raise ValueError("strict-config 模式要求配置 DATABASE_URL，且不能回退旧 db.py 流程")
    validate_db_config_ready(db_config)


def resolve_input_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    candidates = [Path.cwd() / path, PROJECT_ROOT / path, PROJECT_ROOT.parent / path]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return PROJECT_ROOT / path


def resolve_runtime_paths(output_dir: str, log_dir: str) -> tuple[Path, Path, Path, Path]:
    logs_dir = Path(log_dir)
    if not logs_dir.is_absolute():
        logs_dir = PROJECT_ROOT / logs_dir
    output_path = Path(output_dir)
    if not output_path.is_absolute():
        output_path = PROJECT_ROOT / output_path
    return logs_dir, output_path, PROJECT_ROOT / "temp_images", PROJECT_ROOT / "templates" / "template.xlsx"


def setup_logging(logs_dir: Path, debug: bool = False) -> logging.Logger:
    ensure_dir(logs_dir)
    logger = logging.getLogger("db_to_excel_extractor")
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    file_handler = logging.FileHandler(logs_dir / "run.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.addHandler(console_handler)
    return logger


def load_external_ocr_inputs(text_file: str = "", json_file: str = "") -> tuple[str, Dict[str, str]]:
    text = ""
    mapping: Dict[str, str] = {}
    if text_file:
        path = resolve_input_path(text_file)
        text = path.read_text(encoding="utf-8")
    if json_file:
        path = resolve_input_path(json_file)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("--ocr-json-file 必须是 JSON object")
        mapping = {str(key): str(value) for key, value in payload.items() if str(value).strip()}
    return text, mapping


def external_ocr_for_record(record: Dict[str, Any], global_text: str, mapping: Dict[str, str]) -> str:
    keys = [
        str(record.get("_source_id") or ""),
        str(record.get("SourceURL") or ""),
        str(record.get("info_id") or ""),
        str((record.get("_direct_fields") or {}).get("info_id") or ""),
    ]
    for key in keys:
        if key and key in mapping:
            return mapping[key]
    return global_text
