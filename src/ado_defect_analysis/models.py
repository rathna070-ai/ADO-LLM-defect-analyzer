"""Plain data shapes shared across the pipeline stages."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class Defect:
    """One work item pulled from Azure DevOps, before LLM categorization."""

    id: int
    title: str
    description: str
    module: str
    severity: str
    state: str
    resolution_notes: str
    root_cause_raw: str
    created_date: str
    closed_date: Optional[str]
    tags: str = ""
    comments: str = ""
    iteration_path: str = ""
    resolution: str = ""

    @classmethod
    def from_work_item(
        cls, item: dict[str, Any], root_cause_field: str, comments: str = ""
    ) -> "Defect":
        fields = item.get("fields", {})
        return cls(
            id=item["id"],
            title=fields.get("System.Title", ""),
            description=strip_html(fields.get("System.Description", "")),
            module=fields.get("System.AreaPath", ""),
            severity=fields.get("Microsoft.VSTS.Common.Severity", ""),
            state=fields.get("System.State", ""),
            resolution_notes=strip_html(fields.get("System.History", "")),
            root_cause_raw=fields.get(root_cause_field, ""),
            created_date=fields.get("System.CreatedDate", ""),
            closed_date=fields.get("Microsoft.VSTS.Common.ClosedDate"),
            tags=fields.get("System.Tags", ""),
            comments=comments,
            iteration_path=fields.get("System.IterationPath", ""),
            resolution=fields.get("Microsoft.VSTS.Common.ResolvedReason", ""),
        )


@dataclass
class DefectCategorization:
    """Structured LLM judgment for a single defect. Mirrors schemas/categorize_defect.schema.json."""

    defect_id: int
    root_cause_category: str
    testing_gap_flag: bool
    summary: str
    confidence: float
    sdlc_phase: str = "unknown"


def strip_html(value: str) -> str:
    """ADO rich-text fields come back as HTML; keep the categorization prompt free of markup noise."""
    text = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", text).strip()
