import asyncio
from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import Workbook


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _xlsx_bytes() -> bytes:
    from io import BytesIO

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Title", "Content"])
    sheet.append(["政策标题", "政策正文"])
    handle = BytesIO()
    workbook.save(handle)
    workbook.close()
    return handle.getvalue()


def test_upload_lifecycle_stores_safe_xlsx_and_rejects_path_names(tmp_path):
    from api_server import create_app

    output_dir = tmp_path / "out"
    client = TestClient(create_app(record_provider=lambda **_: {"items": [], "total": 0}, output_dir=output_dir, log_dir=tmp_path / "logs"))

    uploaded = client.post(
        "/api/uploads/excel",
        files={"file": (r"..\private\source.xlsx", _xlsx_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    payload = uploaded.json()
    listed = client.get("/api/uploads").json()
    deleted = client.delete(f"/api/uploads/{payload['upload_id']}")

    assert uploaded.status_code == 200
    assert payload["file_name"].startswith(payload["upload_id"])
    assert payload["file_name"].endswith(".xlsx")
    assert "source.xlsx" not in str(payload)
    assert "private" not in str(payload)
    assert ".." not in str(payload)
    assert listed["items"][0]["upload_id"] == payload["upload_id"]
    assert deleted.status_code == 200
    assert not (output_dir / "uploads" / payload["upload_id"]).exists()


def test_upload_rejects_non_xlsx_oversize_and_unrecognizable_workbook(tmp_path):
    from api_server import create_app

    client = TestClient(
        create_app(
            record_provider=lambda **_: {"items": [], "total": 0},
            output_dir=tmp_path / "out",
            log_dir=tmp_path / "logs",
            app_config={"uploads": {"max_file_size_mb": 1}},
        )
    )

    wrong_extension = client.post("/api/uploads/excel", files={"file": ("source.csv", _xlsx_bytes(), "text/csv")})
    too_large = client.post(
        "/api/uploads/excel",
        files={"file": ("source.xlsx", b"x" * (1024 * 1024 + 1), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    bad_workbook = client.post(
        "/api/uploads/excel",
        files={"file": ("source.xlsx", b"not-a-workbook", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert wrong_extension.status_code == 400
    assert wrong_extension.json()["error_type"] == "ValidationError"
    assert too_large.status_code == 413
    assert too_large.json()["error_type"] == "UploadTooLarge"
    assert bad_workbook.status_code == 400
    assert bad_workbook.json()["error_type"] == "ValidationError"


def test_upload_endpoints_use_uploadfile_streaming_instead_of_request_body():
    source = (PROJECT_ROOT / "api_server.py").read_text(encoding="utf-8")

    assert "UploadFile" in source
    assert "File(" in source
    assert "Form(" in source
    assert "await request.body()" not in source
    assert "_parse_multipart_upload" not in source
    assert "BytesParser" not in source


def test_streaming_upload_helper_removes_partial_file_on_size_limit(tmp_path):
    from api_server import ApiError, save_upload_file_stream

    class FakeUpload:
        filename = "source.xlsx"

        def __init__(self):
            self._chunks = [b"abc", b"def"]
            self.closed = False

        async def read(self, _size):
            return self._chunks.pop(0) if self._chunks else b""

        async def close(self):
            self.closed = True

    upload = FakeUpload()
    target = tmp_path / "partial.xlsx"

    try:
        asyncio.run(save_upload_file_stream(upload, target, max_bytes=4, chunk_size=3))
    except ApiError as exc:
        assert exc.status_code == 413
        assert exc.error_type == "UploadTooLarge"
    else:
        raise AssertionError("expected UploadTooLarge")

    assert upload.closed is True
    assert not target.exists()
    assert not target.with_suffix(".xlsx.tmp").exists()


def test_streaming_upload_helper_closes_rejected_suffix(tmp_path):
    from api_server import ApiError, save_upload_file_stream

    class FakeUpload:
        filename = "source.csv"

        def __init__(self):
            self.closed = False

        async def read(self, _size):
            raise AssertionError("invalid suffix should fail before reading")

        async def close(self):
            self.closed = True

    upload = FakeUpload()

    try:
        asyncio.run(save_upload_file_stream(upload, tmp_path / "rejected.xlsx", max_bytes=100))
    except ApiError as exc:
        assert exc.status_code == 400
        assert exc.error_type == "ValidationError"
    else:
        raise AssertionError("expected ValidationError")

    assert upload.closed is True
    assert not (tmp_path / "rejected.xlsx").exists()
    assert not (tmp_path / "rejected.xlsx.tmp").exists()
