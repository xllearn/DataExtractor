from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read_web_file(name: str) -> str:
    return (PROJECT_ROOT / "web" / name).read_text(encoding="utf-8")


def test_web_static_files_wire_productized_api_routes():
    index = _read_web_file("index.html")
    app_js = _read_web_file("app.js")
    result = _read_web_file("result.js")

    assert 'id="uploadXlsxInput"' in index
    assert "/api/uploads/excel" in app_js
    assert "/api/extract/uploaded" in app_js
    assert "/api/jobs?limit=20" in app_js
    assert "/logs?tail=80" in app_js
    assert "/summary" in result
    assert "/download" in result
    assert "/preview" in result


def test_web_static_uses_text_content_instead_of_inner_html():
    combined = "\n".join([_read_web_file("app.js"), _read_web_file("result.js")])

    assert ".innerHTML" not in combined
    assert "textContent" in combined
    assert "document.createElement" in combined
