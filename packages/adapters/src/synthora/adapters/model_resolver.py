"""Implicit model selection: profiles, llm_fallbacks chains, env credentials."""

from __future__ import annotations

import os
from typing import Literal

import httpx
from synthora.adapters.fallback_llm import FallbackChatModel, synthora_model_to_litellm
from synthora.adapters.llm import llm_registry
from synthora.core.models import RunConfig
from synthora.core.ports import ChatModel

ModelProfile = Literal["auto", "local", "cloud", "free", "test"]

ROLE_FIELDS = (
    "planner_model",
    "researcher_model",
    "compressor_model",
    "writer_model",
    "critic_model",
)

AUTO_SENTINEL = "auto"


def _env(*names: str, default: str = "") -> str:
    from synthora.adapters.provider_settings_context import resolve_credential

    return resolve_credential(*names, default=default)


def get_model_profile() -> ModelProfile:
    raw = _env("SYNTHORA_MODEL_PROFILE", default="auto").strip().lower()
    if raw in ("auto", "local", "cloud", "free", "test"):
        return raw  # type: ignore[return-value]
    return "auto"


def is_auto_model(model_id: str) -> bool:
    return not model_id or model_id.strip().lower() == AUTO_SENTINEL


def _has_openai_key() -> bool:
    return bool(_env("OPENAI_API_KEY"))


def _ollama_base_url() -> str:
    return _env("OLLAMA_BASE_URL", default="http://localhost:11434").rstrip("/")


async def ollama_reachable(timeout: float = 2.0) -> bool:
    url = _ollama_base_url()
    if not url:
        return False
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{url}/api/tags")
            return resp.status_code == 200
    except Exception:
        return False


def _explicit_litellm_chain(profile: ModelProfile) -> list[str]:
    """Build ordered LiteLLM model ids for ``auto`` resolution."""
    if profile == "test":
        return ["fake/default"]

    chain: list[str] = []

    if profile in ("auto", "local", "cloud") and _has_openai_key():
        chain.extend(
            [
                synthora_model_to_litellm("openai:gpt-4o-mini"),
                synthora_model_to_litellm("openai:gpt-4o"),
            ]
        )

    if profile in ("auto", "local") and _ollama_base_url():
        default_ollama = _env("SYNTHORA_OLLAMA_MODEL", default="llama3.1")
        chain.append(synthora_model_to_litellm(f"ollama:{default_ollama}"))

    if profile in ("auto", "cloud", "free"):
        try:
            from llm_fallbacks import filter_models, get_fallback_list

            if profile == "free":
                models = filter_models(model_type="chat", free_only=True)
                chain.extend(list(models.keys())[:10])
            else:
                chain.extend(get_fallback_list("chat")[:15])
        except Exception:
            pass

    # Dedupe preserving order
    seen: set[str] = set()
    out: list[str] = []
    for m in chain:
        key = m.casefold()
        if key not in seen:
            seen.add(key)
            out.append(m)
    return out


def _pick_primary_for_role(role: str, profile: ModelProfile) -> tuple[str, list[str]]:
    chain = _explicit_litellm_chain(profile)
    if not chain:
        return "gpt-4o-mini", []
    # Writer role prefers stronger model when available
    if role == "writer" and len(chain) > 1 and profile != "test":
        primary = chain[1] if chain[0].endswith("mini") else chain[0]
        fallbacks = [m for m in chain if m != primary]
        return primary, fallbacks
    primary = chain[0]
    return primary, chain[1:]


def resolve_chat_model(
    model_id: str,
    *,
    role: str,
    profile: ModelProfile | None = None,
    resolved_models: dict[str, str] | None = None,
) -> ChatModel:
    """Resolve a RunConfig model field to a ChatModel."""
    prof = profile or get_model_profile()

    if prof == "test" or model_id.startswith("fake:") or model_id.startswith("exploding:"):
        return llm_registry.resolve(model_id if model_id else "fake:default")

    if not is_auto_model(model_id):
        # Explicit provider:model — use registry for native adapters (anthropic, fake)
        provider, _, _ = model_id.partition(":")
        if provider in ("fake", "exploding", "anthropic"):
            return llm_registry.resolve(model_id)
        litellm_id = synthora_model_to_litellm(model_id)
        return FallbackChatModel(
            role=role,
            primary=litellm_id,
            fallbacks=[],
            resolved_models=resolved_models,
        )

    primary, fallbacks = _pick_primary_for_role(role, prof)
    if prof == "test":
        return llm_registry.resolve("fake:default")
    if not primary and not fallbacks:
        raise RuntimeError(
            "No LLM models available: set OPENAI_API_KEY, OLLAMA_BASE_URL, "
            "or SYNTHORA_MODEL_PROFILE=free with llm_fallbacks configured."
        )
    return FallbackChatModel(
        role=role,
        primary=primary,
        fallbacks=fallbacks,
        resolved_models=resolved_models,
    )


def resolve_run_config(cfg: RunConfig, profile: ModelProfile | None = None) -> RunConfig:
    """Return a copy with ``auto`` model fields replaced by chosen primaries (for persistence)."""
    prof = profile or get_model_profile()
    data = cfg.model_dump()
    for field in ROLE_FIELDS:
        if is_auto_model(str(data.get(field, AUTO_SENTINEL))):
            primary, _ = _pick_primary_for_role(field.replace("_model", ""), prof)
            if prof != "test" and primary:
                data[field] = primary
            elif prof == "test":
                data[field] = "fake:default"
    return RunConfig.model_validate(data)


async def probe_llm_readiness(profile: ModelProfile | None = None) -> dict:
    """Summarize whether research can run with current credentials."""
    prof = profile or get_model_profile()
    chain = _explicit_litellm_chain(prof)
    ollama_ok = await ollama_reachable()
    status = "ok" if chain or ollama_ok or _has_openai_key() else "unavailable"
    if status == "ok" and not chain and not _has_openai_key() and not ollama_ok:
        status = "degraded"
    return {
        "llm": status,
        "profile": prof,
        "openai_key": _has_openai_key(),
        "ollama_reachable": ollama_ok,
        "sample_models": chain[:5],
    }
