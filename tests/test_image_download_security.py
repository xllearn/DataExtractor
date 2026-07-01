import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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


class ImageDownloadSecurityTests(unittest.TestCase):
    def _tmpdir(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        return Path(temp_dir.name)

    def test_rejects_non_http_protocol(self):
        from image_ocr import download_image

        with self.assertRaises(ValueError):
            download_image("file:///etc/passwd", self._tmpdir(), 1, 1)

    def test_rejects_localhost_and_private_ip(self):
        from image_ocr import download_image

        for url in ["http://localhost/a.png", "http://127.0.0.1/a.png", "http://10.0.0.1/a.png", "http://169.254.169.254/latest"]:
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    download_image(url, self._tmpdir(), 1, 1)

    def test_streams_and_validates_image(self):
        from image_ocr import download_image

        body = _png_bytes()
        with patch("image_ocr.requests.get", return_value=FakeResponse(body)):
            path = download_image("https://example.com/a.unknown", self._tmpdir(), 1, 1)

        self.assertEqual(path.suffix, ".jpg")
        self.assertGreater(path.stat().st_size, 0)

    def test_rejects_non_image_content_type(self):
        from image_ocr import download_image

        response = FakeResponse(b"hello", headers={"Content-Type": "text/plain", "Content-Length": "5"})
        with patch("image_ocr.requests.get", return_value=response):
            with self.assertRaises(ValueError) as ctx:
                download_image("https://example.com/a.png", self._tmpdir(), 1, 1)
        self.assertIn("Content-Type", str(ctx.exception))

    def test_rejects_oversized_download(self):
        from image_ocr import download_image

        response = FakeResponse(b"123456", headers={"Content-Type": "image/png", "Content-Length": "6"})
        with patch("image_ocr.requests.get", return_value=response):
            with self.assertRaises(ValueError):
                download_image("https://example.com/a.png", self._tmpdir(), 1, 1, max_bytes=5)

    def test_process_ocr_records_download_error_without_interrupting_batch(self):
        from image_ocr import process_image_ocr

        with patch("image_ocr.download_image", side_effect=RuntimeError("download token=secret failed")):
            summary = process_image_ocr(["https://example.com/a.png"], self._tmpdir(), 7, enabled=True)

        self.assertEqual(summary.success_count, 0)
        self.assertEqual(summary.failure_count, 1)
        self.assertNotIn("secret", summary.errors[0]["error"])


if __name__ == "__main__":
    unittest.main()
