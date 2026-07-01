import importlib.util
import inspect
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

import requests
from PIL import Image

from security_utils import mask_sensitive_text
from utils import ensure_dir


SUPPORTED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
_OCR_ENGINE = None
OCR_UNAVAILABLE_REASON = "未安装 paddleocr/paddlepaddle 或 OCR 初始化失败"
OCR_INSTALL_HINT = "请安装 paddleocr 和 paddlepaddle，或使用外部 OCR 文本 fallback"


@dataclass
class OcrSummary:
    text: str
    success_count: int
    failure_count: int
    errors: List[Dict[str, Any]] = field(default_factory=list)


def get_ocr_status() -> dict:
    missing = []
    if importlib.util.find_spec("paddleocr") is None:
        missing.append("paddleocr")
    if importlib.util.find_spec("paddle") is None:
        missing.append("paddlepaddle")
    if missing:
        return {
            "available": False,
            "reason": "未安装 " + "/".join(missing),
            "engine": "none",
            "install_hint": OCR_INSTALL_HINT,
        }
    try:
        from paddleocr import PaddleOCR  # noqa: F401
        import paddle  # noqa: F401

        return {"available": True, "reason": "OCR 可用", "engine": "paddleocr", "install_hint": ""}
    except Exception as exc:
        return {
            "available": False,
            "reason": f"{OCR_UNAVAILABLE_REASON}: {exc}",
            "engine": "none",
            "install_hint": OCR_INSTALL_HINT,
        }


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
    errors: List[Dict[str, Any]] = []

    for image_index, url in enumerate(image_urls, start=1):
        marker = f"【图片OCR-{image_index}】"
        diagnostic: Dict[str, Any] = {
            "source": "paddleocr",
            "record_index": record_index,
            "image_index": image_index,
            "image_url": url,
            "download_success": False,
            "download_status": "",
            "image_format": "",
            "ocr_initialized": False,
            "error": "",
        }
        try:
            image_path = download_image(url, temp_dir, record_index, image_index)
            diagnostic["download_success"] = True
            diagnostic["download_status"] = "ok"
            prepared_path = prepare_image_for_ocr(image_path)
            diagnostic["image_format"] = detect_image_format(prepared_path)
            engine = get_ocr_engine()
            diagnostic["ocr_initialized"] = True
            ocr_text = recognize_image(prepared_path, engine=engine)
            if not ocr_text.strip():
                ocr_text = "--"
            texts.append(f"{marker}\n{ocr_text}")
            success_count += 1
        except Exception as exc:
            failure_count += 1
            diagnostic["error"] = mask_sensitive_text(str(exc))
            if not diagnostic["download_success"]:
                diagnostic["download_status"] = diagnostic["error"] or "download_failed"
            errors.append(diagnostic)
            texts.append(f"{marker}\n--")
            if logger:
                logger.exception("图片 OCR 失败: record=%s image=%s url=%s error=%s", record_index, image_index, url, exc)

    return OcrSummary(text="\n\n".join(texts), success_count=success_count, failure_count=failure_count, errors=errors)


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


def detect_image_format(image_path: Path) -> str:
    try:
        with Image.open(image_path) as image:
            return str(image.format or image_path.suffix.lstrip(".") or "unknown")
    except Exception as exc:
        return f"unknown: {exc}"


def recognize_image(image_path: Path, engine=None) -> str:
    engine = engine or get_ocr_engine()
    result = _run_ocr(engine, str(image_path))
    return "\n".join(_extract_text_lines(result))


def _run_ocr(engine, image: str):
    if hasattr(engine, "ocr"):
        try:
            return engine.ocr(image, cls=True)
        except TypeError as exc:
            message = str(exc)
            if "cls" not in message or "unexpected keyword argument" not in message:
                raise
            return engine.ocr(image)

    if hasattr(engine, "predict"):
        return engine.predict(image)

    raise TypeError("OCR engine does not provide ocr() or predict()")


def _extract_text_lines(result: Any) -> List[str]:
    lines: List[str] = []
    seen = set()

    def add_text(value: Any) -> None:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            lines.append(text)

    def walk(value: Any) -> None:
        if value is None:
            return

        if isinstance(value, dict):
            for key in ("rec_texts", "texts"):
                texts = value.get(key)
                if isinstance(texts, Iterable) and not isinstance(texts, (str, bytes)):
                    for text in texts:
                        add_text(text)
                    return
            if isinstance(value.get("text"), str):
                add_text(value.get("text"))
                return
            for key in ("res", "result", "ocr_result", "pages"):
                if key in value:
                    walk(value.get(key))
            return

        if isinstance(value, (list, tuple)):
            if len(value) >= 2 and isinstance(value[1], (list, tuple)) and value[1] and isinstance(value[1][0], str):
                add_text(value[1][0])
                return
            if len(value) >= 2 and isinstance(value[0], str) and isinstance(value[1], (int, float)):
                add_text(value[0])
                return
            for item in value:
                walk(item)
            return

    walk(result)
    return lines


def get_ocr_engine():
    global _OCR_ENGINE
    if _OCR_ENGINE is None:
        from paddleocr import PaddleOCR

        _OCR_ENGINE = _create_paddle_ocr_engine(PaddleOCR)
    return _OCR_ENGINE


def _create_paddle_ocr_engine(paddle_ocr_cls):
    try:
        signature = inspect.signature(paddle_ocr_cls.__init__)
        if "use_textline_orientation" in signature.parameters:
            return paddle_ocr_cls(
                lang="ch",
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=True,
            )
    except (TypeError, ValueError):
        pass
    return paddle_ocr_cls(use_angle_cls=True, lang="ch")
