import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from textbook2video.llm import client


class _Response:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_chat_uses_openai_compatible_fallback_without_litellm(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _Response({"choices": [{"message": {"content": "<think>x</think>答案"}}]})

    monkeypatch.setattr(client, "litellm", None)
    monkeypatch.setattr(client, "LLM_BASE_URL", "http://127.0.0.1:8000/v1")
    monkeypatch.setattr(client, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(client, "LLM_DEFAULT_MODEL", "qwen3-32b-awq")
    monkeypatch.setattr(client, "urlopen", fake_urlopen)

    result = client.chat([{"role": "user", "content": "hello"}], max_tokens=99, timeout=12)

    assert result == "答案"
    assert captured["url"] == "http://127.0.0.1:8000/v1/chat/completions"
    assert captured["payload"]["model"] == "qwen3-32b-awq"
    assert captured["payload"]["max_tokens"] == 99
    assert captured["timeout"] == 12


@pytest.mark.parametrize("backend", ["stdlib", "litellm"])
@pytest.mark.parametrize("explicit_thinking", [False, True])
@pytest.mark.parametrize("with_image", [False, True])
def test_json_mode_preserves_local_qwen_controls_and_caller_options(
    monkeypatch, tmp_path, backend, explicit_thinking, with_image,
):
    captured = {}

    def fake_urlopen(request, timeout):
        captured.update(json.loads(request.data.decode("utf-8")))
        return _Response({"choices": [{"message": {"content": "{}"}}]})

    def fake_completion(**kwargs):
        captured.update(kwargs["extra_body"])
        assert kwargs["num_retries"] == kwargs["max_retries"] == 0
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))])

    monkeypatch.setattr(client, "LLM_BASE_URL", "http://127.0.0.1:8000/v1")
    monkeypatch.setattr(client, "LLM_DEFAULT_MODEL", "qwen3-32b-awq")
    monkeypatch.setattr(client, "urlopen", fake_urlopen)
    monkeypatch.setattr(client, "litellm", None if backend == "stdlib" else
                        SimpleNamespace(completion=fake_completion))
    extra = {"response_format": {"type": "json_object"}, "custom": "preserved"}
    if explicit_thinking:
        extra["chat_template_kwargs"] = {"enable_thinking": True, "custom_template": 1}
    original = deepcopy(extra)
    if with_image:
        image = tmp_path / "probe.png"
        image.write_bytes(b"test image bytes")
        assert client.chat_with_images("Return JSON", [image], extra_body=extra) == "{}"
    else:
        assert client.chat_with_system("Return JSON", extra_body=extra) == "{}"
    assert captured["response_format"] == {"type": "json_object"}
    assert captured["custom"] == "preserved"
    assert captured["chat_template_kwargs"]["enable_thinking"] is explicit_thinking
    if explicit_thinking:
        assert captured["chat_template_kwargs"]["custom_template"] == 1
    assert extra == original
