"""Placeholder for a future GitHub Copilot-backed provider.

Not implemented yet — there's no `COPILOT_API_KEY` to test against, and
Copilot's inference surface (GitHub Models API / Copilot Chat extensibility)
isn't finalized in this project. This class exists so `LLM_PROVIDER=copilot`
is already a legal config value: the factory wires it up, `Config` already
has `copilot_api_key` / `copilot_model` fields, and switching away from Groq
later means implementing `complete_json` here, not touching any pipeline
code.

When implementing this for real:
  - GitHub Models API (https://docs.github.com/en/github-models) exposes an
    OpenAI-compatible chat completions endpoint, so the shape of this class
    should end up close to `GroqProvider`.
  - Keep the same `complete_json(system_prompt, user_prompt, schema, ...)`
    signature so no caller needs to change.
"""

from __future__ import annotations

from typing import Any

from .base import LlmProvider, LlmProviderError


class CopilotProvider(LlmProvider):
    def __init__(self, api_key: str, model: str, timeout_seconds: int = 60):
        super().__init__()
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds

    @property
    def model_name(self) -> str:
        return self._model

    def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any],
        temperature: float = 0.0,
        max_tokens: int = 5120,
    ) -> dict[str, Any]:
        raise LlmProviderError(
            "LLM_PROVIDER=copilot is reserved for a future Copilot/GitHub Models "
            "integration and is not implemented yet. Set LLM_PROVIDER=groq (with "
            "GROQ_API_KEY) to run the pipeline today."
        )
