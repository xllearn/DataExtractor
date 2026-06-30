import sys
import time
import subprocess
from pathlib import Path
from typing import Callable, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import PROJECT_ROOT, apply_llm_config, load_settings
from config_loader import load_db_config, parse_selected_ids
from db_reader import fetch_configured_records
from keyword_utils import expand_keyword_groups
from security_utils import mask_sensitive_text
from utils import ensure_dir


MAX_SELECTED = 50


class ExtractRequest(BaseModel):
    selected_ids: List[str]
    mode: str = "merge"
    no_ocr: bool = True
    no_llm: bool = False


def _article_summary(record: dict) -> dict:
    return {
        "id": str(record.get("_source_id") or record.get("SourceURL") or ""),
        "info_id": str(record.get("info_id") or ""),
        "title": str(record.get("Title") or ""),
        "source_url": str(record.get("SourceURL") or ""),
        "audit_time": str(record.get("AuditTime") or ""),
        "region": str(record.get("areaname") or record.get("province") or ""),
        "insurance_type": str(record.get("insurancetypename") or ""),
    }


def _default_record_provider(config_path: str):
    def provider(keyword: str = "", selected_ids: Optional[List[str]] = None, limit: int = 50, offset: int = 0):
        config = load_db_config(config_path, require_ready=True)
        keyword_groups = expand_keyword_groups(keyword)
        return fetch_configured_records(
            config,
            limit=limit,
            offset=offset,
            selected_ids=selected_ids or [],
            keyword_groups=[] if selected_ids else keyword_groups,
            keyword_mode=config.query.keyword_mode,
        )

    return provider


def _default_extract_runner(config_path: str, field_config_path: str, llm_config_path: str, output_dir: Path, log_dir: Path):
    def runner(selected_ids: List[str], mode: str, no_ocr: bool, no_llm: bool) -> Path:
        ensure_dir(output_dir)
        ensure_dir(log_dir)
        started_at = time.time()
        command = [
            sys.executable,
            str(PROJECT_ROOT / "main.py"),
            "--config",
            config_path,
            "--field-config",
            field_config_path,
            "--llm-config",
            llm_config_path,
            "--selected-ids",
            ",".join(selected_ids),
            "--mode",
            mode,
            "--output-dir",
            str(output_dir),
            "--log-dir",
            str(log_dir),
            "--save-intermediate",
        ]
        if no_ocr:
            command.append("--no-ocr")
        if no_llm:
            command.append("--no-llm")
        completed = subprocess.run(command, cwd=PROJECT_ROOT, text=True, capture_output=True, timeout=900)
        if completed.returncode != 0:
            message = mask_sensitive_text((completed.stderr or completed.stdout or "抽取失败").strip())
            raise RuntimeError(message[-1000:])
        candidates = [path for path in output_dir.glob("*.xlsx") if path.stat().st_mtime >= started_at - 1]
        if not candidates:
            raise RuntimeError("抽取完成但未找到输出 Excel")
        return max(candidates, key=lambda item: item.stat().st_mtime)

    return runner


def _ocr_available() -> bool:
    try:
        __import__("paddleocr")
        return True
    except Exception:
        return False


def _safe_download_path(output_dir: Path, file_id: str) -> Path:
    if "/" in file_id or "\\" in file_id or ".." in file_id:
        raise HTTPException(status_code=400, detail="invalid file_id")
    root = output_dir.resolve()
    path = (root / file_id).resolve()
    if path.parent != root or path.suffix.lower() != ".xlsx" or not path.exists():
        raise HTTPException(status_code=404, detail="file not found")
    return path


def create_app(
    config_path: str = "config/db_config.yml",
    field_config_path: str = "config/field_mapping.yml",
    llm_config_path: str = "config/llm_config.yml",
    output_dir: str | Path = "outputs/web",
    log_dir: str | Path = "logs/web",
    record_provider: Optional[Callable[..., list]] = None,
    extract_runner: Optional[Callable[[List[str], str, bool, bool], Path]] = None,
) -> FastAPI:
    output_root = Path(output_dir)
    if not output_root.is_absolute():
        output_root = PROJECT_ROOT / output_root
    log_root = Path(log_dir)
    if not log_root.is_absolute():
        log_root = PROJECT_ROOT / log_root
    provider = record_provider or _default_record_provider(config_path)
    runner = extract_runner or _default_extract_runner(config_path, field_config_path, llm_config_path, output_root, log_root)

    app = FastAPI(title="DataExtractor API")
    web_dir = PROJECT_ROOT / "web"
    if web_dir.exists():
        app.mount("/web", StaticFiles(directory=web_dir), name="web")

    @app.get("/")
    def index():
        index_path = web_dir / "index.html"
        if not index_path.exists():
            raise HTTPException(status_code=404, detail="web index not found")
        return FileResponse(index_path)

    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.get("/api/config/status")
    def config_status():
        settings = load_settings()
        try:
            settings = apply_llm_config(settings, llm_config_path)
        except Exception:
            pass
        db_config = load_db_config(config_path)
        return {
            "database_configured": bool(db_config.use_configured_reader),
            "llm_configured": bool(settings.llm_api_key),
            "ocr_available": _ocr_available(),
        }

    @app.get("/api/articles")
    def articles(
        keyword: str = "",
        selected_ids: str = "",
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ):
        selected = parse_selected_ids(selected_ids)
        rows = provider(keyword=keyword, selected_ids=selected, limit=limit, offset=offset)
        items = [_article_summary(row) for row in rows]
        return {"items": items, "total": len(items)}

    @app.post("/api/extract")
    def extract(request: ExtractRequest):
        selected = [str(item).strip() for item in request.selected_ids if str(item).strip()]
        if not selected:
            raise HTTPException(status_code=400, detail="selected_ids 不能为空")
        if len(selected) > MAX_SELECTED:
            raise HTTPException(status_code=400, detail=f"selected_ids 单次最多 {MAX_SELECTED} 条")
        if request.mode not in {"single", "merge"}:
            raise HTTPException(status_code=400, detail="mode 只能是 single 或 merge")
        try:
            output_path = Path(runner(selected, request.mode, request.no_ocr, request.no_llm))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=mask_sensitive_text(str(exc))) from exc
        file_id = output_path.name
        return {
            "job_id": output_path.stem,
            "status": "success",
            "download_url": f"/api/download/{file_id}",
            "output_path": file_id,
        }

    @app.get("/api/download/{file_id:path}")
    def download(file_id: str):
        path = _safe_download_path(output_root, file_id)
        return FileResponse(
            path,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=path.name,
        )

    return app


app = create_app()


def main() -> int:
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="启动 DataExtractor Web API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--config", default="config/db_config.yml")
    parser.add_argument("--field-config", default="config/field_mapping.yml")
    parser.add_argument("--llm-config", default="config/llm_config.yml")
    args = parser.parse_args()
    uvicorn.run(
        create_app(config_path=args.config, field_config_path=args.field_config, llm_config_path=args.llm_config),
        host=args.host,
        port=args.port,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
