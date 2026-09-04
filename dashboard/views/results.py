"""Leadership view of the RCA: KPIs, where defects concentrate, and what to do.

Form choices follow what each number's job is, not what looks impressive:

- Headline counts are **stat tiles**, not a one-bar chart.
- A rate measured against a benchmark is a **meter** — a ratio against a limit
  reads better on a track with the limit drawn on it than on a pie of two
  slices or a dial.
- Root cause is a **horizontal ranked bar** on a single hue: the job is
  comparing magnitude, and with a dozen long category names a donut would be
  unreadable. The paired table carries the exact numbers.
- Every chart ships with a table, which also discharges the palette's contrast
  warning on the aqua slot.
"""

from __future__ import annotations

from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from ado_defect_analysis.config import Config
from ado_defect_analysis.pipeline.aggregate import (
    build_aggregates,
    filter_by_closed_date,
    load_categorized_dataframe,
)
from ado_defect_analysis.pipeline.export import run_export

from . import render_help_link

# Validated categorical slots (light surface): blue, orange, aqua. Adjacent CVD
# ΔE 9.2, normal-vision 27.6 — both clear. Aqua sits under 3:1 contrast, so
# anywhere it appears is direct-labelled and backed by a table.
_BLUE, _ORANGE, _AQUA = "#2a78d6", "#eb6834", "#1baf7a"
#: Sequential ramp for magnitude — one hue, light to dark.
_SEQUENTIAL = "blues"
#: Reserved status steps, never reused for a series.
_STATUS_GOOD, _STATUS_WARN = "#008300", "#eb6834"
#: Commonly cited healthy band for rejected defects, as a share of total logged.
_REJECTION_BENCHMARK = (0.10, 0.20)


def _pct(value: float) -> str:
    return f"{value:.0%}"


def _title(value: str) -> str:
    return value.replace("_", " ").title()


def render(config: Config) -> None:
    header, actions = st.columns([4, 1])
    header.title("Defect RCA — leadership summary")
    with actions:
        if st.button("← Setup", width="stretch"):
            st.query_params.clear()
            st.session_state["page"] = "home"
            st.rerun()
        render_help_link()

    df = load_categorized_dataframe(config)
    if df.empty:
        st.warning("No analyzed defects yet. Load data and run the analysis first.")
        return

    df = _render_filters(df)
    if df.empty:
        st.warning("No defects match the current filters.")
        return

    agg = build_aggregates(
        df,
        config.rejected_resolutions,
        config.review_confidence_threshold,
        config.borderline_resolutions,
    )

    _render_kpis(agg)
    _render_meters(agg)
    _render_data_quality(agg, config)
    st.divider()
    _render_quality_split(agg)
    st.divider()
    _render_top_rca(agg)
    _render_top_areas(agg)
    st.divider()
    _render_charts(df, agg)
    _render_export(config)


def _render_filters(df: pd.DataFrame) -> pd.DataFrame:
    """Filters in one row above the charts, as the interaction spec calls for."""
    with st.container(border=True):
        col1, col2, col3 = st.columns(3)
        areas = ["All", *sorted(df["module"].dropna().unique().tolist())]
        area = col1.selectbox("Area path", areas)

        iterations = ["All", *sorted(df["iteration_path"].dropna().unique().tolist())]
        iteration = col2.selectbox("Iteration path", iterations)

        closed = pd.to_datetime(df["closed_date"], errors="coerce")
        if closed.notna().any():
            since, until = col3.date_input(
                "Closed between",
                value=(closed.min().date(), closed.max().date()),
                key="date_range",
            ) or (None, None)
        else:
            col3.caption("No closed dates to filter on.")
            since = until = None

    if area != "All":
        df = df[df["module"] == area]
    if iteration != "All":
        df = df[df["iteration_path"] == iteration]
    if since and until:
        df = filter_by_closed_date(df, str(since), str(until))
    return df


def _render_kpis(agg: dict) -> None:
    """Headline counts as stat tiles. Each states the base it is a share of."""
    split = agg["valid_vs_rejected"]
    logged = sum(split.values()) or 1

    row = st.columns(4)
    row[0].metric("Total logged", f"{agg['total_defects']:,}")
    row[1].metric(
        "Valid defects", f"{split['valid']:,}", f"{_pct(split['valid'] / logged)} of logged"
    )
    row[2].metric(
        "Rejected", f"{split['rejected']:,}", f"{_pct(split['rejected'] / logged)} of logged"
    )
    row[3].metric(
        "Borderline",
        f"{split.get('borderline', 0):,}",
        help=(
            "Cannot Reproduce / Not a Bug / Invalid — held separate rather than folded "
            "into either count, since it is a different claim from 'working as designed'."
        ),
    )


def _meter(label: str, value: float, caption: str, benchmark: tuple[float, float] | None) -> str:
    """A ratio against a limit, drawn on its track with the limit marked.

    Same-ramp track rather than a dial: the reader compares a filled length to
    a marked threshold, which is the actual question being asked.
    """
    pct = max(0.0, min(value, 1.0)) * 100
    breached = benchmark is not None and value > benchmark[1]
    fill = _STATUS_WARN if breached else _BLUE
    band = ""
    if benchmark:
        low, high = benchmark
        band = (
            f'<div style="position:absolute;left:{low * 100:.1f}%;'
            f"width:{(high - low) * 100:.1f}%;top:0;bottom:0;"
            "background:rgba(0,131,0,.18);border-left:2px solid #008300;"
            'border-right:2px solid #008300;"></div>'
        )
    return f"""
<div style="margin-bottom:14px">
  <div style="display:flex;justify-content:space-between;font-size:.82rem;
              opacity:.85;margin-bottom:4px">
    <span>{label}</span><strong style="font-size:1.05rem;opacity:1">{value:.0%}</strong>
  </div>
  <div style="position:relative;height:12px;border-radius:6px;
              background:rgba(128,128,128,.18);overflow:hidden">
    {band}
    <div style="position:absolute;left:0;top:0;bottom:0;width:{pct:.1f}%;
                background:{fill};border-radius:6px"></div>
  </div>
  <div style="font-size:.72rem;opacity:.7;margin-top:3px">{caption}</div>
</div>
"""


def _render_meters(agg: dict) -> None:
    split = agg["valid_vs_rejected"]
    logged = sum(split.values()) or 1
    rejection = split["rejected"] / logged
    severity = agg.get("severity_mix") or {}
    low, high = _REJECTION_BENCHMARK

    left, right = st.columns(2)
    with left:
        st.markdown(
            _meter(
                "Rejection rate",
                rejection,
                f"Green band = the {_pct(low)}–{_pct(high)} range commonly cited as healthy. "
                "% of total logged.",
                _REJECTION_BENCHMARK,
            )
            + _meter(
                "Testing-gap rate",
                agg["testing_gap_rate"],
                "Defects better coverage would plausibly have caught. % of analyzed.",
                None,
            ),
            unsafe_allow_html=True,
        )
    with right:
        st.markdown(
            _meter(
                "Late-phase escapes",
                agg.get("escape_rate", 0.0),
                "Root cause traced to build/release or production. % of analyzed.",
                None,
            )
            + _meter(
                "Critical / high severity",
                severity.get("critical_high_rate", 0.0),
                "Severity 1 or 2. % of analyzed.",
                None,
            ),
            unsafe_allow_html=True,
        )

    if rejection > high:
        st.warning(
            f"Rejection rate {_pct(rejection)} is above the {_pct(low)}–{_pct(high)} band "
            "usually cited as healthy. Sustained rates here point at requirements clarity "
            "or test-case design rather than product quality."
        )


def _render_quality_split(agg: dict) -> None:
    """Is it our code, or how we work? Two parts, so a labelled stacked bar."""
    st.subheader("Development quality vs process")
    split = agg.get("quality_split") or {}
    classified = split.get("classified_total", 0)
    if not classified:
        st.info("Not enough classified data yet.")
        return

    dev, proc = split["dev_quality"], split["process_error"]
    frame = pd.DataFrame(
        [
            {"Bucket": "Development quality", "Defects": dev["count"], "Share": dev["share"]},
            {"Bucket": "Process", "Defects": proc["count"], "Share": proc["share"]},
        ]
    )
    chart = (
        alt.Chart(frame)
        .mark_bar(height=34, cornerRadius=4, stroke="white", strokeWidth=2)
        .encode(
            x=alt.X("Defects:Q", stack="normalize", title=None, axis=alt.Axis(format="%")),
            color=alt.Color(
                "Bucket:N",
                scale=alt.Scale(domain=frame["Bucket"].tolist(), range=[_BLUE, _ORANGE]),
                legend=alt.Legend(orient="top", title=None),
            ),
            tooltip=[
                alt.Tooltip("Bucket:N"),
                alt.Tooltip("Defects:Q", format=","),
                alt.Tooltip("Share:Q", format=".0%", title="Share of classified"),
            ],
        )
        .properties(height=70)
    )
    st.altair_chart(chart, use_container_width=True)

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
            "would overstate it. Percentages are of classified defects only."
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


def _ranked_bar(frame: pd.DataFrame, label: str, value: str) -> alt.Chart:
    """Horizontal ranked bar on one hue — the default for comparing magnitude.

    Horizontal because the category names are long; sequential because the job
    is magnitude, not identity.
    """
    return (
        alt.Chart(frame)
        .mark_bar(cornerRadiusEnd=4, height=alt.RelativeBandSize(0.72))
        .encode(
            y=alt.Y(f"{label}:N", sort="-x", title=None),
            x=alt.X(f"{value}:Q", title=None),
            color=alt.Color(f"{value}:Q", scale=alt.Scale(scheme=_SEQUENTIAL), legend=None),
            tooltip=[alt.Tooltip(f"{label}:N"), alt.Tooltip(f"{value}:Q", format=",")],
        )
    )


def _render_charts(df: pd.DataFrame, agg: dict) -> None:
    st.subheader("Where the defects are")

    left, right = st.columns(2)
    with left:
        st.markdown("**Root cause distribution**")
        rca = pd.DataFrame(
            [
                {"Root cause": _title(k), "Defects": v}
                for k, v in agg["root_cause_distribution"].items()
            ]
        )
        st.altair_chart(_ranked_bar(rca, "Root cause", "Defects"), use_container_width=True)
    with right:
        st.markdown("**Defects by area path**")
        areas = pd.DataFrame(
            [{"Area path": k, "Defects": v} for k, v in agg["module_density"].items()]
        ).head(12)
        st.altair_chart(_ranked_bar(areas, "Area path", "Defects"), use_container_width=True)

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

    trend = agg.get("monthly_trend") or {}
    if trend:
        st.markdown("**Monthly trend**")
        tf = pd.DataFrame([{"Month": k, "Defects": v} for k, v in trend.items()])
        line = (
            alt.Chart(tf)
            .mark_line(strokeWidth=2, point=alt.OverlayMarkDef(size=64, filled=True))
            .encode(
                x=alt.X("Month:N", title=None),
                y=alt.Y("Defects:Q", title=None),
                color=alt.value(_BLUE),
                tooltip=[alt.Tooltip("Month:N"), alt.Tooltip("Defects:Q", format=",")],
            )
            .properties(height=220)
        )
        st.altair_chart(line, use_container_width=True)

    if agg.get("rejection_breakdown"):
        with st.expander("Rejected and borderline, by recorded reason"):
            st.dataframe(
                pd.Series(agg["rejection_breakdown"], name="Defects").rename_axis("Reason"),
                width="stretch",
            )

    with st.expander("Area path × iteration path"):
        st.dataframe(
            df.pivot_table(
                index="module", columns="iteration_path", values="id", aggfunc="count", fill_value=0
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
    st.caption(
        "Writes CSV/Excel for Power BI plus a needs-review triage list, then offers them "
        "as downloads."
    )
    if not st.button("Generate export files", type="primary"):
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
            width="stretch",
        )
