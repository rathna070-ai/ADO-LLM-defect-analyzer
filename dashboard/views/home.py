"""Home view: choose where defects come from, load them, run the analysis.

Two ingest routes, picked with a radio button, because the two audiences for
this tool have different access: some can hand over a PAT, some only have
"Open in Excel" on a saved query.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import streamlit as st

from ado_defect_analysis.ado_query import AdoQueryUrlError, parse_query_url
from ado_defect_analysis.config import Config
from ado_defect_analysis.pipeline.categorize import run_categorize
from ado_defect_analysis.pipeline.fetch import run_fetch_from_excel, run_fetch_from_query
from ado_defect_analysis.storage import DefectStore

_UPLOAD = "Upload a file from my computer"
_QUERY = "Azure DevOps query link"


def render(config: Config) -> None:
    st.title("ADO Defect Root-Cause Analysis")
    st.caption(
        "Load closed defects, have an LLM classify why each one happened, then explore "
        "the result and export it."
    )

    source = st.radio(
        "How do you want to provide the defect data?",
        (_UPLOAD, _QUERY),
        help=(
            "The upload path needs no Azure DevOps credentials. The query path pulls "
            "straight from ADO and needs a personal access token."
        ),
    )

    if source == _UPLOAD:
        _render_upload(config)
    else:
        _render_query(config)

    _render_analysis_section(config)


def _render_upload(config: Config) -> None:
    st.subheader("Upload an ADO export")
    st.markdown(
        "Export a query from Azure DevOps (**Open in Excel** or **Export to CSV**). "
        "Include **Tags**, **Comments**, **Iteration Path**, and **Resolution** columns "
        "if you can — each one gives the model more to reason about."
    )

    uploaded = st.file_uploader("Browse for a .xlsx or .csv export", type=["xlsx", "xls", "csv"])
    if st.button("Upload", type="primary", disabled=uploaded is None):
        # Streamlit hands back an in-memory buffer; the parser takes a path,
        # and the suffix is what selects the Excel vs CSV reader.
        suffix = Path(uploaded.name).suffix
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
            handle.write(uploaded.getbuffer())
            temp_path = Path(handle.name)
        try:
            with st.spinner(f"Reading {uploaded.name}…"):
                count = run_fetch_from_excel(config, temp_path)
        except Exception as exc:  # surfaced to the user, not swallowed
            st.error(f"Could not read that file: {exc}")
        else:
            st.success(f"Loaded {count} defect(s) from {uploaded.name}.")
        finally:
            temp_path.unlink(missing_ok=True)


def _render_query(config: Config) -> None:
    st.subheader("Pull from an Azure DevOps query")
    query_url = st.text_input(
        "Query URL",
        placeholder="https://dev.azure.com/your-org/your-project/_queries/query/<id>",
        help="Open the saved query in Azure DevOps and copy your browser's address bar.",
    )

    # Never written to disk — kept only for this session, so a PAT typed here
    # doesn't end up in .env or the database.
    pat = st.text_input(
        "Personal access token",
        type="password",
        help="Needs Work Items (read). Leave blank to use ADO_PAT from your .env.",
    )
    if not pat and config.ado.pat:
        st.caption("Using `ADO_PAT` from your .env.")

    if st.button("Fetch from Azure DevOps", type="primary", disabled=not query_url):
        try:
            ref = parse_query_url(query_url)
        except AdoQueryUrlError as exc:
            st.error(str(exc))
            return

        st.caption(f"Organization **{ref.organization}**, project **{ref.project}**.")
        try:
            with st.spinner("Querying Azure DevOps…"):
                count = run_fetch_from_query(config, query_url, pat=pat or None)
        except Exception as exc:
            st.error(f"Azure DevOps request failed: {exc}")
        else:
            if count:
                st.success(f"Loaded {count} defect(s) from the query.")
            else:
                st.warning("That query returned no work items.")


def _render_analysis_section(config: Config) -> None:
    st.divider()
    st.subheader("Run the analysis")

    store = DefectStore(config.db_path)
    loaded = len(store.get_all_defects())
    pending = len(store.get_uncategorized_defects())
    categorized = loaded - pending

    col1, col2, col3 = st.columns(3)
    col1.metric("Defects loaded", loaded)
    col2.metric("Already analyzed", categorized)
    col3.metric("Awaiting analysis", pending)

    if not loaded:
        st.info("Load some defects above first.")
        return

    model = config.llm.groq_model if config.llm.provider == "groq" else config.llm.copilot_model
    st.markdown(
        f"Sends the {pending or categorized} defect(s) to **{model}** in batches for "
        "root-cause and SDLC-phase classification."
    )
    redo = st.checkbox(
        "Re-analyze defects that already have results",
        help=(
            "Off by default: defects whose fields, prompt, and model are unchanged are "
            "skipped, so you don't pay twice for the same answer."
        ),
    )

    if st.button("Run analysis", type="primary"):
        try:
            with st.spinner("Classifying defects — this can take a minute…"):
                count = run_categorize(config, recategorize_all=redo)
        except Exception as exc:
            st.error(f"Analysis failed: {exc}")
            return

        st.success(f"Analyzed {count} defect(s).")
        st.session_state["page"] = "dashboard"
        st.rerun()

    if categorized and st.button("View dashboard"):
        st.session_state["page"] = "dashboard"
        st.rerun()
