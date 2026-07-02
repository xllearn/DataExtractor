import json
from pathlib import Path

from fastapi.testclient import TestClient


def _write_result_workbook(path: Path) -> None:
    from excel_writer import write_extraction_workbook
    from field_mapping import load_field_mapping

    write_extraction_workbook(
        [{"info_id": "JOB-1", "地区名称": "上海", "保险类型": "医保"}],
        path,
        template_path=path.parent / "missing-template.xlsx",
        field_mapping=load_field_mapping(None),
    )


def test_job_apis_recover_success_job_after_app_restart(tmp_path):
    from api_server import create_app
    from services.job_store import JobStore

    output_dir = tmp_path / "out"
    log_root = tmp_path / "logs"
    workbook_path = output_dir / "job_result.xlsx"
    summary_path = log_root / "job_20260702_010203_deadbeef" / "summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_result_workbook(workbook_path)
    summary_path.write_text(json.dumps({"run_id": "run_jobs", "total_records": 1}) + "\n", encoding="utf-8")
    (summary_path.parent / "run.log").write_text(
        "2026-07-02 [INFO] started\n2026-07-02 [ERROR] failed token=secret\n",
        encoding="utf-8",
    )

    store = JobStore(output_dir)
    job = store.create(
        job_id="job_20260702_010203_deadbeef",
        status="success",
        message="done",
        output_excel_path=workbook_path,
        file_id=workbook_path.name,
        summary_path=summary_path,
        log_dir=summary_path.parent,
        progress_current=1,
        progress_total=1,
    )
    client = TestClient(create_app(record_provider=lambda **_: {"items": [], "total": 0}, output_dir=output_dir, log_dir=log_root))

    listed = client.get("/api/jobs").json()
    status = client.get(f"/api/jobs/{job['job_id']}").json()
    logs = client.get(f"/api/jobs/{job['job_id']}/logs?level=error&tail=5").json()
    summary = client.get(f"/api/jobs/{job['job_id']}/summary").json()
    preview = client.get(f"/api/jobs/{job['job_id']}/preview").json()
    download = client.get(f"/api/jobs/{job['job_id']}/download")

    assert listed["items"][0]["job_id"] == job["job_id"]
    assert status["status"] == "success"
    assert status["download_url"].startswith("/api/download/")
    assert logs["lines"] and "secret" not in "\n".join(logs["lines"])
    assert summary["run_id"] == "run_jobs"
    assert preview["sheet"] == "结果数据"
    assert preview["row_count"] == 1
    assert download.status_code == 200
    assert "spreadsheetml" in download.headers["content-type"]


def test_job_cancel_and_not_ready_download_are_json_errors(tmp_path):
    from api_server import create_app
    from services.job_store import JobStore

    output_dir = tmp_path / "out"
    log_root = tmp_path / "logs"
    store = JobStore(output_dir)
    running = store.create(job_id="job_20260702_010203_deadbee1", status="running", message="running")
    failed = store.create(job_id="job_20260702_010203_deadbee2", status="failed", message="failed")
    client = TestClient(create_app(record_provider=lambda **_: {"items": [], "total": 0}, output_dir=output_dir, log_dir=log_root))

    cancelled = client.post(f"/api/jobs/{running['job_id']}/cancel")
    download = client.get(f"/api/jobs/{failed['job_id']}/download")

    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert download.status_code == 400
    assert download.headers["content-type"].split(";")[0] == "application/json"
    assert download.json()["error_type"] == "JobNotReady"
