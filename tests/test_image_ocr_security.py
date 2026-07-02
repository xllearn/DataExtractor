import io
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image


def _png_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (1, 1), color="white").save(buffer, format="PNG")
    return buffer.getvalue()


class FakeResponse:
    def __init__(self, body=b"", status_code=200, headers=None):
        self.body = body
        self.status_code = status_code
        self.headers = headers or {"Content-Type": "image/png", "Content-Length": str(len(body))}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=8192):
        for index in range(0, len(self.body), chunk_size):
            yield self.body[index : index + chunk_size]


def _dns_ip(ip):
    return [(2, 1, 6, "", (ip, 0))]


def test_download_rejects_domain_resolving_to_private_ip(tmp_path):
    from image_ocr import download_image

    with patch("image_ocr.socket.getaddrinfo", return_value=_dns_ip("10.0.0.1")):
        with pytest.raises(ValueError):
            download_image("https://safe.example/a.png", tmp_path, 1, 1)


def test_download_rejects_redirect_to_private_ip(tmp_path):
    from image_ocr import download_image

    response = FakeResponse(status_code=302, headers={"Location": "http://127.0.0.1/a.png"})
    with patch("image_ocr.socket.getaddrinfo", return_value=_dns_ip("93.184.216.34")):
        with patch("image_ocr.requests.get", return_value=response):
            with pytest.raises(ValueError):
                download_image("https://safe.example/a.png", tmp_path, 1, 1)


def test_signed_image_url_is_masked_in_ocr_diagnostics(tmp_path):
    from image_ocr import process_image_ocr

    url = "https://safe.example/a.png?token=secret&X-Amz-Signature=abc"
    with patch("image_ocr.download_image", side_effect=RuntimeError(f"download failed {url}")):
        summary = process_image_ocr([url], Path(tmp_path), 7, enabled=True)

    assert summary.errors[0]["image_url"] == "https://safe.example/a.png?***"
    assert "secret" not in summary.errors[0]["error"]
    assert "X-Amz-Signature" not in summary.errors[0]["error"]


def test_public_mock_image_download_succeeds(tmp_path):
    from image_ocr import download_image

    with patch("image_ocr.socket.getaddrinfo", return_value=_dns_ip("93.184.216.34")):
        with patch("image_ocr.requests.get", return_value=FakeResponse(_png_bytes())):
            path = download_image("https://safe.example/a.png", tmp_path, 1, 1)

    assert path.exists()
