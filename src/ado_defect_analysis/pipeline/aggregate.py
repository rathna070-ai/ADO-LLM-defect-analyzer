"""Phase 3a: turn categorized defects into the summary stats the narrative
prompt and Power BI both consume.

Returns plain dicts/lists (not a DataFrame) from `build_aggregates` so the
report stage can json.dumps it straight into the narrative prompt without a
pandas-to-JSON conversion step.
"""

from __future__ import annotations

import pandas as pd

from ..config import (
    DEFAULT_BORDERLINE_RESOLUTIONS,
    DEFAULT_REJECTED_RESOLUTIONS,
    Config,
)
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


def filter_by_closed_date(
    df: pd.DataFrame, since: str | None = None, until: str | None = None
) -> pd.DataFrame:
    """Narrow to defects closed within [since, until], inclusive.

    Both bounds are optional ISO dates. Rows with no closed date are dropped
    once either bound is set — an undated defect can't be claimed to fall
    inside a reporting window.
    """
    if df.empty or (since is None and until is None):
        return df

    closed = pd.to_datetime(df["closed_date"], errors="coerce", utc=True)
    mask = closed.notna()
    if since:
        mask &= closed >= pd.Timestamp(since, tz="UTC")
    if until:
        # Inclusive of the whole end day, so --until 2026-03-31 doesn't
        # silently drop anything closed that afternoon.
        mask &= closed < pd.Timestamp(until, tz="UTC") + pd.Timedelta(days=1)
    return df[mask]


def _blank_series(df: pd.DataFrame) -> pd.Series:
    return pd.Series("", index=df.index, dtype="object")


def _matches(df: pd.DataFrame, column: str, wanted_lower: set[str]) -> pd.Series:
    """Case-insensitive membership test that tolerates a missing column."""
    if column not in df.columns:
        return pd.Series(False, index=df.index)
    return df[column].fillna("").astype(str).str.strip().str.lower().isin(wanted_lower)


def needs_review_mask(df: pd.DataFrame, review_confidence_threshold: float = 0.6) -> pd.Series:
    """Rows a human should re-check before the analysis is trusted.

    Either the model told us it wasn't sure (sub-threshold confidence), or it
    declined to make a call at all (`unknown` on either dimension). Shared by
    the aggregate count and the needs-review export so both agree on what
    "needs review" means.
    """
    low_confidence = pd.to_numeric(df["confidence"], errors="coerce").fillna(0.0) < (
        review_confidence_threshold
    )
    unknown_rca = df["root_cause_category"].fillna("unknown").eq("unknown")
    unknown_phase = (
        df["sdlc_phase"].fillna("unknown").eq("unknown")
        if "sdlc_phase" in df.columns
        else pd.Series(False, index=df.index)
    )
    return low_confidence | unknown_rca | unknown_phase


def build_aggregates(
    df: pd.DataFrame,
    rejected_resolutions: list[str] | None = None,
    review_confidence_threshold: float = 0.6,
    borderline_resolutions: list[str] | None = None,
) -> dict:
    if df.empty:
        return {
            "total_defects": 0,
            "root_cause_distribution": {},
            "module_density": {},
            "monthly_trend": {},
            "testing_gap_rate": 0.0,
            "area_iteration_distribution": {},
            "rca_major_contributor": {},
            "valid_vs_rejected": {"valid": 0, "rejected": 0, "borderline": 0},
            "rejection_breakdown": {},
            "rca_pareto": [],
            "rca_sdlc_crosstab": {},
            "needs_review_count": 0,
        }

    rejected_resolutions = rejected_resolutions or DEFAULT_REJECTED_RESOLUTIONS
    borderline_resolutions = borderline_resolutions or DEFAULT_BORDERLINE_RESOLUTIONS
    rejected_lower = {r.strip().lower() for r in rejected_resolutions}
    borderline_lower = {r.strip().lower() for r in borderline_resolutions}

    root_cause_distribution = {
        str(k): int(v) for k, v in df["root_cause_category"].value_counts().items()
    }
    module_density = {str(k): int(v) for k, v in df["module"].value_counts().items()}
    monthly_trend = {
        str(k): int(v) for k, v in df.groupby("closed_month").size().sort_index().items()
    }
    testing_gap_rate = float(df["testing_gap_flag"].astype(bool).mean())

    area_iteration_distribution: dict[str, dict[str, int]] = {}
    area_iteration_counts = df.groupby(["module", "iteration_path"]).size()
    for (area_path, iteration_path), count in area_iteration_counts.items():
        area_iteration_distribution.setdefault(str(area_path), {})[str(iteration_path)] = int(count)

    rca_major_contributor: dict[str, dict] = {}
    category_totals = df["root_cause_category"].value_counts()
    by_category_module = df.groupby(["root_cause_category", "module"]).size()
    for category in category_totals.index:
        per_module = by_category_module[category]
        top_module, top_count = per_module.idxmax(), per_module.max()
        total = int(category_totals[category])
        rca_major_contributor[str(category)] = {
            "area_path": str(top_module),
            "count": int(top_count),
            "pct_of_category": round(float(top_count) / total, 4) if total else 0.0,
        }

    # Processes differ on where a rejection is recorded: some set a resolution
    # ("Duplicate"), others carry it in the workflow state ("Rejected") and
    # leave resolution blank entirely. Checking only one of the two silently
    # reports every defect as valid on a project that uses the other.
    # Precedence matters: the specific reason beats the generic state. A defect
    # with state "Rejected" and resolution "Cannot Reproduce" is borderline, not
    # a clean rejection — the state only says it was closed unfixed, while the
    # resolution says why. Checking state first would silently bury every
    # borderline outcome in a process that always sets state=Rejected.
    borderline_reason = _matches(df, "resolution", borderline_lower)
    rejected_reason = _matches(df, "resolution", rejected_lower)
    is_rejected = rejected_reason | (
        _matches(df, "state", rejected_lower) & ~borderline_reason & ~rejected_reason
    )
    # Borderline outcomes are their own line rather than being folded into
    # either count — "Cannot Reproduce" is a different claim from "Working as
    # Designed", and merging them misstates the rejection rate either way.
    is_borderline = (borderline_reason | _matches(df, "state", borderline_lower)) & ~is_rejected
    valid_vs_rejected = {
        "valid": int((~is_rejected & ~is_borderline).sum()),
        "rejected": int(is_rejected.sum()),
        "borderline": int(is_borderline.sum()),
    }
    # Sub-split so a high "working as designed" share can be read as a
    # requirements-clarity problem rather than a product-quality one. Each row
    # is labelled by the field that actually drove the classification —
    # labelling by resolution regardless would print "Fixed and verified"
    # inside a rejection breakdown whenever the state was what matched.
    matched_reason = _blank_series(df)
    reason_matched = borderline_reason | rejected_reason
    matched_reason = matched_reason.mask(reason_matched, df.get("resolution", matched_reason))
    if "state" in df.columns:
        matched_reason = matched_reason.mask(~reason_matched, df["state"])
    rejection_breakdown = {
        str(label): int(count)
        for label, count in matched_reason[is_rejected | is_borderline]
        .replace("", "(unspecified)")
        .fillna("(unspecified)")
        .value_counts()
        .items()
    }

    rca_sdlc_crosstab: dict[str, dict[str, int]] = {}
    if "sdlc_phase" in df.columns:
        crosstab = pd.crosstab(df["root_cause_category"], df["sdlc_phase"])
        for category, row in crosstab.iterrows():
            rca_sdlc_crosstab[str(category)] = {str(k): int(v) for k, v in row.items()}

    return {
        "total_defects": len(df),
        "root_cause_distribution": root_cause_distribution,
        "module_density": module_density,
        "monthly_trend": monthly_trend,
        "testing_gap_rate": round(testing_gap_rate, 4),
        "area_iteration_distribution": area_iteration_distribution,
        "rca_major_contributor": rca_major_contributor,
        "valid_vs_rejected": valid_vs_rejected,
        "rejection_breakdown": rejection_breakdown,
        "rca_pareto": _pareto(root_cause_distribution),
        "rca_sdlc_crosstab": rca_sdlc_crosstab,
        "needs_review_count": int(needs_review_mask(df, review_confidence_threshold).sum()),
    }


def _pareto(distribution: dict[str, int]) -> list[dict]:
    """Categories sorted descending with a running share.

    `in_vital_few` marks everything up to the 80% cumulative line — the
    classic 80/20 read of "fix these and you've addressed most defects".
    """
    total = sum(distribution.values())
    if not total:
        return []

    rows: list[dict] = []
    cumulative = 0
    for category, count in sorted(distribution.items(), key=lambda kv: kv[1], reverse=True):
        previous = cumulative
        cumulative += count
        rows.append(
            {
                "category": category,
                "count": count,
                "pct_of_total": round(count / total, 4),
                "cumulative_pct": round(cumulative / total, 4),
                # Included if the band *starts* below 80%, so the category
                # that crosses the line is part of the vital few.
                "in_vital_few": previous / total < 0.8,
            }
        )
    return rows
