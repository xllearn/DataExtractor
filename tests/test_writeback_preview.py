import json
import re
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class LocalResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.headers = {"content-type": "application/json"}

    def json(self) -> dict:
        return self._payload


class LocalRouteClient:
    def __init__(self, app):
        self.app = app

    def post(self, path: str, **kwargs):
        from api_server import ApiError, WritebackCommitRequest, WritebackPreviewRequest

        match = re.fullmatch(r"/api/jobs/([^/]+)/writeback/(preview|commit)", path)
        if not match:
            return LocalResponse(404, {"detail": "not found", "error_type": "HTTPException"})
        job_id, action = match.groups()
        endpoint = self._endpoint(f"/api/jobs/{{job_id}}/writeback/{action}", "POST")
        request_model = WritebackPreviewRequest if action == "preview" else WritebackCommitRequest
        try:
            return LocalResponse(200, endpoint(job_id, request_model(**(kwargs.get("json") or {}))))
        except ApiError as exc:
            return LocalResponse(exc.status_code, {"detail": exc.detail, "error_type": exc.error_type})

    def _endpoint(self, path: str, method: str):
        for route in self.app.routes:
            if getattr(route, "path", "") == path and method in getattr(route, "methods", set()):
                return route.endpoint
        raise AssertionError(f"route not registered: {method} {path}")


class WritebackPreviewTests(unittest.TestCase):
    def _write_result_workbook(self, path: Path) -> None:
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "结果数据"
        sheet.append(["info_id", "报销比例", "备注", "未允许字段"])
        sheet.append(["INFO-1", "85%", "人工确认", "blocked-new"])
        sheet.append(["INFO-2", "70%", "复核确认", "blocked-two"])
        sheet.append(["INFO-1' OR '1'='1", "0%", "sql injection probe", "blocked-attack"])
        sheet.append(["", "90%", "missing key", "blocked-empty"])
        workbook.save(path)
        workbook.close()

    def _create_sqlite_db(self, db_path: Path) -> None:
        connection = sqlite3.connect(db_path)
        try:
            connection.execute(
                'CREATE TABLE policy_writeback (info_id TEXT PRIMARY KEY, "报销比例" TEXT, "备注" TEXT, "未允许字段" TEXT)'
            )
            connection.executemany(
                'INSERT INTO policy_writeback (info_id, "报销比例", "备注", "未允许字段") VALUES (?, ?, ?, ?)',
                [
                    ("INFO-1", "80%", "旧备注", "blocked-old"),
                    ("INFO-2", "60%", "旧备注2", "blocked-old2"),
                ],
            )
            connection.commit()
        finally:
            connection.close()

    def _write_config(
        self,
        path: Path,
        db_path: Path,
        *,
        enabled: bool | str = True,
        allowed_columns=None,
        target_table: str = "policy_writeback",
    ) -> None:
        allowed_columns = ["报销比例", "备注"] if allowed_columns is None else allowed_columns
        allowed_yaml = "\n".join(f'    - "{column}"' for column in allowed_columns)
        enabled_text = enabled if isinstance(enabled, str) else ("true" if enabled else "false")
        path.write_text(
            f"""
database:
  url: "sqlite:///{db_path.as_posix()}"
source:
  table: "source_articles"
writeback:
  enabled: {enabled_text}
  target_table: "{target_table}"
  key_column: "info_id"
  allowed_columns:
{allowed_yaml}
""",
            encoding="utf-8",
        )

    def _app_with_job(self, tmp: str, *, enabled: bool = True, allowed_columns=None, target_table: str = "policy_writeback"):
        from api_server import create_app
        from services.job_store import JobStore

        root = Path(tmp)
        output_dir = root / "out"
        output_dir.mkdir(parents=True)
        log_dir = root / "logs"
        db_path = root / "writeback.sqlite"
        config_path = root / "db_config.yml"
        workbook_path = output_dir / "writeback_result.xlsx"

        self._create_sqlite_db(db_path)
        self._write_result_workbook(workbook_path)
        self._write_config(config_path, db_path, enabled=enabled, allowed_columns=allowed_columns, target_table=target_table)

        store = JobStore(output_dir)
        job = store.create(
            job_id="job_20260702_010203_deadbeef",
            status="success",
            message="success",
            output_excel_path=workbook_path,
            file_id=workbook_path.name,
            selected_ids=["INFO-1", "INFO-2"],
        )
        app = create_app(
            config_path=str(config_path),
            record_provider=lambda **_: {"items": [], "total": 0},
            output_dir=output_dir,
            log_dir=log_dir,
        )
        return app, job, db_path, output_dir, config_path

    def _rows(self, db_path: Path) -> dict:
        connection = sqlite3.connect(db_path)
        try:
            rows = connection.execute(
                'SELECT info_id, "报销比例", "备注", "未允许字段" FROM policy_writeback ORDER BY info_id'
            ).fetchall()
        finally:
            connection.close()
        return {row[0]: {"报销比例": row[1], "备注": row[2], "未允许字段": row[3]} for row in rows}

    def test_writeback_is_disabled_by_default_and_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, job, db_path, output_dir, _config_path = self._app_with_job(tmp, enabled=False)
            client = LocalRouteClient(app)
            response = client.post(f"/api/jobs/{job['job_id']}/writeback/preview", json={})

            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.headers["content-type"].split(";")[0], "application/json")
            self.assertEqual(response.json()["error_type"], "WritebackDisabled")
            self.assertEqual(self._rows(db_path)["INFO-1"]["报销比例"], "80%")
            self.assertNotIn(str(output_dir), str(response.json()))
            self.assertNotIn("sqlite://", str(response.json()))
            audit_path = output_dir / "writeback" / job["job_id"] / "audit.jsonl"
            self.assertTrue(audit_path.exists())
            self.assertNotIn(str(output_dir), audit_path.read_text(encoding="utf-8"))
            self.assertNotIn("sqlite://", audit_path.read_text(encoding="utf-8"))

    def test_quoted_false_writeback_enabled_stays_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, job, db_path, _output_dir, _config_path = self._app_with_job(tmp, enabled='"false"')
            client = LocalRouteClient(app)
            response = client.post(f"/api/jobs/{job['job_id']}/writeback/preview", json={})

            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["error_type"], "WritebackDisabled")
            self.assertEqual(self._rows(db_path)["INFO-1"]["报销比例"], "80%")

    def test_preview_is_required_and_dry_run_commit_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, job, db_path, output_dir, _config_path = self._app_with_job(tmp)
            client = LocalRouteClient(app)
            missing_preview = client.post(
                f"/api/jobs/{job['job_id']}/writeback/commit",
                json={"preview_id": "writeback_20990101_000000_deadbeef", "dry_run": False},
            )
            self.assertEqual(missing_preview.status_code, 404)
            self.assertEqual(missing_preview.json()["error_type"], "WritebackPreviewNotFound")

            preview = client.post(f"/api/jobs/{job['job_id']}/writeback/preview", json={})
            self.assertEqual(preview.status_code, 200)
            preview_payload = preview.json()
            self.assertRegex(preview_payload["preview_id"], r"^writeback_\d{8}_\d{6}_[0-9a-f]{8}$")
            self.assertTrue(preview_payload["dry_run"])
            self.assertEqual(preview_payload["row_count"], 2)
            self.assertEqual(preview_payload["workbook_row_count"], 3)
            self.assertEqual(preview_payload["allowed_columns"], ["报销比例", "备注"])
            self.assertEqual(preview_payload["update_columns"], ["报销比例", "备注"])
            self.assertIn("未允许字段", preview_payload["skipped_columns"])
            self.assertNotIn(str(output_dir), str(preview_payload))
            self.assertTrue((output_dir / "writeback" / job["job_id"] / f"{preview_payload['preview_id']}.json").exists())

            dry_run = client.post(
                f"/api/jobs/{job['job_id']}/writeback/commit",
                json={"preview_id": preview_payload["preview_id"]},
            )
            self.assertEqual(dry_run.status_code, 200)
            self.assertTrue(dry_run.json()["dry_run"])
            self.assertEqual(dry_run.json()["committed_rows"], 0)
            self.assertEqual(dry_run.json()["row_count"], 2)
            self.assertEqual(self._rows(db_path)["INFO-1"]["报销比例"], "80%")

    def test_commit_rejects_string_false_dry_run_before_write(self):
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as tmp:
            app, job, db_path, _output_dir, _config_path = self._app_with_job(tmp)
            client = TestClient(app)
            preview = client.post(f"/api/jobs/{job['job_id']}/writeback/preview", json={}).json()

            response = client.post(
                f"/api/jobs/{job['job_id']}/writeback/commit",
                json={"preview_id": preview["preview_id"], "dry_run": "false"},
            )

            self.assertEqual(response.status_code, 422)
            self.assertEqual(self._rows(db_path)["INFO-1"]["报销比例"], "80%")

    def test_commit_does_not_write_when_audit_log_cannot_be_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, job, db_path, output_dir, _config_path = self._app_with_job(tmp)
            client = LocalRouteClient(app)
            preview = client.post(f"/api/jobs/{job['job_id']}/writeback/preview", json={}).json()
            audit_path = output_dir / "writeback" / job["job_id"] / "audit.jsonl"
            audit_path.unlink()
            audit_path.mkdir()

            response = client.post(
                f"/api/jobs/{job['job_id']}/writeback/commit",
                json={"preview_id": preview["preview_id"], "dry_run": False},
            )

            self.assertEqual(response.status_code, 500)
            self.assertEqual(response.json()["error_type"], "WritebackAuditFailed")
            self.assertEqual(self._rows(db_path)["INFO-1"]["报销比例"], "80%")

    def test_commit_after_preview_updates_only_allowed_columns_with_parameterized_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, job, db_path, _output_dir, _config_path = self._app_with_job(tmp)
            client = LocalRouteClient(app)
            preview = client.post(f"/api/jobs/{job['job_id']}/writeback/preview", json={}).json()
            commit = client.post(
                f"/api/jobs/{job['job_id']}/writeback/commit",
                json={"preview_id": preview["preview_id"], "dry_run": False},
            )

            self.assertEqual(commit.status_code, 200)
            payload = commit.json()
            self.assertFalse(payload["dry_run"])
            self.assertEqual(payload["committed_rows"], 2)
            rows = self._rows(db_path)
            self.assertEqual(rows["INFO-1"]["报销比例"], "85%")
            self.assertEqual(rows["INFO-1"]["备注"], "人工确认")
            self.assertEqual(rows["INFO-1"]["未允许字段"], "blocked-old")
            self.assertEqual(rows["INFO-2"]["报销比例"], "70%")
            self.assertEqual(rows["INFO-2"]["备注"], "复核确认")
            self.assertEqual(rows["INFO-2"]["未允许字段"], "blocked-old2")
            self.assertEqual(len(rows), 2)

    def test_commit_rejects_changed_writeback_configuration_after_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, job, db_path, _output_dir, config_path = self._app_with_job(tmp)
            client = LocalRouteClient(app)
            preview = client.post(f"/api/jobs/{job['job_id']}/writeback/preview", json={}).json()
            time.sleep(0.01)
            self._write_config(config_path, db_path, allowed_columns=["报销比例"])
            commit = client.post(
                f"/api/jobs/{job['job_id']}/writeback/commit",
                json={"preview_id": preview["preview_id"], "dry_run": False},
            )

            self.assertEqual(commit.status_code, 409)
            self.assertEqual(commit.json()["error_type"], "WritebackPreviewMismatch")
            self.assertEqual(self._rows(db_path)["INFO-1"]["报销比例"], "80%")

    def test_writeback_rejects_invalid_identifiers_before_sql_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, job, db_path, _output_dir, config_path = self._app_with_job(tmp)
            client = LocalRouteClient(app)
            self._write_config(config_path, db_path, allowed_columns=["备注; DROP TABLE policy_writeback"])

            response = client.post(f"/api/jobs/{job['job_id']}/writeback/preview", json={})

            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["error_type"], "WritebackConfigInvalid")
            self.assertEqual(len(self._rows(db_path)), 2)


if __name__ == "__main__":
    unittest.main()
