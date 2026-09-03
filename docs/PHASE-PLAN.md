# Phase Plan — ADO Defect LLM Analysis

Status of each phase reflects what's in this scaffold today, not a future promise.

## Phase 0 — Scaffold (done)

- Project structure, config loading (`.env` + env vars), SQLite storage schema.
- `LlmProvider` abstraction with a working `GroqProvider` and a `CopilotProvider`
  placeholder, selected by `LLM_PROVIDER` — this is the future-proofing seam:
  moving to Copilot later means implementing one class, not touching pipeline code.
- Unit tests for storage, models, the LLM factory, and the Groq HTTP layer (mocked).

## Phase 1 — Get defects in: ADO API or Excel export

Two input paths, same downstream storage:

- **API path** — `ado_client.py`: WIQL query for closed/resolved/done work items of
  the configured type within a lookback window, then a batched `workitemsbatch`
  fetch for the fields needed downstream (title, description, area path, severity,
  resolution notes, tags, a configurable root-cause field, created/closed dates).
  Comment threads need a separate per-item call (no ADO batch endpoint for them),
  so they're opt-in via `ADO_FETCH_COMMENTS=true`.
  **To exercise**: set `ADO_ORGANIZATION`, `ADO_PROJECT`, `ADO_PAT` in `.env`, then
  `python -m ado_defect_analysis.cli fetch`.
- **Excel/CSV path** — `excel_source.py`: parses a hand-exported ADO extract
  (`.xlsx`/`.csv`), matching columns case-insensitively against known ADO header
  names (both display names and raw field references), with an override hook for
  nonstandard exports. No ADO credentials needed — this is the path for
  environments that won't issue API access, and it's actually cheaper than the API
  path for comments: a Comments column in the export costs nothing extra, versus
  N per-defect REST calls.
  **To exercise**: `python -m ado_defect_analysis.cli fetch --from-excel PATH`.

Either way, `pipeline/fetch.py` lands results in SQLite (`defects` table),
upserting by id so re-running fetch — from either source — is safe.

## Phase 2 — LLM categorization

- `pipeline/categorize.py` batches uncategorized defects (fixed batch size,
  `LLM_CATEGORIZE_BATCH_SIZE`) and asks the configured provider for structured JSON:
  root cause category, a testing-gap flag, a one-line summary, and a confidence score.
- Prompt lives in `prompts/categorize_defect.md`; the expected shape is
  `schemas/categorize_defect.schema.json`. The prompt is sent as plain instructions —
  Groq's JSON mode guarantees valid JSON, not schema conformance — so the pipeline
  validates the category enum and confirms every defect id in the batch got a result,
  raising rather than silently dropping one.
- **To exercise this phase**: set `GROQ_API_KEY`, then
  `python -m ado_defect_analysis.cli categorize`.

## Phase 3 — Aggregation and narrative

- `pipeline/aggregate.py` turns categorized defects into root-cause distribution,
  per-module defect density, and a month-over-month trend — plain dicts, not a
  DataFrame, so they serialize straight into the next prompt.
- `pipeline/report.py` feeds those aggregates to the LLM a second time for an
  exec-tone narrative (`prompts/narrative_summary.md`): headline, top root causes,
  hotspot modules, trend note, recommended actions. Written to
  `data/exports/narrative_summary.json`.
- **To exercise this phase**: `python -m ado_defect_analysis.cli report`.

## Phase 4 — Export for Power BI

- `pipeline/export.py` writes `categorized_defects.csv` and `.xlsx` to
  `data/exports/` — a drop-in second data source alongside the existing `QAEE (2)`
  table, joinable on module or closed date.
- **To exercise this phase**: `python -m ado_defect_analysis.cli export`, or run
  everything at once with `python -m ado_defect_analysis.cli run-all`.

## Phase 5 — Standalone dashboard (optional, done as a demo path)

- `dashboard/streamlit_app.py` reads the same SQLite DB and renders the same
  aggregates as a Streamlit app, for a demo that doesn't require Power BI installed.
  Run with `streamlit run dashboard/streamlit_app.py`.

## Phase 6 — Hardening (not started)

Candidates, roughly in the order they'd matter for a real quarterly run rather than
a portfolio demo:

- Retry/backoff on ADO and Groq HTTP calls (both currently fail fast on error).
- Batch categorization by module instead of fixed-size groups, if accuracy on
  cross-module batches turns out to be worse in practice.
- A `--since`/`--until` CLI flag for report and export, so a quarter's narrative
  doesn't have to mean "everything in the DB."
- Rate-limit-aware pacing for the categorize phase against Groq's per-minute limits
  once the defect volume is large enough to matter.

## Phase 7 — Copilot provider (future, placeholder only)

- Implement `llm/copilot_provider.py` for real once there's an API surface to target
  (GitHub Models' OpenAI-compatible endpoint is the likely fit). No pipeline code
  should need to change — `LLM_PROVIDER=copilot` is already a legal config value,
  `Config` already carries `copilot_api_key`/`copilot_model`, and the factory already
  wires the class in.
