import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

import requests
from PIL import Image

from utils import ensure_dir


SUPPORTED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
_OCR_ENGINE = None
OCR_UNAVAILABLE_REASON = "未安装 paddleocr/paddlepaddle 或 OCR 初始化失败"


@dataclass
class OcrSummary:
    text: str
    success_count: int
    failure_count: int


def get_ocr_status() -> dict:
    try:
        from paddleocr import PaddleOCR  # noqa: F401

        return {"available": True, "reason": "OCR 可用", "engine": "paddleocr"}
    except Exception:
        return {"available": False, "reason": OCR_UNAVAILABLE_REASON, "engine": "none"}


def process_image_ocr(
    image_urls: List[str],
    temp_dir: Path,
    record_index: int,
    enabled: bool = True,
    logger: Optional[logging.Logger] = None,
) -> OcrSummary:
    if not enabled or not image_urls:
        return OcrSummary(text="", success_count=0, failure_count=0)

    ensure_dir(temp_dir)
    texts: List[str] = []
    success_count = 0
    failure_count = 0

    for image_index, url in enumerate(image_urls, start=1):
        marker = f"【图片OCR-{image_index}】"
        try:
            image_path = download_image(url, temp_dir, record_index, image_index)
            prepared_path = prepare_image_for_ocr(image_path)
            ocr_text = recognize_image(prepared_path)
            if not ocr_text.strip():
                ocr_text = "--"
            texts.append(f"{marker}\n{ocr_text}")
            success_count += 1
        except Exception as exc:
            failure_count += 1
            texts.append(f"{marker}\n--")
            if logger:
                logger.exception("图片 OCR 失败: record=%s image=%s url=%s error=%s", record_index, image_index, url, exc)

    return OcrSummary(text="\n\n".join(texts), success_count=success_count, failure_count=failure_count)


def download_image(url: str, temp_dir: Path, record_index: int, image_index: int) -> Path:
    parsed = urlparse(url)
    suffix = Path(parsed.path).suffix.lower()
    if suffix not in SUPPORTED_IMAGE_EXTS:
        suffix = ".jpg"
    output_path = temp_dir / f"record_{record_index:04d}_image_{image_index:03d}{suffix}"

    response = requests.get(url, timeout=20)
    response.raise_for_status()
    output_path.write_bytes(response.content)
    return output_path


def prepare_image_for_ocr(image_path: Path) -> Path:
    if image_path.suffix.lower() != ".gif":
        return image_path
    output_path = image_path.with_suffix(".png")
    with Image.open(image_path) as image:
        image.seek(0)
        image.convert("RGB").save(output_path)
    return output_path


def recognize_image(image_path: Path) -> str:
    engine = get_ocr_engine()
    result = engine.ocr(str(image_path), cls=True)
    lines: List[str] = []
    for page in result or []:
        for item in page or []:
            if len(item) >= 2 and isinstance(item[1], (list, tuple)) and item[1]:
                lines.append(str(item[1][0]))
    return "\n".join(lines)


def get_ocr_engine():
    global _OCR_ENGINE
    if _OCR_ENGINE is None:
        from paddleocr import PaddleOCR

        _OCR_ENGINE = PaddleOCR(use_angle_cls=True, lang="ch")
    return _OCR_ENGINE
