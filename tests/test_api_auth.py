import os
import runpy
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _client(tmp: str, app_config: dict | None = None) -> TestClient:
    from api_server import create_app

    return TestClient(
        create_app(
            record_provider=lambda **_: {"items": [], "total": 0},
            output_dir=Path(tmp) / "out",
            log_dir=Path(tmp) / "logs",
            app_config=app_config,
        )
    )


def test_token_required_blocks_non_public_routes_and_allows_health_version():
    token = "phase3-task8-token"
    app_config = {"api": {"require_token": True}}

    with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"DATAEXTRACTOR_API_TOKEN": token}, clear=False):
        client = _client(tmp, app_config)

        health = client.get("/api/health")
        version = client.get("/api/version")
        missing = client.get("/api/articles")
        invalid = client.get("/api/articles", headers={"Authorization": "Bearer wrong"})
        malformed = client.get("/api/articles", headers={"Authorization": token})
        valid = client.get("/api/articles", headers={"Authorization": f"Bearer {token}"})

    assert health.status_code == 200
    assert version.status_code == 200
    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert malformed.status_code == 401
    assert valid.status_code == 200
    for response in (missing, invalid, malformed):
        assert response.headers["content-type"].split(";")[0] == "application/json"
        assert response.json()["error_type"] == "Unauthorized"
        assert token not in response.text


def test_token_env_does_not_require_auth_when_config_disabled():
    with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"DATAEXTRACTOR_API_TOKEN": "unused-token"}, clear=False):
        client = _client(tmp, {"api": {"require_token": False}})
        response = client.get("/api/articles")

    assert response.status_code == 200


def test_require_token_without_env_raises_clear_config_error():
    from api_server import create_app
    from config_loader import ConfigError

    with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
        with pytest.raises(ConfigError, match="DATAEXTRACTOR_API_TOKEN"):
            create_app(
                record_provider=lambda **_: {"items": [], "total": 0},
                output_dir=Path(tmp) / "out",
                log_dir=Path(tmp) / "logs",
                app_config={"api": {"require_token": True}},
            )


def test_cors_default_closed_and_configured_origin_only():
    with tempfile.TemporaryDirectory() as tmp:
        default_client = _client(tmp, None)
        default_response = default_client.get("/api/health", headers={"Origin": "https://ui.example.test"})

    with tempfile.TemporaryDirectory() as tmp:
        cors_client = _client(tmp, {"server": {"cors_origins": ["https://ui.example.test"]}})
        allowed = cors_client.get("/api/health", headers={"Origin": "https://ui.example.test"})
        denied = cors_client.get("/api/health", headers={"Origin": "https://evil.example.test"})

    assert "access-control-allow-origin" not in default_response.headers
    assert allowed.headers["access-control-allow-origin"] == "https://ui.example.test"
    assert "access-control-allow-origin" not in denied.headers


def test_version_and_config_status_do_not_expose_secrets():
    token = "phase3-super-secret-token"
    env = {
        "DATAEXTRACTOR_API_TOKEN": token,
        "DATABASE_URL": "mysql+pymysql://user:db-secret@127.0.0.1/db",
        "LLM_API_KEY": "sk-test-secret-key",
    }

    with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, env, clear=False):
        client = _client(tmp, {"api": {"require_token": True}})
        version = client.get("/api/version")
        status = client.get("/api/config/status", headers={"Authorization": f"Bearer {token}"})

    assert version.status_code == 200
    assert status.status_code == 200
    combined = f"{version.text}\n{status.text}"
    for secret in (
        token,
        "DATAEXTRACTOR_API_TOKEN",
        "DATABASE_URL",
        "LLM_API_KEY",
        "db-secret",
        "sk-test-secret-key",
        ".env",
    ):
        assert secret not in combined


def test_main_uses_app_config_host_port_and_prints_sanitized_config(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        config_path = Path(tmp) / "app_config.yml"
        config_path.write_text(
            """
server:
  host: "127.0.0.9"
  port: 9876
  cors_origins:
    - "https://ui.example.test"
api:
  require_token: true
""",
            encoding="utf-8",
        )
        calls = []
        fake_uvicorn = types.SimpleNamespace(run=lambda app, **kwargs: calls.append({"app": app, **kwargs}))

        with patch.dict(os.environ, {"DATAEXTRACTOR_API_TOKEN": "main-secret-token"}, clear=False), patch.dict(
            sys.modules, {"uvicorn": fake_uvicorn}
        ), patch.object(sys, "argv", ["api_server.py", "--app-config", str(config_path)]):
            try:
                module_globals = runpy.run_path(str(Path(__file__).resolve().parents[1] / "api_server.py"), run_name="__main__")
            except SystemExit as exc:
                assert exc.code == 0
                module_globals = {}

    assert module_globals is not None
    assert calls
    assert calls[0]["host"] == "127.0.0.9"
    assert calls[0]["port"] == 9876
    output = capsys.readouterr().out
    assert "effective_app_config=" in output
    assert "127.0.0.9" in output
    assert "9876" in output
    assert "main-secret-token" not in output
    assert "DATAEXTRACTOR_API_TOKEN" not in output


def test_upload_extension_cannot_be_relaxed_by_app_config():
    from openpyxl import Workbook

    workbook_path = Path(tempfile.gettempdir()) / "dataextractor-valid-upload-for-extension-test.xlsx"
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(["Title", "Content"])
    worksheet.append(["A", "B"])
    workbook.save(workbook_path)
    workbook.close()
    file_bytes = workbook_path.read_bytes()
    workbook_path.unlink()

    with tempfile.TemporaryDirectory() as tmp:
        client = _client(tmp, {"uploads": {"allowed_extensions": [".csv"]}})
        response = client.post(
            "/api/uploads/excel",
            files={"file": ("unsafe.csv", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )

    assert response.status_code == 400
    assert response.json()["error_type"] == "ValidationError"
    assert ".xlsx" in response.json()["detail"]


def test_main_app_config_override_is_not_blocked_by_bad_default_config(capsys):
    project_root = Path(__file__).resolve().parents[1]

    with tempfile.TemporaryDirectory() as tmp:
        bad_default_path = Path(tmp) / "bad_default_app_config.yml"
        bad_default_path.write_text("server: [broken]\n", encoding="utf-8")
        override_path = Path(tmp) / "app_config.yml"
        override_path.write_text(
            """
server:
  host: "127.0.0.10"
  port: 9877
""",
            encoding="utf-8",
        )
        calls = []
        fake_uvicorn = types.SimpleNamespace(run=lambda app, **kwargs: calls.append({"app": app, **kwargs}))

        with patch("app_config_loader.DEFAULT_APP_CONFIG_PATH", bad_default_path), patch.dict(
            sys.modules, {"uvicorn": fake_uvicorn}
        ), patch.object(sys, "argv", ["api_server.py", "--app-config", str(override_path)]):
            try:
                runpy.run_path(str(project_root / "api_server.py"), run_name="__main__")
            except SystemExit as exc:
                assert exc.code == 0

    assert calls
    assert calls[0]["host"] == "127.0.0.10"
    assert calls[0]["port"] == 9877
    assert "effective_app_config=" in capsys.readouterr().out
