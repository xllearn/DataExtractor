import base64
import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

import yaml
from openai import OpenAI

from config import PROJECT_ROOT, ENV_PATTERN, str_to_bool


class VisionClientError(RuntimeError):
    pass


@dataclass
class VisionConfig:
    enabled: bool = False
    provider: str = ""
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    timeout_seconds: int = 120

    @property
    def ready(self) -> bool:
        return bool(self.enabled and self.api_key and self.base_url and self.model)


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        return ENV_PATTERN.sub(lambda match: os.getenv(match.group(1), ""), value)
    if isinstance(value, dict):
        return {key: _expand_env(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    return value


def load_vision_config(path: str | Path | None = None) -> VisionConfig:
    config_path = Path(path) if path else PROJECT_ROOT / "config" / "llm_config.yml"
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path
    if not config_path.exists():
        return VisionConfig()
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        return VisionConfig()
    vision = _expand_env(payload.get("vision") or {})
    if not isinstance(vision, dict):
        return VisionConfig()
    enabled = vision.get("enabled", False)
    if isinstance(enabled, str):
        enabled = str_to_bool(enabled, False)
    return VisionConfig(
        enabled=bool(enabled),
        provider=str(vision.get("provider") or ""),
        api_key=str(vision.get("api_key") or ""),
        base_url=str(vision.get("base_url") or ""),
        model=str(vision.get("model") or ""),
        timeout_seconds=int(vision.get("timeout_seconds") or 120),
    )


def _image_content_part(image: str) -> Dict[str, Any]:
    text = str(image or "").strip()
    if not text:
        raise VisionClientError("图片地址为空")
    if text.startswith(("http://", "https://", "data:image/")):
        return {"type": "image_url", "image_url": {"url": text}}

    path = Path(text)
    if not path.exists():
        raise VisionClientError(f"本地图片不存在: {path}")
    mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{data}"}}


class OpenAICompatibleVisionClient:
    def __init__(self, config: VisionConfig):
        self.config = config
        self._client: OpenAI | None = None

    @property
    def model(self) -> str:
        return self.config.model

    def is_ready(self) -> bool:
        return self.config.ready

    def extract_image_table(self, image: str, prompt_context: str = "") -> str:
        if not self.config.ready:
            raise VisionClientError("vision 模型未配置完整，需设置 VISION_LLM_API_KEY、VISION_LLM_BASE_URL、VISION_LLM_MODEL")
        if self._client is None:
            self._client = OpenAI(api_key=self.config.api_key, base_url=self.config.base_url, timeout=self.config.timeout_seconds)
        user_content = [
            {
                "type": "text",
                "text": (
                    "请识别图片中的商业保险/医保保障责任表，只输出 JSON object。"
                    "根节点必须包含 tables_text、records、evidence。records 字段使用中文列名，如 类型、补助限额、起付标准、报销比例、备注。"
                    "不要把年龄范围填入人员类型，不要把免责条款疾病填入病种名称。\n\n"
                    f"上下文：\n{prompt_context or '--'}"
                ),
            },
            _image_content_part(image),
        ]
        response = self._client.chat.completions.create(
            model=self.config.model,
            messages=[
                {"role": "system", "content": "你是严格的图片表格 JSON 抽取助手，只输出 JSON。"},
                {"role": "user", "content": user_content},
            ],
            temperature=0,
        )
        return response.choices[0].message.content or ""


def create_vision_client(path: str | Path | None = None) -> OpenAICompatibleVisionClient | None:
    config = load_vision_config(path)
    if not config.enabled:
        return None
    return OpenAICompatibleVisionClient(config)
