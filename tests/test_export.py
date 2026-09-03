from pathlib import Path

import pandas as pd

from ado_defect_analysis.config import AdoConfig, Config, LlmConfig
from ado_defect_analysis.models import Defect, DefectCategorization
from ado_defect_analysis.pipeline.export import run_export
from ado_defect_analysis.storage import DefectStore


def _config(tmp_path: Path) -> Config:
    return Config(
        ado=AdoConfig(),
        llm=LlmConfig(),
        db_path=tmp_path / "d.db",
        output_dir=tmp_path / "out",
        review_confidence_threshold=0.6,
    )


def _defect(defect_id: int) -> Defect:
    return Defect(
        id=defect_id,
        title=f"Bug {defect_id}",
        description="desc",
        module="Checkout",
        severity="High",
        state="Closed",
        resolution_notes="notes",
        root_cause_raw="",
        created_date="2026-01-01",
        closed_date="2026-01-02",
    )


def _categorization(defect_id: int, confidence: float, category: str = "code_defect"):
    return DefectCategorization(
        defect_id=defect_id,
        root_cause_category=category,
        testing_gap_flag=False,
        summary="stub",
        confidence=confidence,
        sdlc_phase="development",
    )


def test_export_writes_needs_review_with_only_weak_rows(tmp_path: Path):
    config = _config(tmp_path)
    store = DefectStore(config.db_path)
    store.upsert_defects([_defect(1), _defect(2), _defect(3)])
    store.save_categorizations(
        [
            _categorization(1, confidence=0.95),  # confident, known -> excluded
            _categorization(2, confidence=0.2),  # low confidence -> included
            _categorization(3, confidence=0.99, category="unknown"),  # unknown -> included
        ]
    )

    written = run_export(config)

    review_path = config.output_dir / "needs_review.csv"
    assert str(review_path) in written
    review_df = pd.read_csv(review_path)
    assert sorted(review_df["id"]) == [2, 3]
    # Weakest call first, so a reviewer starts where the model was least sure.
    assert review_df.iloc[0]["id"] == 2


def test_export_returns_empty_when_nothing_categorized(tmp_path: Path):
    config = _config(tmp_path)
    DefectStore(config.db_path)

    assert run_export(config) == []
