"""Azure AI Foundry provider tests.

The transport is shared with Groq, so these cover what differs: a
resource-specific endpoint with no safe default, the deployment name standing
in for a model id, and the error wording.
"""

import json

import pytest
import responses

from ado_defect_analysis.llm.azure_provider import AzureFoundryProvider
from ado_defect_analysis.llm.base import LlmProviderError

_BASE = "https://my-resource.openai.azure.com/openai/v1"
_URL = f"{_BASE}/chat/completions"


def _provider(**overrides) -> AzureFoundryProvider:
    kwargs = {"api_key": "az-key", "model": "gpt-4o-mini-deploy", "base_url": _BASE}
    kwargs.update(overrides)
    return AzureFoundryProvider(**kwargs)


@responses.activate
def test_complete_json_parses_a_response():
    responses.add(
        responses.POST,
        _URL,
        json={"choices": [{"message": {"content": json.dumps({"results": []})}}]},
        status=200,
    )

    result = _provider().complete_json(
        system_prompt="system", user_prompt="user", schema={"type": "object"}
    )

    assert result == {"results": []}


@responses.activate
def test_request_uses_bearer_auth_and_sends_the_deployment_as_the_model():
    """Azure addresses a model by deployment name, not a publisher-qualified id."""
    responses.add(
        responses.POST, _URL, json={"choices": [{"message": {"content": "{}"}}]}, status=200
    )

    _provider().complete_json(system_prompt="s", user_prompt="u", schema={"type": "object"})

    request = responses.calls[0].request
    assert request.headers["Authorization"] == "Bearer az-key"
    body = json.loads(request.body)
    assert body["model"] == "gpt-4o-mini-deploy"
    assert body["response_format"] == {"type": "json_object"}
    # gpt-4o deployments are not reasoning models and 400 on the parameter.
    assert "reasoning_effort" not in body


def test_a_missing_base_url_fails_with_an_actionable_message():
    """There is no sensible default: the endpoint is resource-specific, so a
    guess would surface as a confusing 404 instead of a config error."""
    with pytest.raises(LlmProviderError, match="AZURE_BASE_URL"):
        AzureFoundryProvider(api_key="k", model="d", base_url="")


def test_a_missing_deployment_fails_with_an_actionable_message():
    with pytest.raises(LlmProviderError, match="AZURE_DEPLOYMENT"):
        AzureFoundryProvider(api_key="k", model="", base_url=_BASE)


def test_a_missing_api_key_names_its_variable():
    with pytest.raises(LlmProviderError, match="AZURE_API_KEY"):
        AzureFoundryProvider(api_key="", model="d", base_url=_BASE)


@responses.activate
def test_reasoning_effort_is_sent_when_explicitly_configured():
    responses.add(
        responses.POST, _URL, json={"choices": [{"message": {"content": "{}"}}]}, status=200
    )

    _provider(model="o1-mini-deploy", reasoning_effort="low").complete_json(
        system_prompt="s", user_prompt="u", schema={"type": "object"}
    )

    assert json.loads(responses.calls[0].request.body)["reasoning_effort"] == "low"


@responses.activate
def test_error_message_names_the_provider():
    responses.add(responses.POST, _URL, json={"error": "quota"}, status=429)

    with pytest.raises(LlmProviderError, match="Azure AI Foundry request failed"):
        _provider().complete_json(system_prompt="s", user_prompt="u", schema={"type": "object"})


@responses.activate
def test_non_json_content_is_reported_clearly():
    responses.add(
        responses.POST,
        _URL,
        json={"choices": [{"message": {"content": "sorry, I can't do that"}}]},
        status=200,
    )

    with pytest.raises(LlmProviderError, match="did not return valid JSON"):
        _provider().complete_json(system_prompt="s", user_prompt="u", schema={"type": "object"})


@responses.activate
def test_usage_is_recorded():
    responses.add(
        responses.POST,
        _URL,
        json={
            "choices": [{"message": {"content": "{}"}}],
            "usage": {"prompt_tokens": 90, "completion_tokens": 30},
        },
        status=200,
    )
    provider = _provider()

    provider.complete_json(system_prompt="s", user_prompt="u", schema={"type": "object"})

    assert provider.usage.total_tokens == 120
