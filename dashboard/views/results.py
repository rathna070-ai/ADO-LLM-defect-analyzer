"""Dashboard view: the analysis result, plus export.

Reads straight from the SQLite DB the pipeline writes to, so it always shows
whatever the last fetch/categorize produced.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from ado_defect_analysis.config import Config
from ado_defect_analysis.pipeline.aggregate import (
    build_aggregates,
    load_categorized_dataframe,
    needs_review_mask,
)
from ado_defect_analysis.pipeline.export import run_export


def render(config: Config) -> None:
    header, back = st.columns([5, 1])
    header.title("Analysis results")
    if back.button("← Back"):
        st.session_state["page"] = "home"
        st.rerun()

    df = load_categorized_dataframe(config)
    if df.empty:
        st.warning("No analyzed defects yet. Load data and run the analysis first.")
        if st.button("Go to setup"):
            st.session_state["page"] = "home"
            st.rerun()
        return

    aggregates = build_aggregates(
        df, config.rejected_resolutions, config.review_confidence_threshold
    )

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total defects", aggregates["total_defects"])
    col2.metric("Testing-gap rate", f"{aggregates['testing_gap_rate']:.0%}")
    col3.metric("Areas affected", len(aggregates["module_density"]))
    col4.metric("Needs review", aggregates["needs_review_count"])

    _render_export(config)
    st.divider()

    st.subheader("Root cause distribution")
    st.bar_chart(aggregates["root_cause_distribution"])

    st.subheader("Defects by area path")
    st.bar_chart(aggregates["module_density"])

    st.subheader("Defects by area path × iteration path")
    area_options = ["All", *sorted(aggregates["area_iteration_distribution"])]
    selected_area = st.selectbox("Area path", area_options)
    scoped = df if selected_area == "All" else df[df["module"] == selected_area]
    pivot = scoped.pivot_table(
        index="module", columns="iteration_path", values="id", aggfunc="count", fill_value=0
    )
    st.bar_chart(pivot)
    st.dataframe(pivot, width="stretch")

    st.subheader("Root cause — major contributor by area path")
    contributors = pd.DataFrame(
        [
            {
                "RCA category": category,
                "Top area path": info["area_path"],
                "Count": info["count"],
                "% of category": f"{info['pct_of_category']:.0%}",
            }
            for category, info in aggregates["rca_major_contributor"].items()
        ]
    ).sort_values("Count", ascending=False)
    st.dataframe(contributors, width="stretch", hide_index=True)
    st.bar_chart(contributors.set_index("RCA category")["Count"])

    st.subheader("Valid vs rejected defects")
    split = aggregates["valid_vs_rejected"]
    resolved = split["valid"] + split["rejected"]
    vcol1, vcol2, vcol3 = st.columns(3)
    vcol1.metric("Valid", split["valid"])
    vcol2.metric("Rejected", split["rejected"])
    vcol3.metric("Rejection rate", f"{(split['rejected'] / resolved if resolved else 0):.0%}")
    st.bar_chart(pd.Series(split, name="count"))

    st.subheader("Root cause vs SDLC phase")
    sdlc = pd.DataFrame(aggregates["rca_sdlc_crosstab"]).fillna(0).T
    st.bar_chart(sdlc)
    st.dataframe(sdlc, width="stretch")

    st.subheader("Monthly trend")
    st.line_chart(aggregates["monthly_trend"])

    st.subheader("Needs review")
    st.caption(
        f"Confidence below {config.review_confidence_threshold:.0%}, or an unknown root "
        "cause / SDLC phase — audit these before trusting the rest."
    )
    review_df = df[needs_review_mask(df, config.review_confidence_threshold)].sort_values(
        "confidence"
    )
    if review_df.empty:
        st.success("Nothing flagged for review.")
    else:
        columns = ["id", "title", "root_cause_category", "sdlc_phase", "confidence"]
        # Present only after a re-run on the current prompt.
        if "evidence" in review_df.columns:
            columns.append("evidence")
        columns.append("summary")
        st.dataframe(review_df[columns], width="stretch", hide_index=True)

    st.subheader("Analyzed defects")
    st.dataframe(df, width="stretch")


def _render_export(config: Config) -> None:
    """Write the export files, then offer each as a download."""
    st.subheader("Export")
    if not st.button("Generate export files", type="primary"):
        st.caption(
            "Writes CSV/Excel for Power BI plus a needs-review triage list, then offers "
            "them as downloads."
        )
        return

    try:
        written = run_export(config)
    except Exception as exc:
        st.error(f"Export failed: {exc}")
        return

    if not written:
        st.warning("Nothing to export.")
        return

    st.success(f"Wrote {len(written)} file(s) to `{config.output_dir}`.")
    for column, path_text in zip(st.columns(len(written)), written, strict=False):
        path = Path(path_text)
        column.download_button(
            label=f"Download {path.name}",
            data=path.read_bytes(),
            file_name=path.name,
            mime="text/csv" if path.suffix == ".csv" else "application/octet-stream",
        )
