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
from datetime import datetime, timezone
from pathlib import Path

from ..ado_client import AdoClient
from ..ado_query import parse_query_url
from ..config import Config
from ..excel_source import parse_excel
from ..models import Defect
from ..storage import DefectStore

logger = logging.getLogger(__name__)


def _stamp_source(defects: list[Defect], source_name: str) -> None:
    """Tag a batch with where it came from, so uploads stay distinguishable."""
    uploaded_at = datetime.now(timezone.utc).isoformat()
    for defect in defects:
        defect.source_name = source_name
        defect.source_uploaded_at = uploaded_at


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
    _stamp_source(defects, f"{ref.project} query {ref.identifier}")

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
    _stamp_source(defects, f"{config.ado.project} API fetch")
    store.upsert_defects(defects)

    logger.info("Fetched and stored %d defects from Azure DevOps.", len(defects))
    return len(defects)


def run_fetch_from_excel(
    config: Config,
    file_path: Path,
    column_map: dict[str, list[str]] | None = None,
    source_name: str | None = None,
) -> int:
    """Load defects from an ADO Excel/CSV export. Returns the count stored.

    No ADO API access required — this is the path for environments that
    won't issue a PAT, or when someone already has the export in hand.

    `source_name` labels the batch; the UI passes the user's original filename
    because the file itself lands in a temp path with a generated name.
    """
    store = DefectStore(config.db_path)

    defects = parse_excel(file_path, column_map=column_map)
    _stamp_source(defects, source_name or file_path.name)
    store.upsert_defects(defects)

    logger.info("Loaded and stored %d defects from %s.", len(defects), file_path)
    return len(defects)
