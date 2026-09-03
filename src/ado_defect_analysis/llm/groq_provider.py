"""Groq chat-completions provider.

Uses Groq's OpenAI-compatible REST API directly via `requests` rather than the
`groq` SDK, so the only dependency this provider needs is one the project
already has. Everything but the endpoint and the error wording is shared with
the other OpenAI-compatible providers — see `openai_compatible.py`.
"""

from __future__ import annotations

from .openai_compatible import OpenAiCompatibleProvider


class GroqProvider(OpenAiCompatibleProvider):
    provider_name = "Groq"
    api_key_env_var = "GROQ_API_KEY"
