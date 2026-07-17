"""LLM provider registry (R-LDR-4, R-ODR-5).

Model identifiers use ``provider:model`` strings, e.g. ``openai:gpt-4o``,
``ollama:llama3.1``, ``anthropic:claude-sonnet-4-20250514``. New providers
register a factory by name; every provider returns an object satisfying the
ChatModel port.

Most third-party providers are thin aliases of
:class:`OpenAICompatibleModel` with provider-specific base URLs and env vars.
"""

from __future__ import annotations

from typing import Callable, Optional

import httpx
from synthora.core.ports import ChatModel

ProviderFactory = Callable[[str], ChatModel]


def _env(*names: str, default: str = "") -> str:
    from synthora.adapters.provider_settings_context import resolve_credential

    return resolve_credential(*names, default=default)


class OpenAICompatibleModel:
    """Chat model over any OpenAI-compatible endpoint (OpenAI, OpenRouter,
    vLLM, LM Studio, llama.cpp server, DeepSeek, xAI, Together, …)."""

    def __init__(
        self,
        model: str,
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 120.0,
    ) -> None:
        self.model = model
        self.api_key = api_key or _env("OPENAI_API_KEY")
        self.base_url = (
            base_url or _env("OPENAI_BASE_URL", default="https://api.openai.com/v1")
        ).rstrip("/")
        self.timeout = timeout

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
    ) -> str:
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions", json=payload, headers=headers
            )
            resp.raise_for_status()
            data = resp.json()
        content = data["choices"][0]["message"]["content"] or ""
        return strip_think_tags(content)


class OllamaModel:
    """Chat model over a local Ollama server."""

    def __init__(
        self, model: str, *, base_url: Optional[str] = None, timeout: float = 300.0
    ) -> None:
        self.model = model
        self.base_url = (
            base_url or _env("OLLAMA_BASE_URL", default="http://localhost:11434")
        ).rstrip("/")
        self.timeout = timeout

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
    ) -> str:
        options: dict = {"temperature": temperature}
        if max_tokens:
            options["num_predict"] = max_tokens
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "options": options,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        return strip_think_tags(data.get("message", {}).get("content", ""))


def strip_think_tags(text: str) -> str:
    """Remove <think>...</think> blocks emitted by reasoning models
    (mirrors Local Deep Research's think-tag wrapper)."""
    import re

    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


class LLMProviderRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, ProviderFactory] = {}

    def register(self, provider: str, factory: ProviderFactory) -> None:
        self._factories[provider] = factory

    def providers(self) -> list[str]:
        return sorted(self._factories)

    def resolve(self, model_id: str) -> ChatModel:
        """Resolve a ``provider:model`` identifier to a chat model."""
        provider, _, model = model_id.partition(":")
        if not model:
            provider, model = "openai", provider
        if provider not in self._factories:
            raise KeyError(
                f"unknown LLM provider '{provider}' (known: {self.providers()})"
            )
        return self._factories[provider](model)


llm_registry = LLMProviderRegistry()
llm_registry.register("openai", lambda m: OpenAICompatibleModel(m))
llm_registry.register(
    "openai-compatible",
    lambda m: OpenAICompatibleModel(m, base_url=_env("OPENAI_BASE_URL")),
)
llm_registry.register("ollama", lambda m: OllamaModel(m))
llm_registry.register(
    "anthropic",
    lambda m: OpenAICompatibleModel(
        m,
        api_key=_env("ANTHROPIC_API_KEY"),
        base_url=_env(
            "ANTHROPIC_BASE_URL", default="https://api.anthropic.com/v1"
        ),
    ),
)
llm_registry.register(
    "google",
    lambda m: OpenAICompatibleModel(
        m,
        api_key=_env("GOOGLE_API_KEY", "GEMINI_API_KEY"),
        base_url=_env(
            "GOOGLE_BASE_URL",
            "GEMINI_BASE_URL",
            default="https://generativelanguage.googleapis.com/v1beta/openai",
        ),
    ),
)
llm_registry.register(
    "openrouter",
    lambda m: OpenAICompatibleModel(
        m,
        api_key=_env("OPENROUTER_API_KEY"),
        base_url=_env("OPENROUTER_BASE_URL", default="https://openrouter.ai/api/v1"),
    ),
)
llm_registry.register(
    "lmstudio",
    lambda m: OpenAICompatibleModel(
        m,
        api_key=_env("LMSTUDIO_API_KEY", default="lm-studio"),
        base_url=_env("LMSTUDIO_BASE_URL", default="http://localhost:1234/v1"),
    ),
)
llm_registry.register(
    "deepseek",
    lambda m: OpenAICompatibleModel(
        m,
        api_key=_env("DEEPSEEK_API_KEY"),
        base_url=_env("DEEPSEEK_BASE_URL", default="https://api.deepseek.com"),
    ),
)
llm_registry.register(
    "xai",
    lambda m: OpenAICompatibleModel(
        m,
        api_key=_env("XAI_API_KEY"),
        base_url=_env("XAI_BASE_URL", default="https://api.x.ai/v1"),
    ),
)
llm_registry.register(
    "together",
    lambda m: OpenAICompatibleModel(
        m,
        api_key=_env("TOGETHER_API_KEY"),
        base_url=_env("TOGETHER_BASE_URL", default="https://api.together.xyz/v1"),
    ),
)
llm_registry.register(
    "custom_openai_endpoint",
    lambda m: OpenAICompatibleModel(
        m,
        api_key=_env("CUSTOM_OPENAI_API_KEY", "OPENAI_API_KEY"),
        base_url=_env(
            "CUSTOM_OPENAI_BASE_URL",
            "OPENAI_BASE_URL",
            default="http://localhost:8000/v1",
        ),
    ),
)
