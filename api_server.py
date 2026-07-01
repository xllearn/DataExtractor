import logging
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from typing import Callable, List, Optional
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from openpyxl import load_workbook
from pydantic import BaseModel

from config import PROJECT_ROOT, apply_llm_config, load_settings
from config_loader import ConfigError, load_db_config, parse_selected_ids, validate_db_config_ready
from db_reader import count_configured_records, fetch_configured_records
from image_ocr import get_ocr_status
from keyword_utils import expand_keyword_groups
from security_utils import mask_sensitive_text
from utils import ensure_dir


MAX_SELECTED = 50
LOGGER = logging.getLogger(__name__)


class ExtractRequest(BaseModel):
    selected_ids: List[str]
    mode: str = "merge"
    no_ocr: bool = True
    no_llm: bool = False
    external_ocr_text: str = ""


class ApiError(Exception):
    def __init__(self, status_code: int, detail: str, error_type: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = mask_sensitive_text(detail)
        self.error_type = error_type


def _json_error(status_code: int, detail: object, error_type: str) -> JSONResponse:
    if isinstance(detail, dict):
        safe_detail: object = {str(key): mask_sensitive_text(str(value)) for key, value in detail.items()}
    else:
        safe_detail = mask_sensitive_text(str(detail or "请求失败"))
    return JSONResponse(status_code=status_code, content={"detail": safe_detail, "error_type": error_type})


def _display_config_path(config_path: str) -> str:
    path = Path(config_path)
    if not path.is_absolute():
        return str(path).replace("\\", "/")
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return path.name


def _database_status(config_path: str) -> tuple[bool, str]:
    try:
        db_config = load_db_config(config_path)
        if not db_config.exists:
            return False, "数据库配置文件不存在，请使用 --config 指定可用 db_config.yml"
        validate_db_config_ready(db_config)
        return True, "数据库配置可用"
    except ConfigError as exc:
        return False, mask_sensitive_text(str(exc))


def _ensure_database_ready(config_path: str) -> None:
    safe, reason = _database_status(config_path)
    if not safe:
        raise ApiError(
            400,
            f"数据库未配置，无法查询文章。请使用 --config 指定可用 db_config.yml：{reason}",
            "DatabaseNotConfigured",
        )


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
        active_keyword_groups = [] if selected_ids else keyword_groups
        items = fetch_configured_records(
            config,
            limit=limit,
            offset=offset,
            selected_ids=selected_ids or [],
            keyword_groups=active_keyword_groups,
            keyword_mode=config.query.keyword_mode,
        )
        total = count_configured_records(
            config,
            selected_ids=selected_ids or [],
            keyword_groups=active_keyword_groups,
            keyword_mode=config.query.keyword_mode,
        )
        return {"items": items, "total": total}

    return provider


def _default_extract_runner(config_path: str, field_config_path: str, llm_config_path: str, output_dir: Path, log_dir: Path):
    def runner(selected_ids: List[str], mode: str, no_ocr: bool, no_llm: bool, external_ocr_text: str = "") -> Path:
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
        if external_ocr_text.strip():
            external_path = log_dir / f"external_ocr_{int(started_at)}_{uuid.uuid4().hex[:8]}.txt"
            external_path.write_text(external_ocr_text, encoding="utf-8")
            command.extend(["--ocr-text-file", str(external_path)])
        completed = subprocess.run(command, cwd=PROJECT_ROOT, text=True, capture_output=True, timeout=900)
        if completed.returncode != 0:
            message = mask_sensitive_text((completed.stderr or completed.stdout or "抽取失败").strip())
            raise RuntimeError(message[-1000:])
        candidates = [path for path in output_dir.glob("*.xlsx") if path.stat().st_mtime >= started_at - 1]
        if not candidates:
            raise RuntimeError("抽取完成但未找到输出 Excel")
        return max(candidates, key=lambda item: item.stat().st_mtime)

    return runner


def _safe_download_path(output_dir: Path, file_id: str) -> Path:
    if "/" in file_id or "\\" in file_id or ".." in file_id:
        raise HTTPException(status_code=400, detail="invalid file_id")
    root = output_dir.resolve()
    path = (root / file_id).resolve()
    if path.parent != root or path.suffix.lower() != ".xlsx" or not path.exists():
        raise HTTPException(status_code=404, detail="file not found")
    return path


def _provider_items_and_total(result: object) -> tuple[list, int]:
    if isinstance(result, dict):
        items = list(result.get("items") or [])
        total = int(result.get("total", len(items)) or 0)
        return items, total
    items = list(result or [])
    return items, len(items)


def _pagination_payload(items: list, total: int, limit: int, offset: int) -> dict:
    minimum_total = offset + len(items) if items else 0
    total = max(int(total or 0), minimum_total)
    page = offset // limit + 1
    total_pages = (total + limit - 1) // limit if total else 0
    return {
        "items": [_article_summary(row) for row in items],
        "total": total,
        "limit": limit,
        "offset": offset,
        "page": page,
        "page_size": limit,
        "total_pages": total_pages,
        "has_next": offset + limit < total,
        "has_prev": offset > 0,
    }


def _call_runner(runner: Callable, selected: List[str], mode: str, no_ocr: bool, no_llm: bool, external_ocr_text: str) -> Path:
    try:
        return Path(runner(selected, mode, no_ocr, no_llm, external_ocr_text))
    except TypeError:
        return Path(runner(selected, mode, no_ocr, no_llm))


def _preview_workbook(path: Path) -> dict:
    if not path.exists():
        raise ApiError(404, "文件不存在", "FileNotFound")
    workbook = load_workbook(path, data_only=True, read_only=True)
    try:
        if "结果数据" not in workbook.sheetnames:
            raise ApiError(404, "Excel 中不存在结果数据 sheet", "PreviewSheetNotFound")
        sheet = workbook["结果数据"]
        headers = [cell.value or "" for cell in next(sheet.iter_rows(min_row=1, max_row=1))]
        rows = []
        for row in sheet.iter_rows(min_row=2, max_row=101, values_only=True):
            if not any(value not in (None, "") for value in row):
                continue
            rows.append(["" if value is None else value for value in row])
        return {"sheet": "结果数据", "headers": headers, "rows": rows, "row_count": len(rows)}
    finally:
        workbook.close()


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
    uses_default_provider = record_provider is None
    uses_default_runner = extract_runner is None
    provider = record_provider or _default_record_provider(config_path)
    runner = extract_runner or _default_extract_runner(config_path, field_config_path, llm_config_path, output_root, log_root)
    executor = ThreadPoolExecutor(max_workers=2)
    jobs: dict[str, dict] = {}
    jobs_lock = Lock()

    app = FastAPI(title="DataExtractor API")
    web_dir = PROJECT_ROOT / "web"
    if web_dir.exists():
        app.mount("/web", StaticFiles(directory=web_dir), name="web")

    @app.exception_handler(ApiError)
    async def api_error_handler(_request: Request, exc: ApiError):
        LOGGER.warning("API error %s: %s", exc.error_type, exc.detail)
        return _json_error(exc.status_code, exc.detail, exc.error_type)

    @app.exception_handler(HTTPException)
    async def http_error_handler(_request: Request, exc: HTTPException):
        return _json_error(exc.status_code, exc.detail, "HTTPException")

    @app.exception_handler(Exception)
    async def unhandled_error_handler(_request: Request, exc: Exception):
        message = mask_sensitive_text(str(exc) or "Internal Server Error")
        LOGGER.error("Unhandled API error %s: %s", exc.__class__.__name__, message)
        return _json_error(500, message, exc.__class__.__name__)

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
        safe_to_query, reason = _database_status(config_path)
        ocr_status = get_ocr_status()
        return {
            "database_configured": safe_to_query,
            "llm_configured": bool(settings.llm_api_key),
            "ocr_available": bool(ocr_status.get("available")),
            "ocr_status_reason": mask_sensitive_text(str(ocr_status.get("reason") or "")),
            "ocr_engine": str(ocr_status.get("engine") or "none"),
            "config_path": _display_config_path(config_path),
            "database_status_reason": reason,
            "safe_to_query": safe_to_query,
        }

    @app.get("/api/articles")
    def articles(
        keyword: str = "",
        selected_ids: str = "",
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ):
        selected = parse_selected_ids(selected_ids)
        if uses_default_provider:
            _ensure_database_ready(config_path)
        result = provider(keyword=keyword, selected_ids=selected, limit=limit, offset=offset)
        rows, total = _provider_items_and_total(result)
        return _pagination_payload(rows, total, limit, offset)

    @app.post("/api/extract")
    def extract(request: ExtractRequest):
        selected = [str(item).strip() for item in request.selected_ids if str(item).strip()]
        if not selected:
            raise ApiError(400, "selected_ids 不能为空", "ValidationError")
        if len(selected) > MAX_SELECTED:
            raise ApiError(400, f"selected_ids 单次最多 {MAX_SELECTED} 条", "ValidationError")
        if request.mode not in {"single", "merge"}:
            raise ApiError(400, "mode 只能是 single 或 merge", "ValidationError")
        if uses_default_runner:
            _ensure_database_ready(config_path)
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        with jobs_lock:
            jobs[job_id] = {
                "job_id": job_id,
                "status": "queued",
                "message": "任务已排队",
                "download_url": "",
                "preview_url": "",
                "error": "",
                "output_path": None,
                "ocr_available": get_ocr_status().get("available"),
                "external_ocr_used": bool(request.external_ocr_text.strip()),
            }

        def run_job() -> None:
            with jobs_lock:
                jobs[job_id]["status"] = "running"
                jobs[job_id]["message"] = "生成中"
            try:
                output_path = _call_runner(runner, selected, request.mode, request.no_ocr, request.no_llm, request.external_ocr_text)
                file_id = output_path.name
                with jobs_lock:
                    jobs[job_id].update(
                        {
                            "status": "success",
                            "message": "生成成功",
                            "download_url": f"/api/download/{quote(file_id, safe='')}",
                            "preview_url": f"/api/jobs/{job_id}/preview",
                            "output_path": output_path,
                        }
                    )
            except Exception as exc:
                with jobs_lock:
                    jobs[job_id].update({"status": "failed", "message": "生成失败", "error": mask_sensitive_text(str(exc))})

        executor.submit(run_job)
        return {
            "job_id": job_id,
            "status": "queued",
            "status_url": f"/api/jobs/{job_id}",
            "result_page": f"/web/result.html?job_id={job_id}",
        }

    @app.get("/api/jobs/{job_id}")
    def job_status(job_id: str):
        with jobs_lock:
            job = dict(jobs.get(job_id) or {})
        if not job:
            raise ApiError(404, "job 不存在", "JobNotFound")
        return {
            "job_id": job["job_id"],
            "status": job["status"],
            "message": job.get("message", ""),
            "download_url": job.get("download_url", ""),
            "preview_url": job.get("preview_url", ""),
            "error": job.get("error", ""),
            "ocr_available": bool(job.get("ocr_available")),
            "external_ocr_used": bool(job.get("external_ocr_used")),
        }

    @app.get("/api/jobs/{job_id}/preview")
    def job_preview(job_id: str):
        with jobs_lock:
            job = dict(jobs.get(job_id) or {})
        if not job:
            raise ApiError(404, "job 不存在", "JobNotFound")
        if job.get("status") != "success":
            raise ApiError(400, "job 尚未完成，不能预览", "JobNotReady")
        return _preview_workbook(Path(job.get("output_path")))

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
