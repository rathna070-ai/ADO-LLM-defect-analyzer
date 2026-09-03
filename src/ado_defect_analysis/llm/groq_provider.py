"""Groq chat-completions provider.

Uses Groq's OpenAI-compatible REST API directly via `requests` rather than
the `groq` SDK, so the only new dependency this provider needs is one the
project already has. Groq's JSON mode (`response_format: json_object`)
guarantees syntactically valid JSON but not conformance to a specific
schema, so the schema is embedded in the prompt and the caller
(`pipeline/categorize.py`) validates the result.
"""

from __future__ import annotations

import json
from typing import Any

from ..http import build_retrying_session
from .base import LlmProvider, LlmProviderError


class GroqProvider(LlmProvider):
    def __init__(self, api_key: str, model: str, base_url: str, timeout_seconds: int = 60):
        if not api_key:
            raise LlmProviderError(
                "GROQ_API_KEY is not set. Add it to .env or export it before running the pipeline."
            )
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        # Retries honour Groq's Retry-After on 429, which doubles as the
        # rate-limit pacing a long categorize run needs.
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
        max_tokens: int = 2048,
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
                f"Groq request failed ({response.status_code}): {response.text[:500]}"
            )

        body = response.json()
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise LlmProviderError(f"Unexpected Groq response shape: {body}") from exc

        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise LlmProviderError(f"Groq did not return valid JSON: {content[:500]}") from exc
