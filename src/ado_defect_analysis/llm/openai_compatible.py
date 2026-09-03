"""Shared transport for OpenAI-compatible chat-completions APIs.

Groq and GitHub Models both speak the OpenAI chat-completions dialect, so the
request shape, JSON-mode handling, error wrapping, and usage accounting are
identical between them — only the endpoint, the model, and the wording of the
"no API key" message differ. Subclasses supply those three things.

JSON mode guarantees syntactically valid JSON but not schema conformance, so
the schema is embedded in the prompt and the caller
(`pipeline/categorize.py`) validates the result.
"""

from __future__ import annotations

import json
from typing import Any

from ..http import build_retrying_session
from .base import LlmProvider, LlmProviderError


class OpenAiCompatibleProvider(LlmProvider):
    #: Name used in error messages, e.g. "Groq request failed (429)".
    provider_name: str = "LLM"
    #: Env var named when the key is missing.
    api_key_env_var: str = "API_KEY"

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        timeout_seconds: int = 60,
        reasoning_effort: str = "",
    ):
        super().__init__()
        if not api_key:
            raise LlmProviderError(
                f"{self.api_key_env_var} is not set. Add it to .env or export it "
                "before running the pipeline."
            )
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._reasoning_effort = reasoning_effort
        # Retries honour the provider's Retry-After on 429, which doubles as
        # the rate-limit pacing a long categorize run needs.
        self._session = build_retrying_session()

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
        schema_instruction = (
            "Respond with a single JSON object only, no prose, matching this shape:\n"
            f"{json.dumps(schema, indent=2)}"
        )
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": f"{system_prompt}\n\n{schema_instruction}"},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        # Only reasoning models accept this; sending it to one that doesn't
        # is a 400, so an empty setting omits it entirely.
        if self._reasoning_effort:
            payload["reasoning_effort"] = self._reasoning_effort

        response = self._session.post(
            f"{self._base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self._timeout_seconds,
        )
        if response.status_code != 200:
            raise LlmProviderError(
                f"{self.provider_name} request failed ({response.status_code}): "
                f"{response.text[:500]}"
            )

        body = response.json()
        self.usage.add(body.get("usage"))
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise LlmProviderError(
                f"Unexpected {self.provider_name} response shape: {body}"
            ) from exc

        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise LlmProviderError(
                f"{self.provider_name} did not return valid JSON: {content[:500]}"
            ) from exc
