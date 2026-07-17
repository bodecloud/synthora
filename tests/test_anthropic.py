"""Adapter contract tests for Anthropic + follow-up brief context."""

from __future__ import annotations

import pytest
from synthora.adapters.llm import AnthropicModel, llm_registry


def test_anthropic_registry_uses_native_client():
    model = llm_registry.resolve("anthropic:claude-sonnet-4-20250514")
    assert isinstance(model, AnthropicModel)


@pytest.mark.asyncio
async def test_anthropic_requires_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    model = AnthropicModel("claude-test", api_key="")
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        await model.complete([{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_anthropic_posts_messages_api(monkeypatch, httpx_mock=None):
    """Native Anthropic uses x-api-key + /v1/messages (not Bearer chat/completions)."""
    import httpx

    captured: dict = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "content": [{"type": "text", "text": "hello from anthropic"}]
            }

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, json=None, headers=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    model = AnthropicModel(
        "claude-test",
        api_key="sk-ant-test",
        base_url="https://api.anthropic.com",
    )
    out = await model.complete(
        [
            {"role": "system", "content": "be brief"},
            {"role": "user", "content": "hi"},
        ]
    )
    assert out == "hello from anthropic"
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["headers"]["x-api-key"] == "sk-ant-test"
    assert "Authorization" not in captured["headers"]
    assert captured["json"]["system"] == "be brief"
    assert captured["json"]["messages"][0]["role"] == "user"
