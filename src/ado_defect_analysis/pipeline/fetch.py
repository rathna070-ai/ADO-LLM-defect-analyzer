"""Phase 1: get closed defects into SQLite, from Azure DevOps directly or
from a hand-exported Excel/CSV extract.

Two entrypoints, one storage step: `run_fetch` talks to the ADO REST API
(needs ADO_ORGANIZATION/ADO_PROJECT/ADO_PAT); `run_fetch_from_excel` reads a
local file someone exported from ADO themselves and needs no ADO credentials
at all. Both end by calling `DefectStore.upsert_defects`, so `categorize`,
`report`, and `export` don't know or care which path a defect came in
through.
"""

from __future__ import annotations

import dataclasses
import logging
from pathlib import Path

from ..ado_client import AdoClient
from ..ado_query import parse_query_url
from ..config import Config
from ..excel_source import parse_excel
from ..storage import DefectStore

logger = logging.getLogger(__name__)


def run_fetch_from_query(config: Config, query_url: str, pat: str | None = None) -> int:
    """Pull the results of a saved ADO query. Returns the count stored.

    The organization and project come from the URL rather than `.env`, so
    someone can point this at any project their token can read without
    editing config. `pat` overrides the configured token, which is what the
    UI passes when the user types one in rather than storing it on disk.
    """
    ref = parse_query_url(query_url)
    ado = dataclasses.replace(
        config.ado,
        organization=ref.organization,
        project=ref.project,
        pat=pat or config.ado.pat,
    )

    client = AdoClient(ado)
    defects = client.fetch_defects_for_query(ref.identifier)

    store = DefectStore(config.db_path)
    store.upsert_defects(defects)

    logger.info(
        "Fetched and stored %d defects from query %s in %s/%s.",
        len(defects),
        ref.identifier,
        ref.organization,
        ref.project,
    )
    return len(defects)


def run_fetch(config: Config) -> int:
    """Pull closed defects from the Azure DevOps REST API. Returns the count stored."""
    client = AdoClient(config.ado)
    store = DefectStore(config.db_path)

    defects = client.fetch_closed_defects()
    store.upsert_defects(defects)

    logger.info("Fetched and stored %d defects from Azure DevOps.", len(defects))
    return len(defects)


def run_fetch_from_excel(
    config: Config, file_path: Path, column_map: dict[str, list[str]] | None = None
) -> int:
    """Load defects from an ADO Excel/CSV export. Returns the count stored.

    No ADO API access required — this is the path for environments that
    won't issue a PAT, or when someone already has the export in hand.
    """
    store = DefectStore(config.db_path)

    defects = parse_excel(file_path, column_map=column_map)
    store.upsert_defects(defects)

    logger.info("Loaded and stored %d defects from %s.", len(defects), file_path)
    return len(defects)
