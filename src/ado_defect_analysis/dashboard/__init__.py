"""Streamlit UI, shipped inside the package.

It lives here rather than at the repo root so `pip install` carries it: a
wheel only contains what is under the package, and a dashboard that only
works from a git checkout is not deployable. `cli.py`'s `dashboard` command
locates `streamlit_app.py` through this package and hands it to Streamlit.
"""

from __future__ import annotations

from pathlib import Path

#: Absolute path to the Streamlit entry script, wherever the package installed.
APP_PATH = Path(__file__).resolve().parent / "streamlit_app.py"
