"""Leadership view of the RCA: the KPIs, where defects concentrate, and what
to do about it.

Ordered for someone reading it once in a meeting — headline KPIs, then the two
"who is contributing most" tables with their corrective actions, then the
supporting breakdowns. Percentage bases are labelled everywhere, because
mixing "% of total logged" with "% of analyzed" is the fastest way to mislead
a leadership audience.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from ado_defect_analysis.config import Config
from ado_defect_analysis.pipeline.aggregate import build_aggregates, load_categorized_dataframe
from ado_defect_analysis.pipeline.export import run_export

#: Commonly cited healthy band for rejected/invalid defects as a share of total
#: logged. Sustained rates above the upper bound usually indicate a
#: requirements or test-design problem rather than poor product quality.
_REJECTION_BENCHMARK = (0.10, 0.20)


def _pct(value: float) -> str:
    return f"{value:.0%}"


def _title(value: str) -> str:
    return value.replace("_", " ").title()


def render(config: Config) -> None:
    header, back = st.columns([5, 1])
    header.title("Defect RCA — leadership summary")
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

    agg = build_aggregates(
        df,
        config.rejected_resolutions,
        config.review_confidence_threshold,
        config.borderline_resolutions,
    )

    _render_kpis(agg)
    _render_data_quality(agg, config)
    st.divider()
    _render_quality_split(agg)
    _render_top_rca(agg)
    _render_top_areas(agg)
    st.divider()
    _render_breakdowns(df, agg)
    _render_export(config)


def _render_kpis(agg: dict) -> None:
    """Headline numbers, each labelled with the base it is a share of."""
    split = agg["valid_vs_rejected"]
    logged = sum(split.values()) or 1
    rejection_rate = split["rejected"] / logged
    severity = agg.get("severity_mix") or {}

    row1 = st.columns(4)
    row1[0].metric("Total logged", agg["total_defects"])
    row1[1].metric("Valid defects", split["valid"], help="Share of total logged.")
    row1[2].metric("Rejected", split["rejected"], help="Share of total logged.")
    row1[3].metric(
        "Borderline",
        split.get("borderline", 0),
        help=(
            "Cannot Reproduce / Not a Bug / Invalid — held separate rather than folded "
            "into either count, since it is a different claim from 'working as designed'."
        ),
    )

    row2 = st.columns(4)
    row2[0].metric(
        "Testing-gap rate",
        _pct(agg["testing_gap_rate"]),
        help="Defects better test coverage would plausibly have caught. % of analyzed.",
    )
    row2[1].metric(
        "Late-phase escapes",
        _pct(agg.get("escape_rate", 0.0)),
        help=(
            "Root cause traced to build/release or production-operations — work that "
            "reached a late phase before anyone caught it. % of analyzed."
        ),
    )
    row2[2].metric(
        "Critical / high severity",
        _pct(severity.get("critical_high_rate", 0.0)),
        help="Severity 1 or 2, as a share of analyzed defects.",
    )
    row2[3].metric("Areas affected", len(agg["module_density"]))

    low, high = _REJECTION_BENCHMARK
    if rejection_rate > high:
        st.warning(
            f"Rejection rate {_pct(rejection_rate)} is above the {_pct(low)}-{_pct(high)} band "
            "usually cited as healthy. Sustained rates here point at requirements clarity "
            "or test-case design rather than product quality — read the rejection reasons "
            "below before treating it as a quality signal."
        )
    else:
        st.caption(
            f"Rejection rate {_pct(rejection_rate)} of total logged, within the "
            f"{_pct(low)}-{_pct(high)} band commonly cited as healthy. Substitute your own "
            "internal benchmark if you have one."
        )


def _render_quality_split(agg: dict) -> None:
    """Is this our code, or how we work? The first cut leadership wants."""
    st.subheader("Development quality vs process")
    split = agg.get("quality_split") or {}
    classified = split.get("classified_total", 0)
    if not classified:
        st.info("Not enough classified data yet.")
        return

    dev, proc = split["dev_quality"], split["process_error"]
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Bucket": "Development quality",
                    "Defects": dev["count"],
                    "% of classified": _pct(dev["share"]),
                    "Root causes included": ", ".join(
                        f"{_title(c)} ({n})" for c, n in dev["categories"].items()
                    )
                    or "—",
                    "Where to act": "Code review depth, unit-test coverage, static analysis.",
                },
                {
                    "Bucket": "Process",
                    "Defects": proc["count"],
                    "% of classified": _pct(proc["share"]),
                    "Root causes included": ", ".join(
                        f"{_title(c)} ({n})" for c, n in proc["categories"].items()
                    )
                    or "—",
                    "Where to act": (
                        "Requirements, design, test design, config and release controls."
                    ),
                },
            ]
        ),
        width="stretch",
        hide_index=True,
    )

    unattributed = split.get("unattributed", {})
    if unattributed.get("count"):
        detail = ", ".join(f"{_title(c)} ({n})" for c, n in unattributed["categories"].items())
        st.caption(
            f"Excluded from both buckets: {unattributed['count']} defect(s) — {detail}. "
            "A duplicate or works-as-designed item says nothing about the process, and an "
            "unclassified one says nothing at all, so counting them as process failures "
            "would overstate it. Percentages above are of classified defects only."
        )


def _render_top_rca(agg: dict) -> None:
    st.subheader("Top 5 root causes — and what to do about them")
    rows = agg.get("top_rca_contributors") or []
    if not rows:
        st.info("Not enough analyzed data yet.")
        return

    st.caption("Shares are of analyzed defects. Actions are CAPA-style: fix, then prevent.")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Root cause": _title(r["category"]) + (" (!)" if r["priority"] else ""),
                    "Defects": r["count"],
                    "% of analyzed": _pct(r["share"]),
                    "Concentrated in": f"{r['top_area']} ({r['top_area_count']})",
                    "Testing gap": _pct(r["testing_gap_rate"]),
                    "Corrective action": r["corrective"],
                    "Preventive action": r["preventive"],
                }
                for r in rows
            ]
        ),
        width="stretch",
        hide_index=True,
    )
    if any(r["priority"] for r in rows):
        st.caption("(!) marks categories warranting escalation regardless of volume.")


def _render_top_areas(agg: dict) -> None:
    st.subheader("Top 5 area paths — and what to do about them")
    rows = agg.get("top_area_contributors") or []
    if not rows:
        st.info("Not enough analyzed data yet.")
        return

    st.caption(
        "Ranked by defect volume. Read the rejection rate separately: a high one signals "
        "unclear requirements or test design in that area, not poor code."
    )
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Area path": r["area_path"],
                    "Defects": r["count"],
                    "% of analyzed": _pct(r["share"]),
                    "Dominant cause": (
                        f"{_title(r['dominant_cause'])} ({r['dominant_cause_count']})"
                    ),
                    "Rejection rate": _pct(r["rejection_rate"]),
                    "Corrective action": r["corrective"],
                    "Preventive action": r["preventive"],
                }
                for r in rows
            ]
        ),
        width="stretch",
        hide_index=True,
    )


def _render_breakdowns(df: pd.DataFrame, agg: dict) -> None:
    st.subheader("Where the defects are")

    pareto = agg.get("rca_pareto") or []
    if pareto:
        vital = [_title(r["category"]) for r in pareto if r["in_vital_few"]]
        st.markdown(
            f"**Pareto:** {len(vital)} of {len(pareto)} categories account for ~80% of "
            f"defects — {', '.join(vital)}."
        )
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Root cause": _title(r["category"]),
                        "Defects": r["count"],
                        "% of analyzed": _pct(r["pct_of_total"]),
                        "Cumulative": _pct(r["cumulative_pct"]),
                        "Vital few": "yes" if r["in_vital_few"] else "",
                    }
                    for r in pareto
                ]
            ),
            width="stretch",
            hide_index=True,
        )

    left, right = st.columns(2)
    with left:
        st.markdown("**Defects by area path**")
        st.bar_chart(agg["module_density"])
    with right:
        st.markdown("**Root cause vs SDLC phase**")
        sdlc = pd.DataFrame(agg["rca_sdlc_crosstab"]).fillna(0).T
        if sdlc.empty:
            st.caption("No SDLC phase data.")
        else:
            st.bar_chart(sdlc)

    if agg.get("rejection_breakdown"):
        st.markdown("**Rejected and borderline, by recorded reason**")
        st.dataframe(
            pd.Series(agg["rejection_breakdown"], name="Defects").rename_axis("Reason"),
            width="stretch",
        )

    st.markdown("**Monthly trend**")
    st.line_chart(agg["monthly_trend"])

    with st.expander("Area path x iteration path"):
        st.dataframe(
            df.pivot_table(
                index="module",
                columns="iteration_path",
                values="id",
                aggfunc="count",
                fill_value=0,
            ),
            width="stretch",
        )


def _render_data_quality(agg: dict, config: Config) -> None:
    """Stated up front: a conclusion built on sparse data must carry the caveat."""
    needs_review = agg.get("needs_review_count", 0)
    total = agg["total_defects"] or 1
    share = needs_review / total
    if share >= 0.25:
        st.warning(
            f"**Data-quality caveat:** {needs_review} of {total} defects ({_pct(share)}) are "
            "low-confidence or unclassified — usually because the export carried a title but "
            "no description, resolution notes or comments. Treat the breakdowns below as "
            "indicative until those are reviewed."
        )
    elif needs_review:
        st.caption(
            f"{needs_review} of {total} defects ({_pct(share)}) flagged for review "
            f"(confidence below {_pct(config.review_confidence_threshold)} or unclassified)."
        )


def _render_export(config: Config) -> None:
    st.divider()
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
