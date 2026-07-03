import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from security_utils import mask_sensitive_text
from utils import ensure_dir


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _retry_id(record: Dict[str, Any]) -> str:
    for key in ("info_id", "source_id", "_source_id"):
        value = str(record.get(key) or "").strip()
        if value:
            return value
    return ""


@dataclass
class RunSummary:
    input_mode: str
    total_records: int
    log_dir: Path
    run_id: str = field(default_factory=lambda: f"run_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}")
    started_at: str = field(default_factory=_now_iso)
    _started_monotonic: float = field(default_factory=time.monotonic)
    success_records: int = 0
    failed_record_count: int = 0
    output_rows: int = 0
    llm_parse_failed_records: int = 0
    ocr_triggered_records: int = 0
    ocr_failed_records: int = 0
    manual_review_records: int = 0
    output_paths: List[Path] = field(default_factory=list)
    failed_records: List[Dict[str, Any]] = field(default_factory=list)
    row_quality_metrics: Dict[str, Any] = field(default_factory=dict)

    def update_input(self, input_mode: str, total_records: int) -> None:
        self.input_mode = input_mode
        self.total_records = total_records

    def record_success(
        self,
        output_rows: int,
        manual_review: bool = False,
        ocr_triggered: bool = False,
        ocr_failed: bool = False,
        llm_parse_failed: bool = False,
    ) -> None:
        self.success_records += 1
        self.output_rows += int(output_rows or 0)
        self.manual_review_records += 1 if manual_review else 0
        self.ocr_triggered_records += 1 if ocr_triggered else 0
        self.ocr_failed_records += 1 if ocr_failed else 0
        self.llm_parse_failed_records += 1 if llm_parse_failed else 0

    def record_failure(self, payload: Dict[str, Any], count_record_failure: bool = True) -> Dict[str, Any]:
        safe = {
            "run_id": self.run_id,
            "record_index": payload.get("record_index", ""),
            "source_id": payload.get("source_id") or payload.get("_source_id") or "",
            "info_id": payload.get("info_id", ""),
            "Title": payload.get("Title") or payload.get("title") or "",
            "SourceURL": payload.get("SourceURL") or payload.get("source_url") or "",
            "phase": payload.get("phase", "process_record"),
            "error": mask_sensitive_text(str(payload.get("error", ""))),
        }
        self.failed_records.append(safe)
        if count_record_failure:
            self.failed_record_count += 1
        return safe

    def add_output_path(self, path: Path) -> None:
        if path:
            self.output_paths.append(Path(path))

    def set_row_quality_metrics(self, metrics: Dict[str, Any]) -> None:
        self.row_quality_metrics = dict(metrics or {})

    def _payload(self) -> Dict[str, Any]:
        finished_at = _now_iso()
        payload = {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "finished_at": finished_at,
            "elapsed_seconds": round(time.monotonic() - self._started_monotonic, 3),
            "input_mode": self.input_mode,
            "total_records": self.total_records,
            "success_records": self.success_records,
            "failed_records": self.failed_record_count,
            "output_rows": self.output_rows,
            "llm_parse_failed_records": self.llm_parse_failed_records,
            "ocr_triggered_records": self.ocr_triggered_records,
            "ocr_failed_records": self.ocr_failed_records,
            "manual_review_records": self.manual_review_records,
            "output_excel_path": str(self.output_paths[-1]) if self.output_paths else "",
            "output_excel_paths": [str(path) for path in self.output_paths],
            "log_dir": str(self.log_dir),
        }
        payload.update(self.row_quality_metrics)
        return payload

    def write_artifacts(self) -> Dict[str, Any]:
        ensure_dir(self.log_dir)
        payload = self._payload()
        (self.log_dir / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        failed_path = self.log_dir / "failed_records.jsonl"
        retry_path = self.log_dir / "retry_ids.txt"
        if self.failed_records:
            failed_path.write_text(
                "".join(json.dumps(item, ensure_ascii=False, default=str) + "\n" for item in self.failed_records),
                encoding="utf-8",
            )
            retry_ids = []
            for item in self.failed_records:
                value = _retry_id(item)
                if value and value not in retry_ids:
                    retry_ids.append(value)
            retry_path.write_text("\n".join(retry_ids) + ("\n" if retry_ids else ""), encoding="utf-8")
        else:
            failed_path.write_text("", encoding="utf-8")
            retry_path.write_text("", encoding="utf-8")
        return payload
