"""Turn an Azure DevOps query URL — the thing someone copies out of their
browser — into the organization, project, and query reference the REST API
needs.

Users paste whatever the address bar shows, so this accepts the shapes ADO
actually produces: the modern `dev.azure.com/{org}/{project}` host, the legacy
`{org}.visualstudio.com/{project}` one, both the read (`query`) and edit
(`query-edit`) routes, and a query addressed either by GUID or by its folder
path ("Shared Queries/Escaped Defects").
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

_GUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def is_query_guid(value: str) -> bool:
    """True if `value` is an ADO query GUID rather than a folder path."""
    return bool(_GUID.match(value or ""))


class AdoQueryUrlError(ValueError):
    """The pasted text isn't a query URL we can make sense of."""


@dataclass(frozen=True)
class AdoQueryRef:
    """Where a saved query lives. Exactly one of id/path is set."""

    organization: str
    project: str
    query_id: str | None = None
    query_path: str | None = None

    @property
    def identifier(self) -> str:
        """What the WIQL endpoint accepts in place of a query id."""
        return self.query_id or (self.query_path or "")


def parse_query_url(url: str) -> AdoQueryRef:
    """Parse an ADO saved-query URL.

    Raises `AdoQueryUrlError` with a message aimed at whoever pasted it,
    since this runs behind a text box in the UI.
    """
    text = (url or "").strip()
    if not text:
        raise AdoQueryUrlError("Paste an Azure DevOps query URL.")
    if "://" not in text:
        text = f"https://{text}"

    parsed = urlparse(text)
    host = (parsed.hostname or "").lower()
    segments = [unquote(s) for s in parsed.path.split("/") if s]

    if host.endswith("visualstudio.com"):
        # https://{org}.visualstudio.com/{project}/_queries/...
        organization = host.split(".", 1)[0]
        remaining = segments
    elif host == "dev.azure.com" or host.endswith(".dev.azure.com"):
        # https://dev.azure.com/{org}/{project}/_queries/...
        if len(segments) < 2:
            raise AdoQueryUrlError(
                "That URL is missing the organization and project. Expected something like "
                "https://dev.azure.com/your-org/your-project/_queries/query/<id>."
            )
        organization, remaining = segments[0], segments[1:]
    else:
        raise AdoQueryUrlError(
            f"Unrecognized Azure DevOps host '{parsed.hostname or text}'. Expected a "
            "dev.azure.com or *.visualstudio.com URL."
        )

    if not remaining:
        raise AdoQueryUrlError("That URL is missing the project name.")
    project, rest = remaining[0], remaining[1:]

    # An explicit ?path= wins — ADO uses it on some query routes.
    path_param = parse_qs(parsed.query).get("path", [None])[0]
    if path_param:
        return AdoQueryRef(organization, project, query_path=unquote(path_param).strip("/"))

    # Everything after the _queries/query[-edit] marker identifies the query.
    tail: list[str] = []
    for index, segment in enumerate(rest):
        if segment.lower() in ("query", "query-edit"):
            tail = rest[index + 1 :]
            break
    else:
        # No marker: tolerate a bare ".../_queries/<guid>" style tail.
        tail = [s for s in rest if s.lower() != "_queries"]

    tail = [s for s in tail if s]
    if not tail:
        raise AdoQueryUrlError(
            "Couldn't find a query id or path in that URL. Open the query in Azure DevOps "
            "and copy the address bar — it should look like "
            "https://dev.azure.com/your-org/your-project/_queries/query/<id>."
        )

    if len(tail) == 1 and is_query_guid(tail[0]):
        return AdoQueryRef(organization, project, query_id=tail[0])
    return AdoQueryRef(organization, project, query_path="/".join(tail))
