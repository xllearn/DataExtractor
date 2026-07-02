import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from quality_eval import run_quality_eval
from security_utils import mask_sensitive_text
from utils import ensure_dir


REPORT_ID_RE = re.compile(r"^quality_\d{8}_\d{6}_[0-9a-f]{8}$")
WINDOWS_PATH_RE = re.compile(r"[A-Za-z]:\\.*?(?=\s+(?:and|or)\s+|[,;\"'\]}]|$)", re.IGNORECASE)
POSIX_PATH_RE = re.compile(r"(?<![\w:/])/(?:[^/\s,;\"'\]}]+/)+[^/\s,;\"'\]}]+")


class QualityServiceError(ValueError):
    def __init__(self, status_code: int, detail: str, error_type: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.error_type = error_type


class QualityService:
    def __init__(self, output_root: str | Path):
        self.output_root = Path(output_root).resolve()
        self.root = (self.output_root / "quality").resolve()

    def validate_manual_upload(self, filename: str, file_bytes: bytes, max_bytes: int) -> None:
        suffix = Path(str(filename).replace("\\", "/")).suffix.lower()
        if suffix != ".xlsx":
            raise QualityServiceError(400, "只允许上传 .xlsx 文件", "ValidationError")
        if not file_bytes:
            raise QualityServiceError(400, "上传 Excel 文件不能为空", "ValidationError")
        if len(file_bytes) > max_bytes:
            raise QualityServiceError(413, f"上传文件超过 {max_bytes // (1024 * 1024)}MB 限制", "UploadTooLarge")

    def evaluate(
        self,
        job_id: str,
        generated_workbook_path: str | Path,
        manual_filename: str,
        manual_bytes: bytes,
        max_bytes: int,
    ) -> dict:
        self.validate_manual_upload(manual_filename, manual_bytes, max_bytes)
        generated = self._safe_generated_workbook_path(generated_workbook_path)
        report_id = _new_report_id()
        report_dir = self._report_dir(report_id)
        ensure_dir(report_dir)

        manual_path = (report_dir / "manual.xlsx").resolve()
        if manual_path.parent != report_dir:
            raise QualityServiceError(400, "quality report path is invalid", "ValidationError")
        manual_path.write_bytes(manual_bytes)

        report_xlsx = (report_dir / f"{report_id}.xlsx").resolve()
        report_json = (report_dir / f"{report_id}.json").resolve()
        if report_xlsx.parent != report_dir or report_json.parent != report_dir:
            raise QualityServiceError(400, "quality report path is invalid", "ValidationError")

        try:
            result = run_quality_eval(generated, manual_path, report_xlsx, report_json)
        except Exception as exc:
            raise QualityServiceError(400, f"quality evaluation failed: {self._safe_text(exc)}", "QualityEvaluationFailed") from exc

        summary = self._summary(report_id, job_id, result)
        self._write_summary(report_id, summary)
        return summary

    def report(self, report_id: str) -> dict:
        summary_path = self._summary_path(report_id)
        if not summary_path.exists():
            raise QualityServiceError(404, "quality report not found", "QualityReportNotFound")
        try:
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise QualityServiceError(500, f"quality report read failed: {self._safe_text(exc)}", "QualityReportReadError") from exc
        if not isinstance(payload, dict) or payload.get("report_id") != report_id:
            raise QualityServiceError(500, "quality report metadata is invalid", "QualityReportReadError")
        return self._sanitize(payload)

    def report_workbook_path(self, report_id: str) -> Path:
        report_dir = self._report_dir(report_id)
        path = (report_dir / f"{report_id}.xlsx").resolve()
        if not self._is_relative_to(path, report_dir) or path.suffix.lower() != ".xlsx" or not path.exists():
            raise QualityServiceError(404, "quality report not found", "QualityReportNotFound")
        return path

    def _summary(self, report_id: str, job_id: str, result: dict[str, Any]) -> dict:
        return self._sanitize(
            {
                "report_id": report_id,
                "job_id": job_id,
                "overall_similarity": _safe_float(result.get("overall_similarity")),
                "core_field_similarity": _safe_float(result.get("core_field_similarity")),
                "passed": bool(result.get("passed")),
                "worst_fields": self._worst_fields(result.get("field_metrics")),
                "worst_rows": self._worst_rows(result.get("row_matches")),
                "missing_core_fields": self._missing_core_fields(result.get("missing_core_fields")),
                "low_confidence_count": _safe_int(result.get("low_confidence_count")),
                "conflict_count": _safe_int(result.get("conflict_count")),
                "download_url": f"/api/quality/reports/{report_id}/download",
                "created_at": _now_iso(),
            }
        )

    def _worst_fields(self, field_metrics: Any) -> list[dict[str, Any]]:
        if not isinstance(field_metrics, dict):
            return []
        rows: list[dict[str, Any]] = []
        for field, metrics in field_metrics.items():
            metric_payload = metrics if isinstance(metrics, dict) else {}
            rows.append(
                {
                    "field": self._safe_text(field),
                    "similarity": _safe_float(metric_payload.get("similarity")),
                    "accuracy": _safe_float(metric_payload.get("accuracy")),
                    "count": _safe_int(metric_payload.get("count")),
                }
            )
        rows.sort(key=lambda item: (item["similarity"], item["field"]))
        return rows[:5]

    def _worst_rows(self, row_matches: Any) -> list[dict[str, Any]]:
        if not isinstance(row_matches, list):
            return []
        rows: list[dict[str, Any]] = []
        for item in row_matches:
            if not isinstance(item, dict):
                continue
            rows.append(
                {
                    "generated_row": _nullable_int(item.get("generated_row")),
                    "manual_row": _nullable_int(item.get("manual_row")),
                    "similarity": _safe_float(item.get("similarity")),
                }
            )
        rows.sort(key=lambda item: (item["similarity"], item["generated_row"] or 0, item["manual_row"] or 0))
        return rows[:5]

    def _missing_core_fields(self, missing_core_fields: Any) -> list[dict[str, Any]]:
        if not isinstance(missing_core_fields, list):
            return []
        rows: list[dict[str, Any]] = []
        for item in missing_core_fields[:20]:
            if not isinstance(item, dict):
                continue
            rows.append({"row": _safe_int(item.get("row")), "field": self._safe_text(item.get("field"))})
        return rows

    def _safe_generated_workbook_path(self, path: str | Path) -> Path:
        workbook = Path(path).resolve()
        if not self._is_relative_to(workbook, self.output_root) or workbook.suffix.lower() != ".xlsx" or not workbook.exists():
            raise QualityServiceError(404, "generated workbook not found", "JobWorkbookNotFound")
        return workbook

    def _report_dir(self, report_id: str) -> Path:
        if not REPORT_ID_RE.fullmatch(str(report_id or "")):
            raise QualityServiceError(404, "quality report not found", "QualityReportNotFound")
        path = (self.root / report_id).resolve()
        if not self._is_relative_to(path, self.root):
            raise QualityServiceError(404, "quality report not found", "QualityReportNotFound")
        return path

    def _summary_path(self, report_id: str) -> Path:
        return (self._report_dir(report_id) / "summary.json").resolve()

    def _write_summary(self, report_id: str, summary: dict[str, Any]) -> None:
        path = self._summary_path(report_id)
        ensure_dir(path.parent)
        temp_path = path.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
        temp_path.replace(path)

    def _sanitize(self, payload: Any) -> Any:
        if isinstance(payload, dict):
            return {self._safe_text(key): self._sanitize(value) for key, value in payload.items()}
        if isinstance(payload, list):
            return [self._sanitize(item) for item in payload]
        if isinstance(payload, str):
            return self._safe_text(payload)
        return payload

    def _safe_text(self, value: Any) -> str:
        text = mask_sensitive_text("" if value is None else str(value))
        if text.startswith("/api/"):
            return text
        text = WINDOWS_PATH_RE.sub("[path]", text)
        text = POSIX_PATH_RE.sub("[path]", text)
        return text

    def _is_relative_to(self, path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False


def _new_report_id() -> str:
    return f"quality_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(value: Any) -> float:
    try:
        return round(float(value or 0), 6)
    except (TypeError, ValueError):
        return 0.0


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _nullable_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
