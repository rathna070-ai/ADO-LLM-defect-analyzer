"""Command-line entrypoint: `python -m ado_defect_analysis.cli <command>`."""

from __future__ import annotations

import argparse
import getpass
import json
import logging
import subprocess
import sys
from pathlib import Path

from .config import Config
from .pipeline.categorize import run_categorize
from .pipeline.export import run_export
from .pipeline.fetch import run_fetch, run_fetch_from_excel
from .pipeline.report import run_report
from .secrets import MANAGED_SECRETS, clear_secret, secret_status, set_secret


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ado-defect-analysis",
        description=(
            "Pull closed ADO defects, categorize root causes with an LLM, and export for Power BI."
        ),
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

    categorize_parser = subparsers.add_parser(
        "categorize", help="Send uncategorized defects to the LLM."
    )
    categorize_parser.add_argument(
        "--recategorize-all",
        action="store_true",
        help=(
            "Re-run categorization for every defect in the DB, not just uncategorized "
            "ones. Use this to backfill a newly added categorization field (e.g. "
            "sdlc_phase) onto defects categorized before the field existed. Defects "
            "whose fields, prompt, and model are all unchanged are skipped."
        ),
    )
    categorize_parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "With --recategorize-all, re-send even defects whose inputs, prompt, and "
            "model are unchanged. Costs a full re-run; use it to resample a "
            "non-deterministic model."
        ),
    )
    report_parser = subparsers.add_parser(
        "report", help="Generate the exec-tone narrative summary."
    )
    export_parser = subparsers.add_parser("export", help="Export categorized defects to CSV/Excel.")
    for date_scoped in (report_parser, export_parser):
        _add_date_window_args(date_scoped)

    dashboard_parser = subparsers.add_parser(
        "dashboard",
        help="Launch the Streamlit UI (upload defects, run the analysis, view the dashboard).",
    )
    dashboard_parser.add_argument(
        "--port", type=int, default=8501, help="Port to serve on (default 8501)."
    )
    dashboard_parser.add_argument(
        "--no-browser", action="store_true", help="Don't open a browser window on start."
    )

    secrets_parser = subparsers.add_parser(
        "secrets",
        help="Store credentials in the OS credential store instead of a plaintext .env.",
    )
    secrets_parser.add_argument("action", choices=("status", "set", "clear"), help="What to do.")
    secrets_parser.add_argument(
        "name",
        nargs="?",
        choices=MANAGED_SECRETS,
        help="Which credential (required for set/clear).",
    )

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
    _add_date_window_args(run_all_parser)

    return parser


def _add_date_window_args(parser: argparse.ArgumentParser) -> None:
    """Scope a stage to defects closed within a window, e.g. one quarter."""
    parser.add_argument(
        "--since",
        default=None,
        metavar="YYYY-MM-DD",
        help="Only include defects closed on or after this date.",
    )
    parser.add_argument(
        "--until",
        default=None,
        metavar="YYYY-MM-DD",
        help="Only include defects closed on or before this date (inclusive).",
    )


def _run_dashboard(args: argparse.Namespace) -> int:
    """Hand the packaged Streamlit script to the `streamlit` CLI.

    Streamlit has no supported in-process API for serving a script, so this
    shells out the way its own docs do. Resolving the path through the
    installed package (rather than a path relative to the repo) is what makes
    this work from a wheel on a machine that never saw the source tree.
    """
    from .dashboard import APP_PATH

    if not APP_PATH.exists():  # pragma: no cover - only if the wheel is malformed
        print(f"Dashboard files are missing from the installation: {APP_PATH}")
        return 1

    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(APP_PATH),
        "--server.port",
        str(args.port),
    ]
    if args.no_browser:
        command += ["--server.headless", "true"]

    try:
        return subprocess.call(command)
    except FileNotFoundError:
        print(
            "Streamlit is not installed. Install the dashboard extra:\n"
            '    pip install "ado-defect-analysis[dashboard]"'
        )
        return 1


def _run_secrets(args: argparse.Namespace) -> int:
    """Manage credentials without ever writing them to a file.

    `set` reads the value from a prompt rather than an argument, so the key
    does not end up in shell history or in the process list.
    """
    if args.action == "status":
        for name, source in secret_status().items():
            print(f"  {name:<16} {source}")
        return 0

    if not args.name:
        print(f"Specify which credential: {', '.join(MANAGED_SECRETS)}")
        return 2

    if args.action == "clear":
        removed = clear_secret(args.name)
        print(f"{args.name}: {'removed' if removed else 'nothing stored'}")
        return 0

    value = getpass.getpass(f"{args.name} (input hidden): ").strip()
    if not value:
        print("Nothing entered; leaving the stored value untouched.")
        return 1
    try:
        set_secret(args.name, value)
    except RuntimeError as exc:
        print(str(exc))
        return 1
    print(f"{args.name}: stored in the OS credential store. Remove it from .env now.")
    return 0


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
        count = run_categorize(config, recategorize_all=args.recategorize_all, force=args.force)
        print(f"Categorized {count} defects.")
    elif args.command == "dashboard":
        return _run_dashboard(args)
    elif args.command == "secrets":
        return _run_secrets(args)
    elif args.command == "report":
        narrative = run_report(config, since=args.since, until=args.until)
        print(json.dumps(narrative, indent=2))
    elif args.command == "export":
        paths = run_export(config, since=args.since, until=args.until)
        print("Exported:\n" + "\n".join(paths))
    elif args.command == "run-all":
        if args.from_excel:
            run_fetch_from_excel(config, args.from_excel)
        else:
            run_fetch(config)
        run_categorize(config)
        run_report(config, since=args.since, until=args.until)
        run_export(config, since=args.since, until=args.until)
        print("Pipeline complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
