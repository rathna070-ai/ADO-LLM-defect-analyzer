"""Multi-key parallel categorization.

Rate limits are per API key, so several keys are several budgets. These cover
the parts that concurrency can break: work must be spread across providers,
every batch must be accounted for exactly once, DB writes must stay on one
thread, and a failure in one worker must not take the others down.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from ado_defect_analysis.config import AdoConfig, Config, LlmConfig
from ado_defect_analysis.llm import get_llm_providers
from ado_defect_analysis.llm.base import LlmProvider, LlmProviderError
from ado_defect_analysis.models import Defect
from ado_defect_analysis.pipeline.categorize import run_categorize
from ado_defect_analysis.storage import DefectStore


class TrackingProvider(LlmProvider):
    """Records which thread used it, so parallelism is observable."""

    def __init__(self, name: str, fail_ids: set[int] | None = None):
        super().__init__()
        self._name = name
        self._fail_ids = fail_ids or set()
        self.batches_handled = 0
        self.threads: set[int] = set()

    @property
    def model_name(self) -> str:
        return "fake-model-v1"

    def complete_json(
        self, *, system_prompt, user_prompt, schema, temperature=0.0, max_tokens=2048
    ) -> dict[str, Any]:
        import json

        self.batches_handled += 1
        self.threads.add(threading.get_ident())
        defects = json.loads(user_prompt)["defects"]
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
                for d in defects
                if d["defect_id"] not in self._fail_ids
            ]
        }


def _config(tmp_path: Path, batch_size: int = 2, concurrency: int = 2) -> Config:
    return Config(
        ado=AdoConfig(),
        llm=LlmConfig(categorize_batch_size=batch_size, max_concurrency=concurrency),
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


def test_config_collects_multiple_keys_from_a_comma_list(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "key-one, key-two")
    monkeypatch.setenv("GROQ_API_KEYS", "key-two,key-three")

    keys = Config.from_env().llm.groq_api_keys

    # Order preserved, duplicates dropped — key-two appears in both settings.
    assert keys == ["key-one", "key-two", "key-three"]


def test_factory_builds_one_provider_per_key():
    config = LlmConfig(provider="groq", groq_api_keys=["a", "b", "c"])

    providers = get_llm_providers(config)

    assert len(providers) == 3
    assert {p._api_key for p in providers} == {"a", "b", "c"}


def test_factory_falls_back_to_the_single_key():
    providers = get_llm_providers(LlmConfig(provider="groq", groq_api_key="solo"))

    assert len(providers) == 1
    assert providers[0]._api_key == "solo"


def test_every_batch_is_categorized_exactly_once_across_workers(tmp_path: Path, monkeypatch):
    """The correctness bar for parallelism: no defect dropped or done twice."""
    config = _config(tmp_path)
    store = DefectStore(config.db_path)
    store.upsert_defects([_defect(i) for i in range(1, 11)])
    providers = [TrackingProvider("a"), TrackingProvider("b")]
    monkeypatch.setattr(
        "ado_defect_analysis.pipeline.categorize.get_llm_providers", lambda _: providers
    )

    count = run_categorize(config)

    assert count == 10
    stored = store.get_categorized_defects()
    assert sorted(d["id"] for d in stored) == list(range(1, 11))
    # 10 defects / batch size 2 = 5 batches, shared between the two providers.
    assert sum(p.batches_handled for p in providers) == 5
    assert all(p.batches_handled > 0 for p in providers), "work never reached the second key"


def test_two_batches_are_genuinely_in_flight_at_once(tmp_path: Path, monkeypatch):
    """Proves real concurrency rather than fast sequential execution.

    Each call waits at a two-party barrier, so it can only be crossed if two
    batches are actually running simultaneously. A sequential implementation
    deadlocks here and the barrier times out.
    """
    barrier = threading.Barrier(2, timeout=10)

    class RendezvousProvider(TrackingProvider):
        def complete_json(self, **kwargs):
            barrier.wait()
            return super().complete_json(**kwargs)

    config = _config(tmp_path)
    # 8 defects at batch size 2 = 4 batches, an even number so every worker
    # finds a partner at the barrier.
    DefectStore(config.db_path).upsert_defects([_defect(i) for i in range(1, 9)])
    providers = [RendezvousProvider("a"), RendezvousProvider("b")]
    monkeypatch.setattr(
        "ado_defect_analysis.pipeline.categorize.get_llm_providers", lambda _: providers
    )

    count = run_categorize(config)

    assert count == 8
    assert len({t for p in providers for t in p.threads}) == 2


def test_concurrency_is_capped_by_config_not_key_count(tmp_path: Path, monkeypatch):
    """Extra same-org keys must not silently become extra concurrent load —
    Groq limits per organization, so that only trades 200s for 429s."""
    config = _config(tmp_path, concurrency=1)
    DefectStore(config.db_path).upsert_defects([_defect(i) for i in range(1, 7)])
    providers = [TrackingProvider("a"), TrackingProvider("b"), TrackingProvider("c")]
    monkeypatch.setattr(
        "ado_defect_analysis.pipeline.categorize.get_llm_providers", lambda _: providers
    )

    run_categorize(config)

    assert providers[0].batches_handled == 3
    assert providers[1].batches_handled == 0
    assert providers[2].batches_handled == 0
    assert len(providers[0].threads) == 1


def test_one_failing_worker_does_not_sink_the_run(tmp_path: Path, monkeypatch):
    config = _config(tmp_path)
    store = DefectStore(config.db_path)
    store.upsert_defects([_defect(i) for i in range(1, 11)])
    # Defect 3's batch comes back short, so that batch raises on its worker.
    providers = [TrackingProvider("a", fail_ids={3}), TrackingProvider("b", fail_ids={3})]
    monkeypatch.setattr(
        "ado_defect_analysis.pipeline.categorize.get_llm_providers", lambda _: providers
    )

    count = run_categorize(config)

    assert count == 8  # the other four batches still landed
    assert 3 not in {d["id"] for d in store.get_categorized_defects()}


def test_all_batches_failing_still_raises(tmp_path: Path, monkeypatch):
    config = _config(tmp_path)
    DefectStore(config.db_path).upsert_defects([_defect(1), _defect(2)])
    providers = [TrackingProvider("a", fail_ids={1, 2}), TrackingProvider("b", fail_ids={1, 2})]
    monkeypatch.setattr(
        "ado_defect_analysis.pipeline.categorize.get_llm_providers", lambda _: providers
    )

    try:
        run_categorize(config)
    except LlmProviderError:
        return
    raise AssertionError("expected LlmProviderError when every batch fails")
