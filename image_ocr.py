import importlib.util
import inspect
import ipaddress
import logging
import os
import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urljoin, urlparse

import requests
from PIL import Image

from security_utils import mask_sensitive_text, mask_url
from utils import ensure_dir


SUPPORTED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
DEFAULT_IMAGE_DOWNLOAD_TIMEOUT = 20.0
DEFAULT_IMAGE_MAX_BYTES = 10 * 1024 * 1024
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
            "image_url": mask_url(url),
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
            diagnostic["error"] = mask_url(mask_sensitive_text(str(exc)))
            if not diagnostic["download_success"]:
                diagnostic["download_status"] = diagnostic["error"] or "download_failed"
            errors.append(diagnostic)
            texts.append(f"{marker}\n--")
            if logger:
                logger.exception("图片 OCR 失败: record=%s image=%s url=%s error=%s", record_index, image_index, mask_url(url), mask_sensitive_text(str(exc)))

    return OcrSummary(text="\n\n".join(texts), success_count=success_count, failure_count=failure_count, errors=errors)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except Exception:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except Exception:
        return default


def _blocked_ip_reason(ip_text: str) -> str:
    ip = ipaddress.ip_address(ip_text)
    if (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or ip.is_reserved
    ):
        return "blocked"
    return ""


def _resolve_host_ips(host: str) -> List[str]:
    ips: List[str] = []
    for item in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM):
        ip_text = item[4][0]
        if ip_text not in ips:
            ips.append(ip_text)
    return ips


def _validate_download_url(url: str, resolve_dns: bool = True) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("图片下载只允许 http/https 协议")
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host:
        raise ValueError("图片 URL 缺少主机名")
    if host == "localhost" or host.endswith(".localhost"):
        raise ValueError("拒绝下载 localhost 图片地址")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if resolve_dns:
            try:
                ips = _resolve_host_ips(host)
            except socket.gaierror as exc:
                raise ValueError(f"图片 URL DNS 解析失败: {host}") from exc
            for resolved_ip in ips:
                if _blocked_ip_reason(resolved_ip):
                    raise ValueError(f"拒绝下载 DNS 解析到内网或保留地址的图片: {host}")
        return
    if _blocked_ip_reason(str(ip)):
        raise ValueError(f"拒绝下载内网或保留地址图片: {host}")


def _validate_content_type(content_type: str) -> None:
    media_type = str(content_type or "").split(";", 1)[0].strip().lower()
    if media_type and not media_type.startswith("image/"):
        raise ValueError(f"图片响应 Content-Type 非 image/*: {media_type}")


def _verify_downloaded_image(path: Path) -> None:
    try:
        with Image.open(path) as image:
            image.verify()
    except Exception as exc:
        raise ValueError(f"下载内容不是可识别图片: {mask_sensitive_text(str(exc))}") from exc


def download_image(
    url: str,
    temp_dir: Path,
    record_index: int,
    image_index: int,
    timeout: float | None = None,
    max_bytes: int | None = None,
) -> Path:
    _validate_download_url(url)
    parsed = urlparse(url)
    suffix = Path(parsed.path).suffix.lower()
    if suffix not in SUPPORTED_IMAGE_EXTS:
        suffix = ".jpg"
    ensure_dir(temp_dir)
    output_path = temp_dir / f"record_{record_index:04d}_image_{image_index:03d}{suffix}"

    timeout = _env_float("IMAGE_DOWNLOAD_TIMEOUT", DEFAULT_IMAGE_DOWNLOAD_TIMEOUT) if timeout is None else timeout
    max_bytes = _env_int("IMAGE_MAX_BYTES", DEFAULT_IMAGE_MAX_BYTES) if max_bytes is None else int(max_bytes)
    try:
        response_context = requests.get(url, timeout=timeout, stream=True, allow_redirects=False)
        with response_context as response:
            if 300 <= int(getattr(response, "status_code", 0) or 0) < 400:
                location = response.headers.get("Location", "")
                redirect_url = urljoin(url, location)
                _validate_download_url(redirect_url)
                raise ValueError(f"图片下载不允许重定向: {mask_url(redirect_url)}")
            response.raise_for_status()
            _validate_content_type(response.headers.get("Content-Type", ""))
            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    if int(content_length) > max_bytes:
                        raise ValueError(f"图片过大，超过限制 {max_bytes} bytes")
                except ValueError:
                    raise
                except Exception:
                    pass
            total = 0
            with output_path.open("wb") as file:
                for chunk in response.iter_content(chunk_size=8192):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError(f"图片过大，超过限制 {max_bytes} bytes")
                    file.write(chunk)
    except Exception as exc:
        if output_path.exists():
            try:
                output_path.unlink()
            except OSError:
                pass
        if isinstance(exc, ValueError):
            raise
        raise RuntimeError(mask_url(mask_sensitive_text(str(exc)))) from exc
    _verify_downloaded_image(output_path)
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
