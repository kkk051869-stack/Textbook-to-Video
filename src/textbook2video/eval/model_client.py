"""Small OpenAI-compatible client used by cloud-capable eval commands."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any


def extract_json(text: str) -> Any:
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        starts = [position for position in (cleaned.find("{"), cleaned.find("[")) if position >= 0]
        if not starts:
            raise ValueError("model output contains no JSON object or array")
        start = min(starts)
        end = max(cleaned.rfind("}"), cleaned.rfind("]"))
        if end <= start:
            raise ValueError("model output contains incomplete JSON")
        return json.loads(re.sub(r",(\s*[}\]])", r"\1", cleaned[start : end + 1]))


class OpenAICompatibleClient:
    def __init__(
        self,
        *,
        api_base: str,
        model: str,
        timeout: int = 600,
        api_key: str | None = None,
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.api_key = api_key

    def chat(self, messages: list[dict[str, Any]], *, max_tokens: int) -> tuple[Any, str]:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": max_tokens,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            f"{self.api_base}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code}: {body[:1000]}") from exc
        raw = body["choices"][0]["message"]["content"]
        return extract_json(raw), raw
