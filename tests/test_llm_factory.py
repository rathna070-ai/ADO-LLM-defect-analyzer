import pytest

from ado_defect_analysis.config import LlmConfig
from ado_defect_analysis.llm import LlmProviderError, get_llm_provider
from ado_defect_analysis.llm.copilot_provider import CopilotProvider
from ado_defect_analysis.llm.groq_provider import GroqProvider


def test_factory_returns_groq_provider_when_configured():
    config = LlmConfig(provider="groq", groq_api_key="test-key")
    provider = get_llm_provider(config)
    assert isinstance(provider, GroqProvider)


def test_factory_returns_copilot_provider_when_configured():
    config = LlmConfig(provider="copilot", copilot_api_key="test-key")
    provider = get_llm_provider(config)
    assert isinstance(provider, CopilotProvider)
    assert provider.model_name == "openai/gpt-4o-mini"


def test_factory_does_not_force_reasoning_effort_onto_copilot():
    """The default effort is tuned for Groq's gpt-oss; gpt-4o-mini 400s on it."""
    config = LlmConfig(provider="copilot", copilot_api_key="test-key", reasoning_effort="low")

    provider = get_llm_provider(config)

    assert provider._reasoning_effort == ""


def test_factory_rejects_unknown_provider():
    config = LlmConfig(provider="not-a-real-provider")
    with pytest.raises(LlmProviderError):
        get_llm_provider(config)


def test_groq_provider_requires_api_key():
    with pytest.raises(LlmProviderError):
        GroqProvider(
            api_key="", model="llama-3.3-70b-versatile", base_url="https://api.groq.com/openai/v1"
        )


def test_copilot_provider_requires_api_key():
    with pytest.raises(LlmProviderError, match="COPILOT_API_KEY"):
        CopilotProvider(api_key="", model="openai/gpt-4o-mini")
