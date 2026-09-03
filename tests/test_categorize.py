from pathlib import Path
from typing import Any

import pytest

from ado_defect_analysis.config import AdoConfig, Config, LlmConfig
from ado_defect_analysis.llm.base import LlmProvider, LlmProviderError
from ado_defect_analysis.models import Defect
from ado_defect_analysis.pipeline.categorize import run_categorize
from ado_defect_analysis.storage import DefectStore


class FakeProvider(LlmProvider):
    def __init__(self, response: dict[str, Any] | None = None, fail_ids: set[int] | None = None):
        self._response = response
        self._fail_ids = fail_ids or set()
        self.last_defects: list[dict[str, Any]] = []

    @property
    def model_name(self) -> str:
        return "fake-model-v1"

    def complete_json(
        self, *, system_prompt, user_prompt, schema, temperature=0.0, max_tokens=2048
    ):
        import json

        defects = json.loads(user_prompt)["defects"]
        self.last_defects = defects
        if self._response is not None:
            return self._response
        results = [
            {
                "defect_id": d["defect_id"],
                "root_cause_category": "code_defect",
                "testing_gap_flag": True,
                "sdlc_phase": "development",
                "summary": "stub",
                "confidence": 0.8,
            }
            for d in defects
            if d["defect_id"] not in self._fail_ids
        ]
        return {"results": results}


def _config(tmp_path: Path) -> Config:
    return Config(
        ado=AdoConfig(),
        llm=LlmConfig(categorize_batch_size=10),
        db_path=tmp_path / "d.db",
        output_dir=tmp_path / "out",
    )


def _defect(defect_id: int, **overrides) -> Defect:
    fields = {
        "id": defect_id,
        "title": "Bug",
        "description": "desc",
        "module": "Checkout",
        "severity": "High",
        "state": "Closed",
        "resolution_notes": "notes",
        "root_cause_raw": "",
        "created_date": "2026-01-01",
        "closed_date": "2026-01-02",
    }
    fields.update(overrides)
    return Defect(**fields)  # type: ignore[arg-type]


def test_run_categorize_stores_results(tmp_path: Path):
    config = _config(tmp_path)
    store = DefectStore(config.db_path)
    store.upsert_defects([_defect(1, root_cause_raw="Race condition", resolution="Fixed")])

    provider = FakeProvider()
    count = run_categorize(config, provider=provider)

    assert count == 1
    categorized = store.get_categorized_defects()
    assert categorized[0]["root_cause_category"] == "code_defect"
    assert categorized[0]["sdlc_phase"] == "development"
    # The prompt payload must carry state/disposition/root_cause_raw so the LLM
    # can cross-reference them, not just title/description.
    sent = provider.last_defects[0]
    assert sent["state"] == "Closed"
    assert sent["disposition"] == "Fixed"
    assert sent["root_cause_raw"] == "Race condition"


def test_run_categorize_defaults_invalid_sdlc_phase_to_unknown(tmp_path: Path):
    config = _config(tmp_path)
    store = DefectStore(config.db_path)
    store.upsert_defects([_defect(1)])
    bad_response = {
        "results": [
            {
                "defect_id": 1,
                "root_cause_category": "code_defect",
                "testing_gap_flag": True,
                "sdlc_phase": "not_a_real_phase",
                "summary": "stub",
                "confidence": 0.8,
            }
        ]
    }

    run_categorize(config, provider=FakeProvider(response=bad_response))

    categorized = store.get_categorized_defects()
    assert categorized[0]["sdlc_phase"] == "unknown"


def test_run_categorize_recategorize_all_reprocesses_existing(tmp_path: Path):
    config = _config(tmp_path)
    store = DefectStore(config.db_path)
    store.upsert_defects([_defect(1)])
    run_categorize(config, provider=FakeProvider())
    assert store.get_uncategorized_defects() == []

    count = run_categorize(config, provider=FakeProvider(), recategorize_all=True)

    assert count == 1


def test_run_categorize_returns_zero_when_nothing_pending(tmp_path: Path):
    config = _config(tmp_path)
    DefectStore(config.db_path)

    count = run_categorize(config, provider=FakeProvider())

    assert count == 0


def test_run_categorize_records_provenance(tmp_path: Path):
    config = _config(tmp_path)
    store = DefectStore(config.db_path)
    store.upsert_defects([_defect(1)])

    run_categorize(config, provider=FakeProvider())

    row = store.get_categorized_defects()[0]
    assert row["model"] == "fake-model-v1"
    # Derived from the prompt text, so it changes whenever the prompt does.
    assert row["prompt_version"] and len(row["prompt_version"]) == 12
    assert row["categorized_at"].startswith("20")


@pytest.mark.parametrize(
    ("raw_confidence", "expected"),
    [("high", 0.0), (None, 0.0), (5.0, 1.0), (-2.0, 0.0), (0.75, 0.75)],
)
def test_run_categorize_coerces_and_clamps_confidence(
    tmp_path: Path, raw_confidence: object, expected: float
):
    """A bad confidence value shouldn't crash a batch or skew the review threshold."""
    config = _config(tmp_path)
    store = DefectStore(config.db_path)
    store.upsert_defects([_defect(1)])
    response = {
        "results": [
            {
                "defect_id": 1,
                "root_cause_category": "code_defect",
                "testing_gap_flag": True,
                "sdlc_phase": "development",
                "summary": "stub",
                "confidence": raw_confidence,
            }
        ]
    }

    run_categorize(config, provider=FakeProvider(response=response))

    assert store.get_categorized_defects()[0]["confidence"] == expected


def test_run_categorize_continues_after_a_failed_batch(tmp_path: Path):
    """One bad batch must not discard every batch queued behind it."""
    config = _config(tmp_path)
    config.llm.categorize_batch_size = 1
    store = DefectStore(config.db_path)
    store.upsert_defects([_defect(1), _defect(2), _defect(3)])

    # Defect 2's batch comes back missing its result, so that batch raises.
    count = run_categorize(config, provider=FakeProvider(fail_ids={2}))

    assert count == 2
    assert sorted(d["id"] for d in store.get_categorized_defects()) == [1, 3]


def test_run_categorize_raises_when_every_batch_fails(tmp_path: Path):
    config = _config(tmp_path)
    config.llm.categorize_batch_size = 1
    store = DefectStore(config.db_path)
    store.upsert_defects([_defect(1), _defect(2)])

    with pytest.raises(LlmProviderError):
        run_categorize(config, provider=FakeProvider(fail_ids={1, 2}))


def test_run_categorize_raises_when_llm_drops_a_defect(tmp_path: Path):
    config = _config(tmp_path)
    store = DefectStore(config.db_path)
    store.upsert_defects([_defect(1)])

    with pytest.raises(LlmProviderError):
        run_categorize(config, provider=FakeProvider(fail_ids={1}))
