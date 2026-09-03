import pandas as pd

from ado_defect_analysis.pipeline.aggregate import build_aggregates, filter_by_closed_date


def test_build_aggregates_empty_dataframe():
    result = build_aggregates(pd.DataFrame())

    assert result["total_defects"] == 0
    assert result["testing_gap_rate"] == 0.0
    assert result["area_iteration_distribution"] == {}
    assert result["rca_major_contributor"] == {}
    assert result["valid_vs_rejected"] == {"valid": 0, "rejected": 0, "borderline": 0}
    assert result["rca_sdlc_crosstab"] == {}


def _sample_df() -> pd.DataFrame:
    df = pd.DataFrame(
        [
            {
                "module": "Checkout",
                "iteration_path": "Sprint 1",
                "root_cause_category": "coding_error",
                "sdlc_phase": "development",
                "testing_gap_flag": 1,
                "confidence": 0.9,
                "resolution": "Fixed",
                "closed_date": "2026-01-05",
            },
            {
                "module": "Checkout",
                "iteration_path": "Sprint 2",
                "root_cause_category": "test_gap",
                "sdlc_phase": "testing",
                "testing_gap_flag": 1,
                "confidence": 0.85,
                "resolution": "Duplicate",
                "closed_date": "2026-01-20",
            },
            {
                "module": "Search",
                "iteration_path": "Sprint 1",
                "root_cause_category": "coding_error",
                "sdlc_phase": "development",
                "testing_gap_flag": 0,
                "confidence": 0.3,
                "resolution": "Fixed",
                "closed_date": "2026-02-01",
            },
        ]
    )
    df["closed_date"] = pd.to_datetime(df["closed_date"])
    df["closed_month"] = df["closed_date"].dt.to_period("M").astype(str)
    return df


def test_filter_by_closed_date_bounds_are_inclusive():
    df = _sample_df()

    assert len(filter_by_closed_date(df, since="2026-01-01", until="2026-01-31")) == 2
    # The end day counts in full — a defect closed on the boundary date stays.
    assert len(filter_by_closed_date(df, since="2026-01-20", until="2026-01-20")) == 1
    assert len(filter_by_closed_date(df, since="2026-02-01")) == 1
    assert len(filter_by_closed_date(df, until="2026-01-05")) == 1


def test_filter_by_closed_date_without_bounds_is_a_passthrough():
    df = _sample_df()

    assert len(filter_by_closed_date(df)) == len(df)


def test_filter_by_closed_date_drops_undated_rows_when_scoped():
    """An undated defect can't be claimed to fall inside a reporting window."""
    df = _sample_df()
    df.loc[0, "closed_date"] = pd.NaT

    assert len(filter_by_closed_date(df, since="2026-01-01")) == 2
    assert len(filter_by_closed_date(df)) == 3


def test_build_aggregates_computes_distributions():
    result = build_aggregates(_sample_df())

    assert result["total_defects"] == 3
    assert result["root_cause_distribution"]["coding_error"] == 2
    assert result["module_density"]["Checkout"] == 2
    assert result["monthly_trend"]["2026-01"] == 2
    assert round(result["testing_gap_rate"], 2) == 0.67
    assert isinstance(result["root_cause_distribution"]["coding_error"], int)


def test_build_aggregates_area_iteration_distribution():
    result = build_aggregates(_sample_df())

    assert result["area_iteration_distribution"]["Checkout"]["Sprint 1"] == 1
    assert result["area_iteration_distribution"]["Checkout"]["Sprint 2"] == 1
    assert result["area_iteration_distribution"]["Search"]["Sprint 1"] == 1


def test_build_aggregates_rca_major_contributor():
    result = build_aggregates(_sample_df())

    top = result["rca_major_contributor"]["coding_error"]
    assert top["area_path"] in {"Checkout", "Search"}
    assert top["count"] == 1
    assert top["pct_of_category"] == 0.5


def test_build_aggregates_valid_vs_rejected_uses_rejected_resolutions():
    result = build_aggregates(_sample_df(), rejected_resolutions=["Duplicate"])

    assert result["valid_vs_rejected"] == {"valid": 2, "rejected": 1, "borderline": 0}


def test_rejection_is_detected_from_state_when_resolution_is_blank():
    """Some ADO processes record rejection as a workflow state, leaving
    resolution empty — reading only resolution would call everything valid."""
    df = _sample_df()
    df["resolution"] = ""
    df["state"] = ["Closed", "Rejected", "Closed"]

    result = build_aggregates(df, rejected_resolutions=["Duplicate", "Rejected"])

    assert result["valid_vs_rejected"] == {"valid": 2, "rejected": 1, "borderline": 0}


def test_a_defect_rejected_in_both_fields_is_counted_once():
    df = _sample_df()
    df["resolution"] = ["Fixed", "Duplicate", "Fixed"]
    df["state"] = ["Closed", "Rejected", "Closed"]

    result = build_aggregates(df, rejected_resolutions=["Duplicate", "Rejected"])

    assert result["valid_vs_rejected"] == {"valid": 2, "rejected": 1, "borderline": 0}


def test_borderline_outcomes_are_held_separate_from_rejected():
    """Cannot Reproduce is a different claim from Working as Designed —
    folding them together misstates the rejection rate either way."""
    df = _sample_df()
    df["resolution"] = ["Fixed", "Duplicate", "Cannot Reproduce"]

    result = build_aggregates(
        df, rejected_resolutions=["Duplicate"], borderline_resolutions=["Cannot Reproduce"]
    )

    assert result["valid_vs_rejected"] == {"valid": 1, "rejected": 1, "borderline": 1}


def test_a_specific_borderline_reason_beats_a_generic_rejected_state():
    """Real ADO processes set state=Rejected on everything closed unfixed.
    Reading state first would bury every borderline outcome inside it."""
    df = _sample_df()
    df["resolution"] = ["Fixed", "Duplicate", "Cannot Reproduce"]
    df["state"] = ["Closed", "Rejected", "Rejected"]

    result = build_aggregates(
        df,
        rejected_resolutions=["Duplicate", "Rejected"],
        borderline_resolutions=["Cannot Reproduce"],
    )

    assert result["valid_vs_rejected"] == {"valid": 1, "rejected": 1, "borderline": 1}


def test_rejected_wins_when_a_value_appears_in_both_lists():
    df = _sample_df()
    df["resolution"] = ["Fixed", "Duplicate", "Fixed"]
    df["state"] = ["Closed", "Rejected", "Closed"]

    result = build_aggregates(
        df, rejected_resolutions=["Duplicate", "Rejected"], borderline_resolutions=["Duplicate"]
    )

    assert result["valid_vs_rejected"]["rejected"] == 1
    assert result["valid_vs_rejected"]["borderline"] == 0


def test_rejection_breakdown_names_the_recorded_reasons():
    df = _sample_df()
    df["resolution"] = ["Fixed", "Duplicate", "Cannot Reproduce"]

    result = build_aggregates(
        df, rejected_resolutions=["Duplicate"], borderline_resolutions=["Cannot Reproduce"]
    )

    assert result["rejection_breakdown"] == {"Duplicate": 1, "Cannot Reproduce": 1}


def test_pareto_marks_the_vital_few():
    df = pd.concat([_sample_df()] * 4, ignore_index=True)
    df.loc[:5, "root_cause_category"] = "coding_error"

    pareto = build_aggregates(df)["rca_pareto"]

    assert next(row["category"] for row in pareto) == "coding_error"
    assert pareto[0]["cumulative_pct"] >= pareto[0]["pct_of_total"]
    assert pareto[0]["in_vital_few"] is True
    # Cumulative share must end at 100%.
    assert pareto[-1]["cumulative_pct"] == 1.0


def test_pareto_is_empty_for_an_empty_frame():
    assert build_aggregates(pd.DataFrame())["rca_pareto"] == []


def test_build_aggregates_rca_sdlc_crosstab():
    result = build_aggregates(_sample_df())

    assert result["rca_sdlc_crosstab"]["coding_error"]["development"] == 2
    assert result["rca_sdlc_crosstab"]["test_gap"]["testing"] == 1
