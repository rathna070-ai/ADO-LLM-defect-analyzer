"""Phase 2: batch uncategorized defects to the LLM for structured root-cause
classification.

Batching is by fixed group size, not by module/sprint as a first cut — the
prompt gives the model each defect's module already, and grouping by a fixed
size keeps prompt length predictable regardless of how lopsided the module
distribution is. Swap in a group-by-module batcher later if per-module
context turns out to matter for accuracy.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from ..config import Config
from ..llm import LlmProvider, LlmProviderError, get_llm_provider
from ..models import Defect, DefectCategorization
from ..storage import DefectStore

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"

_SYSTEM_PROMPT = (_PROMPTS_DIR / "categorize_defect.md").read_text()
_SCHEMA = json.loads((_SCHEMAS_DIR / "categorize_defect.schema.json").read_text())

# Derived from the prompt text itself rather than hand-maintained, so editing
# the prompt automatically marks every categorization made after the edit as
# coming from a different revision.
_PROMPT_VERSION = hashlib.sha256(_SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12]

_VALID_CATEGORIES = set(
    _SCHEMA["properties"]["results"]["items"]["properties"]["root_cause_category"]["enum"]
)
_VALID_SDLC_PHASES = set(
    _SCHEMA["properties"]["results"]["items"]["properties"]["sdlc_phase"]["enum"]
)


def run_categorize(
    config: Config, provider: LlmProvider | None = None, recategorize_all: bool = False
) -> int:
    """Returns the number of defects categorized.

    `recategorize_all` re-runs every defect in the DB rather than only
    uncategorized ones — use it to backfill a newly added categorization field
    (e.g. `sdlc_phase`) onto defects categorized before the field existed.
    `save_categorizations` upserts by defect id, so this is safe to re-run.
    """
    store = DefectStore(config.db_path)
    provider = provider or get_llm_provider(config.llm)

    pending = store.get_all_defects() if recategorize_all else store.get_uncategorized_defects()
    if not pending:
        logger.info(
            "No defects to categorize." if recategorize_all else "No uncategorized defects found."
        )
        return 0

    batch_size = config.llm.categorize_batch_size
    total = 0
    failed_batches = 0
    for start in range(0, len(pending), batch_size):
        batch = pending[start : start + batch_size]
        # One bad batch (a dropped defect id, a malformed response, an
        # exhausted retry) shouldn't throw away every batch still queued
        # behind it — log it and keep going.
        try:
            categorizations = _categorize_batch(provider, batch, config)
        except LlmProviderError:
            failed_batches += 1
            logger.exception(
                "Batch %d-%d failed; continuing with the next batch.",
                start + 1,
                start + len(batch),
            )
            continue
        store.save_categorizations(categorizations)
        total += len(categorizations)
        logger.info(
            "Categorized defects %d-%d of %d.",
            start + 1,
            start + len(batch),
            len(pending),
        )

    if failed_batches:
        logger.warning("%d batch(es) failed and were skipped.", failed_batches)
        # Nothing got through at all — surface that as a failure rather than
        # letting the CLI print a cheerful "Categorized 0 defects."
        if total == 0:
            raise LlmProviderError(
                f"All {failed_batches} categorization batch(es) failed; see the log for details."
            )
    return total


def _categorize_batch(
    provider: LlmProvider, batch: list[Defect], config: Config
) -> list[DefectCategorization]:
    user_prompt = json.dumps(
        {
            "defects": [
                {
                    "defect_id": d.id,
                    "title": d.title,
                    "description": d.description[:2000],
                    "module": d.module,
                    "severity": d.severity,
                    "state": d.state,
                    "disposition": d.resolution,
                    "resolution_notes": d.resolution_notes[:2000],
                    "root_cause_raw": d.root_cause_raw,
                    "tags": d.tags,
                    "comments": d.comments[:2000],
                }
                for d in batch
            ]
        },
        indent=2,
    )

    result = provider.complete_json(
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        schema=_SCHEMA,
        temperature=config.llm.temperature,
        max_tokens=config.llm.max_tokens,
    )

    known_ids = {d.id for d in batch}
    categorized_at = datetime.now(timezone.utc).isoformat()
    categorizations: list[DefectCategorization] = []
    for entry in result.get("results", []):
        defect_id = entry.get("defect_id")
        if defect_id not in known_ids:
            logger.warning("LLM returned unknown defect_id %s; skipping.", defect_id)
            continue
        category = entry.get("root_cause_category")
        if category not in _VALID_CATEGORIES:
            logger.warning(
                "LLM returned invalid root_cause_category %r for defect %s; using 'unknown'.",
                category,
                defect_id,
            )
            category = "unknown"
        sdlc_phase = entry.get("sdlc_phase")
        if sdlc_phase not in _VALID_SDLC_PHASES:
            logger.warning(
                "LLM returned invalid sdlc_phase %r for defect %s; using 'unknown'.",
                sdlc_phase,
                defect_id,
            )
            sdlc_phase = "unknown"
        categorizations.append(
            DefectCategorization(
                defect_id=defect_id,
                root_cause_category=category,
                testing_gap_flag=bool(entry.get("testing_gap_flag", False)),
                summary=entry.get("summary", ""),
                confidence=_parse_confidence(entry.get("confidence"), defect_id),
                sdlc_phase=sdlc_phase,
                model=provider.model_name,
                prompt_version=_PROMPT_VERSION,
                categorized_at=categorized_at,
            )
        )

    missing = known_ids - {c.defect_id for c in categorizations}
    if missing:
        raise LlmProviderError(
            f"LLM did not return categorizations for defect ids: {sorted(missing)}"
        )
    return categorizations


def _parse_confidence(raw: object, defect_id: int) -> float:
    """Coerce the model's confidence to a usable 0.0-1.0 float.

    A bare `float()` here would crash the whole batch on a string like "high",
    and would happily store a nonsense 5.0 that then skews the needs-review
    threshold.
    """
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        logger.warning(
            "LLM returned non-numeric confidence %r for defect %s; using 0.0.", raw, defect_id
        )
        return 0.0
    if not 0.0 <= value <= 1.0:
        logger.warning(
            "LLM returned out-of-range confidence %r for defect %s; clamping.", value, defect_id
        )
    return min(max(value, 0.0), 1.0)
