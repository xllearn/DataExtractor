from openai import OpenAI

from config import Settings


class LLMClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = None

    def extract(self, prompt: str) -> str:
        if not self.settings.llm_api_key:
            raise RuntimeError("LLM_API_KEY 未配置")
        if self.client is None:
            self.client = OpenAI(api_key=self.settings.llm_api_key, base_url=self.settings.llm_base_url)

        response = self.client.chat.completions.create(
            model=self.settings.llm_model,
            messages=[
                {"role": "system", "content": "你是严格的 JSON 数据抽取助手，只输出 JSON。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
        )
        return response.choices[0].message.content or ""
