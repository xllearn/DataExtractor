import logging
import time
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from config import Settings
from security_utils import mask_sensitive_text


LOGGER = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    content: str
    model: str
    elapsed_seconds: float
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class LLMClientError(RuntimeError):
    retryable = False


class LLMAuthenticationError(LLMClientError):
    pass


class LLMRateLimitError(LLMClientError):
    retryable = True


class LLMTimeoutError(LLMClientError):
    retryable = True


class LLMServerError(LLMClientError):
    retryable = True


class LLMEmptyResponseError(LLMClientError):
    pass


class LLMNetworkError(LLMClientError):
    retryable = True


def _usage_value(usage: Any, key: str) -> int | None:
    if usage is None:
        return None
    if isinstance(usage, dict):
        value = usage.get(key)
    else:
        value = getattr(usage, key, None)
    try:
        return int(value) if value is not None else None
    except Exception:
        return None


def _status_code(exc: Exception) -> int | None:
    for attr in ("status_code", "status"):
        value = getattr(exc, attr, None)
        if value is not None:
            try:
                return int(value)
            except Exception:
                pass
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    try:
        return int(value) if value is not None else None
    except Exception:
        return None


def _classify_exception(exc: Exception) -> LLMClientError:
    message = mask_sensitive_text(str(exc) or exc.__class__.__name__)
    lowered = message.lower()
    status = _status_code(exc)
    if status in {401, 403} or "unauthorized" in lowered or "authentication" in lowered or "认证" in message:
        return LLMAuthenticationError(f"LLM 认证失败: {message}")
    if status == 429 or "rate limit" in lowered or "限流" in message or "too many requests" in lowered:
        return LLMRateLimitError(f"LLM 限流: {message}")
    if status is not None and status >= 500:
        return LLMServerError(f"LLM 服务端错误: {message}")
    if isinstance(exc, TimeoutError) or "timeout" in lowered or "timed out" in lowered or "超时" in message:
        return LLMTimeoutError(f"LLM 网络超时: {message}")
    return LLMNetworkError(f"LLM 网络错误: {message}")


class LLMClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = None

    def _client(self):
        if not self.settings.llm_api_key:
            raise LLMAuthenticationError("LLM_API_KEY 未配置")
        if self.client is None:
            self.client = OpenAI(
                api_key=self.settings.llm_api_key,
                base_url=self.settings.llm_base_url,
            )
        return self.client

    def extract(self, prompt: str) -> str:
        return self.extract_detail(prompt).content

    def extract_detail(self, prompt: str) -> LLMResponse:
        max_retries = max(0, int(getattr(self.settings, "llm_max_retries", 0) or 0))
        backoff = max(0.0, float(getattr(self.settings, "llm_retry_backoff", 0.0) or 0.0))
        timeout = float(getattr(self.settings, "llm_timeout", 60.0) or 60.0)
        attempts = max_retries + 1
        last_error: LLMClientError | None = None

        for attempt in range(1, attempts + 1):
            started = time.monotonic()
            try:
                response = self._client().chat.completions.create(
                    model=self.settings.llm_model,
                    messages=[
                        {"role": "system", "content": "你是严格的 JSON 数据抽取助手，只输出 JSON。"},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0,
                    timeout=timeout,
                )
                elapsed = time.monotonic() - started
                content = response.choices[0].message.content or ""
                if not content.strip():
                    raise LLMEmptyResponseError("LLM 返回空响应")
                usage = getattr(response, "usage", None)
                result = LLMResponse(
                    content=content,
                    model=str(getattr(response, "model", "") or self.settings.llm_model),
                    elapsed_seconds=elapsed,
                    prompt_tokens=_usage_value(usage, "prompt_tokens"),
                    completion_tokens=_usage_value(usage, "completion_tokens"),
                    total_tokens=_usage_value(usage, "total_tokens"),
                )
                LOGGER.info(
                    "LLM 调用完成: model=%s elapsed=%.2fs prompt_tokens=%s completion_tokens=%s total_tokens=%s",
                    result.model,
                    result.elapsed_seconds,
                    result.prompt_tokens,
                    result.completion_tokens,
                    result.total_tokens,
                )
                return result
            except LLMClientError as exc:
                last_error = exc
            except Exception as exc:
                last_error = _classify_exception(exc)

            if not getattr(last_error, "retryable", False) or attempt >= attempts:
                raise last_error
            sleep_seconds = backoff * (2 ** (attempt - 1))
            LOGGER.warning(
                "LLM 调用失败，将重试: attempt=%s/%s wait=%.2fs error=%s",
                attempt,
                attempts,
                sleep_seconds,
                mask_sensitive_text(str(last_error)),
            )
            if sleep_seconds:
                time.sleep(sleep_seconds)

        raise last_error or LLMClientError("LLM 调用失败")
