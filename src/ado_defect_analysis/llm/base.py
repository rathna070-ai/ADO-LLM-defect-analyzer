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


class TokenUsage:
    """Running token total across the calls one provider instance has made.

    Kept on the provider rather than threaded through every `complete_json`
    return value, so adding usage tracking didn't change the call signature
    every pipeline stage codes against.
    """

    def __init__(self) -> None:
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.calls = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def add(self, usage: dict[str, Any] | None) -> None:
        """Accumulate one response's `usage` block, tolerating its absence."""
        self.calls += 1
        if not usage:
            return
        self.prompt_tokens += int(usage.get("prompt_tokens") or 0)
        self.completion_tokens += int(usage.get("completion_tokens") or 0)

    def cost_estimate(self, input_per_mtok: float, output_per_mtok: float) -> float:
        return (
            self.prompt_tokens * input_per_mtok + self.completion_tokens * output_per_mtok
        ) / 1_000_000

    def summary(self, input_per_mtok: float = 0.0, output_per_mtok: float = 0.0) -> str:
        line = (
            f"{self.calls} LLM call(s), {self.prompt_tokens:,} prompt + "
            f"{self.completion_tokens:,} completion = {self.total_tokens:,} tokens"
        )
        if input_per_mtok or output_per_mtok:
            line += f", est. ${self.cost_estimate(input_per_mtok, output_per_mtok):.4f}"
        return line


class LlmProvider(ABC):
    def __init__(self) -> None:
        self.usage = TokenUsage()

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Identifier of the model behind this provider, recorded as provenance.

        Stored on every categorization so results stay traceable to the model
        that produced them across model upgrades.
        """
        raise NotImplementedError

    @abstractmethod
    def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any],
        temperature: float = 0.0,
        max_tokens: int = 5120,
    ) -> dict[str, Any]:
        """Send a prompt and return a dict matching `schema`.

        Implementations are responsible for asking the underlying model for
        JSON, parsing the response, and raising `LlmProviderError` if the
        result can't be parsed as JSON. Schema *validation* against a JSON
        Schema document is the caller's job (see `pipeline/categorize.py`),
        since not every provider can enforce a schema server-side.
        """
        raise NotImplementedError
