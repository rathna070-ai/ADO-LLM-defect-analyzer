"""GitHub Models provider tests.

Mirrors test_groq_provider.py — the two share a transport, so these guard the
parts that differ: endpoint, auth header, error wording, and the fact that no
Groq-tuned defaults leak in.
"""

import json

import pytest
import responses

from ado_defect_analysis.llm.base import LlmProviderError
from ado_defect_analysis.llm.copilot_provider import DEFAULT_BASE_URL, CopilotProvider

_URL = f"{DEFAULT_BASE_URL}/chat/completions"


def _provider(**overrides) -> CopilotProvider:
    kwargs = {"api_key": "ghp_test", "model": "openai/gpt-4o-mini"}
    kwargs.update(overrides)
    return CopilotProvider(**kwargs)


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
def test_request_targets_github_models_with_bearer_auth():
    responses.add(
        responses.POST, _URL, json={"choices": [{"message": {"content": "{}"}}]}, status=200
    )

    _provider().complete_json(system_prompt="s", user_prompt="u", schema={"type": "object"})

    request = responses.calls[0].request
    assert request.headers["Authorization"] == "Bearer ghp_test"
    body = json.loads(request.body)
    assert body["model"] == "openai/gpt-4o-mini"
    assert body["response_format"] == {"type": "json_object"}
    # Not a reasoning model — the parameter must not be sent by default.
    assert "reasoning_effort" not in body


@responses.activate
def test_reasoning_effort_is_sent_when_explicitly_configured():
    responses.add(
        responses.POST, _URL, json={"choices": [{"message": {"content": "{}"}}]}, status=200
    )

    _provider(model="openai/o1-mini", reasoning_effort="low").complete_json(
        system_prompt="s", user_prompt="u", schema={"type": "object"}
    )

    assert json.loads(responses.calls[0].request.body)["reasoning_effort"] == "low"


@responses.activate
def test_a_custom_base_url_is_honoured():
    """GitHub has moved this surface before; the endpoint stays configurable."""
    legacy = "https://models.inference.ai.azure.com"
    responses.add(
        responses.POST,
        f"{legacy}/chat/completions",
        json={"choices": [{"message": {"content": "{}"}}]},
        status=200,
    )

    _provider(base_url=legacy).complete_json(
        system_prompt="s", user_prompt="u", schema={"type": "object"}
    )

    assert responses.calls[0].request.url.startswith(legacy)


@responses.activate
def test_error_message_names_the_provider():
    responses.add(responses.POST, _URL, json={"error": "no access"}, status=403)

    with pytest.raises(LlmProviderError, match="GitHub Models request failed"):
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
