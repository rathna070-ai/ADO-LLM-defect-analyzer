import json

import responses

from ado_defect_analysis.llm.base import LlmProviderError
from ado_defect_analysis.llm.groq_provider import GroqProvider


@responses.activate
def test_complete_json_parses_groq_response():
    responses.add(
        responses.POST,
        "https://api.groq.com/openai/v1/chat/completions",
        json={
            "choices": [
                {"message": {"content": json.dumps({"results": [{"defect_id": 1}]})}}
            ]
        },
        status=200,
    )
    provider = GroqProvider(
        api_key="test-key", model="llama-3.3-70b-versatile", base_url="https://api.groq.com/openai/v1"
    )

    result = provider.complete_json(
        system_prompt="system", user_prompt="user", schema={"type": "object"}
    )

    assert result == {"results": [{"defect_id": 1}]}


@responses.activate
def test_complete_json_raises_on_non_200():
    responses.add(
        responses.POST,
        "https://api.groq.com/openai/v1/chat/completions",
        json={"error": "bad request"},
        status=400,
    )
    provider = GroqProvider(
        api_key="test-key", model="llama-3.3-70b-versatile", base_url="https://api.groq.com/openai/v1"
    )

    try:
        provider.complete_json(system_prompt="s", user_prompt="u", schema={"type": "object"})
        assert False, "expected LlmProviderError"
    except LlmProviderError:
        pass


@responses.activate
def test_complete_json_raises_on_invalid_json_content():
    responses.add(
        responses.POST,
        "https://api.groq.com/openai/v1/chat/completions",
        json={"choices": [{"message": {"content": "not json"}}]},
        status=200,
    )
    provider = GroqProvider(
        api_key="test-key", model="llama-3.3-70b-versatile", base_url="https://api.groq.com/openai/v1"
    )

    try:
        provider.complete_json(system_prompt="s", user_prompt="u", schema={"type": "object"})
        assert False, "expected LlmProviderError"
    except LlmProviderError:
        pass
