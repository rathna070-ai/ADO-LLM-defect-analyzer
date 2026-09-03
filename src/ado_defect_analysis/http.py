"""Shared HTTP session factory with retry/backoff.

Both network clients in this project — the ADO REST client and the Groq
provider — are batch jobs that run unattended against rate-limited APIs, so a
single 429 or a transient 503 shouldn't lose a run's work. `urllib3`'s `Retry`
ships with `requests`, so this costs no new dependency.

`respect_retry_after_header` is what makes this double as rate-limit pacing:
Groq returns `Retry-After` on 429, and urllib3 will wait exactly that long
rather than guessing with the backoff curve.
"""

from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Retried statuses: rate limiting plus the transient 5xx family. 4xx other than
# 429 are the caller's fault and fail fast.
_RETRY_STATUSES = (429, 500, 502, 503, 504)


def build_retrying_session(
    total_retries: int = 3,
    backoff_factor: float = 1.0,
    auth: tuple[str, str] | None = None,
) -> requests.Session:
    """A `requests.Session` that retries transient failures with backoff."""
    retry = Retry(
        total=total_retries,
        status_forcelist=_RETRY_STATUSES,
        backoff_factor=backoff_factor,
        respect_retry_after_header=True,
        raise_on_status=False,
        # POST is included deliberately: every POST this project makes is a
        # read-only query (ADO WIQL, ADO work-item batch read, Groq chat
        # completion), so retrying one can't double-write anything.
        allowed_methods=frozenset({"GET", "POST"}),
    )
    adapter = HTTPAdapter(max_retries=retry)

    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    if auth is not None:
        session.auth = auth
    return session
