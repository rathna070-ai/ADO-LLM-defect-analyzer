"""Leadership KPIs, top-5 contributor tables, and their CAPA actions."""

from __future__ import annotations

import pandas as pd
import pytest

from ado_defect_analysis.capa import actions_for
from ado_defect_analysis.pipeline.aggregate import (
    build_aggregates,
    top_area_contributors,
    top_rca_contributors,
)


def _df() -> pd.DataFrame:
    """Checkout dominates volume; Search carries the rejections."""
    rows = []
    for i in range(6):
        rows.append(
            {
                "id": i,
                "module": "Checkout",
                "iteration_path": "Sprint 1",
                "root_cause_category": "coding_error",
                "sdlc_phase": "development",
                "testing_gap_flag": 1,
                "confidence": 0.9,
                "severity": "1 - Critical" if i < 2 else "3 - Medium",
                "resolution": "Fixed",
                "state": "Closed",
                "closed_date": "2026-01-05",
            }
        )
    for i in range(3):
        rows.append(
            {
                "id": 100 + i,
                "module": "Search",
                "iteration_path": "Sprint 2",
                "root_cause_category": "requirements_gap",
                "sdlc_phase": "requirements",
                "testing_gap_flag": 0,
                "confidence": 0.8,
                "severity": "2 - High",
                "resolution": "Duplicate",
                "state": "Closed",
                "closed_date": "2026-01-20",
            }
        )
    rows.append(
        {
            "id": 200,
            "module": "Payments",
            "iteration_path": "Sprint 2",
            "root_cause_category": "security_defect",
            "sdlc_phase": "production_operations",
            "testing_gap_flag": 0,
            "confidence": 0.95,
            "severity": "1 - Critical",
            "resolution": "Fixed",
            "state": "Closed",
            "closed_date": "2026-02-01",
        }
    )
    df = pd.DataFrame(rows)
    df["closed_date"] = pd.to_datetime(df["closed_date"])
    df["closed_month"] = df["closed_date"].dt.to_period("M").astype(str)
    return df


def test_top_rca_ranks_by_volume_and_names_where_it_concentrates():
    rows = top_rca_contributors(_df())

    assert [r["category"] for r in rows][:2] == ["coding_error", "requirements_gap"]
    top = rows[0]
    assert top["count"] == 6
    assert top["share"] == pytest.approx(0.6)
    assert top["top_area"] == "Checkout"
    assert top["top_area_count"] == 6


def test_every_top_rca_row_carries_a_corrective_and_preventive_action():
    """A count without a recommended control doesn't answer 'so what do we do'."""
    for row in top_rca_contributors(_df()):
        assert row["corrective"] and row["preventive"]
        assert row["corrective"] != row["preventive"]


def test_security_is_flagged_for_escalation_regardless_of_volume():
    rows = {r["category"]: r for r in top_rca_contributors(_df())}

    assert rows["security_defect"]["count"] == 1
    assert rows["security_defect"]["priority"] is True
    assert rows["coding_error"]["priority"] is False


def test_top_areas_report_their_dominant_cause_and_rejection_rate_separately():
    """Volume and rejection rate mean different things; both must be visible."""
    rows = {r["area_path"]: r for r in top_area_contributors(_df())}

    assert rows["Checkout"]["count"] == 6
    assert rows["Checkout"]["dominant_cause"] == "coding_error"
    assert rows["Checkout"]["rejection_rate"] == 0.0
    # Every Search defect is a duplicate — pure rejection, not a quality problem.
    assert rows["Search"]["rejection_rate"] == pytest.approx(1.0)


def test_area_actions_follow_that_area_dominant_cause():
    rows = {r["area_path"]: r for r in top_area_contributors(_df())}

    assert rows["Search"]["corrective"] == actions_for("requirements_gap").corrective
    assert rows["Checkout"]["preventive"] == actions_for("coding_error").preventive


def test_tables_are_capped_at_five_rows():
    df = pd.concat(
        [
            _df().assign(
                module=f"Area{i}",
                root_cause_category=f"cat{i}",
                id=range(1000 + i * 10, 1010 + i * 10),
            )
            for i in range(8)
        ],
        ignore_index=True,
    )

    assert len(top_rca_contributors(df)) == 5
    assert len(top_area_contributors(df)) == 5


def test_severity_mix_counts_only_severity_one_and_two_as_high_impact():
    mix = build_aggregates(_df())["severity_mix"]

    # Six sev-1/2 defects (2 Checkout + 3 Search + 1 Payments) out of ten.
    assert mix["critical_high"] == 6
    assert mix["critical_high_rate"] == pytest.approx(0.6)


def test_escape_rate_counts_late_phase_root_causes():
    """One production_operations defect out of ten."""
    assert build_aggregates(_df())["escape_rate"] == pytest.approx(0.1)


def test_leadership_keys_exist_for_an_empty_frame():
    """The view reads these unconditionally; missing keys would crash it."""
    agg = build_aggregates(pd.DataFrame())

    assert agg["top_rca_contributors"] == []
    assert agg["top_area_contributors"] == []
    assert agg["severity_mix"] == {}
    assert agg["escape_rate"] == 0.0


def test_an_unmapped_category_still_gets_a_usable_action():
    capa = actions_for("something_new")

    assert capa.corrective and capa.preventive
    assert capa.priority is False
