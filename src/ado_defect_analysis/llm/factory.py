"""Selects an LlmProvider from config. The only place that knows provider names exist."""

from __future__ import annotations

from ..config import LlmConfig
from .base import LlmProvider, LlmProviderError
from .copilot_provider import CopilotProvider
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
    if provider == "copilot":
        return CopilotProvider(
            api_key=llm_config.copilot_api_key,
            model=llm_config.copilot_model,
            base_url=llm_config.copilot_base_url,
            timeout_seconds=llm_config.request_timeout_seconds,
            # LLM_REASONING_EFFORT is deliberately not forwarded here: it's
            # tuned for Groq's gpt-oss default, and sending it to a
            # non-reasoning model like the gpt-4o-mini default is a 400. Pass
            # it explicitly if you point COPILOT_MODEL at an o-series model.
        )
    raise LlmProviderError(
        f"Unknown LLM_PROVIDER '{provider}'. Supported values: 'groq', 'copilot'."
    )
