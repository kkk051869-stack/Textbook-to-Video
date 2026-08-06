import json

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
