"""Selects an LlmProvider from config. The only place that knows provider names exist."""

from __future__ import annotations

from ..config import LlmConfig
from .azure_provider import AzureFoundryProvider
from .base import LlmProvider, LlmProviderError
from .groq_provider import GroqProvider


def get_llm_providers(llm_config: LlmConfig) -> list[LlmProvider]:
    """One provider per available credential.

    Rate limits are per key, so a second Groq key is a second token budget —
    the categorize stage runs one worker per provider to use them all. Any
    other provider yields a single-item list, so callers need no special case.
    """
    if llm_config.provider == "groq":
        keys = llm_config.groq_api_keys or [llm_config.groq_api_key]
        return [
            GroqProvider(
                api_key=key,
                model=llm_config.groq_model,
                base_url=llm_config.groq_base_url,
                timeout_seconds=llm_config.request_timeout_seconds,
                reasoning_effort=llm_config.reasoning_effort,
            )
            for key in keys
        ]
    return [get_llm_provider(llm_config)]


def get_llm_provider(llm_config: LlmConfig) -> LlmProvider:
    provider = llm_config.provider
    if provider == "groq":
        return GroqProvider(
            # The primary key; multi-key work goes through get_llm_providers.
            api_key=llm_config.groq_api_key or next(iter(llm_config.groq_api_keys), ""),
            model=llm_config.groq_model,
            base_url=llm_config.groq_base_url,
            timeout_seconds=llm_config.request_timeout_seconds,
            reasoning_effort=llm_config.reasoning_effort,
        )
    if provider == "azure":
        return AzureFoundryProvider(
            api_key=llm_config.azure_api_key,
            model=llm_config.azure_deployment,
            base_url=llm_config.azure_base_url,
            timeout_seconds=llm_config.request_timeout_seconds,
            # LLM_REASONING_EFFORT is deliberately not forwarded: it is tuned
            # for Groq's gpt-oss default, and a non-reasoning deployment
            # rejects the parameter outright. Pass it explicitly if you point
            # AZURE_DEPLOYMENT at an o-series model.
        )
    if provider == "copilot":
        # Recognised only to give anyone with the old value an actionable
        # message instead of a 404 from a host that no longer answers.
        raise LlmProviderError(
            "LLM_PROVIDER=copilot referred to GitHub Models, which was retired on "
            "30 July 2026. Use LLM_PROVIDER=azure with AZURE_API_KEY, AZURE_BASE_URL "
            "and AZURE_DEPLOYMENT instead."
        )
    raise LlmProviderError(f"Unknown LLM_PROVIDER '{provider}'. Supported values: 'groq', 'azure'.")
