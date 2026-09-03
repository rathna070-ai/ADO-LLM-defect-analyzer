"""Phase 2: batch uncategorized defects to the LLM for structured root-cause
classification.

Batching is by fixed group size, not by module/sprint as a first cut — the
prompt gives the model each defect's module already, and grouping by a fixed
size keeps prompt length predictable regardless of how lopsided the module
distribution is. Swap in a group-by-module batcher later if per-module
context turns out to matter for accuracy.
"""

from __future__ import annotations

import json
import logging
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

_VALID_CATEGORIES = set(
    _SCHEMA["properties"]["results"]["items"]["properties"]["root_cause_category"]["enum"]
)


def run_categorize(config: Config, provider: LlmProvider | None = None) -> int:
    """Returns the number of defects newly categorized."""
    store = DefectStore(config.db_path)
    provider = provider or get_llm_provider(config.llm)

    pending = store.get_uncategorized_defects()
    if not pending:
        logger.info("No uncategorized defects found.")
        return 0

    batch_size = config.llm.categorize_batch_size
    total = 0
    for start in range(0, len(pending), batch_size):
        batch = pending[start : start + batch_size]
        categorizations = _categorize_batch(provider, batch, config)
        store.save_categorizations(categorizations)
        total += len(categorizations)
        logger.info(
            "Categorized defects %d-%d of %d.",
            start + 1,
            start + len(batch),
            len(pending),
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
                    "resolution_notes": d.resolution_notes[:2000],
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
        categorizations.append(
            DefectCategorization(
                defect_id=defect_id,
                root_cause_category=category,
                testing_gap_flag=bool(entry.get("testing_gap_flag", False)),
                summary=entry.get("summary", ""),
                confidence=float(entry.get("confidence", 0.0)),
            )
        )

    missing = known_ids - {c.defect_id for c in categorizations}
    if missing:
        raise LlmProviderError(
            f"LLM did not return categorizations for defect ids: {sorted(missing)}"
        )
    return categorizations
