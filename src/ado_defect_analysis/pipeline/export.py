"""Phase 4: export categorized defects to CSV/Excel for Power BI to pick up
as a data source alongside the existing QAEE table.
"""

from __future__ import annotations

import logging

from ..config import Config
from .aggregate import load_categorized_dataframe

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

    logger.info("Exported %d categorized defects to: %s", len(df), ", ".join(written))
    return written
