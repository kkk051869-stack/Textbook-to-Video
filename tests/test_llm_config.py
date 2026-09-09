"""LLM configuration selection tests."""

import os
from collections.abc import Callable
from collections.abc import Generator
from contextlib import contextmanager
from importlib import import_module
from importlib import reload
from typing import cast

SelectLlmConfig = Callable[[], tuple[str, str, str]]


def _select_llm_config() -> tuple[str, str, str]:
    module = import_module("textbook2video.pipeline.config")
    module = reload(module)
    select = cast(SelectLlmConfig, getattr(module, "select_llm_config"))
    return select()


@contextmanager
def _temporary_env(**env: str) -> Generator[None, None, None]:
    keys = {
        "ECNU_API_KEY",
        "ECNU_BASE_URL",
        "ECNU_DEFAULT_MODEL",
        "LLM_API_KEY",
        "LLM_BASE_URL",
        "LLM_DEFAULT_MODEL",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_MODEL",
        "TEXTBOOK2VIDEO_SKIP_DOTENV",
    }
    original = {key: os.environ.get(key) for key in keys}
    try:
        for key in keys:
            _ = os.environ.pop(key, None)
        os.environ["TEXTBOOK2VIDEO_SKIP_DOTENV"] = "1"
        os.environ.update(env)
        yield
    finally:
        for key in keys:
            _ = os.environ.pop(key, None)
        for key, value in original.items():
            if value is not None:
                os.environ[key] = value


def test_llm_config_does_not_pair_ecnu_key_with_openai_base_url():
    with _temporary_env(
        ECNU_API_KEY="ecnu-key",
        ECNU_BASE_URL="https://ecnu.example/v1",
        OPENAI_BASE_URL="https://openai-compatible.example/v1",
    ):
        api_key, base_url, _model = _select_llm_config()

    assert api_key == "ecnu-key"
    assert base_url == "https://ecnu.example/v1"


def test_llm_config_uses_openai_pair_only_when_key_and_base_url_are_present():
    with _temporary_env(
        ECNU_API_KEY="ecnu-key",
        ECNU_BASE_URL="https://ecnu.example/v1",
        OPENAI_API_KEY="openai-key",
        OPENAI_BASE_URL="https://openai-compatible.example/v1",
        OPENAI_MODEL="gpt-test",
    ):
        api_key, base_url, model = _select_llm_config()

    assert api_key == "openai-key"
    assert base_url == "https://openai-compatible.example/v1"
    assert model == "gpt-test"


def test_llm_config_prefers_explicit_llm_pair():
    with _temporary_env(
        ECNU_API_KEY="ecnu-key",
        ECNU_BASE_URL="https://ecnu.example/v1",
        OPENAI_API_KEY="openai-key",
        OPENAI_BASE_URL="https://openai-compatible.example/v1",
        LLM_API_KEY="llm-key",
        LLM_BASE_URL="https://llm.example/v1",
        LLM_DEFAULT_MODEL="gpt-5.5",
    ):
        api_key, base_url, model = _select_llm_config()

    assert api_key == "llm-key"
    assert base_url == "https://llm.example/v1"
    assert model == "gpt-5.5"
