"""Streamlit views for the defect-analysis app."""

from __future__ import annotations

import os

import streamlit as st

#: Architecture walkthrough shown behind the app's "How it works" link.
#: Overridable so a fork can point at its own docs without a code change; the
#: default is the published page for this repo. Note the hosted page is private
#: until its owner shares it, so a self-hosted deployment should set this to
#: something its own users can reach.
HELP_URL = os.environ.get(
    "HELP_PAGE_URL",
    "https://claude.ai/code/artifact/f910cb6e-4d84-475e-b1da-db0224cbbdf8",
)


def render_help_link(label: str = "How it works") -> None:
    """A quiet link to the architecture page, for both pages' headers.

    A real anchor rather than a button: it leaves the app entirely, so it
    opens in a new tab and the current run, filters, and upload selection stay
    exactly where they were.
    """
    st.markdown(
        f'<a href="{HELP_URL}" target="_blank" rel="noopener" '
        'style="font-size:.85rem;text-decoration:none;color:#2a78d6;font-weight:600">'
        f"{label} ↗</a>",
        unsafe_allow_html=True,
    )
