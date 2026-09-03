"""Azure DevOps REST client: WIQL query for closed defects, then a batch
work-item fetch for the fields we need.

Kept deliberately thin — no pagination beyond what WIQL already returns in one
shot (ADO caps WIQL results at 20,000 work item ids, which is far beyond what a
single fetch run needs). If this ever needs to run against a project large
enough to hit that cap, split the query by date range rather than adding
pagination here. Retry/backoff comes from the shared session in `http.py`.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import requests

from .ado_query import is_query_guid
from .config import AdoConfig
from .http import build_retrying_session
from .models import Defect

_DEFAULT_FIELDS = [
    "System.Id",
    "System.Title",
    "System.Description",
    "System.AreaPath",
    "System.IterationPath",
    "System.State",
    "System.CreatedDate",
    "System.History",
    "System.Tags",
    "Microsoft.VSTS.Common.Severity",
    "Microsoft.VSTS.Common.ClosedDate",
    "Microsoft.VSTS.Common.ResolvedReason",
]


class AdoClientError(RuntimeError):
    pass


class AdoClient:
    def __init__(self, config: AdoConfig):
        if not config.organization or not config.project or not config.pat:
            raise AdoClientError(
                "ADO_ORGANIZATION, ADO_PROJECT, and ADO_PAT must all be set to query Azure DevOps."
            )
        self._config = config
        self._session = build_retrying_session(auth=("", config.pat))
        self._timeout = config.request_timeout_seconds

    def fetch_closed_defects(self) -> list[Defect]:
        ids = self._query_work_item_ids()
        if not ids:
            return []
        items = self._fetch_work_items(ids)
        root_cause_field = self._config.root_cause_field
        return [
            Defect.from_work_item(
                item,
                root_cause_field,
                comments=(
                    self._fetch_comment_text(item["id"]) if self._config.fetch_comments else ""
                ),
            )
            for item in items
        ]

    def fetch_defects_for_query(self, query: str) -> list[Defect]:
        """Run a saved ADO query by GUID or folder path and return its results.

        The alternative to `fetch_closed_defects`, which composes its own WIQL
        from config. Here the query already encodes what the team considers in
        scope, so nothing is filtered further — what the query returns is what
        gets analyzed.
        """
        query_id = query if is_query_guid(query) else self._resolve_query_id(query)
        url = f"{self._config.base_url}/wit/wiql/{query_id}?api-version={self._config.api_version}"
        response = self._session.get(url, timeout=self._timeout)
        self._raise_for_status(response, f"saved query '{query}'")

        payload = response.json()
        # A flat query returns workItems; a tree/one-hop query returns
        # workItemRelations with the item under `target`.
        ids = [item["id"] for item in payload.get("workItems", [])]
        if not ids:
            ids = [
                relation["target"]["id"]
                for relation in payload.get("workItemRelations", [])
                if relation.get("target")
            ]
        if not ids:
            return []

        items = self._fetch_work_items(list(dict.fromkeys(ids)))
        root_cause_field = self._config.root_cause_field
        return [
            Defect.from_work_item(
                item,
                root_cause_field,
                comments=(
                    self._fetch_comment_text(item["id"]) if self._config.fetch_comments else ""
                ),
            )
            for item in items
        ]

    def _resolve_query_id(self, query_path: str) -> str:
        """Look up a query's GUID from its folder path."""
        url = (
            f"{self._config.base_url}/wit/queries/{quote(query_path)}"
            f"?api-version={self._config.api_version}"
        )
        response = self._session.get(url, timeout=self._timeout)
        self._raise_for_status(response, f"query lookup for '{query_path}'")
        query_id = response.json().get("id")
        if not query_id:
            raise AdoClientError(f"Azure DevOps returned no id for query '{query_path}'.")
        return str(query_id)

    def _fetch_comment_text(self, work_item_id: int) -> str:
        """One request per work item — ADO has no batch endpoint for comments.

        Off by default (ADO_FETCH_COMMENTS=false) because it turns an N-defect
        fetch into N+1 requests; turn it on for smaller pulls where comment
        threads add real signal, or use the Excel import path instead, which
        carries comments at no extra API cost.
        """
        url = (
            f"{self._config.base_url}/wit/workItems/{work_item_id}/comments"
            f"?api-version={self._config.api_version}-preview.4"
        )
        response = self._session.get(url, timeout=self._timeout)
        if response.status_code >= 400:
            return ""
        comments = response.json().get("comments", [])
        return " | ".join(c.get("text", "") for c in comments if c.get("text"))

    def _query_work_item_ids(self) -> list[int]:
        wiql = self._build_wiql()
        url = f"{self._config.base_url}/wit/wiql?api-version={self._config.api_version}"
        response = self._session.post(url, json={"query": wiql}, timeout=self._timeout)
        self._raise_for_status(response, "WIQL query")
        work_items = response.json().get("workItems", [])
        return [item["id"] for item in work_items]

    def _fetch_work_items(self, ids: list[int]) -> list[dict[str, Any]]:
        url = f"{self._config.base_url}/wit/workitemsbatch?api-version={self._config.api_version}"
        fields = [*_DEFAULT_FIELDS, self._config.root_cause_field]
        items: list[dict[str, Any]] = []
        for chunk_start in range(0, len(ids), self._config.batch_size):
            chunk = ids[chunk_start : chunk_start + self._config.batch_size]
            response = self._session.post(
                url, json={"ids": chunk, "fields": fields}, timeout=self._timeout
            )
            self._raise_for_status(response, "work item batch fetch")
            items.extend(response.json().get("value", []))
        return items

    def _build_wiql(self) -> str:
        conditions = [
            f"[System.WorkItemType] = '{self._config.work_item_type}'",
            "[System.State] IN ('Closed', 'Resolved', 'Done')",
            f"[System.ChangedDate] >= @Today - {self._config.lookback_days}",
        ]
        if self._config.area_path:
            conditions.append(f"[System.AreaPath] UNDER '{self._config.area_path}'")
        where_clause = " AND ".join(conditions)
        return (
            "SELECT [System.Id] FROM WorkItems "
            f"WHERE {where_clause} "
            "ORDER BY [System.ChangedDate] DESC"
        )

    @staticmethod
    def _raise_for_status(response: requests.Response, action: str) -> None:
        if response.status_code >= 400:
            raise AdoClientError(
                f"ADO {action} failed ({response.status_code}): {response.text[:500]}"
            )
