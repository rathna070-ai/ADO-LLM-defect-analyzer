"""Phase 3b: feed aggregated stats back to the LLM for an exec-tone narrative."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ..config import Config
from ..llm import LlmProvider, get_llm_provider
from .aggregate import build_aggregates, filter_by_closed_date, load_categorized_dataframe

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"

_SYSTEM_PROMPT = (_PROMPTS_DIR / "narrative_summary.md").read_text()
_SCHEMA = json.loads((_SCHEMAS_DIR / "narrative_summary.schema.json").read_text())


def run_report(
    config: Config,
    provider: LlmProvider | None = None,
    since: str | None = None,
    until: str | None = None,
) -> dict:
    """Returns the narrative dict (also matches narrative_summary.schema.json).

    `since`/`until` scope the narrative to defects closed in a window, so a
    quarterly summary doesn't have to mean "everything in the DB".
    """
    df = filter_by_closed_date(load_categorized_dataframe(config), since, until)
    aggregates = build_aggregates(
        df, config.rejected_resolutions, config.review_confidence_threshold
    )

    if aggregates["total_defects"] == 0:
        logger.warning("No categorized defects to report on. Run fetch and categorize first.")
        return {}

    provider = provider or get_llm_provider(config.llm)
    narrative = provider.complete_json(
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=json.dumps(aggregates, indent=2),
        schema=_SCHEMA,
        temperature=config.llm.temperature,
        max_tokens=config.llm.max_tokens,
    )

    logger.info(
        "Report run used %s.",
        provider.usage.summary(config.llm.cost_per_mtok_input, config.llm.cost_per_mtok_output),
    )

    config.output_dir.mkdir(parents=True, exist_ok=True)
    report_path = config.output_dir / "narrative_summary.json"
    report_path.write_text(json.dumps(narrative, indent=2))
    logger.info("Wrote narrative summary to %s", report_path)

    return narrative
