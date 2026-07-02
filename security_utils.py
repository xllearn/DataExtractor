import re
from urllib.parse import urlsplit, urlunsplit


SENSITIVE_KEYS = [
    "DATABASE_URL",
    "DB_PASSWORD",
    "LLM_API_KEY",
    "Authorization",
    "api_key",
    "password",
    "token",
    "secret",
]


def mask_database_url(url: str) -> str:
    text = "" if url is None else str(url)
    try:
        parts = urlsplit(text)
        if not parts.password:
            return text
        user = parts.username or ""
        host = parts.hostname or ""
        port = f":{parts.port}" if parts.port else ""
        netloc = f"{user}:***@{host}{port}"
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    except Exception:
        return re.sub(r"://([^:/@]+):([^@]+)@", r"://\1:***@", text)


def mask_sensitive_text(value: str) -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"([A-Za-z0-9+.-]+://[^:/@\s]+):([^@\s]+)@", r"\1:***@", text)
    text = re.sub(r"([A-Za-z_]*(?:API_KEY|TOKEN|PASSWORD|SECRET|Authorization|api_key|password|token|secret)[A-Za-z_]*\s*[=:]\s*)([^\s,;]+)", r"\1***", text, flags=re.IGNORECASE)
    text = re.sub(r"(Bearer\s+)([A-Za-z0-9._\-]+)", r"\1***", text, flags=re.IGNORECASE)
    text = re.sub(r"sk-[A-Za-z0-9_-]+", "sk-***", text)
    return text


def mask_url(url: str) -> str:
    text = "" if url is None else str(url)
    try:
        parts = urlsplit(text)
        if not parts.query and not parts.fragment:
            return mask_sensitive_text(text)
        return mask_sensitive_text(urlunsplit((parts.scheme, parts.netloc, parts.path, "***", "")))
    except Exception:
        return mask_sensitive_text(re.sub(r"([?&])[^=\s]+=[^&\s]+", r"\1***=***", text))


def sanitize_excel_value(value, max_length: int = 32767):
    if value is None:
        return ""
    if isinstance(value, (int, float, bool)):
        return value
    text = str(value)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    if len(text) > max_length:
        text = text[:max_length]
    if text != "--" and text.startswith(("=", "+", "-", "@")):
        text = "'" + text
    return text
