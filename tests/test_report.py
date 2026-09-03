import json
from pathlib import Path
from typing import Any

from ado_defect_analysis.config import AdoConfig, Config, LlmConfig
from ado_defect_analysis.llm.base import LlmProvider
from ado_defect_analysis.models import Defect, DefectCategorization
from ado_defect_analysis.pipeline.report import run_report
from ado_defect_analysis.storage import DefectStore

_NARRATIVE = {"headline": "Defects trending down", "top_root_causes": ["code_defect"]}


class FakeProvider(LlmProvider):
    def __init__(self) -> None:
        self.last_user_prompt = ""

    @property
    def model_name(self) -> str:
        return "fake-model-v1"

    def complete_json(
        self, *, system_prompt, user_prompt, schema, temperature=0.0, max_tokens=2048
    ) -> dict[str, Any]:
        self.last_user_prompt = user_prompt
        return _NARRATIVE


def _config(tmp_path: Path) -> Config:
    return Config(
        ado=AdoConfig(),
        llm=LlmConfig(),
        db_path=tmp_path / "d.db",
        output_dir=tmp_path / "out",
        rejected_resolutions=["Duplicate"],
    )


def _seed(config: Config) -> DefectStore:
    store = DefectStore(config.db_path)
    store.upsert_defects(
        [
            Defect(
                id=1,
                title="Bug",
                description="desc",
                module="Checkout",
                severity="High",
                state="Closed",
                resolution_notes="notes",
                root_cause_raw="",
                created_date="2026-01-01",
                closed_date="2026-01-02",
                resolution="Duplicate",
            )
        ]
    )
    store.save_categorizations(
        [
            DefectCategorization(
                defect_id=1,
                root_cause_category="code_defect",
                testing_gap_flag=False,
                summary="stub",
                confidence=0.9,
                sdlc_phase="development",
            )
        ]
    )
    return store


def test_run_report_writes_narrative_to_disk(tmp_path: Path):
    config = _config(tmp_path)
    _seed(config)

    narrative = run_report(config, provider=FakeProvider())

    assert narrative == _NARRATIVE
    written = json.loads((config.output_dir / "narrative_summary.json").read_text())
    assert written == _NARRATIVE


def test_run_report_honours_configured_rejected_resolutions(tmp_path: Path):
    """Regression: report.py used to fall back to the default rejection list."""
    config = _config(tmp_path)
    _seed(config)
    provider = FakeProvider()

    run_report(config, provider=provider)

    aggregates = json.loads(provider.last_user_prompt)
    assert aggregates["valid_vs_rejected"] == {"valid": 0, "rejected": 1}


def test_run_report_returns_empty_when_nothing_categorized(tmp_path: Path):
    config = _config(tmp_path)
    DefectStore(config.db_path)

    assert run_report(config, provider=FakeProvider()) == {}
