import json
import re
import tempfile
from pathlib import Path

import pytest


REQUIRED_PUBLIC_FIELDS = {
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
}


def test_job_store_create_update_read_list_and_restart_recovery():
    from services.job_store import JobStore

    with tempfile.TemporaryDirectory() as tmp:
        output_root = Path(tmp)
        store = JobStore(output_root)

        job = store.create(input_mode="configured-db", selected_ids=["A1", "A2"], keyword="policy")
        job_id = job["job_id"]
        assert re.fullmatch(r"job_\d{8}_\d{6}_[0-9a-f]{8}", job_id)
        assert "/" not in job_id
        assert "\\" not in job_id
        assert Path(job_id).name == job_id
        assert REQUIRED_PUBLIC_FIELDS <= set(job)

        output_file = output_root / "result.xlsx"
        summary_file = output_root / "logs" / job_id / "summary.json"
        store.update(
            job_id,
            run_id="run_20260702_101112_abcdef12",
            status="success",
            message="done",
            progress_current=2,
            progress_total=2,
            current_title="Policy DATABASE_URL=mysql+pymysql://user:secret@127.0.0.1/db",
            current_source_url="https://example.test/a?X-Amz-Signature=secret-token",
            success_records=1,
            failed_records=1,
            manual_review_records=1,
            started_at="2026-07-02T01:00:00+00:00",
            finished_at="2026-07-02T01:00:01+00:00",
            output_excel_path=output_file,
            download_url="/api/download/result.xlsx",
            preview_url=f"/api/jobs/{job_id}/preview",
            summary_path=summary_file,
            log_dir=summary_file.parent,
        )

        recovered = JobStore(output_root).read(job_id)
        assert recovered["status"] == "success"
        assert recovered["run_id"] == "run_20260702_101112_abcdef12"
        assert recovered["selected_ids"] == ["A1", "A2"]
        assert recovered["current_title"] == "Policy [redacted]=mysql+pymysql://user:***@127.0.0.1/db"
        assert "secret-token" not in recovered["current_source_url"]
        assert recovered["success_records"] == 1
        assert recovered["failed_records"] == 1
        assert recovered["manual_review_records"] == 1
        assert recovered["output_excel_path"] == "result.xlsx"
        assert recovered["summary_path"].endswith("summary.json")
        assert not Path(recovered["summary_path"]).is_absolute()
        assert str(output_root) not in json.dumps(recovered, ensure_ascii=False)

        listed = JobStore(output_root).list(limit=5)
        assert listed[0]["job_id"] == job_id
        assert REQUIRED_PUBLIC_FIELDS <= set(listed[0])


def test_job_store_writes_metadata_atomically_and_filters_sensitive_values():
    from services.job_store import JobStore

    with tempfile.TemporaryDirectory() as tmp:
        output_root = Path(tmp)
        store = JobStore(output_root)
        job_id = store.create(
            input_mode="configured-db",
            selected_ids=["1"],
            keyword="DATABASE_URL=mysql+pymysql://user:secret@127.0.0.1/db password=abc sk-test-token",
        )["job_id"]

        store.update(
            job_id,
            error="extract failed DATABASE_URL=mysql+pymysql://user:secret@127.0.0.1/db password=abc sk-test-token",
            output_excel_path=output_root / "nested" / "secret-output.xlsx",
            summary_path=output_root / "logs" / "summary.json",
            log_dir=output_root / "logs",
        )

        metadata_path = store.metadata_path(job_id)
        raw = metadata_path.read_text(encoding="utf-8")
        payload = json.loads(raw)

        assert metadata_path.name == f"{job_id}.json"
        assert not metadata_path.with_suffix(".json.tmp").exists()
        assert payload["job_id"] == job_id
        assert "DATABASE_URL" not in raw
        assert "mysql+pymysql://user:secret" not in raw
        assert "secret" not in raw
        assert "abc" not in raw
        assert "sk-test-token" not in raw
        assert str(output_root) not in raw


def test_job_store_rejects_path_like_job_ids_and_supports_archive_delete():
    from services.job_store import JobStore, JobStoreError

    with tempfile.TemporaryDirectory() as tmp:
        store = JobStore(Path(tmp))
        job_id = store.create()["job_id"]

        with pytest.raises(JobStoreError):
            store.read("../escape")
        with pytest.raises(JobStoreError):
            store.metadata_path("job_20260702_010203_bad/path")

        archived = store.archive(job_id)
        assert archived["status"] == "archived"
        assert store.read(job_id)["status"] == "archived"

        assert store.delete(job_id) is True
        assert store.read(job_id) == {}
