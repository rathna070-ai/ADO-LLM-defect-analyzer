"""Home view: pick a source, load defects, choose which uploads to analyze.

Uploads are kept as distinct batches rather than accumulating into one pool,
so a user can load several exports and run the analyzer against only the ones
they care about.
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

import streamlit as st

from ado_defect_analysis.ado_query import AdoQueryUrlError, parse_query_url
from ado_defect_analysis.config import Config
from ado_defect_analysis.pipeline.categorize import CategorizeProgress, run_categorize
from ado_defect_analysis.pipeline.fetch import run_fetch_from_excel, run_fetch_from_query
from ado_defect_analysis.storage import DefectStore

_UPLOAD = "Upload file"
_QUERY = "ADO link"
#: Observed round-trip for one batch, used only for the up-front estimate.
_SECONDS_PER_BATCH = 20


def _format_duration(seconds: float) -> str:
    if seconds < 90:
        return f"{max(int(seconds), 1)} seconds"
    return f"{seconds / 60:.0f} minutes"


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

        if not selected:
            st.caption("Select at least one upload.")
        elif not queued:
            st.caption(
                "Everything in the selected upload(s) is already analyzed — "
                "tick *Re-run already analyzed* to process it again."
            )
        else:
            st.caption(
                f"{queued} defect(s) in {batches} batch(es). Expect roughly "
                f"{_format_duration(batches * _SECONDS_PER_BATCH)}. Each batch is saved as "
                "it finishes, so nothing is lost if this stops partway — but **keep this "
                "tab open**, because closing it ends the run."
            )

        if st.button("Run analyzer", type="primary", disabled=not queued):
            _run(config, selected, rerun_analyzed)

    if processed and st.button("View dashboard"):
        st.session_state["page"] = "dashboard"
        st.rerun()


def _run(config: Config, sources: list[str], rerun_analyzed: bool) -> None:
    progress_bar = st.progress(0.0)
    status = st.empty()
    started = time.monotonic()

    def _report(update: CategorizeProgress) -> None:
        fraction = update.defects_done / max(update.defects_total, 1)
        elapsed = time.monotonic() - started
        remaining = (elapsed / fraction - elapsed) if fraction else 0.0
        note = f" · {update.failed_batches} batch(es) failed" if update.failed_batches else ""
        progress_bar.progress(min(fraction, 1.0))
        status.markdown(
            f"Batch **{update.batch_index}/{update.batch_count}** · "
            f"**{update.defects_done}/{update.defects_total}** defects · "
            f"about {_format_duration(remaining)} left{note}"
        )

    try:
        count = run_categorize(
            config,
            recategorize_all=rerun_analyzed,
            on_progress=_report,
            sources=sources,
        )
    except Exception as exc:
        progress_bar.empty()
        status.empty()
        st.error(f"Analysis failed: {exc}")
        return

    progress_bar.empty()
    status.empty()
    st.success(f"Analyzed {count} defect(s).")
    st.session_state["page"] = "dashboard"
    st.rerun()
