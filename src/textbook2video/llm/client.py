"""
LLM 调用封装

统一通过 OpenAI-compatible 接口调用 LLM。
优先使用通用 LLM_* / OPENAI_* 环境变量，未配置时回退到 ECNU 配置。
"""

import os
import re
import json
from typing import Any
from urllib.request import Request, urlopen

try:
    import litellm
except ModuleNotFoundError:  # pragma: no cover - exercised in minimal runtimes
    litellm = None

from textbook2video.pipeline.config import (
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_DEFAULT_MODEL,
)

# litellm 全局配置：关闭不必要的 verbose 日志
if litellm is not None:
    litellm.suppress_debug_info = True


def _is_local_qwen3(model: str | None = None) -> bool:
    name = (model or LLM_DEFAULT_MODEL or "").lower()
    base = (LLM_BASE_URL or "").lower()
    return "qwen3" in name and (
        "127.0.0.1" in base or "localhost" in base or "0.0.0.0" in base
    )


def _strip_qwen_thinking(text: str | None) -> str:
    """Remove Qwen3 thinking traces that break downstream JSON parsers."""
    if not text:
        return ""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"^\s*<think>.*", "", text, flags=re.DOTALL | re.IGNORECASE)
    return text.strip()


def _local_qwen3_max_tokens() -> int:
    raw = os.environ.get("T2V_LOCAL_QWEN3_MAX_TOKENS", "8192")
    try:
        value = int(raw)
    except ValueError:
        value = 8192
    return max(1, value)


def _cap_local_qwen3_max_tokens(max_tokens: int | None, model: str | None = None) -> int | None:
    if max_tokens is None or not _is_local_qwen3(model):
        return max_tokens
    return min(max_tokens, _local_qwen3_max_tokens())


def _build_model_name(model: str | None = None) -> str:
    """构建 litellm 识别的模型名：openai/<model_name>"""
    name = model or LLM_DEFAULT_MODEL
    if not name.startswith("openai/"):
        name = f"openai/{name}"
    return name


def _openai_compatible_completion(
    messages: list[dict[str, str]],
    *,
    model: str | None,
    temperature: float,
    max_tokens: int | None,
    timeout: float | None,
    extra_body: dict[str, Any] | None = None,
) -> str:
    """Minimal OpenAI-compatible fallback for runtimes without LiteLLM."""
    payload: dict[str, Any] = {
        "model": model or LLM_DEFAULT_MODEL,
        "messages": messages,
        "temperature": temperature,
    }
    capped_max_tokens = _cap_local_qwen3_max_tokens(max_tokens, model)
    if capped_max_tokens is not None:
        payload["max_tokens"] = capped_max_tokens
    if extra_body:
        payload.update(extra_body)

    base_url = LLM_BASE_URL.rstrip("/")
    request = Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {LLM_API_KEY}"} if LLM_API_KEY else {}),
        },
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - configured endpoint
        data = json.loads(response.read().decode("utf-8"))
    content = data["choices"][0]["message"].get("content") or ""
    return str(content)


def chat(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    timeout: float | None = None,
    **kwargs: Any,
) -> str:
    """
    发送聊天请求，返回助手回复文本。

    Args:
        messages: OpenAI 格式的消息列表 [{"role": "user", "content": "..."}]
        model: 模型名，默认使用 ECNU_DEFAULT_MODEL
        temperature: 生成温度
        max_tokens: 最大生成 token 数
        timeout: 请求超时秒数，None 使用 litellm 默认
        **kwargs: 透传给 litellm.completion 的额外参数

    Returns:
        助手回复的文本内容
    """
    # 禁用底层重试，让 timeout 精确生效：
    # litellm 的 num_retries 和 OpenAI SDK 默认的 max_retries=2（共 3 次尝试）会各自
    # 等满一个 timeout 再重试，把传入的 timeout 放大约 3 倍（实测 timeout=180s 实际跑到
    # ~540s 才中断）。重试由上层 generate_batch 统一负责，这里关掉底层重试避免放大叠加。
    kwargs.setdefault("num_retries", 0)
    kwargs.setdefault("max_retries", 0)
    if _is_local_qwen3(model):
        kwargs.setdefault(
            "extra_body",
            {"chat_template_kwargs": {"enable_thinking": False}},
        )
    if litellm is None:
        extra_body = kwargs.pop("extra_body", None)
        content = _openai_compatible_completion(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            extra_body=extra_body if isinstance(extra_body, dict) else None,
        )
    else:
        response = litellm.completion(
            model=_build_model_name(model),
            messages=messages,
            api_key=LLM_API_KEY,
            api_base=LLM_BASE_URL,
            temperature=temperature,
            max_tokens=_cap_local_qwen3_max_tokens(max_tokens, model),
            timeout=timeout,
            **kwargs,
        )
        content = response.choices[0].message.content
    return _strip_qwen_thinking(content) if _is_local_qwen3(model) else content


def chat_with_system(
    user_content: str,
    *,
    system_prompt: str = "",
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    timeout: float | None = None,
    **kwargs: Any,
) -> str:
    """
    便捷方法：发送 system + user 消息。

    Args:
        user_content: 用户消息内容
        system_prompt: 系统提示词
        model: 模型名
        temperature: 生成温度
        max_tokens: 最大 token 数
        timeout: 请求超时秒数

    Returns:
        助手回复的文本内容
    """
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_content})

    return chat(
        messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        **kwargs,
    )


def load_prompt(prompt_file: str) -> str:
    """
    加载 prompts/ 目录下的 Prompt 模板文件。

    Args:
        prompt_file: 文件名，如 "slide_content_core.md"

    Returns:
        模板文件内容
    """
    from pathlib import Path

    prompts_dir = Path(__file__).resolve().parent / "prompts"
    path = prompts_dir / prompt_file
    return path.read_text(encoding="utf-8")
