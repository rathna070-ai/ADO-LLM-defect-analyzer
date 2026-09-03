"""Smoke tests for the Streamlit app.

`AppTest` actually executes the script, so these catch the class of breakage a
plain import check misses — a bad column reference or a missing aggregate key
only blows up when the view runs. They exercise both pages against a seeded
database rather than mocking the pipeline.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from ado_defect_analysis.models import Defect, DefectCategorization
from ado_defect_analysis.storage import DefectStore

APP = str(Path(__file__).resolve().parent.parent / "dashboard" / "streamlit_app.py")


def _seed(db_path: Path, analyzed: bool = True) -> None:
    store = DefectStore(db_path)
    store.upsert_defects(
        [
            Defect(
                id=i,
                title=f"Bug {i}",
                description="desc",
                module="Web\\Checkout" if i % 2 else "Web\\Search",
                severity="2 - High",
                state="Closed",
                resolution_notes="fixed a thing",
                root_cause_raw="",
                created_date="2026-01-01",
                closed_date="2026-01-05",
                iteration_path="Sprint 1" if i % 2 else "Sprint 2",
                resolution="Fixed" if i % 3 else "Duplicate",
            )
            for i in range(1, 7)
        ]
    )
    if analyzed:
        store.save_categorizations(
            [
                DefectCategorization(
                    defect_id=i,
                    root_cause_category="coding_error" if i % 2 else "test_gap",
                    testing_gap_flag=bool(i % 2),
                    summary="stub",
                    confidence=0.9 if i % 2 else 0.4,
                    sdlc_phase="development" if i % 2 else "testing",
                    model="fake-model",
                    prompt_version="abc123",
                    categorized_at="2026-01-06T00:00:00+00:00",
                    input_hash=f"hash{i}",
                )
                for i in range(1, 7)
            ]
        )


@pytest.fixture()
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point the app at a throwaway DB rather than the developer's real one."""
    monkeypatch.setenv("DEFECT_DB_PATH", str(tmp_path / "ui.db"))
    monkeypatch.setenv("DEFECT_OUTPUT_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("GROQ_API_KEY", "not-used-in-these-tests")
    return tmp_path


def _run(tmp_path: Path) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    return at


def test_home_page_offers_both_data_sources(app: Path):
    _seed(app / "ui.db", analyzed=False)

    at = _run(app)

    assert not at.exception
    assert at.radio[0].options == [
        "Upload a file from my computer",
        "Azure DevOps query link",
    ]
    assert at.get("file_uploader")  # the browse control
    assert "Upload" in [b.label for b in at.button]


def test_selecting_the_query_source_swaps_in_the_url_and_token_inputs(app: Path):
    _seed(app / "ui.db", analyzed=False)
    at = _run(app)

    at.radio[0].set_value("Azure DevOps query link").run()

    assert not at.exception
    labels = [t.label for t in at.text_input]
    assert "Query URL" in labels
    assert "Personal access token" in labels
    assert "Fetch from Azure DevOps" in [b.label for b in at.button]


def test_home_reports_how_much_is_loaded_and_analyzed(app: Path):
    _seed(app / "ui.db")

    at = _run(app)

    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Defects loaded"] == "6"
    assert metrics["Already analyzed"] == "6"
    assert metrics["Awaiting analysis"] == "0"


def test_dashboard_renders_every_section(app: Path):
    _seed(app / "ui.db")
    at = _run(app)

    next(b for b in at.button if b.label == "View dashboard").click().run()

    assert not at.exception
    headings = [s.value for s in at.subheader]
    for expected in (
        "Root cause distribution",
        "Defects by area path",
        "Root cause vs SDLC phase",
        "Valid vs rejected defects",
        "Needs review",
        "Export",
    ):
        assert any(expected in h for h in headings), f"missing section: {expected}"
    assert {m.label for m in at.metric} >= {"Total defects", "Needs review", "Valid", "Rejected"}


def test_dashboard_guides_the_user_back_when_nothing_is_analyzed(app: Path):
    _seed(app / "ui.db", analyzed=False)
    at = _run(app)
    at.session_state["page"] = "dashboard"

    at.run()

    assert not at.exception
    assert any("run the analysis" in w.value.lower() for w in at.warning)


def test_export_button_produces_downloadable_files(app: Path):
    _seed(app / "ui.db")
    at = _run(app)
    next(b for b in at.button if b.label == "View dashboard").click().run()

    next(b for b in at.button if b.label == "Generate export files").click().run()

    assert not at.exception
    downloads = [d.label for d in at.get("download_button")]
    assert any("categorized_defects.csv" in label for label in downloads)
    assert any("needs_review.csv" in label for label in downloads)
