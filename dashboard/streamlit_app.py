"""Optional standalone dashboard — a demo path that doesn't need Power BI installed.

Reads straight from the SQLite DB the pipeline already writes to, so it's
always showing whatever `fetch`/`categorize` last produced. Needs the package
installed (`pip install -e ".[dashboard]"`), then run with:

    streamlit run dashboard/streamlit_app.py
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ado_defect_analysis.config import Config
from ado_defect_analysis.pipeline.aggregate import (
    build_aggregates,
    load_categorized_dataframe,
    needs_review_mask,
)

st.set_page_config(page_title="ADO Defect Analysis", layout="wide")
st.title("ADO Defect Root-Cause Analysis")

config = Config.from_env()
df = load_categorized_dataframe(config)

if df.empty:
    st.warning(
        "No categorized defects found. Run `python -m ado_defect_analysis.cli run-all` first."
    )
    st.stop()

aggregates = build_aggregates(df, config.rejected_resolutions, config.review_confidence_threshold)

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total defects", aggregates["total_defects"])
col2.metric("Testing-gap rate", f"{aggregates['testing_gap_rate']:.0%}")
col3.metric("Areas affected", len(aggregates["module_density"]))
col4.metric("Needs review", aggregates["needs_review_count"])

st.subheader("Root cause distribution")
st.bar_chart(aggregates["root_cause_distribution"])

st.subheader("Defects by area path")
st.bar_chart(aggregates["module_density"])

st.subheader("Defects by area path × iteration path")
area_options = ["All", *sorted(aggregates["area_iteration_distribution"].keys())]
selected_area = st.selectbox("Area path", area_options)
iteration_df = df if selected_area == "All" else df[df["module"] == selected_area]
iteration_pivot = iteration_df.pivot_table(
    index="module", columns="iteration_path", values="id", aggfunc="count", fill_value=0
)
st.bar_chart(iteration_pivot)
st.dataframe(iteration_pivot, use_container_width=True)

st.subheader("Root cause — major contributor by area path")
contributor_rows = [
    {
        "RCA category": category,
        "Top area path": info["area_path"],
        "Count": info["count"],
        "% of category": f"{info['pct_of_category']:.0%}",
    }
    for category, info in aggregates["rca_major_contributor"].items()
]
contributor_df = pd.DataFrame(contributor_rows).sort_values("Count", ascending=False)
st.dataframe(contributor_df, use_container_width=True, hide_index=True)
st.bar_chart(contributor_df.set_index("RCA category")["Count"])

st.subheader("Valid vs rejected defects")
valid_vs_rejected = aggregates["valid_vs_rejected"]
total_resolved = valid_vs_rejected["valid"] + valid_vs_rejected["rejected"]
rejection_rate = valid_vs_rejected["rejected"] / total_resolved if total_resolved else 0.0
vcol1, vcol2, vcol3 = st.columns(3)
vcol1.metric("Valid", valid_vs_rejected["valid"])
vcol2.metric("Rejected", valid_vs_rejected["rejected"])
vcol3.metric("Rejection rate", f"{rejection_rate:.0%}")
st.bar_chart(pd.Series(valid_vs_rejected, name="count"))

st.subheader("Root cause vs SDLC phase")
sdlc_df = pd.DataFrame(aggregates["rca_sdlc_crosstab"]).fillna(0).T
st.bar_chart(sdlc_df)
st.dataframe(sdlc_df, use_container_width=True)

st.subheader("Monthly trend")
st.line_chart(aggregates["monthly_trend"])

st.subheader("Needs review")
st.caption(
    f"Confidence below {config.review_confidence_threshold:.0%}, or an unknown "
    "root cause / SDLC phase — audit these before trusting the rest."
)
review_df = df[needs_review_mask(df, config.review_confidence_threshold)].sort_values("confidence")
if review_df.empty:
    st.success("Nothing flagged for review.")
else:
    st.dataframe(
        review_df[["id", "title", "root_cause_category", "sdlc_phase", "confidence", "summary"]],
        use_container_width=True,
        hide_index=True,
    )

st.subheader("Categorized defects")
st.dataframe(df, use_container_width=True)
