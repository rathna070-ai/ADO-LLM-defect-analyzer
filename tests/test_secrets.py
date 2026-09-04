"""Credential resolution: environment first, then the OS credential store.

The store is faked rather than exercised for real — a test that wrote to
Windows Credential Manager or the developer's Keychain would leave residue on
the machine running it, and the contract worth pinning here is the resolution
order, not the backend.
"""

from __future__ import annotations

import pytest

from ado_defect_analysis import secrets as secrets_module


class FakeKeyring:
    """Stand-in for the keyring module: same three functions, in a dict."""

    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self.store = dict(initial or {})

    def get_password(self, service: str, name: str) -> str | None:
        return self.store.get(f"{service}:{name}")

    def set_password(self, service: str, name: str, value: str) -> None:
        self.store[f"{service}:{name}"] = value

    def delete_password(self, service: str, name: str) -> None:
        del self.store[f"{service}:{name}"]


@pytest.fixture()
def fake_store(monkeypatch: pytest.MonkeyPatch) -> FakeKeyring:
    fake = FakeKeyring()
    monkeypatch.setattr(secrets_module, "_keyring", lambda: fake)
    for name in secrets_module.MANAGED_SECRETS:
        monkeypatch.delenv(name, raising=False)
    return fake


def test_environment_wins_over_the_store(fake_store: FakeKeyring, monkeypatch: pytest.MonkeyPatch):
    """A container or CI job injects a credential without touching the host."""
    secrets_module.set_secret("GROQ_API_KEY", "from-store")
    monkeypatch.setenv("GROQ_API_KEY", "from-env")

    assert secrets_module.get_secret("GROQ_API_KEY") == "from-env"


def test_falls_back_to_the_store_when_the_environment_is_empty(fake_store: FakeKeyring):
    secrets_module.set_secret("GROQ_API_KEY", "from-store")

    assert secrets_module.get_secret("GROQ_API_KEY") == "from-store"


def test_missing_everywhere_returns_the_default(fake_store: FakeKeyring):
    assert secrets_module.get_secret("GROQ_API_KEY") == ""
    assert secrets_module.get_secret("GROQ_API_KEY", "fallback") == "fallback"


def test_clear_removes_the_stored_value(fake_store: FakeKeyring):
    secrets_module.set_secret("ADO_PAT", "pat-value")

    assert secrets_module.clear_secret("ADO_PAT") is True
    assert secrets_module.get_secret("ADO_PAT") == ""
    # Clearing something that was never stored is not an error.
    assert secrets_module.clear_secret("ADO_PAT") is False


def test_status_reports_the_source_but_never_the_value(
    fake_store: FakeKeyring, monkeypatch: pytest.MonkeyPatch
):
    """`secrets status` is meant to be safe to run with someone watching."""
    secrets_module.set_secret("GROQ_API_KEY", "gsk_secret_value")
    monkeypatch.setenv("ADO_PAT", "pat_secret_value")

    status = secrets_module.secret_status()

    assert status["GROQ_API_KEY"] == "credential store (16 chars)"
    assert status["ADO_PAT"] == "environment (16 chars)"
    assert status["AZURE_API_KEY"] == "not set"
    rendered = " ".join(status.values())
    assert "gsk_secret_value" not in rendered
    assert "pat_secret_value" not in rendered


def test_no_backend_degrades_to_environment_only(monkeypatch: pytest.MonkeyPatch):
    """Headless CI has no credential store; that must not break a run."""
    monkeypatch.setattr(secrets_module, "_keyring", lambda: None)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    assert secrets_module.get_secret("GROQ_API_KEY") == ""
    assert secrets_module.clear_secret("GROQ_API_KEY") is False
    with pytest.raises(RuntimeError, match="No OS credential store"):
        secrets_module.set_secret("GROQ_API_KEY", "value")


def test_a_broken_backend_does_not_take_down_the_run(monkeypatch: pytest.MonkeyPatch):
    """A locked or failing store should fall through, not raise mid-pipeline."""

    class Broken(FakeKeyring):
        def get_password(self, service: str, name: str) -> str | None:
            raise OSError("credential store unavailable")

    monkeypatch.setattr(secrets_module, "_keyring", lambda: Broken())
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    assert secrets_module.get_secret("GROQ_API_KEY", "fallback") == "fallback"


def test_config_resolves_credentials_through_the_store(
    fake_store: FakeKeyring, monkeypatch: pytest.MonkeyPatch
):
    """The point of the feature: a blank .env still yields a working config."""
    import dotenv

    from ado_defect_analysis.config import Config

    # from_env() loads the repo's real .env, which on a developer machine still
    # holds keys — exactly the file this feature exists to empty. Stub the load
    # so the test sees the blank-.env state it is describing.
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)
    monkeypatch.delenv("GROQ_API_KEYS", raising=False)
    secrets_module.set_secret("GROQ_API_KEY", "gsk_from_store")
    secrets_module.set_secret("ADO_PAT", "pat_from_store")

    config = Config.from_env()

    assert config.llm.groq_api_key == "gsk_from_store"
    assert config.llm.groq_api_keys == ["gsk_from_store"]
    assert config.ado.pat == "pat_from_store"
