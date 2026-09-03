"""Optional standalone dashboard — a demo path that doesn't need Power BI installed.

Reads straight from the SQLite DB the pipeline already writes to, so it's
always showing whatever `fetch`/`categorize` last produced. Run with:

    streamlit run dashboard/streamlit_app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import streamlit as st

from ado_defect_analysis.config import Config
from ado_defect_analysis.pipeline.aggregate import build_aggregates, load_categorized_dataframe

st.set_page_config(page_title="ADO Defect Analysis", layout="wide")
st.title("ADO Defect Root-Cause Analysis")

config = Config.from_env()
df = load_categorized_dataframe(config)

if df.empty:
    st.warning(
        "No categorized defects found. Run `python -m ado_defect_analysis.cli run-all` first."
    )
    st.stop()

aggregates = build_aggregates(df)

col1, col2, col3 = st.columns(3)
col1.metric("Total defects", aggregates["total_defects"])
col2.metric("Testing-gap rate", f"{aggregates['testing_gap_rate']:.0%}")
col3.metric("Modules affected", len(aggregates["module_density"]))

st.subheader("Root cause distribution")
st.bar_chart(aggregates["root_cause_distribution"])

st.subheader("Defect density by module")
st.bar_chart(aggregates["module_density"])

st.subheader("Monthly trend")
st.line_chart(aggregates["monthly_trend"])

st.subheader("Categorized defects")
st.dataframe(df, use_container_width=True)
