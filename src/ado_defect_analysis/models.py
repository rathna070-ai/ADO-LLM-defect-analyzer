"""Plain data shapes shared across the pipeline stages."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Any


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
    closed_date: str | None
    tags: str = ""
    comments: str = ""
    iteration_path: str = ""
    resolution: str = ""
    # Fields common in customized ADO bug templates. Captured because they
    # carry RCA signal the model would otherwise have to guess at: the team's
    # own SDLC phase, and where the defect was introduced vs found (which is
    # what makes leakage measurable).
    sdlc_phase_raw: str = ""
    environment: str = ""
    found_in_environment: str = ""
    introduced_in_month: str = ""
    introduced_in_year: str = ""
    user_impact: str = ""
    parent: str = ""
    work_item_type: str = ""
    # Which upload this defect arrived in. Defects still upsert by id, so a
    # re-upload re-stamps the row with the newer source — the question these
    # answer is "which batch does this belong to now", not "every batch it has
    # ever appeared in".
    source_name: str = ""
    source_uploaded_at: str = ""

    @classmethod
    def from_work_item(
        cls, item: dict[str, Any], root_cause_field: str, comments: str = ""
    ) -> Defect:
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
    """Structured LLM judgment for one defect.

    Mirrors schemas/categorize_defect.schema.json.
    """

    defect_id: int
    root_cause_category: str
    testing_gap_flag: bool
    summary: str
    confidence: float
    sdlc_phase: str = "unknown"
    # Which fields the model says drove the call — makes a low-confidence
    # judgment reviewable instead of opaque.
    evidence: str = ""
    # Provenance: which model and prompt revision produced this judgment, and
    # when. Without these, a stored categorization can't be audited or
    # selectively re-run after a prompt or model change.
    model: str = ""
    prompt_version: str = ""
    categorized_at: str = ""
    # Fingerprint of the defect fields sent to the model, so a re-run can tell
    # whether anything it saw actually changed.
    input_hash: str = ""


def strip_html(value: str) -> str:
    """ADO rich-text fields come back as HTML; keep the categorization prompt free of markup noise.

    Entities are unescaped after tag removal so `&nbsp;` and `&amp;` reach the
    LLM as real characters instead of literal markup noise.
    """
    text = re.sub(r"<[^>]+>", " ", value or "")
    text = html.unescape(text)
    # unescape turns &nbsp; into U+00A0, which \s only matches under re.UNICODE
    # on str (it does) — but normalize it explicitly so the collapse is total.
    text = text.replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()
