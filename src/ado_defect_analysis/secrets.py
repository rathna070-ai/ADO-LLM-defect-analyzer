"""Resolve credentials from the OS credential store, not a plaintext file.

What this does and does not buy you, stated plainly: the process has to present
the key to the provider's API in plaintext, so it must be able to recover it at
runtime. Nothing here makes a key unrecoverable — any scheme that let the app
decrypt unattended would keep the decryption material next to the ciphertext,
which is obfuscation rather than security.

What it does change is *where the key sits at rest*. In the OS store it is
encrypted under the user account (DPAPI on Windows, Keychain on macOS, Secret
Service on Linux) instead of readable by anything that can open a file in the
project directory. That removes the realistic failure modes: a key committed by
accident, copied out with the folder, caught in a backup, or read over a shared
screen. It does not defend against code already running as you.

Resolution order is environment first, then the store. Environment wins so a
container or CI job can inject a credential without touching the host's
keyring, while a developer machine can keep `.env` free of secrets entirely.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

#: Namespace the credentials are filed under in the OS store.
SERVICE_NAME = "ado-defect-analysis"

#: The credentials this project knows how to store, by the env var they mirror.
MANAGED_SECRETS = ("GROQ_API_KEY", "AZURE_API_KEY", "ADO_PAT")


def _keyring():
    """The keyring module, or None when it or a backend is unavailable.

    Optional on purpose: CI containers and headless Linux often have no
    backend, and a missing credential store should degrade to environment-only
    resolution rather than breaking the run.
    """
    try:
        import keyring
        from keyring.backends.fail import Keyring as FailBackend
    except ImportError:
        return None
    try:
        if isinstance(keyring.get_keyring(), FailBackend):
            return None
    except Exception:  # pragma: no cover - backend probing is platform-specific
        return None
    return keyring


def get_secret(name: str, default: str = "") -> str:
    """Read a credential: environment first, then the OS credential store."""
    value = os.environ.get(name, "")
    if value:
        return value

    keyring = _keyring()
    if keyring is None:
        return default
    try:
        stored = keyring.get_password(SERVICE_NAME, name)
    except Exception as exc:  # pragma: no cover - depends on the OS backend
        logger.warning("Could not read %s from the credential store: %s", name, exc)
        return default
    return stored or default


def set_secret(name: str, value: str) -> None:
    """Store a credential in the OS credential store."""
    keyring = _keyring()
    if keyring is None:
        raise RuntimeError(
            "No OS credential store is available here. Install the `keyring` extra "
            '(pip install -e ".[secrets]") on a desktop OS, or keep using environment '
            "variables."
        )
    keyring.set_password(SERVICE_NAME, name, value)


def clear_secret(name: str) -> bool:
    """Remove a credential. Returns False when there was nothing stored."""
    keyring = _keyring()
    if keyring is None:
        return False
    try:
        keyring.delete_password(SERVICE_NAME, name)
    except Exception:
        return False
    return True


def secret_status() -> dict[str, str]:
    """Where each managed credential is coming from — for `secrets` in the CLI.

    Never returns a value, only its source and length, so the command is safe
    to run with someone watching.
    """
    keyring = _keyring()
    status: dict[str, str] = {}
    for name in MANAGED_SECRETS:
        if os.environ.get(name):
            status[name] = f"environment ({len(os.environ[name])} chars)"
        elif keyring is not None and keyring.get_password(SERVICE_NAME, name):
            stored = keyring.get_password(SERVICE_NAME, name) or ""
            status[name] = f"credential store ({len(stored)} chars)"
        else:
            status[name] = "not set"
    return status
