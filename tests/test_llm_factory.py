import pytest

from ado_defect_analysis.config import LlmConfig
from ado_defect_analysis.llm import LlmProviderError, get_llm_provider
from ado_defect_analysis.llm.azure_provider import AzureFoundryProvider
from ado_defect_analysis.llm.groq_provider import GroqProvider


def test_factory_returns_groq_provider_when_configured():
    config = LlmConfig(provider="groq", groq_api_key="test-key")
    provider = get_llm_provider(config)
    assert isinstance(provider, GroqProvider)


def test_factory_returns_azure_provider_when_configured():
    config = LlmConfig(
        provider="azure",
        azure_api_key="test-key",
        azure_deployment="gpt-4o-mini-deploy",
        azure_base_url="https://r.openai.azure.com/openai/v1",
    )

    provider = get_llm_provider(config)

    assert isinstance(provider, AzureFoundryProvider)
    assert provider.model_name == "gpt-4o-mini-deploy"


def test_factory_does_not_force_reasoning_effort_onto_azure():
    """The default effort is tuned for Groq's gpt-oss; a gpt-4o deployment 400s."""
    config = LlmConfig(
        provider="azure",
        azure_api_key="test-key",
        azure_deployment="gpt-4o-mini-deploy",
        azure_base_url="https://r.openai.azure.com/openai/v1",
        reasoning_effort="low",
    )

    assert get_llm_provider(config)._reasoning_effort == ""


def test_the_retired_copilot_value_explains_itself():
    """Anyone with the old value in .env should get a pointer, not a 404."""
    with pytest.raises(LlmProviderError, match="retired"):
        get_llm_provider(LlmConfig(provider="copilot"))


def test_groq_provider_requires_api_key():
    with pytest.raises(LlmProviderError):
        GroqProvider(
            api_key="", model="llama-3.3-70b-versatile", base_url="https://api.groq.com/openai/v1"
        )
