"""Background categorize runs.

The point of running off-thread is that work survives the browser session, so
these check the guarantees that makes: only one run at a time, progress is
observable while it happens, and a failure on the worker surfaces instead of
vanishing.

The fake provider blocks on an Event rather than sleeping, so "while the run is
active" is a deterministic window instead of a race against the clock.
"""

from __future__ import annotations

import dataclasses
import threading
from pathlib import Path
from typing import Any

import pytest

from ado_defect_analysis.background import BackgroundRun, RunStatus
from ado_defect_analysis.config import AdoConfig, Config, LlmConfig
from ado_defect_analysis.llm.base import LlmProvider
from ado_defect_analysis.models import Defect
from ado_defect_analysis.storage import DefectStore


class GatedProvider(LlmProvider):
    """Holds each batch until released, so the run can be inspected mid-flight."""

    def __init__(self, gate: threading.Event, boom: bool = False):
        super().__init__()
        self._gate = gate
        self._boom = boom
        self.entered = threading.Event()

    @property
    def model_name(self) -> str:
        return "fake-model-v1"

    def complete_json(
        self, *, system_prompt, user_prompt, schema, temperature=0.0, max_tokens=2048
    ) -> dict[str, Any]:
        import json

        self.entered.set()
        self._gate.wait(timeout=10)
        if self._boom:
            raise RuntimeError("provider exploded")
        return {
            "results": [
                {
                    "defect_id": d["defect_id"],
                    "root_cause_category": "coding_error",
                    "testing_gap_flag": True,
                    "sdlc_phase": "development",
                    "evidence": "title",
                    "summary": "stub",
                    "confidence": 0.8,
                }
                for d in json.loads(user_prompt)["defects"]
            ]
        }


def _config(tmp_path: Path) -> Config:
    return Config(
        ado=AdoConfig(),
        llm=LlmConfig(categorize_batch_size=2),
        db_path=tmp_path / "d.db",
        output_dir=tmp_path / "out",
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


@pytest.fixture()
def seeded(tmp_path: Path) -> Config:
    config = _config(tmp_path)
    DefectStore(config.db_path).upsert_defects([_defect(i) for i in range(1, 5)])
    return config


def _patch_provider(monkeypatch, provider: LlmProvider) -> None:
    monkeypatch.setattr(
        "ado_defect_analysis.pipeline.categorize.get_llm_providers", lambda _: [provider]
    )


def test_a_run_reports_active_then_completes(seeded: Config, monkeypatch):
    gate = threading.Event()
    provider = GatedProvider(gate)
    _patch_provider(monkeypatch, provider)
    run = BackgroundRun()

    assert run.start(seeded) is True
    assert provider.entered.wait(timeout=5), "worker never reached the provider"
    assert run.is_active()

    gate.set()
    run._thread.join(timeout=15)

    status = run.status()
    assert not status.active
    assert status.error is None
    assert status.result_count == 4
    assert status.defects_done == status.defects_total == 4


def test_a_second_start_is_refused_while_one_is_running(seeded: Config, monkeypatch):
    """A page reload re-runs the script; without this guard it would pay twice."""
    gate = threading.Event()
    provider = GatedProvider(gate)
    _patch_provider(monkeypatch, provider)
    run = BackgroundRun()

    assert run.start(seeded) is True
    assert provider.entered.wait(timeout=5)

    assert run.start(seeded) is False

    gate.set()
    run._thread.join(timeout=15)
    assert run.status().result_count == 4


def test_a_worker_exception_is_captured_not_lost(seeded: Config, monkeypatch):
    """An exception on a thread is otherwise invisible — the UI would just
    show a run that quietly stopped advancing."""
    gate = threading.Event()
    gate.set()
    _patch_provider(monkeypatch, GatedProvider(gate, boom=True))
    run = BackgroundRun()

    run.start(seeded)
    run._thread.join(timeout=15)

    status = run.status()
    assert not status.active
    assert status.error is not None
    assert status.result_count is None


def test_status_is_a_snapshot_not_live_state(seeded: Config, monkeypatch):
    """Handed out by value so the UI can't mutate the run's state."""
    gate = threading.Event()
    gate.set()
    _patch_provider(monkeypatch, GatedProvider(gate))
    run = BackgroundRun()
    run.start(seeded)
    run._thread.join(timeout=15)

    first = run.status()

    assert isinstance(first, RunStatus)
    with pytest.raises(dataclasses.FrozenInstanceError):
        first.defects_done = 99  # type: ignore[misc]


def test_no_run_yet_reports_nothing_to_show():
    status = BackgroundRun().status()

    assert not status.has_run
    assert not status.active
    assert status.eta_seconds() is None


def test_eta_is_none_until_something_has_finished(monkeypatch):
    """Better no estimate than a fabricated one — a hardcoded per-batch
    constant is what produced a '3 minutes' claim for a 20-minute run."""
    import ado_defect_analysis.background as bg

    monkeypatch.setattr(bg.time, "monotonic", lambda: 1_010.0)
    status = RunStatus(active=True, started_at=1_000.0, defects_total=100, defects_done=0)

    assert status.eta_seconds() is None


def test_eta_comes_from_observed_throughput(monkeypatch):
    import ado_defect_analysis.background as bg

    monkeypatch.setattr(bg.time, "monotonic", lambda: 1_010.0)
    # A quarter done after 10s implies ~30s remaining.
    status = RunStatus(active=True, started_at=1_000.0, defects_total=100, defects_done=25)

    assert status.eta_seconds() == pytest.approx(30.0)


def test_eta_survives_a_zero_length_elapsed_window(monkeypatch):
    """A status read in the same instant it started must not divide by zero."""
    import ado_defect_analysis.background as bg

    monkeypatch.setattr(bg.time, "monotonic", lambda: 1_000.0)
    status = RunStatus(active=True, started_at=1_000.0, defects_total=100, defects_done=5)

    assert status.eta_seconds() is None
