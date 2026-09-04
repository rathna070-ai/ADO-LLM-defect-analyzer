"""Alternate defect input: an Excel extract exported from Azure DevOps by hand.

Some environments won't hand out a PAT with API read access, or the person
running this pipeline just has "Open in Excel" / a saved ADO query exported
to .xlsx. This module is the second way defects get in: no org, project, or
PAT needed — just a spreadsheet with the usual ADO work-item columns,
including Tags and, if the export was configured to include them, Comments.

Column names in ADO exports vary by which query/view produced them (raw
field reference names like "System.Title" vs. display names like "Title").
`_COLUMN_SYNONYMS` matches on either, case-insensitively, so a typical export
works with no configuration; pass `column_map` to override or extend it for
an export that names things unusually.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from .models import Defect, strip_html

logger = logging.getLogger(__name__)

# Each target Defect field maps to the column headers ADO is known to export
# it under. First match wins; matching is case-insensitive and ignores
# surrounding whitespace.
#
# Only vendor-standard headers belong here. Organisations that prefix their
# custom fields (a "XX_Root Cause" convention, say) should add those through
# EXCEL_COLUMN_MAP rather than editing this list, so a deployment's internal
# field naming stays out of the repository.
_COLUMN_SYNONYMS: dict[str, list[str]] = {
    "id": ["ID", "Work Item Id", "Work Item ID", "System.Id"],
    "title": ["Title", "System.Title"],
    "description": ["Description", "System.Description"],
    "module": ["Area Path", "System.AreaPath", "Module"],
    "iteration_path": ["Iteration Path", "System.IterationPath", "Sprint"],
    "severity": ["Severity", "Microsoft.VSTS.Common.Severity"],
    "state": ["State", "System.State"],
    "resolution": [
        "Disposition",
        "Resolution",
        "Resolved Reason",
        "Microsoft.VSTS.Common.ResolvedReason",
        "Reason",
        "System.Reason",
    ],
    "resolution_notes": ["History", "System.History", "Resolution Notes"],
    "root_cause_raw": ["Root Cause", "Microsoft.VSTS.CMMI.RootCause"],
    "sdlc_phase_raw": ["SDLC", "SDLC Phase", "Phase"],
    "environment": ["Environment"],
    "found_in_environment": [
        "Found in Environment",
        "Found In Environment",
    ],
    "introduced_in_month": ["Introduced In Month"],
    "introduced_in_year": ["Introduced In Year"],
    "user_impact": ["User Impact"],
    "parent": ["Parent", "System.Parent"],
    "work_item_type": ["Work Item Type", "System.WorkItemType"],
    "created_date": ["Created Date", "System.CreatedDate"],
    "closed_date": ["Closed Date", "Microsoft.VSTS.Common.ClosedDate"],
    "tags": ["Tags", "System.Tags"],
    "comments": ["Comments", "Discussion", "Comment"],
}

_REQUIRED_FIELDS = ("id", "title")


class ExcelSourceError(RuntimeError):
    pass


def parse_excel(file_path: Path, column_map: dict[str, list[str]] | None = None) -> list[Defect]:
    """Read an ADO Excel/CSV export and return it as `Defect` objects.

    `column_map` overrides `_COLUMN_SYNONYMS` per field, e.g.
    `{"module": ["Component"]}` for an export that calls area path "Component".
    Fields not listed keep their default synonyms.
    """
    if not file_path.exists():
        raise ExcelSourceError(f"File not found: {file_path}")

    df = _read_table(file_path)
    synonyms = {**_COLUMN_SYNONYMS, **(column_map or {})}
    resolved = _resolve_columns(df.columns, synonyms)

    missing_required = [f for f in _REQUIRED_FIELDS if f not in resolved]
    if missing_required:
        raise ExcelSourceError(
            f"Could not find a column for required field(s) {missing_required} in "
            f"{file_path.name}. Available columns: {list(df.columns)}. "
            "Pass column_map to point at the right header."
        )

    defects: list[Defect] = []
    for _, row in df.iterrows():
        raw_id = _cell(row, resolved, "id")
        if not raw_id:
            continue
        try:
            defect_id = int(float(raw_id))
        except ValueError:
            # Exports often carry a trailing summary/footer row ("Total", a
            # note) in the ID column; skip it rather than failing the import.
            logger.warning("Skipping row with non-numeric ID %r in %s.", raw_id, file_path.name)
            continue
        defects.append(
            Defect(
                id=defect_id,
                title=_cell(row, resolved, "title"),
                description=strip_html(_cell(row, resolved, "description")),
                module=_cell(row, resolved, "module"),
                severity=_cell(row, resolved, "severity"),
                state=_cell(row, resolved, "state"),
                resolution_notes=strip_html(_cell(row, resolved, "resolution_notes")),
                root_cause_raw=_cell(row, resolved, "root_cause_raw"),
                created_date=_cell(row, resolved, "created_date"),
                closed_date=_cell(row, resolved, "closed_date") or None,
                tags=_cell(row, resolved, "tags"),
                comments=strip_html(_cell(row, resolved, "comments")),
                iteration_path=_cell(row, resolved, "iteration_path"),
                resolution=_cell(row, resolved, "resolution"),
                sdlc_phase_raw=_cell(row, resolved, "sdlc_phase_raw"),
                environment=_cell(row, resolved, "environment"),
                found_in_environment=_cell(row, resolved, "found_in_environment"),
                introduced_in_month=_cell(row, resolved, "introduced_in_month"),
                introduced_in_year=_cell(row, resolved, "introduced_in_year"),
                user_impact=_cell(row, resolved, "user_impact"),
                parent=_cell(row, resolved, "parent"),
                work_item_type=_cell(row, resolved, "work_item_type"),
            )
        )
    return defects


def _read_table(file_path: Path) -> pd.DataFrame:
    if file_path.suffix.lower() in (".xlsx", ".xls", ".xlsm"):
        return pd.read_excel(file_path, dtype=str).fillna("")
    if file_path.suffix.lower() == ".csv":
        return pd.read_csv(file_path, dtype=str).fillna("")
    raise ExcelSourceError(f"Unsupported file type: {file_path.suffix}. Use .xlsx or .csv.")


def _resolve_columns(columns: pd.Index, synonyms: dict[str, list[str]]) -> dict[str, str]:
    normalized = {str(c).strip().lower(): c for c in columns}
    resolved: dict[str, str] = {}
    for field, candidates in synonyms.items():
        for candidate in candidates:
            match = normalized.get(candidate.strip().lower())
            if match is not None:
                resolved[field] = match
                break
    return resolved


def _cell(row: pd.Series, resolved: dict[str, str], field: str) -> str:
    column = resolved.get(field)
    if column is None:
        return ""
    value = row[column]
    return "" if pd.isna(value) else str(value).strip()
