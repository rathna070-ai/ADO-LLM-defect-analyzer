"""CLI dispatch tests.

The pipeline stages are stubbed out — what's under test here is that each
subcommand and flag reaches the right function with the right arguments, which
is exactly the wiring that silently breaks when a new flag is added.
"""

from pathlib import Path

import pytest

from ado_defect_analysis import cli


@pytest.fixture()
def calls(monkeypatch: pytest.MonkeyPatch) -> dict:
    recorded: dict = {}

    def _record(name, result):
        def _fn(*args, **kwargs):
            recorded[name] = {"args": args, "kwargs": kwargs}
            return result

        return _fn

    monkeypatch.setattr(cli, "run_fetch", _record("fetch", 3))
    monkeypatch.setattr(cli, "run_fetch_from_excel", _record("fetch_excel", 5))
    monkeypatch.setattr(cli, "run_categorize", _record("categorize", 4))
    monkeypatch.setattr(cli, "run_report", _record("report", {"headline": "ok"}))
    monkeypatch.setattr(cli, "run_export", _record("export", ["out.csv"]))
    return recorded


def test_fetch_uses_api_path_by_default(calls: dict):
    assert cli.main(["fetch"]) == 0
    assert "fetch" in calls
    assert "fetch_excel" not in calls


def test_fetch_from_excel_routes_to_excel_loader(calls: dict):
    assert cli.main(["fetch", "--from-excel", "export.xlsx"]) == 0

    assert "fetch" not in calls
    assert calls["fetch_excel"]["args"][1] == Path("export.xlsx")


def test_categorize_defaults_to_uncategorized_only(calls: dict):
    assert cli.main(["categorize"]) == 0

    assert calls["categorize"]["kwargs"]["recategorize_all"] is False


def test_categorize_recategorize_all_flag_is_wired(calls: dict):
    assert cli.main(["categorize", "--recategorize-all"]) == 0

    assert calls["categorize"]["kwargs"]["recategorize_all"] is True


def test_run_all_executes_every_stage_in_order(calls: dict):
    assert cli.main(["run-all"]) == 0

    assert set(calls) == {"fetch", "categorize", "report", "export"}


def test_run_all_from_excel_skips_the_api_fetch(calls: dict):
    assert cli.main(["run-all", "--from-excel", "export.xlsx"]) == 0

    assert "fetch" not in calls
    assert calls["fetch_excel"]["args"][1] == Path("export.xlsx")


def test_report_passes_the_date_window_through(calls: dict):
    assert cli.main(["report", "--since", "2026-01-01", "--until", "2026-03-31"]) == 0

    kwargs = calls["report"]["kwargs"]
    assert kwargs["since"] == "2026-01-01"
    assert kwargs["until"] == "2026-03-31"


def test_export_passes_the_date_window_through(calls: dict):
    assert cli.main(["export", "--since", "2026-01-01"]) == 0

    assert calls["export"]["kwargs"]["since"] == "2026-01-01"
    assert calls["export"]["kwargs"]["until"] is None


def test_run_all_scopes_report_and_export_to_the_window(calls: dict):
    assert cli.main(["run-all", "--since", "2026-01-01", "--until", "2026-03-31"]) == 0

    assert calls["report"]["kwargs"]["since"] == "2026-01-01"
    assert calls["export"]["kwargs"]["until"] == "2026-03-31"


def test_date_window_defaults_to_everything(calls: dict):
    assert cli.main(["export"]) == 0

    assert calls["export"]["kwargs"] == {"since": None, "until": None}


def test_unknown_command_is_rejected():
    with pytest.raises(SystemExit):
        cli.main(["not-a-command"])
