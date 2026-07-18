"""LiteLLM-backed chat model with ordered fallbacks (via llm_fallbacks lists)."""

from __future__ import annotations

from typing import Optional

from synthora.adapters.llm import strip_think_tags


def synthora_model_to_litellm(model_id: str) -> str:
    """Map ``provider:model`` to a LiteLLM model string."""
    provider, _, model = model_id.partition(":")
    if not model:
        return model_id
    if provider == "openai":
        return model
    if provider == "ollama":
        return f"ollama/{model}"
    if provider in ("openai-compatible", "custom_openai_endpoint"):
        return f"openai/{model}"
    return f"{provider}/{model}"


class FallbackChatModel:
    """Try a primary LiteLLM model, then fallbacks in order."""

    def __init__(
        self,
        *,
        role: str,
        primary: str,
        fallbacks: list[str] | None = None,
        resolved_models: dict[str, str] | None = None,
        temperature_default: float = 0.3,
    ) -> None:
        self.role = role
        self.primary = primary
        self.fallbacks = list(fallbacks or [])
        self._resolved_models = resolved_models
        self.temperature_default = temperature_default
        self.last_used_model: str | None = None

    @property
    def model(self) -> str:
        return self.last_used_model or self.primary

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
    ) -> str:
        import litellm

        chain = [self.primary, *[m for m in self.fallbacks if m != self.primary]]
        last_error: Exception | None = None
        for model in chain:
            try:
                kwargs: dict = {
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                }
                if max_tokens is not None:
                    kwargs["max_tokens"] = max_tokens
                response = await litellm.acompletion(**kwargs)
                content = response.choices[0].message.content or ""
                self.last_used_model = model
                if self._resolved_models is not None:
                    self._resolved_models[self.role] = model
                return strip_think_tags(content)
            except Exception as exc:
                last_error = exc
                continue
        raise RuntimeError(
            f"All LLM fallbacks failed for role {self.role!r} "
            f"(tried {len(chain)} model(s)): {last_error}"
        ) from last_error
