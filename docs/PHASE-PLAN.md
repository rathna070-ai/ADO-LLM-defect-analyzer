# Phase Plan — ADO Defect LLM Analysis

Status of each phase reflects what's in this scaffold today, not a future promise.

## Phase 0 — Scaffold (done)

- Project structure, config loading (`.env` + env vars), SQLite storage schema.
- `LlmProvider` abstraction with a working `GroqProvider` and a second provider
  placeholder, selected by `LLM_PROVIDER` — this is the future-proofing seam:
  swapping backends later means implementing one class, not touching pipeline code.
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
  root cause category, SDLC phase, a testing-gap flag, a one-line summary, and a
  confidence score. The prompt is given `state`, `disposition`, `root_cause_raw`,
  `resolution_notes`, `tags`, and `comments` and told to cross-reference them
  rather than judging on title/description alone.
- `--recategorize-all` re-runs every defect in the DB, for backfilling after a
  prompt or model change; each row records the model, prompt fingerprint, and
  timestamp that produced it.
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

- `dashboard/streamlit_app.py` reads the same SQLite DB and renders the aggregates as
  a Streamlit app, for a demo that doesn't require Power BI installed.
  Run with `streamlit run dashboard/streamlit_app.py`.
- Sections: root-cause distribution, defects by area path, area path × iteration path,
  RCA major contributor, valid vs rejected, RCA vs SDLC phase, monthly trend, and the
  needs-review triage list.
- Supporting this needed `iteration_path` and a structured `resolution` field carried
  end to end (ADO API + Excel import + SQLite), plus an LLM-classified `sdlc_phase`
  alongside `root_cause_category`.

## Phase 6 — Hardening (done)

- **Retry/backoff** — `http.py` builds one retrying `requests.Session` (429 + 5xx,
  exponential backoff, honours `Retry-After`) shared by the ADO client and the Groq
  provider. This also covers the rate-limit pacing the categorize phase needed.
- **Timeouts** — every ADO call now passes one (`ADO_REQUEST_TIMEOUT_SECONDS`);
  previously they could hang indefinitely.
- **Batch failure isolation** — one bad batch is logged and skipped instead of
  aborting the whole categorize run; it only raises if every batch failed.
- **Input resilience** — HTML entities are unescaped before prompting, non-numeric
  ID rows in an Excel export are skipped, and malformed confidence values are
  coerced and clamped.

## Phase 6b — Project scaffolding (done)

- `pyproject.toml` (PEP 621): packaging, `ado-defect-analysis` console script,
  `dashboard`/`dev` extras, and config for ruff, mypy, pytest, and coverage.
- GitHub Actions CI running lint, format check, type check, and tests on Python
  3.10–3.12; pre-commit config; MIT license.
- Categorization provenance (`model`, `prompt_version`, `categorized_at`) and a
  confidence-driven `needs_review.csv` triage export.

## Phase 7 — Efficiency, validation, and reporting controls (done)

- **Content-hash skip** — each categorization stores an `input_hash` of the exact
  fields the model was shown. `--recategorize-all` skips any defect whose hash,
  prompt version, and model all match the stored answer, so a backfill only spends
  on work that could actually come out differently. `--force` overrides it.
- **Schema validation** — responses are checked against
  `categorize_defect.schema.json` with `jsonschema`. The default logs the offending
  field path and falls back to the existing lenient per-field handling;
  `LLM_STRICT_SCHEMA=true` rejects the batch instead.
- **Token/cost tracking** — providers accumulate prompt/completion tokens from each
  response's `usage` block, and categorize and report log a run summary. Optional
  `LLM_COST_PER_MTOK_INPUT`/`_OUTPUT` add a dollar estimate; they default to 0 so
  no stale prices are baked in.
- **`--since`/`--until`** on report, export, and run-all, filtering by closed date.
  `--until` covers the whole end day; undated defects drop out once a bound is set.
- **Batch strategy** — `LLM_BATCH_STRATEGY=module` groups each area path into its
  own batches so they share context; `fixed` (the default) keeps prompt length
  predictable.

## Phase 8 — Second provider: GitHub Models, then Azure AI Foundry (done)

- Implemented first against **GitHub Models**, which spoke the OpenAI
  chat-completions dialect. The shared transport in `llm/openai_compatible.py`
  came out of that work: request shape, JSON mode, error wrapping and usage
  accounting live there, so each backend is a ~10-line subclass supplying an
  endpoint and its error wording.
- **GitHub Models was retired on 30 July 2026**, taking that endpoint with it, so
  the provider never ran against it live. GitHub's own notice points to Azure AI
  Foundry, and Copilot itself is an IDE assistant with no general inference API,
  so it was never a candidate to back this pipeline.
- Replaced by `llm/azure_provider.py` (`LLM_PROVIDER=azure`). Foundry is
  OpenAI-compatible over bearer auth, so the swap needed no new transport — only
  the endpoint, the deployment-name-as-model convention, and a required
  `AZURE_BASE_URL` with no default, since the endpoint belongs to your resource.
- `LLM_PROVIDER=copilot` still resolves, but only to raise a message explaining
  the retirement and pointing at `azure` — a pointed error beats a 404 from a
  host that no longer answers.
- The abstraction held: two backend changes, and no pipeline stage was touched.
- **Not yet exercised against a live Foundry resource.** Mocked tests cover the
  contract; the first real run should confirm the deployment accepts
  `response_format: json_object` and whether it wants `max_completion_tokens`
  rather than `max_tokens`.

## Remaining

Nothing in the phase plan is unbuilt. What's outstanding is verification rather than
code:

- The pipeline has never been run on real defects — every test uses a fake provider
  or mocked HTTP, so field mappings, prompt accuracy, and the dashboard are
  unvalidated against actual ADO data.
- The Azure AI Foundry provider needs one live run to confirm the endpoint contract.
