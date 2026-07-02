import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_app_config_expands_env_values_in_strict_mode():
    from app_config_loader import load_app_config

    with tempfile.TemporaryDirectory() as tmp:
        config_path = Path(tmp) / "app_config.yml"
        config_path.write_text(
            """
server:
  host: "${DATAEXTRACTOR_TEST_HOST}"
  port: "${DATAEXTRACTOR_TEST_PORT}"
  cors_origins:
    - "${DATAEXTRACTOR_TEST_ORIGIN}"
jobs:
  max_workers: "${DATAEXTRACTOR_TEST_WORKERS}"
  job_ttl_days: 9
uploads:
  max_file_size_mb: "${DATAEXTRACTOR_TEST_UPLOAD_MB}"
api:
  require_token: "${DATAEXTRACTOR_TEST_REQUIRE_TOKEN}"
""",
            encoding="utf-8",
        )
        env = {
            "DATAEXTRACTOR_TEST_HOST": "127.0.0.2",
            "DATAEXTRACTOR_TEST_PORT": "9100",
            "DATAEXTRACTOR_TEST_ORIGIN": "https://ui.example.test",
            "DATAEXTRACTOR_TEST_WORKERS": "3",
            "DATAEXTRACTOR_TEST_UPLOAD_MB": "7",
            "DATAEXTRACTOR_TEST_REQUIRE_TOKEN": "true",
        }

        with patch.dict(os.environ, env, clear=False):
            config = load_app_config(config_path)

    assert config.server.host == "127.0.0.2"
    assert config.server.port == 9100
    assert config.server.cors_origins == ["https://ui.example.test"]
    assert config.jobs.max_workers == 3
    assert config.jobs.job_ttl_days == 9
    assert config.uploads.max_file_size_mb == 7
    assert config.api.require_token is True


def test_app_config_strict_mode_rejects_missing_env_values():
    from app_config_loader import ConfigError, load_app_config

    with tempfile.TemporaryDirectory() as tmp:
        config_path = Path(tmp) / "app_config.yml"
        config_path.write_text(
            """
server:
  host: "${DATAEXTRACTOR_TEST_MISSING_HOST}"
""",
            encoding="utf-8",
        )

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ConfigError, match="DATAEXTRACTOR_TEST_MISSING_HOST"):
                load_app_config(config_path)
