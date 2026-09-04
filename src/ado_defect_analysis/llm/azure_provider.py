"""Azure AI Foundry provider.

Foundry exposes an OpenAI-compatible chat-completions endpoint authenticated
with a bearer token, so this is the shared `OpenAiCompatibleProvider`
transport pointed at a Foundry resource. Two things differ from the other
backends and both bite if you assume otherwise:

- The `model` field carries the **deployment name** you chose in Foundry, not
  a publisher-qualified id like Groq's `openai/gpt-oss-120b`.
- The base URL is resource-specific
  (`https://<resource>.openai.azure.com/openai/v1`), so unlike a fixed public
  endpoint there is no sensible default — a wrong guess would fail with a
  confusing 404 rather than an actionable message.

Replaces the GitHub Models provider that used to live here. That surface was
retired on 30 July 2026, and GitHub's own notice points to Foundry.

Not yet exercised against a live resource. Two details to confirm on a first
real run: whether the chosen deployment accepts
`response_format: {"type": "json_object"}` (the GPT-4o family does, not every
Foundry-hosted model), and whether it wants `max_completion_tokens` instead of
`max_tokens` (o-series deployments do).
"""

from __future__ import annotations

from .base import LlmProviderError
from .openai_compatible import OpenAiCompatibleProvider


class AzureFoundryProvider(OpenAiCompatibleProvider):
    provider_name = "Azure AI Foundry"
    api_key_env_var = "AZURE_API_KEY"

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "",
        timeout_seconds: int = 60,
        reasoning_effort: str = "",
    ):
        if not base_url:
            raise LlmProviderError(
                "AZURE_BASE_URL is not set. It is specific to your Foundry resource, "
                "so there is no default — use "
                "https://<your-resource>.openai.azure.com/openai/v1"
            )
        if not model:
            raise LlmProviderError(
                "AZURE_DEPLOYMENT is not set. Azure addresses a model by the deployment "
                "name you gave it in Foundry, not by a publisher-qualified model id."
            )
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            reasoning_effort=reasoning_effort,
        )
