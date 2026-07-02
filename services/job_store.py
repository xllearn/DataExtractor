import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Iterable, List
from urllib.parse import quote

from security_utils import mask_sensitive_text, mask_url
from utils import ensure_dir


JOB_ID_RE = re.compile(r"^job_\d{8}_\d{6}_[0-9a-f]{8}$")
SENSITIVE_NAME_RE = re.compile(r"\b(DATABASE_URL|DB_PASSWORD|LLM_API_KEY|Authorization|api_key|password|token|secret)\b", re.IGNORECASE)
PUBLIC_FIELDS = [
    "job_id",
    "run_id",
    "status",
    "message",
    "progress_current",
    "progress_total",
    "current_title",
    "current_source_url",
    "success_records",
    "failed_records",
    "manual_review_records",
    "created_at",
    "updated_at",
    "started_at",
    "finished_at",
    "input_mode",
    "selected_ids",
    "keyword",
    "output_excel_path",
    "download_url",
    "preview_url",
    "summary_path",
    "log_dir",
    "error",
    "file_id",
    "ocr_available",
    "external_ocr_used",
]


class JobStoreError(ValueError):
    pass


def new_job_id() -> str:
    return f"job_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStore:
    def __init__(self, output_dir: str | Path):
        self.output_dir = Path(output_dir)
        self.jobs_dir = self.output_dir / "jobs"
        self._lock = Lock()

    def metadata_path(self, job_id: str) -> Path:
        if not JOB_ID_RE.fullmatch(str(job_id or "")):
            raise JobStoreError("invalid job_id")
        return self.jobs_dir / f"{job_id}.json"

    def create(self, **fields: Any) -> Dict[str, Any]:
        timestamp = now_iso()
        job = self._default_payload(str(fields.pop("job_id", "") or new_job_id()), timestamp)
        job.update(fields)
        job["created_at"] = str(job.get("created_at") or timestamp)
        job["updated_at"] = str(job.get("updated_at") or timestamp)
        return self._write(job)

    def update(self, job_id: str, **fields: Any) -> Dict[str, Any]:
        with self._lock:
            existing = self.read(job_id)
            if not existing:
                existing = self._default_payload(job_id, now_iso())
            existing.update(fields)
            existing["updated_at"] = str(fields.get("updated_at") or now_iso())
            return self._write_unlocked(existing)

    def read(self, job_id: str) -> Dict[str, Any]:
        path = self.metadata_path(job_id)
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise JobStoreError(f"job metadata read failed: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("job_id") != job_id:
            raise JobStoreError("job metadata invalid")
        return self.public_payload(payload)

    def list(self, limit: int = 20) -> List[Dict[str, Any]]:
        ensure_dir(self.jobs_dir)
        jobs: List[Dict[str, Any]] = []
        for path in self.jobs_dir.glob("job_*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(payload, dict) and JOB_ID_RE.fullmatch(str(payload.get("job_id") or "")):
                jobs.append(self.public_payload(payload))
        jobs.sort(key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True)
        return jobs[: max(0, int(limit))]

    def archive(self, job_id: str) -> Dict[str, Any]:
        return self.update(job_id, status="archived", message="archived", finished_at=now_iso())

    def delete(self, job_id: str) -> bool:
        path = self.metadata_path(job_id)
        if not path.exists():
            return False
        path.unlink()
        return True

    def public_payload(self, job: Dict[str, Any]) -> Dict[str, Any]:
        public = self._default_payload(str(job.get("job_id") or ""), str(job.get("created_at") or now_iso()))
        for field in PUBLIC_FIELDS:
            if field in job:
                public[field] = job[field]
        public["selected_ids"] = [self._safe_text(item) for item in _as_list(public.get("selected_ids"))]
        for field in ("keyword", "message", "error", "run_id", "input_mode", "current_title"):
            public[field] = self._safe_text(public.get(field))
        public["current_source_url"] = self._safe_url_text(public.get("current_source_url"))
        for field in ("output_excel_path", "summary_path", "log_dir"):
            public[field] = self._safe_path(public.get(field))

        file_id = self._safe_text(public.get("file_id"))
        if not file_id and public.get("output_excel_path"):
            file_id = self._safe_text(Path(str(public["output_excel_path"])).name)
        public["file_id"] = file_id
        if file_id and not public.get("download_url"):
            public["download_url"] = f"/api/download/{quote(file_id, safe='')}"
        if public.get("job_id") and not public.get("preview_url"):
            public["preview_url"] = f"/api/jobs/{public['job_id']}/preview"
        public["download_url"] = self._safe_url(public.get("download_url"))
        public["preview_url"] = self._safe_url(public.get("preview_url"))
        public["progress_current"] = _safe_int(public.get("progress_current"))
        public["progress_total"] = _safe_int(public.get("progress_total"))
        public["success_records"] = _safe_int(public.get("success_records"))
        public["failed_records"] = _safe_int(public.get("failed_records"))
        public["manual_review_records"] = _safe_int(public.get("manual_review_records"))
        public["ocr_available"] = bool(public.get("ocr_available"))
        public["external_ocr_used"] = bool(public.get("external_ocr_used"))
        return public

    def _write(self, job: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            return self._write_unlocked(job)

    def _write_unlocked(self, job: Dict[str, Any]) -> Dict[str, Any]:
        public = self.public_payload(job)
        path = self.metadata_path(public["job_id"])
        ensure_dir(path.parent)
        temp_path = path.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(public, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
        temp_path.replace(path)
        return public

    def _default_payload(self, job_id: str, timestamp: str) -> Dict[str, Any]:
        return {
            "job_id": job_id,
            "run_id": "",
            "status": "queued",
            "message": "",
            "progress_current": 0,
            "progress_total": 0,
            "current_title": "",
            "current_source_url": "",
            "success_records": 0,
            "failed_records": 0,
            "manual_review_records": 0,
            "created_at": timestamp,
            "updated_at": timestamp,
            "started_at": "",
            "finished_at": "",
            "input_mode": "",
            "selected_ids": [],
            "keyword": "",
            "output_excel_path": "",
            "download_url": "",
            "preview_url": "",
            "summary_path": "",
            "log_dir": "",
            "error": "",
            "file_id": "",
            "ocr_available": False,
            "external_ocr_used": False,
        }

    def _safe_path(self, value: Any) -> str:
        if value in (None, ""):
            return ""
        path = Path(str(value))
        if path.is_absolute():
            try:
                text = path.resolve().relative_to(self.output_dir.resolve()).as_posix()
            except ValueError:
                text = path.name
        else:
            text = path.as_posix()
        if ".." in Path(text).parts:
            text = Path(text).name
        return self._safe_text(text)

    def _safe_text(self, value: Any) -> str:
        text = "" if value is None else str(value)
        text = mask_sensitive_text(text)
        return SENSITIVE_NAME_RE.sub("[redacted]", text)

    def _safe_url(self, value: Any) -> str:
        text = self._safe_text(value)
        if text.startswith("/"):
            return text
        return ""

    def _safe_url_text(self, value: Any) -> str:
        text = "" if value is None else str(value)
        return self._safe_text(mask_url(text))


def _as_list(value: Any) -> Iterable[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0
