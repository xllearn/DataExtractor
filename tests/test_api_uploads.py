from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import Workbook


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
