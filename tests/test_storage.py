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
            )
        ]
    )

    pending = store.get_uncategorized_defects()
    categorized = store.get_categorized_defects()

    assert [d.id for d in pending] == [2]
    assert len(categorized) == 1
    assert categorized[0]["root_cause_category"] == "code_defect"


def test_upsert_is_idempotent(tmp_path: Path):
    store = DefectStore(tmp_path / "defects.db")
    store.upsert_defects([_sample_defect(1)])
    updated = _sample_defect(1)
    updated.title = "Updated title"
    store.upsert_defects([updated])

    pending = store.get_uncategorized_defects()

    assert len(pending) == 1
    assert pending[0].title == "Updated title"
