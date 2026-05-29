"""
LLM 调用封装

统一通过 OpenAI-compatible 接口调用 LLM。
优先使用通用 LLM_* / OPENAI_* 环境变量，未配置时回退到 ECNU 配置。
"""

from typing import Any

import litellm

from textbook2video.pipeline.config import (
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_DEFAULT_MODEL,
)

# litellm 全局配置：关闭不必要的 verbose 日志
litellm.suppress_debug_info = True


def _build_model_name(model: str | None = None) -> str:
    """构建 litellm 识别的模型名：openai/<model_name>"""
    name = model or LLM_DEFAULT_MODEL
    if not name.startswith("openai/"):
        name = f"openai/{name}"
    return name


def chat(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    **kwargs: Any,
) -> str:
    """
    发送聊天请求，返回助手回复文本。

    Args:
        messages: OpenAI 格式的消息列表 [{"role": "user", "content": "..."}]
        model: 模型名，默认使用 ECNU_DEFAULT_MODEL
        temperature: 生成温度
        max_tokens: 最大生成 token 数
        **kwargs: 透传给 litellm.completion 的额外参数

    Returns:
        助手回复的文本内容
    """
    response = litellm.completion(
        model=_build_model_name(model),
        messages=messages,
        api_key=LLM_API_KEY,
        api_base=LLM_BASE_URL,
        temperature=temperature,
        max_tokens=max_tokens,
        **kwargs,
    )
    return response.choices[0].message.content


def chat_with_system(
    user_content: str,
    *,
    system_prompt: str = "",
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
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
