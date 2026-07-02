import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    load_dotenv = None

from config import PROJECT_ROOT
from config_loader import ConfigError


ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
DEFAULT_APP_CONFIG_PATH = PROJECT_ROOT / "config" / "app_config.yml"


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: list[str] = field(default_factory=list)


@dataclass
class JobsConfig:
    max_workers: int = 2
    job_ttl_days: int = 7


@dataclass
class UploadsConfig:
    max_file_size_mb: int = 20

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024


@dataclass
class ApiConfig:
    require_token: bool = False


@dataclass
class AppConfig:
    server: ServerConfig = field(default_factory=ServerConfig)
    jobs: JobsConfig = field(default_factory=JobsConfig)
    uploads: UploadsConfig = field(default_factory=UploadsConfig)
    api: ApiConfig = field(default_factory=ApiConfig)
    path: Optional[Path] = None


def load_app_config(path: str | Path | None = None, strict_env: bool = True) -> AppConfig:
    _load_dotenv_once()
    config_path = Path(path) if path else DEFAULT_APP_CONFIG_PATH
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path
    if not config_path.exists():
        if path:
            raise ConfigError(f"app config file not found: {config_path}")
        return AppConfig(path=config_path)

    try:
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"app config YAML parse failed: {exc}") from exc
    payload = _expand_env(_as_mapping(payload, "app config"), strict_env=strict_env)
    return app_config_from_mapping(payload, path=config_path)


def coerce_app_config(value: AppConfig | dict[str, Any] | None = None, path: str | Path | None = None) -> AppConfig:
    if value is None:
        return load_app_config(path)
    if isinstance(value, AppConfig):
        return value
    if not isinstance(value, dict):
        raise ConfigError("app_config must be a mapping or AppConfig")
    _load_dotenv_once()
    return app_config_from_mapping(_expand_env(value, strict_env=True), path=Path(path) if path else None)


def app_config_from_mapping(payload: dict[str, Any], path: Path | None = None) -> AppConfig:
    server_payload = _as_mapping(payload.get("server"), "server")
    jobs_payload = _as_mapping(payload.get("jobs"), "jobs")
    uploads_payload = _as_mapping(payload.get("uploads"), "uploads")
    api_payload = _as_mapping(payload.get("api"), "api")

    server = ServerConfig(
        host=str(server_payload.get("host", "127.0.0.1") or "127.0.0.1").strip(),
        port=_as_int(server_payload.get("port"), "server.port", 8000, minimum=1, maximum=65535),
        cors_origins=_as_origin_list(server_payload.get("cors_origins"), "server.cors_origins"),
    )
    if not server.host:
        raise ConfigError("server.host must not be empty")

    jobs = JobsConfig(
        max_workers=_as_int(jobs_payload.get("max_workers"), "jobs.max_workers", 2, minimum=1),
        job_ttl_days=_as_int(jobs_payload.get("job_ttl_days"), "jobs.job_ttl_days", 7, minimum=1),
    )
    uploads = UploadsConfig(
        max_file_size_mb=_as_int(uploads_payload.get("max_file_size_mb"), "uploads.max_file_size_mb", 20, minimum=1),
    )
    api = ApiConfig(require_token=_as_bool(api_payload.get("require_token"), "api.require_token", False))
    return AppConfig(server=server, jobs=jobs, uploads=uploads, api=api, path=path)


def sanitized_app_config(config: AppConfig) -> dict[str, Any]:
    return {
        "server": {
            "host": config.server.host,
            "port": config.server.port,
            "cors_origins": list(config.server.cors_origins),
        },
        "jobs": {
            "max_workers": config.jobs.max_workers,
            "job_ttl_days": config.jobs.job_ttl_days,
        },
        "uploads": {
            "max_file_size_mb": config.uploads.max_file_size_mb,
            "allowed_extensions": [".xlsx"],
        },
        "api": {
            "require_token": config.api.require_token,
        },
    }


def _load_dotenv_once() -> None:
    if load_dotenv is not None:
        load_dotenv(PROJECT_ROOT / ".env", encoding="utf-8-sig", interpolate=False)


def _expand_env(value: Any, strict_env: bool) -> Any:
    if isinstance(value, str):
        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in os.environ:
                if strict_env:
                    raise ConfigError(f"missing required environment variable for app config: {name}")
                return ""
            return os.environ[name]

        return ENV_PATTERN.sub(replace, value)
    if isinstance(value, list):
        return [_expand_env(item, strict_env=strict_env) for item in value]
    if isinstance(value, dict):
        return {key: _expand_env(item, strict_env=strict_env) for key, item in value.items()}
    return value


def _as_mapping(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{name} must be a YAML object")
    return value


def _as_bool(value: Any, name: str, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "on"}:
            return True
        if normalized in {"false", "0", "no", "n", "off", ""}:
            return False
    raise ConfigError(f"{name} must be a boolean")


def _as_int(value: Any, name: str, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    if value is None:
        result = default
    elif isinstance(value, bool):
        raise ConfigError(f"{name} must be an integer")
    elif isinstance(value, int):
        result = value
    elif isinstance(value, str) and value.strip().isdigit():
        result = int(value.strip())
    else:
        raise ConfigError(f"{name} must be an integer")
    if minimum is not None and result < minimum:
        raise ConfigError(f"{name} must be >= {minimum}")
    if maximum is not None and result > maximum:
        raise ConfigError(f"{name} must be <= {maximum}")
    return result


def _as_string_list(value: Any, name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ConfigError(f"{name} must be a YAML list")
    return [str(item or "").strip() for item in value if str(item or "").strip()]


def _as_origin_list(value: Any, name: str) -> list[str]:
    origins = _as_string_list(value, name)
    if any(origin == "*" for origin in origins):
        raise ConfigError("server.cors_origins must list explicit origins; wildcard is not allowed")
    return origins
