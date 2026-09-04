"""Standalone Streamlit app for the defect-analysis pipeline.

Two pages: setup (choose a data source, load defects, run the analysis) and the
leadership dashboard. Which one renders is driven by the `view` query
parameter, so the dashboard has a real URL of its own and can be opened in a
new browser tab, bookmarked, or shared with someone who only wants the result.

Needs the package installed (`pip install -e ".[dashboard]"`), then:

    streamlit run dashboard/streamlit_app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# Streamlit executes this file as a script, so the sibling `views` package is
# only importable once its directory is on the path.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ado_defect_analysis.config import Config
from views import home, results

_DASHBOARD_VIEW = "dashboard"

# The query parameter is the source of truth so a bookmarked or newly-opened
# tab lands on the right page; session_state only mirrors it for in-page
# navigation.
_view = st.query_params.get("view") or st.session_state.get("page", "home")

st.set_page_config(
    page_title=(
        "Defect RCA — leadership summary" if _view == _DASHBOARD_VIEW else "AI RCA Analyzer"
    ),
    page_icon="🔎",
    layout="wide",
)

# Deliberately not cached: reading .env is cheap, and caching it means an
# edited setting is ignored until the server restarts.
config = Config.from_env()

if _view == _DASHBOARD_VIEW:
    results.render(config)
else:
    home.render(config)
