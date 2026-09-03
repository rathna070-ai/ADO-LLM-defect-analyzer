import json

import responses

from ado_defect_analysis.llm.base import TokenUsage
from ado_defect_analysis.llm.groq_provider import GroqProvider

_URL = "https://api.groq.com/openai/v1/chat/completions"


def test_usage_accumulates_across_calls():
    usage = TokenUsage()
    usage.add({"prompt_tokens": 100, "completion_tokens": 50})
    usage.add({"prompt_tokens": 200, "completion_tokens": 25})

    assert usage.calls == 2
    assert usage.prompt_tokens == 300
    assert usage.completion_tokens == 75
    assert usage.total_tokens == 375


def test_usage_tolerates_a_missing_usage_block():
    """Not every provider returns usage; that must not break the run."""
    usage = TokenUsage()
    usage.add(None)
    usage.add({})

    assert usage.calls == 2
    assert usage.total_tokens == 0


def test_cost_estimate_uses_separate_input_and_output_rates():
    usage = TokenUsage()
    usage.add({"prompt_tokens": 1_000_000, "completion_tokens": 500_000})

    # $0.15/Mtok in, $0.60/Mtok out -> 0.15 + 0.30
    assert round(usage.cost_estimate(0.15, 0.60), 4) == 0.45


def test_summary_omits_cost_when_no_rates_configured():
    usage = TokenUsage()
    usage.add({"prompt_tokens": 10, "completion_tokens": 5})

    assert "est. $" not in usage.summary()
    assert "est. $" in usage.summary(0.15, 0.60)


@responses.activate
def test_provider_records_usage_from_the_response():
    responses.add(
        responses.POST,
        _URL,
        json={
            "choices": [{"message": {"content": json.dumps({"ok": True})}}],
            "usage": {"prompt_tokens": 145, "completion_tokens": 174},
        },
        status=200,
    )
    provider = GroqProvider(
        api_key="k", model="openai/gpt-oss-120b", base_url=_URL.rsplit("/", 2)[0]
    )

    provider.complete_json(system_prompt="s", user_prompt="u", schema={"type": "object"})

    assert provider.usage.prompt_tokens == 145
    assert provider.usage.completion_tokens == 174
    assert provider.usage.calls == 1
