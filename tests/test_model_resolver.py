"""Tests for implicit model resolution and LiteLLM fallbacks."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from synthora.adapters.fallback_llm import synthora_model_to_litellm
from synthora.adapters.llm import llm_registry
from synthora.adapters.model_resolver import (
    get_model_profile,
    is_auto_model,
    resolve_chat_model,
    resolve_run_config,
)
from synthora.core.models import RunConfig


def test_synthora_model_to_litellm():
    assert synthora_model_to_litellm("openai:gpt-4o-mini") == "gpt-4o-mini"
    assert synthora_model_to_litellm("ollama:llama3.1") == "ollama/llama3.1"
    assert synthora_model_to_litellm("openrouter:meta/llama") == "openrouter/meta/llama"


def test_is_auto_model():
    assert is_auto_model("auto")
    assert is_auto_model("")
    assert not is_auto_model("fake:m")


def test_resolve_run_config_test_profile(monkeypatch):
    monkeypatch.setenv("SYNTHORA_MODEL_PROFILE", "test")
    cfg = resolve_run_config(RunConfig())
    assert cfg.planner_model == "fake:default"
    assert cfg.writer_model == "fake:default"


def test_resolve_chat_model_explicit_fake():
    from synthora.adapters.llm import FakeRoutingModel

    llm_registry.register("fake", lambda m: FakeRoutingModel())
    model = resolve_chat_model("fake:m", role="planner", profile="test")
    import asyncio

    out = asyncio.run(model.complete([{"role": "user", "content": "hi"}]))
    assert out == "ok"


@pytest.mark.asyncio
async def test_fallback_chat_model_tries_chain(monkeypatch):
    monkeypatch.setenv("SYNTHORA_MODEL_PROFILE", "cloud")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    calls: list[str] = []

    async def fake_acompletion(*, model, messages, **kwargs):
        calls.append(model)
        if len(calls) == 1:
            raise RuntimeError("primary failed")
        mock_resp = AsyncMock()
        mock_resp.choices = [AsyncMock(message=AsyncMock(content="hello"))]
        return mock_resp

    with patch("litellm.acompletion", side_effect=fake_acompletion):
        model = resolve_chat_model("auto", role="planner", profile="cloud")
        text = await model.complete([{"role": "user", "content": "hi"}])
    assert text == "hello"
    assert len(calls) >= 2


def test_run_config_defaults_auto():
    cfg = RunConfig()
    assert cfg.planner_model == "auto"
    assert get_model_profile() in ("auto", "test")
