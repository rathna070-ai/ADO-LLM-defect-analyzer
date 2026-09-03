import pytest

from ado_defect_analysis.config import LlmConfig
from ado_defect_analysis.llm import LlmProviderError, get_llm_provider
from ado_defect_analysis.llm.copilot_provider import CopilotProvider
from ado_defect_analysis.llm.groq_provider import GroqProvider


def test_factory_returns_groq_provider_when_configured():
    config = LlmConfig(provider="groq", groq_api_key="test-key")
    provider = get_llm_provider(config)
    assert isinstance(provider, GroqProvider)


def test_factory_returns_copilot_placeholder_when_configured():
    config = LlmConfig(provider="copilot")
    provider = get_llm_provider(config)
    assert isinstance(provider, CopilotProvider)


def test_factory_rejects_unknown_provider():
    config = LlmConfig(provider="not-a-real-provider")
    with pytest.raises(LlmProviderError):
        get_llm_provider(config)


def test_groq_provider_requires_api_key():
    with pytest.raises(LlmProviderError):
        GroqProvider(
            api_key="", model="llama-3.3-70b-versatile", base_url="https://api.groq.com/openai/v1"
        )


def test_copilot_provider_is_not_implemented_yet():
    provider = CopilotProvider(api_key="", model="")
    with pytest.raises(LlmProviderError):
        provider.complete_json(
            system_prompt="system",
            user_prompt="user",
            schema={"type": "object"},
        )
