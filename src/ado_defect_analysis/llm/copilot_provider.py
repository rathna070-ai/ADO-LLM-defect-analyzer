"""GitHub Models provider — the "Copilot" option in `LLM_PROVIDER`.

GitHub Models exposes an OpenAI-compatible chat-completions endpoint
authenticated with a GitHub token (a PAT with the `models:read` scope, or the
`GITHUB_TOKEN` inside Actions), so this provider is the shared
`OpenAiCompatibleProvider` transport pointed at a different base URL. Model
ids are publisher-qualified, e.g. `openai/gpt-4o-mini`.

Both the endpoint and the model are configurable (`COPILOT_BASE_URL`,
`COPILOT_MODEL`) because GitHub has moved this surface before — an older
deployment answers at `https://models.inference.ai.azure.com`. If a future
change breaks the default, it's a config edit, not a code change.

Not yet exercised against the live endpoint — there was no token to test with
when it was written, so treat the first real run as the verification step.
The request/response contract is covered by mocked tests either way.
"""

from __future__ import annotations

from .openai_compatible import OpenAiCompatibleProvider

DEFAULT_BASE_URL = "https://models.github.ai/inference"


class CopilotProvider(OpenAiCompatibleProvider):
    provider_name = "GitHub Models"
    api_key_env_var = "COPILOT_API_KEY"

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: int = 60,
        reasoning_effort: str = "",
    ):
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=base_url or DEFAULT_BASE_URL,
            timeout_seconds=timeout_seconds,
            reasoning_effort=reasoning_effort,
        )
