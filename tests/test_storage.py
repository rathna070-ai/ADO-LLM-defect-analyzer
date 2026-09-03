import sqlite3
from pathlib import Path

from ado_defect_analysis.models import Defect, DefectCategorization
from ado_defect_analysis.storage import DefectStore


def _sample_defect(defect_id: int) -> Defect:
    return Defect(
        id=defect_id,
        title=f"Bug {defect_id}",
        description="Something broke",
        module="App\\Checkout",
        severity="2 - High",
        state="Closed",
        resolution_notes="Fixed null check",
        root_cause_raw="",
        created_date="2026-01-01T00:00:00Z",
        closed_date="2026-01-05T00:00:00Z",
        iteration_path="App\\Sprint 12",
        resolution="Fixed",
    )


def test_upsert_and_fetch_uncategorized(tmp_path: Path):
    store = DefectStore(tmp_path / "defects.db")
    store.upsert_defects([_sample_defect(1), _sample_defect(2)])

    pending = store.get_uncategorized_defects()

    assert {d.id for d in pending} == {1, 2}


def test_categorized_defects_excluded_from_pending(tmp_path: Path):
    store = DefectStore(tmp_path / "defects.db")
    store.upsert_defects([_sample_defect(1), _sample_defect(2)])
    store.save_categorizations(
        [
            DefectCategorization(
                defect_id=1,
                root_cause_category="code_defect",
                testing_gap_flag=True,
                summary="Null check missing.",
                confidence=0.9,
                sdlc_phase="development",
            )
        ]
    )

    pending = store.get_uncategorized_defects()
    categorized = store.get_categorized_defects()

    assert [d.id for d in pending] == [2]
    assert len(categorized) == 1
    assert categorized[0]["root_cause_category"] == "code_defect"
    assert categorized[0]["sdlc_phase"] == "development"
    assert categorized[0]["iteration_path"] == "App\\Sprint 12"
    assert categorized[0]["resolution"] == "Fixed"


def test_get_all_defects_includes_already_categorized(tmp_path: Path):
    store = DefectStore(tmp_path / "defects.db")
    store.upsert_defects([_sample_defect(1), _sample_defect(2)])
    store.save_categorizations(
        [
            DefectCategorization(
                defect_id=1,
                root_cause_category="code_defect",
                testing_gap_flag=True,
                summary="Null check missing.",
                confidence=0.9,
                sdlc_phase="development",
            )
        ]
    )

    all_defects = store.get_all_defects()

    assert {d.id for d in all_defects} == {1, 2}


def test_upgrades_db_created_with_old_schema(tmp_path: Path):
    db_path = tmp_path / "old.db"
    old_schema = """
    CREATE TABLE defects (
        id INTEGER PRIMARY KEY,
        title TEXT NOT NULL,
        description TEXT,
        module TEXT,
        severity TEXT,
        state TEXT,
        resolution_notes TEXT,
        root_cause_raw TEXT,
        created_date TEXT,
        closed_date TEXT,
        tags TEXT,
        comments TEXT
    );
    CREATE TABLE categorizations (
        defect_id INTEGER PRIMARY KEY REFERENCES defects(id),
        root_cause_category TEXT NOT NULL,
        testing_gap_flag INTEGER NOT NULL,
        summary TEXT NOT NULL,
        confidence REAL NOT NULL
    );
    """
    conn = sqlite3.connect(db_path)
    conn.executescript(old_schema)
    conn.execute(
        "INSERT INTO defects (id, title) VALUES (1, 'Legacy bug')"
    )
    conn.commit()
    conn.close()

    store = DefectStore(db_path)
    store.upsert_defects([_sample_defect(1)])

    all_defects = store.get_all_defects()
    assert all_defects[0].iteration_path == "App\\Sprint 12"
    assert all_defects[0].resolution == "Fixed"


def test_upsert_is_idempotent(tmp_path: Path):
    store = DefectStore(tmp_path / "defects.db")
    store.upsert_defects([_sample_defect(1)])
    updated = _sample_defect(1)
    updated.title = "Updated title"
    store.upsert_defects([updated])

    pending = store.get_uncategorized_defects()

    assert len(pending) == 1
    assert pending[0].title == "Updated title"
