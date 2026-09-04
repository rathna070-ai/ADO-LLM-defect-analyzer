# ADO Defect LLM Analysis

[![CI](https://github.com/rathna070-ai/ADO-LLM-defect-analyzer/actions/workflows/ci.yml/badge.svg)](https://github.com/rathna070-ai/ADO-LLM-defect-analyzer/actions/workflows/ci.yml)

Pulls closed defects out of Azure DevOps — via the API or a hand-exported Excel/CSV
extract — has an LLM classify root cause, SDLC phase, and testing gaps, aggregates
the results, and exports them for Power BI (or a standalone Streamlit dashboard).
The "AI does judgment, human/BI tool does presentation" companion to
[Web Test Toolkit](https://github.com/rathna070-ai/automation_testing_toolkit-c).

See [docs/PHASE-PLAN.md](docs/PHASE-PLAN.md) for what each phase does and its
current status.

## Setup

```bash
git clone https://github.com/rathna070-ai/ADO-LLM-defect-analyzer.git
cd ADO-LLM-defect-analyzer
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev,dashboard]"

cp .env.example .env
# fill in ADO_ORGANIZATION / ADO_PROJECT / ADO_PAT and GROQ_API_KEY
```

The install is editable, so the package is importable everywhere (tests and the
dashboard rely on that rather than any `sys.path` juggling). `.env.example`
documents every setting the pipeline reads.

## Run it

```bash
# one defect-analysis pass end to end
ado-defect-analysis run-all

# or step by step
ado-defect-analysis fetch
ado-defect-analysis categorize
ado-defect-analysis report
ado-defect-analysis export

# optional standalone dashboard
streamlit run dashboard/streamlit_app.py
```

`python -m ado_defect_analysis <command>` works identically if you'd rather not
use the console script.

Output lands in `data/`: `defects.db` (SQLite — raw pull + categorizations) and
`exports/` (`categorized_defects.csv`/`.xlsx`, `needs_review.csv`,
`narrative_summary.json`). Both are gitignored; regenerate them by re-running the
pipeline.

### Re-categorizing existing defects

`categorize` only sends defects that have no categorization yet. After a prompt
change, a model change, or a new categorization field, backfill everything with:

```bash
ado-defect-analysis categorize --recategorize-all
```

Every categorization records the model, a prompt fingerprint, a timestamp, and a
hash of the fields the model was shown. A re-run **skips any defect where all
three of those inputs are unchanged**, since re-asking would buy the same answer
at full token price — so backfilling one new field costs only the defects it
actually affects. Add `--force` to re-send everything anyway (e.g. to resample a
non-deterministic model).

Each run logs what it spent: `12 LLM call(s), 41,204 prompt + 9,102 completion =
50,306 tokens`. Set `LLM_COST_PER_MTOK_INPUT`/`_OUTPUT` to your model's current
rates to get a dollar estimate alongside it.

### Scoping to a date range

`report`, `export`, and `run-all` accept `--since`/`--until` (on closed date), so a
quarterly summary doesn't have to mean everything in the database:

```bash
ado-defect-analysis report --since 2026-01-01 --until 2026-03-31
```

### Trusting the output

The LLM emits a confidence score per defect. Anything below
`REVIEW_CONFIDENCE_THRESHOLD` (0.6 by default), or classified `unknown`, is
written to `data/exports/needs_review.csv` and surfaced in the dashboard's "Needs
review" section — audit those before taking the rest at face value.

## Getting defects in: ADO API or an Excel export

Two ways to populate `defects.db` — pick whichever matches what access you actually have:

**Direct API** (`fetch`, no flag) — needs `ADO_ORGANIZATION`, `ADO_PROJECT`, `ADO_PAT`
in `.env`. Queries ADO's WIQL endpoint for closed/resolved/done work items, then
batch-fetches fields for each. Comment threads are *not* pulled by default (ADO has
no batch endpoint for comments — it's one REST call per work item); set
`ADO_FETCH_COMMENTS=true` to turn that on if you want them and can afford the extra
calls.

**Excel/CSV import** (`fetch --from-excel PATH`) — no PAT, no API access, no
`ADO_ORGANIZATION`/`ADO_PROJECT` needed at all. Point it at a file exported from ADO
by hand (a query's "Open in Microsoft Excel," or "Export to CSV"):

```bash
python -m ado_defect_analysis.cli fetch --from-excel path/to/defects_export.xlsx
# or run the whole pipeline against the export in one shot
python -m ado_defect_analysis.cli run-all --from-excel path/to/defects_export.xlsx
```

Column headers are matched case-insensitively against both the display name ADO
shows in the UI ("Title", "Area Path", "Tags") and the raw field reference name
("System.Title", "System.AreaPath", "System.Tags") — a typical export just works.
Include a **Tags** and a **Comments** column in the export (add them to the query's
column options before exporting) and both flow into the categorization prompt as
extra signal, the same as the API path's `ADO_FETCH_COMMENTS=true` would give you,
at zero extra API cost. Only `ID` and `Title` are required; everything else is
optional and defaults to blank if the column isn't present. If your export uses
unusual header names, pass a `column_map` to `parse_excel()`
(`src/ado_defect_analysis/excel_source.py`) rather than renaming the sheet.

## Tests and checks

```bash
pytest                    # or: pytest --cov
ruff check . && ruff format --check .
mypy
```

All tests run offline — the ADO and Groq HTTP layers are mocked (`responses`), and
the LLM pipeline stages take an injectable `LlmProvider`, so no API key is needed
to run the suite. CI runs the same four commands on Python 3.10–3.12.

`pre-commit install` wires ruff into your commit hook if you want the formatting
enforced locally.

## LLM provider: Groq or Azure AI Foundry

`LLM_PROVIDER` in `.env` picks the backend. Every pipeline stage codes against the
`LlmProvider` interface (`src/ado_defect_analysis/llm/base.py`) and never imports a
vendor directly, so switching is a config change:

- `LLM_PROVIDER=groq` (default) — Groq's OpenAI-compatible chat completions API.
  Needs `GROQ_API_KEY`, defaults to `openai/gpt-oss-120b` at low reasoning effort.
  `GROQ_API_KEY` accepts a comma-separated list, though note Groq enforces its
  rate limit **per organization**, so extra keys from the same account add no
  throughput.
- `LLM_PROVIDER=azure` — Azure AI Foundry. Needs `AZURE_API_KEY`,
  `AZURE_BASE_URL` (`https://<your-resource>.openai.azure.com/openai/v1`) and
  `AZURE_DEPLOYMENT`. Two things differ from Groq: the deployment *name* goes in
  `AZURE_DEPLOYMENT` rather than a publisher-qualified model id, and there is no
  default base URL because the endpoint belongs to your resource. Foundry quota is
  set per deployment, which is the reason to move if a free tier's daily token cap
  is the constraint.
  *Not yet exercised against a live resource — the contract is covered by mocked
  tests, so treat your first real run as the verification step. Two things to
  confirm then: whether the deployment accepts `response_format: json_object`, and
  whether it wants `max_completion_tokens` instead of `max_tokens` (o-series does).*

`LLM_PROVIDER=copilot` used to mean GitHub Models. That surface was **retired on
30 July 2026**; the value is still recognised, but only to raise a message
pointing at `azure` rather than failing with a 404. GitHub Copilot itself is an
IDE assistant with no general inference API, so it cannot back this pipeline.

Both providers are thin subclasses of `llm/openai_compatible.py`, which holds the
shared request/JSON-mode/error/usage handling — adding another OpenAI-compatible
backend is roughly ten lines.

## Repository layout

```
pyproject.toml        Packaging, deps/extras, and ruff/mypy/pytest/coverage config
src/ado_defect_analysis/
  config.py           Env-driven settings (ADO connection, LLM provider + keys, paths)
  models.py           Defect / DefectCategorization dataclasses
  http.py              Shared retrying/backing-off requests session
  ado_client.py        Azure DevOps WIQL query + batched work-item fetch (API path)
  excel_source.py       ADO Excel/CSV export parser (no-API path)
  storage.py              SQLite persistence (defects, categorizations, migrations)
  llm/
    base.py             LlmProvider interface + token accounting
    openai_compatible.py  Shared transport for OpenAI-dialect APIs
    groq_provider.py       Groq endpoint/wording
    azure_provider.py       Azure AI Foundry endpoint/wording
    factory.py               LLM_PROVIDER -> LlmProvider
  prompts/               Markdown prompt templates
  schemas/                Expected JSON response shapes
  pipeline/
    fetch.py              Phase 1 — ADO API or Excel/CSV -> SQLite
    categorize.py          Phase 2 — batch LLM categorization
    aggregate.py            Phase 3a — stats from categorized defects
    report.py                Phase 3b — LLM narrative summary
    export.py                 Phase 4 — CSV/Excel for Power BI + needs-review triage
  cli.py                       Entrypoint: fetch / categorize / report / export / run-all
dashboard/streamlit_app.py     Phase 5 — optional standalone dashboard
tests/                          pytest suite, all offline
docs/PHASE-PLAN.md              Phase-by-phase plan and status
.github/workflows/ci.yml        Lint, format, type-check, and test on 3.10-3.12
```
