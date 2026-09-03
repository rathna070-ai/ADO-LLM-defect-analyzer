"""Selects an LlmProvider from config. The only place that knows provider names exist."""

from __future__ import annotations

from ..config import LlmConfig
from .base import LlmProvider, LlmProviderError
from .copilot_provider import CopilotProvider
from .groq_provider import GroqProvider


def get_llm_provider(llm_config: LlmConfig) -> LlmProvider:
    provider = llm_config.provider
    if provider == "groq":
        return GroqProvider(
            api_key=llm_config.groq_api_key,
            model=llm_config.groq_model,
            base_url=llm_config.groq_base_url,
            timeout_seconds=llm_config.request_timeout_seconds,
            reasoning_effort=llm_config.reasoning_effort,
        )
    if provider == "copilot":
        return CopilotProvider(
            api_key=llm_config.copilot_api_key,
            model=llm_config.copilot_model,
            timeout_seconds=llm_config.request_timeout_seconds,
        )
    raise LlmProviderError(
        f"Unknown LLM_PROVIDER '{provider}'. Supported values: 'groq', 'copilot'."
    )
