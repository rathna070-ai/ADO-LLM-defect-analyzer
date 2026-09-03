"""Run categorization on a background thread so it outlives the browser.

Streamlit executes a page as a script and terminates that script when the
browser session goes away — a reload, a closed tab, a dropped websocket. A
categorize run driven inline therefore dies mid-flight with no error, leaving
only completed batches saved. That happened repeatedly on real runs.

Threads are not part of the script's lifecycle, so work started here keeps
going. The module-level `RUN` singleton is created once per server process,
which means every script rerun and every browser session sees the same run.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, replace

from .config import Config
from .pipeline.categorize import CategorizeProgress, run_categorize

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunStatus:
    """A snapshot of the current or most recent run.

    Frozen and handed out by value so the UI can never mutate live state, and
    never sees a half-updated record while a batch is landing.
    """

    active: bool = False
    # None rather than 0.0 as the "never started" sentinel: time.monotonic()
    # measures from an arbitrary origin, so 0.0 is a legitimate reading, not a
    # safe marker for absence.
    started_at: float | None = None
    finished_at: float | None = None
    batch_index: int = 0
    batch_count: int = 0
    defects_done: int = 0
    defects_total: int = 0
    failed_batches: int = 0
    error: str | None = None
    result_count: int | None = None
    sources: tuple[str, ...] = ()

    @property
    def has_run(self) -> bool:
        return self.started_at is not None

    @property
    def elapsed_seconds(self) -> float:
        if self.started_at is None:
            return 0.0
        finished = self.finished_at if self.finished_at is not None else time.monotonic()
        return finished - self.started_at

    @property
    def fraction(self) -> float:
        if not self.defects_total:
            return 0.0
        return min(self.defects_done / self.defects_total, 1.0)

    def eta_seconds(self) -> float | None:
        """Remaining time from observed throughput, or None until measurable.

        Deliberately returns None rather than a guess before the first batch
        lands — a hardcoded per-batch constant is what produced the "roughly 3
        minutes" estimate for work that takes twenty.
        """
        elapsed = self.elapsed_seconds
        if not self.active or not self.defects_done or elapsed <= 0:
            return None
        rate = self.defects_done / elapsed
        return (self.defects_total - self.defects_done) / rate


class BackgroundRun:
    """Owns at most one categorize run and the state the UI polls."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._status = RunStatus()
        self._thread: threading.Thread | None = None

    def status(self) -> RunStatus:
        with self._lock:
            return self._status

    def is_active(self) -> bool:
        return self.status().active

    def start(
        self,
        config: Config,
        sources: list[str] | None = None,
        recategorize_all: bool = False,
    ) -> bool:
        """Begin a run. Returns False if one is already going.

        The guard matters because a page reload re-executes the script: without
        it, coming back to the tab could launch a second run over the same
        defects and pay for them twice.
        """
        with self._lock:
            if self._status.active:
                return False
            self._status = RunStatus(
                active=True,
                started_at=time.monotonic(),
                sources=tuple(sources or ()),
            )

        # Not a daemon: a daemon thread would be killed at interpreter exit
        # mid-batch, losing work that was about to be saved.
        self._thread = threading.Thread(
            target=self._work,
            args=(config, sources, recategorize_all),
            name="categorize-run",
            daemon=False,
        )
        self._thread.start()
        return True

    def _work(self, config: Config, sources: list[str] | None, recategorize_all: bool) -> None:
        try:
            count = run_categorize(
                config,
                recategorize_all=recategorize_all,
                on_progress=self._record,
                sources=sources,
            )
        except Exception as exc:
            # Captured rather than raised: an exception on a worker thread is
            # otherwise invisible, and the UI would show a run that simply
            # stopped advancing with no explanation.
            logger.exception("Background categorize run failed.")
            self._finish(error=str(exc))
        else:
            self._finish(result_count=count)

    def _record(self, update: CategorizeProgress) -> None:
        with self._lock:
            self._status = replace(
                self._status,
                batch_index=update.batch_index,
                batch_count=update.batch_count,
                defects_done=update.defects_done,
                defects_total=update.defects_total,
                failed_batches=update.failed_batches,
            )

    def _finish(self, result_count: int | None = None, error: str | None = None) -> None:
        with self._lock:
            self._status = replace(
                self._status,
                active=False,
                finished_at=time.monotonic(),
                result_count=result_count,
                error=error,
            )


#: One per server process, shared across script reruns and browser sessions.
RUN = BackgroundRun()
