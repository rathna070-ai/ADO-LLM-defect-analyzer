"""Command-line entrypoint: `python -m ado_defect_analysis.cli <command>`."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .config import Config
from .pipeline.categorize import run_categorize
from .pipeline.export import run_export
from .pipeline.fetch import run_fetch, run_fetch_from_excel
from .pipeline.report import run_report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ado-defect-analysis",
        description="Pull closed ADO defects, categorize root causes with an LLM, and export for Power BI.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch_parser = subparsers.add_parser(
        "fetch",
        help="Load closed defects into SQLite, from Azure DevOps or a local Excel/CSV export.",
    )
    fetch_parser.add_argument(
        "--from-excel",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "Load defects from an ADO Excel/CSV export instead of the ADO API. "
            "No ADO_ORGANIZATION/ADO_PROJECT/ADO_PAT needed with this option."
        ),
    )

    subparsers.add_parser("categorize", help="Send uncategorized defects to the LLM.")
    subparsers.add_parser("report", help="Generate the exec-tone narrative summary.")
    subparsers.add_parser("export", help="Export categorized defects to CSV/Excel.")

    run_all_parser = subparsers.add_parser(
        "run-all", help="Run fetch, categorize, report, and export in sequence."
    )
    run_all_parser.add_argument(
        "--from-excel",
        type=Path,
        default=None,
        metavar="PATH",
        help="Same as `fetch --from-excel` — skips the ADO API for the fetch step.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = _build_parser()
    args = parser.parse_args(argv)
    config = Config.from_env()

    if args.command == "fetch":
        count = (
            run_fetch_from_excel(config, args.from_excel) if args.from_excel else run_fetch(config)
        )
        print(f"Fetched {count} defects.")
    elif args.command == "categorize":
        count = run_categorize(config)
        print(f"Categorized {count} defects.")
    elif args.command == "report":
        narrative = run_report(config)
        print(json.dumps(narrative, indent=2))
    elif args.command == "export":
        paths = run_export(config)
        print("Exported:\n" + "\n".join(paths))
    elif args.command == "run-all":
        if args.from_excel:
            run_fetch_from_excel(config, args.from_excel)
        else:
            run_fetch(config)
        run_categorize(config)
        run_report(config)
        run_export(config)
        print("Pipeline complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
