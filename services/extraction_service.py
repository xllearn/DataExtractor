import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from config import apply_llm_config, load_settings
from db_reader import fetch_configured_records
from excel_writer import build_merge_output_path, build_single_output_path, write_extraction_workbook
from field_mapping import FieldMapping, load_field_mapping
from image_ocr import get_ocr_status
from input_xlsx import read_records_from_xlsx
from keyword_utils import expand_keyword_groups
from llm_client import LLMClient
from pipeline import create_empty_metadata, extract_record_rows
from run_summary import RunSummary
from security_utils import mask_sensitive_text
from table_extractor import load_table_mapping
from utils import ensure_dir, today_yyyymmdd
from vision_client import create_vision_client

from config_loader import load_db_config, validate_db_config_ready
from .run_context import RunContext


class ExtractionCancelled(RuntimeError):
    pass


@dataclass
class ExtractionRequest:
    selected_ids: List[str] = field(default_factory=list)
    mode: str = "merge"
    no_ocr: bool = True
    no_llm: bool = False
    external_ocr_text: str = ""
    prompt_version: str = "v3"
    keyword: str = ""
    input_xlsx: str = ""
    offset: int = 0
    limit: Optional[int] = None
    job_id: str = ""
    debug: bool = False
    save_intermediate: bool = True


@dataclass
class ExtractionResult:
    run_id: str
    input_mode: str
    selected_ids: List[str]
    keyword: str
    total_records: int
    output_rows: int
    failed_record_count: int
    output_excel_path: Path
    summary_path: Path
    log_dir: Path
    output_paths: List[Path] = field(default_factory=list)


class ExtractionService:
    def __init__(
        self,
        output_dir: str | Path,
        log_dir: str | Path,
        *,
        record_provider: Optional[Callable[..., Any]] = None,
        pipeline: Callable[..., List[Dict[str, Any]]] = extract_record_rows,
        workbook_writer: Callable[..., Path] = write_extraction_workbook,
        field_mapping: FieldMapping | None = None,
        config_path: str | Path = "config/db_config.yml",
        field_config_path: str | Path | None = "config/field_mapping.yml",
        llm_config_path: str | Path = "config/llm_config.yml",
        table_config_path: str | Path = "config/table_mapping.yml",
        llm_client_factory: Callable[[Any], Any] = LLMClient,
        ocr_status_provider: Callable[[], Dict[str, Any]] = get_ocr_status,
        vision_client_factory: Callable[[str | Path], Any] = create_vision_client,
        settings: Any = None,
        table_mapping: Any = None,
        context: RunContext | None = None,
        progress_callback: Callable[[Dict[str, Any]], None] | None = None,
        cancel_checker: Callable[[], bool] | None = None,
    ):
        self.context = context or RunContext.from_roots(output_dir, log_dir)
        self.record_provider = record_provider or self._configured_record_provider(config_path)
        self.pipeline = pipeline
        self.workbook_writer = workbook_writer
        self.config_path = config_path
        self.field_config_path = field_config_path
        self.llm_config_path = llm_config_path
        self.table_config_path = table_config_path
        self.llm_client_factory = llm_client_factory
        self.ocr_status_provider = ocr_status_provider
        self.vision_client_factory = vision_client_factory
        self.settings = settings
        self.field_mapping = field_mapping
        self.table_mapping = table_mapping
        self.progress_callback = progress_callback
        self.cancel_checker = cancel_checker

    def run(
        self,
        request: ExtractionRequest,
        progress_callback: Callable[[Dict[str, Any]], None] | None = None,
        cancel_checker: Callable[[], bool] | None = None,
    ) -> ExtractionResult:
        if request.mode not in {"single", "merge"}:
            raise ValueError("mode must be single or merge")
        selected_ids = [str(item).strip() for item in request.selected_ids if str(item).strip()]
        run_log_dir = self.context.job_log_dir(request.job_id)
        logger = _setup_logger(run_log_dir, request.debug)
        summary = RunSummary(input_mode="", total_records=0, log_dir=run_log_dir)
        field_mapping = self.field_mapping or load_field_mapping(self.field_config_path)
        table_mapping = self.table_mapping if self.table_mapping is not None else load_table_mapping(self.table_config_path)
        settings = self.settings or apply_llm_config(load_settings(), self.llm_config_path)
        ocr_status = self.ocr_status_provider()

        input_mode, records = self._read_records(request, selected_ids)
        summary.update_input(input_mode, len(records))
        on_progress = progress_callback or self.progress_callback
        is_cancelled = cancel_checker or self.cancel_checker

        def cancelled() -> bool:
            return bool(is_cancelled and is_cancelled())

        def write_cancelled() -> None:
            logger.warning("extraction cancelled")
            payload = summary.write_artifacts()
            payload["status"] = "cancelled"
            (run_log_dir / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            _close_logger(logger)

        def emit_progress(record: Dict[str, Any], current: int) -> None:
            if not on_progress:
                return
            on_progress(
                {
                    "progress_current": current,
                    "progress_total": len(records),
                    "current_title": record.get("Title") or record.get("title") or "",
                    "current_source_url": record.get("SourceURL") or record.get("source_url") or "",
                    "success_records": summary.success_records,
                    "failed_records": summary.failed_record_count,
                    "manual_review_records": summary.manual_review_records,
                }
            )

        no_llm = bool(request.no_llm)
        no_ocr = bool(request.no_ocr or no_llm)
        llm_client = None if no_llm else self.llm_client_factory(settings)
        ocr_enabled = bool(getattr(settings, "ocr_enabled", False)) and not no_ocr and bool(ocr_status.get("available"))
        ocr_skipped_reason = _ocr_skipped_reason(request.no_ocr, no_llm, settings, ocr_status)
        vision_client = None if no_llm else self._create_vision_client(logger)

        all_rows: List[Dict[str, Any]] = []
        all_metadata = create_empty_metadata()
        output_paths: List[Path] = []
        record_error_count = 0
        today = today_yyyymmdd()

        for index, record in enumerate(records, start=1):
            if cancelled():
                write_cancelled()
                raise ExtractionCancelled("extraction cancelled")
            record_metadata = create_empty_metadata()
            try:
                rows = self.pipeline(
                    record=record,
                    record_index=request.offset + index,
                    llm_client=llm_client,
                    logs_dir=run_log_dir,
                    temp_images_dir=self.context.temp_images_dir,
                    today=today,
                    image_base_url=getattr(settings, "image_base_url", ""),
                    ocr_enabled=ocr_enabled,
                    debug=request.debug,
                    logger=logger,
                    field_mapping=field_mapping,
                    llm_format=getattr(settings, "llm_format", "v2"),
                    table_mapping=table_mapping,
                    no_llm=no_llm,
                    input_mode=input_mode,
                    save_intermediate=request.save_intermediate,
                    metadata=record_metadata,
                    external_ocr_text=request.external_ocr_text,
                    prompt_version=(request.prompt_version or "v3").strip() or "v3",
                    ocr_status=ocr_status,
                    ocr_skipped_reason=ocr_skipped_reason,
                    vision_client=vision_client,
                    run_id=summary.run_id,
                )
                if request.mode == "single":
                    output_path = build_single_output_path(record, self.context.output_dir, request.offset + index)
                    self._write_workbook(output_path, [*rows], field_mapping, record_metadata)
                    output_paths.append(output_path)
                    summary.add_output_path(output_path)
                else:
                    all_rows.extend(rows)
                    _extend_metadata(all_metadata, record_metadata)
                summary.record_success(output_rows=len(rows), **_metadata_flags(record_metadata))
                emit_progress(record, index)
            except Exception as exc:
                record_error_count += 1
                safe_error = mask_sensitive_text(str(exc))
                failed = summary.record_failure(
                    {
                        "phase": "process_record",
                        "record_index": request.offset + index,
                        "source_id": record.get("_source_id"),
                        "info_id": record.get("info_id"),
                        "Title": record.get("Title"),
                        "SourceURL": record.get("SourceURL"),
                        "error": safe_error,
                    }
                )
                all_metadata["failed_records"].append(failed)
                all_metadata["collection_logs"].append(
                    {
                        "source_id": record.get("_source_id"),
                        "info_id": record.get("info_id"),
                        "title": record.get("Title"),
                        "source_url": record.get("SourceURL"),
                        "status": "failed",
                        "input_mode": input_mode,
                        "llm_format": "none" if no_llm else getattr(settings, "llm_format", "v2"),
                        "error": safe_error,
                    }
                )
                logger.error("record processing failed: %s", safe_error)
                emit_progress(record, index)
                continue

        if request.mode == "merge":
            output_path = build_merge_output_path(self.context.output_dir)
            try:
                self._write_workbook(output_path, all_rows, field_mapping, all_metadata)
            except Exception as exc:
                safe_error = mask_sensitive_text(str(exc))
                summary.record_failure({"phase": "excel_write", "error": safe_error})
                summary_payload = summary.write_artifacts()
                logger.error("workbook write failed: %s", safe_error)
                _close_logger(logger)
                raise RuntimeError(safe_error) from exc
            output_paths.append(output_path)
            summary.add_output_path(output_path)

        summary_payload = summary.write_artifacts()
        output_excel_path = output_paths[-1] if output_paths else Path("")
        result = ExtractionResult(
            run_id=str(summary_payload.get("run_id") or summary.run_id),
            input_mode=input_mode,
            selected_ids=selected_ids,
            keyword=request.keyword,
            total_records=len(records),
            output_rows=int(summary_payload.get("output_rows") or 0),
            failed_record_count=int(summary_payload.get("failed_records") or record_error_count),
            output_excel_path=output_excel_path,
            summary_path=run_log_dir / "summary.json",
            log_dir=run_log_dir,
            output_paths=output_paths,
        )
        _close_logger(logger)
        return result

    def _read_records(self, request: ExtractionRequest, selected_ids: List[str]) -> tuple[str, List[Dict[str, Any]]]:
        if request.input_xlsx:
            return "uploaded-xlsx", read_records_from_xlsx(Path(request.input_xlsx), limit=request.limit, offset=request.offset)
        limit = request.limit if request.limit is not None else max(len(selected_ids), 1)
        result = self.record_provider(keyword=request.keyword, selected_ids=selected_ids, limit=limit, offset=request.offset)
        if isinstance(result, dict):
            return "configured-db", list(result.get("items") or [])
        return "configured-db", list(result or [])

    def _write_workbook(
        self,
        output_path: Path,
        rows: List[Dict[str, Any]],
        field_mapping: FieldMapping,
        metadata: Dict[str, List[Dict[str, Any]]],
    ) -> Path:
        return self.workbook_writer(
            rows,
            output_path,
            self.context.template_path,
            field_mapping,
            collection_logs=metadata["collection_logs"],
            field_evidence=metadata["field_evidence"],
            conflict_evidence=metadata["conflict_evidence"],
            extract_evaluations=metadata["extract_evaluations"],
            failed_records=metadata["failed_records"],
            field_confidence=metadata["field_confidence"],
            review_rows=metadata["review_rows"],
            row_match_evidence=metadata["row_match_evidence"],
        )

    def _create_vision_client(self, logger: logging.Logger):
        try:
            return self.vision_client_factory(self.llm_config_path)
        except Exception as exc:
            logger.error("vision config load failed: %s", mask_sensitive_text(str(exc)))
            return None

    @staticmethod
    def _configured_record_provider(config_path: str | Path):
        def provider(keyword: str = "", selected_ids: List[str] | None = None, limit: int = 50, offset: int = 0):
            db_config = load_db_config(config_path, require_ready=True)
            validate_db_config_ready(db_config)
            keyword_groups = expand_keyword_groups(keyword)
            rows = fetch_configured_records(
                db_config,
                limit=limit,
                offset=offset,
                selected_ids=selected_ids or [],
                keyword_groups=[] if selected_ids else keyword_groups,
                keyword_mode=db_config.query.keyword_mode,
            )
            return {"items": rows, "total": len(rows)}

        return provider


def _setup_logger(log_dir: Path, debug: bool) -> logging.Logger:
    ensure_dir(log_dir)
    logger = logging.getLogger(f"db_to_excel_extractor.service.{log_dir.name}")
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.handlers.clear()
    handler = logging.FileHandler(log_dir / "run.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    handler.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def _close_logger(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)


def _extend_metadata(target: Dict[str, List[Dict[str, Any]]], source: Dict[str, List[Dict[str, Any]]]) -> None:
    for key in target:
        target[key].extend(source.get(key, []))


def _metadata_flags(record_metadata: Dict[str, List[Dict[str, Any]]]) -> Dict[str, bool]:
    logs = record_metadata.get("collection_logs", [])
    return {
        "manual_review": any(bool(item.get("need_manual_review")) for item in logs),
        "ocr_triggered": any(bool(item.get("ocr_triggered")) for item in logs),
        "ocr_failed": any(int(item.get("ocr_failure_count") or 0) > 0 for item in logs),
        "llm_parse_failed": any(item.get("llm_parse_success") is False for item in logs),
    }


def _ocr_skipped_reason(no_ocr: bool, no_llm: bool, settings: Any, ocr_status: Dict[str, Any]) -> str:
    if no_llm:
        return "no_llm skips OCR"
    if no_ocr:
        return "user disabled OCR"
    if not getattr(settings, "ocr_enabled", False):
        return "config disabled OCR"
    if not ocr_status.get("available"):
        return "OCR unavailable"
    return ""
