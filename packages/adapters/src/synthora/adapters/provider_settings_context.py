"""Workspace provider settings overlay for credential resolution.

When a research run starts, the worker loads ``provider_settings`` for the
run's workspace into a ContextVar. Adapter ``_env`` helpers consult this
before falling back to process environment variables.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any

# Map well-known env var names → (settings key, value field).
_ENV_TO_SETTING: dict[str, tuple[str, str]] = {
    "OPENAI_API_KEY": ("openai", "api_key"),
    "OPENAI_BASE_URL": ("openai", "base_url"),
    "ANTHROPIC_API_KEY": ("anthropic", "api_key"),
    "ANTHROPIC_BASE_URL": ("anthropic", "base_url"),
    "GOOGLE_API_KEY": ("google", "api_key"),
    "GEMINI_API_KEY": ("google", "api_key"),
    "OPENROUTER_API_KEY": ("openrouter", "api_key"),
    "OPENROUTER_BASE_URL": ("openrouter", "base_url"),
    "DEEPSEEK_API_KEY": ("deepseek", "api_key"),
    "XAI_API_KEY": ("xai", "api_key"),
    "TOGETHER_API_KEY": ("together", "api_key"),
    "LMSTUDIO_API_KEY": ("lmstudio", "api_key"),
    "LMSTUDIO_BASE_URL": ("lmstudio", "base_url"),
    "OLLAMA_BASE_URL": ("ollama", "base_url"),
    "TAVILY_API_KEY": ("tavily", "api_key"),
    "BRAVE_API_KEY": ("brave", "api_key"),
    "SERPER_API_KEY": ("serper", "api_key"),
    "SERPAPI_API_KEY": ("serpapi", "api_key"),
    "EXA_API_KEY": ("exa", "api_key"),
    "SEARXNG_URL": ("searxng", "base_url"),
    "ELASTICSEARCH_URL": ("elasticsearch", "base_url"),
    "GOOGLE_PSE_API_KEY": ("google_pse", "api_key"),
    "GOOGLE_PSE_CX": ("google_pse", "cx"),
}

_provider_settings: ContextVar[dict[str, dict[str, Any]]] = ContextVar(
    "synthora_provider_settings", default={}
)


def get_provider_settings() -> dict[str, dict[str, Any]]:
    return dict(_provider_settings.get() or {})


def set_provider_settings(settings: dict[str, dict[str, Any]]) -> Token:
    return _provider_settings.set(dict(settings or {}))


def reset_provider_settings(token: Token) -> None:
    _provider_settings.reset(token)


def setting_value(key: str, field: str, default: str = "") -> str:
    """Return a string field from the active workspace settings overlay."""
    bucket = (_provider_settings.get() or {}).get(key) or {}
    value = bucket.get(field)
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def resolve_credential(*env_names: str, default: str = "") -> str:
    """Prefer workspace provider_settings, then process environment.

    Env names are mapped via ``_ENV_TO_SETTING``. Unknown env names fall
    through to ``os.environ`` only.
    """
    import os

    for name in env_names:
        mapped = _ENV_TO_SETTING.get(name)
        if mapped is not None:
            key, field = mapped
            from_settings = setting_value(key, field)
            if from_settings:
                return from_settings
            # Also accept alternate field names commonly stored in JSON.
            if field == "api_key":
                alt = setting_value(key, "key") or setting_value(key, "token")
                if alt:
                    return alt
            if field == "base_url":
                alt = setting_value(key, "url")
                if alt:
                    return alt
        value = os.environ.get(name)
        if value:
            return value
    return default
