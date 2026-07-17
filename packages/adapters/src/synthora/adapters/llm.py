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


class AnthropicModel:
    """Native Anthropic Messages API client (not OpenAI-compatible)."""

    def __init__(
        self,
        model: str,
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 120.0,
    ) -> None:
        self.model = model
        self.api_key = api_key or _env("ANTHROPIC_API_KEY")
        self.base_url = (
            base_url
            or _env("ANTHROPIC_BASE_URL", default="https://api.anthropic.com")
        ).rstrip("/")
        # Allow accidental ``.../v1`` env values; we append ``/v1/messages``.
        if self.base_url.endswith("/v1"):
            self.base_url = self.base_url[: -len("/v1")]
        self.timeout = timeout

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
    ) -> str:
        if not self.api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is required for anthropic:* models"
            )
        system_parts: list[str] = []
        converted: list[dict[str, str]] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                system_parts.append(content)
            else:
                converted.append(
                    {
                        "role": "assistant" if role == "assistant" else "user",
                        "content": content,
                    }
                )
        if not converted:
            converted = [{"role": "user", "content": "\n".join(system_parts) or "."}]
            system_parts = []
        payload: dict = {
            "model": self.model,
            "messages": converted,
            "max_tokens": max_tokens or 4096,
            "temperature": temperature,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/v1/messages", json=payload, headers=headers
            )
            resp.raise_for_status()
            data = resp.json()
        blocks = data.get("content") or []
        text = "".join(
            block.get("text", "")
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        )
        return strip_think_tags(text)


class FakeRoutingModel:
    """Deterministic offline LLM for smoke tests and local demos.

    Routes by system-prompt keywords so planner / researcher / writer roles
    all work without an API key. Enable with ``fake:any-model``.
    """

    def __init__(self) -> None:
        self._supervisor_calls = 0

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
    ) -> str:
        import json

        system = (messages[0].get("content") if messages else "") or ""
        if "Rewrite the research request" in system:
            user = messages[-1].get("content", "") if len(messages) > 1 else ""
            return f"Smoke research brief.\n\n{user[:500]}"
        if "researcher with a search tool" in system:
            user = messages[-1].get("content", "") if len(messages) > 1 else ""
            findings_body = ""
            if "Findings:\n" in user:
                findings_body = user.split("Findings:\n", 1)[-1].strip()
            if findings_body and findings_body != "(none yet)":
                return json.dumps(
                    {"action": "complete", "reflection": "enough for smoke"}
                )
            return json.dumps(
                {"action": "search", "query": "smoke query", "reflection": "start"}
            )
        if "research supervisor" in system:
            self._supervisor_calls += 1
            if self._supervisor_calls <= 1:
                return json.dumps(
                    {
                        "action": "conduct_research",
                        "topics": ["smoke focus topic"],
                    }
                )
            return json.dumps({"action": "research_complete", "reason": "done"})
        if "Compress these research findings" in system:
            return "compressed smoke findings [1]"
        if "final research report" in system:
            return (
                "# Smoke Report\n\nDeterministic offline finding [1].\n\n## Sources"
            )
        if "Decompose the research topic" in system:
            return "smoke sub-query"
        if "Summarize the web page" in system:
            return "smoke page summary"
        if "academic literature search" in system:
            return "smoke lit query one\nsmoke lit query two"
        if "Generate 2-3 concrete" in system or "investigable hypotheses" in system:
            return "smoke hypothesis A\nsmoke hypothesis B"
        if "Identify the most important unanswered" in system or "knowledge gaps" in system:
            return ""
        if "academic peer reviewer" in system:
            return "1. Add one more primary source."
        if "rigorous reviewer" in system or "Critique" in system:
            return "- Looks complete for a smoke test."
        if "verify sources" in system.lower() or "Verify sources" in system:
            return json.dumps({"verified": [1], "rejected": []})
        if "perspective" in system.lower() or "expert persona" in system.lower():
            return json.dumps(
                {
                    "perspectives": [
                        {"name": "Engineer", "focus": "reliability", "expertise": "qa"}
                    ]
                }
            )
        if (
            "hierarchical outline" in system.lower()
            or "JSON outline" in system
            or "Design a report outline" in system
        ):
            return json.dumps(
                {
                    "title": "Smoke Report",
                    "sections": [{"title": "Findings", "description": "results"}],
                }
            )
        if (
            "Deduplicate" in system
            or "polished Markdown" in system
            or "citation markers intact" in system
        ):
            return (
                messages[-1].get("content", "polished")
                if len(messages) > 1
                else "polished"
            )
        return "ok"


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
llm_registry.register("fake", lambda m: FakeRoutingModel())
llm_registry.register(
    "anthropic",
    lambda m: AnthropicModel(m),
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
