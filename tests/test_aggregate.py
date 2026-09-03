import pandas as pd

from ado_defect_analysis.pipeline.aggregate import build_aggregates


def test_build_aggregates_empty_dataframe():
    result = build_aggregates(pd.DataFrame())

    assert result["total_defects"] == 0
    assert result["testing_gap_rate"] == 0.0


def test_build_aggregates_computes_distributions():
    df = pd.DataFrame(
        [
            {
                "module": "Checkout",
                "root_cause_category": "code_defect",
                "testing_gap_flag": 1,
                "closed_date": "2026-01-05",
            },
            {
                "module": "Checkout",
                "root_cause_category": "testing_gap",
                "testing_gap_flag": 1,
                "closed_date": "2026-01-20",
            },
            {
                "module": "Search",
                "root_cause_category": "code_defect",
                "testing_gap_flag": 0,
                "closed_date": "2026-02-01",
            },
        ]
    )
    df["closed_date"] = pd.to_datetime(df["closed_date"])
    df["closed_month"] = df["closed_date"].dt.to_period("M").astype(str)

    result = build_aggregates(df)

    assert result["total_defects"] == 3
    assert result["root_cause_distribution"]["code_defect"] == 2
    assert result["module_density"]["Checkout"] == 2
    assert result["monthly_trend"]["2026-01"] == 2
    assert round(result["testing_gap_rate"], 2) == 0.67
    assert isinstance(result["root_cause_distribution"]["code_defect"], int)
