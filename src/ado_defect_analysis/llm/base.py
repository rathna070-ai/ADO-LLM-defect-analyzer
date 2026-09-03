"""Provider-agnostic LLM interface.

Every pipeline stage that calls an LLM (categorization, narrative summary)
codes against `LlmProvider`, never against Groq or Copilot directly. Swapping
the backend — or falling back to a second one when the first has no key — is
a config change (`LLM_PROVIDER`), not a code change. See `factory.py`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LlmProviderError(RuntimeError):
    """Raised when a provider can't produce a usable structured response."""


class LlmProvider(ABC):
    @abstractmethod
    def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any],
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> dict[str, Any]:
        """Send a prompt and return a dict matching `schema`.

        Implementations are responsible for asking the underlying model for
        JSON, parsing the response, and raising `LlmProviderError` if the
        result can't be parsed as JSON. Schema *validation* against a JSON
        Schema document is the caller's job (see `pipeline/categorize.py`),
        since not every provider can enforce a schema server-side.
        """
        raise NotImplementedError
