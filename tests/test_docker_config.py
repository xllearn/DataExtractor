from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read_text(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def _stage_text(dockerfile: str, stage_name: str) -> str:
    marker = f" AS {stage_name}"
    start = dockerfile.lower().find(marker.lower())
    assert start != -1, f"missing Docker stage {stage_name}"
    next_stage = dockerfile.lower().find("\nfrom ", start + 1)
    if next_stage == -1:
        return dockerfile[start:]
    return dockerfile[start:next_stage]


def _compose() -> dict:
    return yaml.safe_load(_read_text("docker-compose.yml"))


def test_dockerignore_excludes_env_and_runtime_artifacts():
    patterns = {
        line.strip()
        for line in _read_text(".dockerignore").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }

    for expected in {
        ".env",
        ".env.*",
        "outputs/",
        "logs/",
        "uploads/",
        "temp_images/",
        "__pycache__/",
        ".pytest_cache/",
        ".venv/",
        ".venv_ocr/",
    }:
        assert expected in patterns


def test_default_docker_stage_excludes_ocr_dependencies_and_ocr_stage_installs_them():
    dockerfile = _read_text("Dockerfile")
    default_stage = _stage_text(dockerfile, "runtime")
    ocr_stage = _stage_text(dockerfile, "ocr")

    assert "requirements-runtime.txt" in default_stage
    assert "sed " not in default_stage.lower()
    assert "paddleocr" not in default_stage.lower()
    assert "paddlepaddle" not in default_stage.lower()
    assert "paddleocr" in ocr_stage.lower()
    assert "paddlepaddle" in ocr_stage.lower()


def test_runtime_requirements_exclude_ocr_dependencies():
    requirements = _read_text("requirements-runtime.txt").lower()

    assert "fastapi" in requirements
    assert "uvicorn" in requirements
    assert "paddleocr" not in requirements
    assert "paddlepaddle" not in requirements


def test_compose_has_default_runtime_service_and_optional_ocr_profile():
    compose = _compose()
    services = compose["services"]
    api = services["api"]
    ocr = services["api-ocr"]

    assert api["build"]["target"] == "runtime"
    assert "profiles" not in api
    assert ocr["build"]["target"] == "ocr"
    assert "ocr" in ocr["profiles"]


def test_compose_mounts_runtime_directories():
    compose = _compose()
    volumes = compose["services"]["api"]["volumes"]

    for expected in {
        "./outputs:/app/outputs",
        "./logs:/app/logs",
        "./uploads:/app/uploads",
        "./config:/app/config",
    }:
        assert expected in volumes


def test_healthchecks_call_api_health():
    dockerfile = _read_text("Dockerfile")
    compose = _compose()

    assert "/api/health" in dockerfile
    assert "/api/health" in " ".join(compose["services"]["api"]["healthcheck"]["test"])
    assert "/api/health" in " ".join(compose["services"]["api-ocr"]["healthcheck"]["test"])


def test_container_command_binds_all_interfaces_and_local_config_stays_loopback():
    compose = _compose()
    api_command = compose["services"]["api"]["command"]
    ocr_command = compose["services"]["api-ocr"]["command"]
    app_config = yaml.safe_load(_read_text("config/app_config.yml"))

    assert "0.0.0.0" in api_command
    assert "0.0.0.0" in ocr_command
    assert app_config["server"]["host"] == "127.0.0.1"


def test_docker_files_do_not_embed_secret_configuration():
    combined = "\n".join([_read_text("Dockerfile"), _read_text("docker-compose.yml")])

    for forbidden in {
        ".env",
        "DATAEXTRACTOR_API_TOKEN",
        "LLM_API_KEY",
        "DATABASE_URL",
        "DB_PASSWORD",
        "password=",
        "token=",
        "secret=",
    }:
        assert forbidden not in combined
