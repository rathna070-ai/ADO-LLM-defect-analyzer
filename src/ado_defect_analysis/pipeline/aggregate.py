"""Phase 3a: turn categorized defects into the summary stats the narrative
prompt and Power BI both consume.

Returns plain dicts/lists (not a DataFrame) from `build_aggregates` so the
report stage can json.dumps it straight into the narrative prompt without a
pandas-to-JSON conversion step.
"""

from __future__ import annotations

import pandas as pd

from ..config import Config
from ..storage import DefectStore


def load_categorized_dataframe(config: Config) -> pd.DataFrame:
    store = DefectStore(config.db_path)
    rows = store.get_categorized_defects()
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["closed_date"] = pd.to_datetime(df["closed_date"], errors="coerce")
    df["closed_month"] = df["closed_date"].dt.to_period("M").astype(str)
    return df


def build_aggregates(df: pd.DataFrame) -> dict:
    if df.empty:
        return {
            "total_defects": 0,
            "root_cause_distribution": {},
            "module_density": {},
            "monthly_trend": {},
            "testing_gap_rate": 0.0,
        }

    root_cause_distribution = {
        str(k): int(v) for k, v in df["root_cause_category"].value_counts().items()
    }
    module_density = {str(k): int(v) for k, v in df["module"].value_counts().items()}
    monthly_trend = {
        str(k): int(v) for k, v in df.groupby("closed_month").size().sort_index().items()
    }
    testing_gap_rate = float(df["testing_gap_flag"].astype(bool).mean())

    return {
        "total_defects": int(len(df)),
        "root_cause_distribution": root_cause_distribution,
        "module_density": module_density,
        "monthly_trend": monthly_trend,
        "testing_gap_rate": round(testing_gap_rate, 4),
    }
