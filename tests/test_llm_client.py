import unittest
from types import SimpleNamespace
from unittest.mock import patch

from config import Settings


def _settings(**overrides):
    values = dict(
        db_host="127.0.0.1",
        db_port=3306,
        db_name="",
        db_user="",
        db_password="",
        db_table="",
        llm_provider="test",
        llm_api_key="key-secret",
        llm_base_url="https://llm.example.com",
        llm_model="model-a",
        ocr_enabled=False,
        image_base_url="",
        output_dir="outputs",
        default_mode="single",
        default_limit=1,
        default_offset=0,
        llm_timeout=3.0,
        llm_max_retries=1,
        llm_retry_backoff=0.0,
    )
    values.update(overrides)
    return Settings(**values)


def _response(content="{}", usage=None):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=usage,
        model="model-a",
    )


class LLMClientTests(unittest.TestCase):
    def test_extract_detail_returns_content_elapsed_and_usage(self):
        from llm_client import LLMClient

        usage = SimpleNamespace(prompt_tokens=2, completion_tokens=3, total_tokens=5)

        class ChatCompletions:
            def create(self, **kwargs):
                self.kwargs = kwargs
                return _response('{"ok": true}', usage=usage)

        completions = ChatCompletions()
        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

        with patch("llm_client.OpenAI", return_value=fake_client):
            result = LLMClient(_settings()).extract_detail("prompt")

        self.assertEqual(result.content, '{"ok": true}')
        self.assertEqual(result.model, "model-a")
        self.assertGreaterEqual(result.elapsed_seconds, 0)
        self.assertEqual(result.prompt_tokens, 2)
        self.assertEqual(result.completion_tokens, 3)
        self.assertEqual(result.total_tokens, 5)
        self.assertEqual(completions.kwargs["timeout"], 3.0)

    def test_extract_keeps_legacy_string_return(self):
        from llm_client import LLMClient

        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: _response("[]"))))
        with patch("llm_client.OpenAI", return_value=fake_client):
            self.assertEqual(LLMClient(_settings()).extract("prompt"), "[]")

    def test_missing_api_key_is_classified(self):
        from llm_client import LLMAuthenticationError, LLMClient

        with self.assertRaises(LLMAuthenticationError) as ctx:
            LLMClient(_settings(llm_api_key="")).extract_detail("prompt")
        self.assertIn("LLM_API_KEY 未配置", str(ctx.exception))

    def test_empty_response_is_classified(self):
        from llm_client import LLMClient, LLMEmptyResponseError

        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: _response(""))))
        with patch("llm_client.OpenAI", return_value=fake_client):
            with self.assertRaises(LLMEmptyResponseError):
                LLMClient(_settings()).extract_detail("prompt")

    def test_rate_limit_retries_and_masks_key(self):
        from llm_client import LLMClient, LLMRateLimitError

        calls = {"count": 0}

        def fail(**_kwargs):
            calls["count"] += 1
            raise RuntimeError("rate limit reached for RPM api_key=key-secret")

        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fail)))
        with patch("llm_client.OpenAI", return_value=fake_client), patch("llm_client.time.sleep"):
            with self.assertRaises(LLMRateLimitError) as ctx:
                LLMClient(_settings(llm_max_retries=2)).extract_detail("prompt")

        self.assertEqual(calls["count"], 3)
        self.assertNotIn("key-secret", str(ctx.exception))
        self.assertIn("限流", str(ctx.exception))

    def test_timeout_is_classified(self):
        from llm_client import LLMClient, LLMTimeoutError

        def fail(**_kwargs):
            raise TimeoutError("request timed out")

        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fail)))
        with patch("llm_client.OpenAI", return_value=fake_client):
            with self.assertRaises(LLMTimeoutError):
                LLMClient(_settings()).extract_detail("prompt")


if __name__ == "__main__":
    unittest.main()
