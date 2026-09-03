"""Home view: pick a source, load defects, choose which uploads to analyze.

Uploads are kept as distinct batches rather than accumulating into one pool,
so a user can load several exports and run the analyzer against only the ones
they care about.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import streamlit as st

from ado_defect_analysis.ado_query import AdoQueryUrlError, parse_query_url
from ado_defect_analysis.background import RUN
from ado_defect_analysis.config import Config
from ado_defect_analysis.pipeline.fetch import run_fetch_from_excel, run_fetch_from_query
from ado_defect_analysis.storage import DefectStore

_UPLOAD = "Upload file"
_QUERY = "ADO link"

# Token cost of one call, measured rather than guessed: the system prompt and
# schema are re-sent every time (~2,650), each defect adds ~126 of prompt and
# ~85 of output, and a reasoning model spends ~1,200 thinking before it emits
# anything. Used only to estimate a run before the first batch lands; observed
# throughput takes over immediately afterwards.
_TOKENS_FIXED = 2650
_TOKENS_PROMPT_PER_DEFECT = 126
_TOKENS_OUTPUT_PER_DEFECT = 85
_TOKENS_REASONING = 1200
#: Groq free-tier budget, enforced per organization.
_TOKENS_PER_MINUTE = 8000


def _format_duration(seconds: float) -> str:
    if seconds < 90:
        return f"{max(int(seconds), 1)} seconds"
    return f"{seconds / 60:.0f} minutes"


def _estimate_seconds(queued: int, batch_size: int) -> float:
    """Rough run time, bounded by the token budget rather than by latency.

    Throughput here is capped by tokens per minute, not by how fast the model
    answers — so the estimate comes from how many calls the budget allows, not
    from a per-batch stopwatch constant.
    """
    if queued <= 0:
        return 0.0
    batches = -(-queued // batch_size)
    tokens_per_call = (
        _TOKENS_FIXED
        + (_TOKENS_PROMPT_PER_DEFECT + _TOKENS_OUTPUT_PER_DEFECT) * batch_size
        + _TOKENS_REASONING
    )
    minutes_per_call = max(tokens_per_call / _TOKENS_PER_MINUTE, 0.0)
    return batches * minutes_per_call * 60


def render(config: Config) -> None:
    st.title("AI RCA Analyzer")

    _render_source_picker()
    # Defaults to upload rather than staying blank until Start is pressed —
    # an empty panel on first load reads as broken.
    if st.session_state.get("source_mode", _UPLOAD) == _UPLOAD:
        _render_upload(config)
    else:
        _render_query(config)

    _render_analysis_panel(config)


def _render_source_picker() -> None:
    """Panel 1 — choose where the data comes from, then Start."""
    with st.container(border=True):
        choice = st.radio(
            "Data source",
            (_UPLOAD, _QUERY),
            horizontal=True,
            label_visibility="collapsed",
            index=0 if st.session_state.get("source_mode", _UPLOAD) == _UPLOAD else 1,
        )
        if st.button("Start", type="primary"):
            st.session_state["source_mode"] = choice
            st.rerun()


def _render_upload(config: Config) -> None:
    """Panel 2a — browse and upload a file."""
    with st.container(border=True):
        uploaded = st.file_uploader(
            "Browse file", type=["xlsx", "xls", "csv"], label_visibility="collapsed"
        )
        if st.button("Upload", disabled=uploaded is None):
            # Streamlit gives an in-memory buffer; the parser takes a path, and
            # the suffix selects the Excel vs CSV reader. The user's original
            # filename is passed separately so the batch is labelled usefully
            # rather than by the temp file's generated name.
            suffix = Path(uploaded.name).suffix
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
                handle.write(uploaded.getbuffer())
                temp_path = Path(handle.name)
            try:
                with st.spinner(f"Reading {uploaded.name}…"):
                    count = run_fetch_from_excel(config, temp_path, source_name=uploaded.name)
            except Exception as exc:
                st.error(f"Could not read that file: {exc}")
            else:
                st.success(f"Loaded {count} defect(s) from {uploaded.name}.")
                st.rerun()
            finally:
                temp_path.unlink(missing_ok=True)


def _render_query(config: Config) -> None:
    """Panel 2b — pull straight from a saved ADO query."""
    with st.container(border=True):
        query_url = st.text_input(
            "ADO query link",
            placeholder="https://dev.azure.com/your-org/your-project/_queries/query/<id>",
            help="Open the saved query in Azure DevOps and copy your browser's address bar.",
        )
        # Never written to disk — kept for this session only, so a PAT typed
        # here doesn't end up in .env or the database.
        pat = st.text_input(
            "Personal access token",
            type="password",
            help="Needs Work Items (read). Leave blank to use ADO_PAT from your .env.",
        )
        if not pat and config.ado.pat:
            st.caption("Using `ADO_PAT` from your .env.")

        if st.button("Fetch from Azure DevOps", disabled=not query_url):
            try:
                parse_query_url(query_url)
            except AdoQueryUrlError as exc:
                st.error(str(exc))
                return
            try:
                with st.spinner("Querying Azure DevOps…"):
                    count = run_fetch_from_query(config, query_url, pat=pat or None)
            except Exception as exc:
                st.error(f"Azure DevOps request failed: {exc}")
            else:
                if count:
                    st.success(f"Loaded {count} defect(s) from the query.")
                    st.rerun()
                else:
                    st.warning("That query returned no work items.")


def _render_analysis_panel(config: Config) -> None:
    """Panel 3 — counts, the upload picker, and the run button."""
    store = DefectStore(config.db_path)
    sources = store.get_upload_sources()

    with st.container(border=True):
        total = sum(s["total"] for s in sources)
        processed = sum(s["categorized"] for s in sources)

        col1, col2, col3 = st.columns(3)
        col1.metric("Total defects", total)
        col2.metric("Processed", processed)
        col3.metric("Unprocessed", total - processed)

        if not sources:
            st.info("Load some defects above to get started.")
            return

        st.markdown("**Select the uploads to analyze**")
        selected: list[str] = []
        for index, source in enumerate(sources):
            label = (
                f"{source['name']} — {source['total']} defect(s), {source['categorized']} analyzed"
            )
            # Default to anything with outstanding work, so the common case is
            # one click.
            if st.checkbox(label, value=source["uncategorized"] > 0, key=f"src_{index}"):
                selected.append(source["name"])

        rerun_analyzed = st.toggle(
            "Re-run already analyzed",
            help=(
                "Off by default: defects whose fields, prompt, and model are unchanged "
                "are skipped, so you don't pay twice for the same answer."
            ),
        )

        chosen = [s for s in sources if s["name"] in selected]
        queued = sum(s["total"] if rerun_analyzed else s["uncategorized"] for s in chosen)
        batch_size = config.llm.categorize_batch_size
        batches = -(-queued // batch_size) if queued else 0
        model = config.llm.groq_model if config.llm.provider == "groq" else config.llm.copilot_model
        running = RUN.is_active()

        if running:
            st.info("A run is already in progress — see below.")
        elif not selected:
            st.caption("Select at least one upload.")
        elif not queued:
            st.caption(
                "Everything in the selected upload(s) is already analyzed — "
                "tick *Re-run already analyzed* to process it again."
            )
        else:
            st.markdown(
                f"Sends **{queued}** defect(s) to **{model}** in **{batches}** batch(es) "
                f"of {batch_size} for root-cause and SDLC-phase classification."
            )
            st.caption(
                f"Expect roughly {_format_duration(_estimate_seconds(queued, batch_size))} — "
                f"throughput is capped by the {_TOKENS_PER_MINUTE:,} tokens/minute budget, "
                "not by model speed. The run continues in the background, so you can close "
                "this tab and come back to it."
            )

        if st.button("Run analyzer", type="primary", disabled=running or not queued):
            RUN.start(config, sources=selected, recategorize_all=rerun_analyzed)
            st.rerun()

    _render_run_progress()

    if processed and not RUN.is_active() and st.button("View dashboard"):
        st.session_state["page"] = "dashboard"
        st.rerun()


@st.fragment(run_every=2)
def _render_run_progress() -> None:
    """Live view of the background run, refreshed on its own every 2s.

    A fragment reruns only itself, so this ticks without re-executing the page
    or blocking anything. Rendered outside the bordered panel so the bar gets
    full width.
    """
    status = RUN.status()
    if not status.has_run:
        return

    if status.error:
        st.error(f"Analysis failed: {status.error}")
        return

    if not status.active:
        analyzed = status.result_count if status.result_count is not None else status.defects_done
        message = f"Analyzed {analyzed} defect(s) in {_format_duration(status.elapsed_seconds)}."
        if status.failed_batches:
            message += f" {status.failed_batches} batch(es) failed — see the log."
        st.success(message)
        return

    st.progress(status.fraction)
    eta = status.eta_seconds()
    # A batch is a single LLM call, so there is no true sub-batch progress to
    # report. The elapsed timer is what shows it is alive in the meantime.
    if status.batch_count:
        line = (
            f"Batch **{status.batch_index + 1}/{status.batch_count}** in progress · "
            f"**{status.defects_done}/{status.defects_total}** defects done · "
            f"running for {_format_duration(status.elapsed_seconds)}"
        )
        line += f" · about {_format_duration(eta)} left" if eta else ""
    else:
        line = f"Starting first batch · running for {_format_duration(status.elapsed_seconds)}"
    if status.failed_batches:
        line += f" · {status.failed_batches} batch(es) failed"
    st.markdown(line)
