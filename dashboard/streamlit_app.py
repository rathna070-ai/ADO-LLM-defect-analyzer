"""Standalone Streamlit app for the defect-analysis pipeline.

Two pages behind a session-state router: setup (choose a data source, load
defects, run the analysis) and results (charts + export). Routing is explicit
rather than using Streamlit's `pages/` directory because the flow is ordered —
there's nothing to show on the results page until an analysis has run.

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

st.set_page_config(page_title="ADO Defect Analysis", page_icon="🔎", layout="wide")


# Deliberately not cached: reading .env is cheap, and caching it means an
# edited setting is ignored until the server restarts.
config = Config.from_env()

page = st.session_state.setdefault("page", "home")
if page == "dashboard":
    results.render(config)
else:
    home.render(config)
