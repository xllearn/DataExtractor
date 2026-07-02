import json
import subprocess
import tempfile
from pathlib import Path


class CapturingWriter:
    def __init__(self):
        self.calls = []

    def __call__(self, result_rows, output_path, template_path, field_mapping, **metadata):
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("fake workbook", encoding="utf-8")
        self.calls.append(
            {
                "result_rows": list(result_rows),
                "output_path": output_path,
                "template_path": Path(template_path),
                "field_mapping": field_mapping,
                **metadata,
            }
        )
        return output_path


def test_extraction_service_runs_selected_ids_without_subprocess_or_real_dependencies(monkeypatch):
    from field_mapping import FieldMapping
    from services.extraction_service import ExtractionRequest, ExtractionService

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("subprocess should not be used")),
    )

    provider_calls = []
    pipeline_calls = []

    def provider(keyword="", selected_ids=None, limit=50, offset=0):
        provider_calls.append({"keyword": keyword, "selected_ids": list(selected_ids or []), "limit": limit, "offset": offset})
        return {
            "items": [
                {
                    "_source_id": "R1",
                    "info_id": "INFO-1",
                    "Title": "Policy",
                    "SourceURL": "https://example.test/1",
                    "Content": "<p>coverage</p>",
                }
            ],
            "total": 1,
        }

    def pipeline(**kwargs):
        pipeline_calls.append(kwargs)
        kwargs["metadata"]["collection_logs"].append({"source_id": "R1", "status": "success", "output_rows": 1})
        kwargs["metadata"]["field_evidence"].append({"source_id": "R1", "field": "ratio", "value": "80%"})
        return [{"info_id": "INFO-1", "ratio": "80%"}]

    writer = CapturingWriter()

    with tempfile.TemporaryDirectory() as tmp:
        output_root = Path(tmp) / "outputs"
        log_root = Path(tmp) / "logs"
        service = ExtractionService(
            output_dir=output_root,
            log_dir=log_root,
            record_provider=provider,
            pipeline=pipeline,
            workbook_writer=writer,
            field_mapping=FieldMapping(),
        )

        result = service.run(
            ExtractionRequest(
                selected_ids=["R1"],
                mode="merge",
                no_ocr=True,
                no_llm=True,
                external_ocr_text="external text",
            )
        )

        assert provider_calls == [{"keyword": "", "selected_ids": ["R1"], "limit": 1, "offset": 0}]
        assert len(pipeline_calls) == 1
        assert pipeline_calls[0]["input_mode"] == "configured-db"
        assert pipeline_calls[0]["external_ocr_text"] == "external text"
        assert pipeline_calls[0]["llm_client"] is None
        assert pipeline_calls[0]["ocr_enabled"] is False
        assert pipeline_calls[0]["run_id"] == result.run_id

        assert result.input_mode == "configured-db"
        assert result.total_records == 1
        assert result.output_rows == 1
        assert result.failed_record_count == 0
        assert result.output_excel_path.exists()
        assert result.summary_path.exists()
        assert writer.calls[0]["result_rows"] == [{"info_id": "INFO-1", "ratio": "80%"}]
        assert writer.calls[0]["collection_logs"] == [{"source_id": "R1", "status": "success", "output_rows": 1}]

        summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
        assert summary["run_id"] == result.run_id
        assert summary["input_mode"] == "configured-db"
        assert summary["total_records"] == 1
        assert summary["output_rows"] == 1


def test_extraction_service_records_per_record_failures_in_summary_and_workbook_metadata():
    from field_mapping import FieldMapping
    from services.extraction_service import ExtractionRequest, ExtractionService

    def provider(**_kwargs):
        return {
            "items": [
                {
                    "_source_id": "R2",
                    "info_id": "INFO-2",
                    "Title": "Bad policy",
                    "SourceURL": "https://example.test/2",
                    "Content": "<p>bad</p>",
                }
            ],
            "total": 1,
        }

    def failing_pipeline(**_kwargs):
        raise RuntimeError("pipeline failed password=abc sk-test-token")

    writer = CapturingWriter()

    with tempfile.TemporaryDirectory() as tmp:
        service = ExtractionService(
            output_dir=Path(tmp) / "outputs",
            log_dir=Path(tmp) / "logs",
            record_provider=provider,
            pipeline=failing_pipeline,
            workbook_writer=writer,
            field_mapping=FieldMapping(),
        )

        result = service.run(ExtractionRequest(selected_ids=["R2"], mode="merge", no_ocr=True, no_llm=True))

        assert result.total_records == 1
        assert result.output_rows == 0
        assert result.failed_record_count == 1
        assert result.output_excel_path.exists()
        assert len(writer.calls) == 1
        assert writer.calls[0]["result_rows"] == []
        assert writer.calls[0]["failed_records"][0]["source_id"] == "R2"
        assert "abc" not in writer.calls[0]["failed_records"][0]["error"]
        assert "sk-test-token" not in writer.calls[0]["failed_records"][0]["error"]

        summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
        assert summary["failed_records"] == 1
        failed_records = (result.log_dir / "failed_records.jsonl").read_text(encoding="utf-8")
        assert "abc" not in failed_records
        assert "sk-test-token" not in failed_records
