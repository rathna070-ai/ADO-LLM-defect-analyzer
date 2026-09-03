"""Phase 4: export categorized defects to CSV/Excel for Power BI to pick up
as a data source alongside the existing QAEE table.

Also writes a `needs_review.csv` triage list — the categorizations the model
was least sure about — so a human can audit the weakest calls instead of
taking the whole set at face value.
"""

from __future__ import annotations

import logging

from ..config import Config
from .aggregate import load_categorized_dataframe, needs_review_mask

logger = logging.getLogger(__name__)


def run_export(config: Config, formats: tuple[str, ...] = ("csv", "xlsx")) -> list[str]:
    """Returns the list of file paths written."""
    df = load_categorized_dataframe(config)
    if df.empty:
        logger.warning("No categorized defects to export. Run fetch and categorize first.")
        return []

    config.output_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    if "csv" in formats:
        csv_path = config.output_dir / "categorized_defects.csv"
        df.to_csv(csv_path, index=False)
        written.append(str(csv_path))

    if "xlsx" in formats:
        xlsx_path = config.output_dir / "categorized_defects.xlsx"
        df.to_excel(xlsx_path, index=False, sheet_name="Defects")
        written.append(str(xlsx_path))

    review_df = df[needs_review_mask(df, config.review_confidence_threshold)].sort_values(
        "confidence"
    )
    review_path = config.output_dir / "needs_review.csv"
    review_df.to_csv(review_path, index=False)
    written.append(str(review_path))

    logger.info(
        "Exported %d categorized defects (%d flagged for review) to: %s",
        len(df),
        len(review_df),
        ", ".join(written),
    )
    return written
