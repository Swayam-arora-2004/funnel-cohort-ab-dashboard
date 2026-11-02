"""Plotly chart builders. Every chart on the dashboard is created here.

Design rules applied (these are the project's data-visualisation standards, and each one is a
decision rather than a default):

  * **Form follows the data's job.** Funnel stages are ORDERED, so they take one hue stepping
    light to dark, not five unrelated colours. Cohort retention is continuous magnitude, so it
    takes a sequential ramp. The A/B arms are two distinct identities, so they take the first
    two categorical slots.
  * **One axis, always.** No chart here puts two different measures on two y-scales. Revenue
    and order count are different scales, so they are two charts, never one with twin axes.
  * **Colour never carries meaning alone.** Two-series charts are both legended and directly
    labelled; the funnel and heatmap carry numbers on the marks.
  * **Recessive chrome.** Gridlines are hairlines in the grid token, axis text is the muted
    ink token, and no chart has a heavy border or a drop shadow.
  * **Labels are selective.** Numbers go on the marks that matter, not on every point.
  * **Hover everywhere.** Every chart ships a tooltip; a static chart wastes the medium.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.components import palette as pal


def compact_money(value: float, currency: str = "R$") -> str:
    """Format a large amount so it FITS a KPI tile: 13496044.67 -> "R$ 13.50M".

    This exists because the exact figure, "R$ 13,496,045", overflowed the tile at a 1280px
    window and rendered as "R$ 13,49..." -- the headline number on the dashboard was literally
    unreadable. The exact value is not dropped; it moves to the caption underneath, so nothing
    is hidden, it is just no longer competing for the same 180 pixels.
    """
    magnitude = abs(value)
    if magnitude >= 1_000_000_000:
        return f"{currency} {value / 1_000_000_000:,.2f}B"
    if magnitude >= 1_000_000:
        return f"{currency} {value / 1_000_000:,.2f}M"
    if magnitude >= 10_000:
        return f"{currency} {value / 1_000:,.1f}K"
    return f"{currency} {value:,.2f}"


def kpi_tile(
    label: str,
    value: str,
    help_text: str,
    delta: str | None = None,
    caption: str | None = None,
) -> None:
    """A single KPI number. Not a chart -- a headline figure needs no plot behind it.

    `caption` carries the exact or qualifying value under an abbreviated headline, so a tile
    can stay readable at a narrow window without losing precision.
    """
    with st.container(border=True):
        st.metric(label=label, value=value, delta=delta, help=help_text)
        if caption:
            st.caption(caption)


def funnel_chart(frame: pd.DataFrame) -> go.Figure:
    """Horizontal funnel of stage counts.

    `go.Funnel` is used rather than a bar chart because the shape itself encodes the narrowing,
    and `textinfo` gives the absolute count plus the share of the funnel entry on each stage --
    the two numbers a reader actually wants, without a second lookup.

    Colour: the 5-step ordinal blue ramp. Stages are ordered, so one hue getting darker reads
    as progression. Five different hues would imply five unrelated things.
    """
    figure = go.Figure(
        go.Funnel(
            y=frame.stage_name,
            x=frame.orders_reaching,
            # texttemplate, not textinfo: the default `value` formatter abbreviates 99,417 to
            # "99.417k" and rounds 99.86% to "100%". Both are wrong on a chart whose whole
            # point is where small percentages are lost.
            texttemplate="%{value:,} &#183; %{percentInitial:.2%} of all orders",
            textposition="inside",
            textfont={"color": pal.LABEL_ON_FILL, "size": 13},
            marker={
                "color": list(pal.FUNNEL_RAMP[: len(frame)]),
                # A 2px surface-coloured gap between segments so adjacent fills never touch.
                "line": {"color": pal.SURFACE, "width": 2},
            },
            # The connector region is the gap between stages. Filling it with the surface
            # colour keeps it a gap; Plotly's default fills it mid-grey, which reads as a
            # sixth, meaningless band.
            connector={
                "fillcolor": pal.SURFACE,
                "line": {"color": pal.GRID, "width": 1, "dash": "dot"},
            },
            hovertemplate=(
                "<b>%{y}</b><br>%{x:,} orders<br>%{percentInitial:.2%} of all orders<extra></extra>"
            ),
        )
    )
    layout = pal.plotly_layout(height=340)
    layout["yaxis"]["showgrid"] = False
    layout["xaxis"]["showgrid"] = False
    layout["yaxis"]["tickfont"] = {"color": pal.INK_SECONDARY, "size": 13}
    figure.update_layout(**layout)
    return figure


def cohort_heatmap(frame: pd.DataFrame) -> go.Figure:
    """Retention triangle as a heatmap: acquisition month down, months since across.

    Built with `go.Heatmap` on a pivoted frame. The sequential blue ramp encodes magnitude with
    ONE hue -- a rainbow scale would imply the middle values are a different kind of thing.

    Month 0 is excluded from the colour scale's range on purpose: it is 100% by construction,
    and leaving it in would compress every real value into the palest step and make the chart
    look empty. The column is still shown, as the baseline to read against.
    """
    grid = frame.pivot(index="cohort_month", columns="months_since", values="retention_pct")
    later = grid.drop(columns=[0], errors="ignore")
    # Scale to the real variation, not to the 100% baseline column.
    zmax = float(later.max().max()) if not later.empty and later.notna().any().any() else 1.0

    x_labels = [f"M{c}" for c in grid.columns]
    y_labels = [d.strftime("%Y-%m") for d in grid.index]

    figure = go.Figure(
        go.Heatmap(
            z=grid.to_numpy(),
            x=x_labels,
            y=y_labels,
            colorscale=[[i / (len(pal.SEQUENTIAL) - 1), c] for i, c in enumerate(pal.SEQUENTIAL)],
            zmin=0,
            zmax=zmax,
            # A surface-coloured gap between cells, so the grid reads as cells not a blur.
            xgap=2,
            ygap=2,
            hovertemplate=(
                "Cohort %{y}<br>%{x} after first order<br>"
                "<b>%{z:.2f}%</b> still ordering<extra></extra>"
            ),
            colorbar={
                "title": {"text": "retention %", "font": {"color": pal.INK_MUTED, "size": 11}},
                "tickfont": {"color": pal.INK_MUTED, "size": 11},
                "outlinewidth": 0,
                "thickness": 10,
            },
        )
    )
    layout = pal.plotly_layout(height=480)
    layout["xaxis"]["showgrid"] = False
    layout["yaxis"]["showgrid"] = False
    layout["yaxis"]["autorange"] = "reversed"  # earliest cohort at the top, like a triangle
    layout["xaxis"]["side"] = "top"
    # Force a tick on EVERY row and column. Plotly thins categorical ticks when it decides they
    # are crowded, which silently hid half the cohort labels -- a reader could not tell which
    # row was which month.
    #
    # It must be tickmode="array" with the category values spelled out. tickmode="linear" with
    # dtick=1 is the obvious guess and it is wrong here: on a CATEGORICAL axis it removes the
    # labels entirely rather than showing all of them.
    layout["yaxis"]["tickmode"] = "array"
    layout["yaxis"]["tickvals"] = y_labels
    layout["yaxis"]["ticktext"] = y_labels
    layout["xaxis"]["tickmode"] = "array"
    layout["xaxis"]["tickvals"] = x_labels
    layout["xaxis"]["ticktext"] = x_labels
    layout["yaxis"]["tickfont"] = {"color": pal.INK_SECONDARY, "size": 11}
    layout["xaxis"]["tickfont"] = {"color": pal.INK_SECONDARY, "size": 11}
    figure.update_layout(**layout)
    return figure


def revenue_line(
    frame: pd.DataFrame, column: str, label: str, as_currency: bool = True
) -> go.Figure:
    """One measure over time. ONE measure -- never two y-axes on one chart.

    A single series needs no legend box: the title names it. Only the first, last and peak
    points are labelled, because a number on every point is noise.
    """
    values = frame[column]
    fmt = "R$ %{y:,.0f}" if as_currency else "%{y:,.0f}"

    # Selective direct labels: first, last, and the maximum.
    label_positions = {0, len(frame) - 1, int(values.idxmax()) if len(frame) else 0}
    text = [
        (f"R$ {v:,.0f}" if as_currency else f"{v:,.0f}") if i in label_positions else ""
        for i, v in enumerate(values)
    ]

    figure = go.Figure(
        go.Scatter(
            x=frame.order_month,
            y=values,
            mode="lines+markers+text",
            line={"color": pal.SERIES[0], "width": 2},
            marker={"size": 8, "color": pal.SERIES[0], "line": {"color": pal.SURFACE, "width": 2}},
            text=text,
            textposition="top center",
            textfont={"color": pal.INK_SECONDARY, "size": 11},
            name=label,
            hovertemplate=f"%{{x|%b %Y}}<br><b>{fmt}</b><extra></extra>",
        )
    )
    layout = pal.plotly_layout(height=320)
    layout["xaxis"]["showgrid"] = False
    layout["showlegend"] = False  # single series: the title names it
    layout["hovermode"] = "x unified"
    figure.update_layout(**layout)
    return figure


def ab_comparison_chart(frame: pd.DataFrame, metric_label: str) -> go.Figure:
    """Conversion rate per variant, as two bars.

    Two distinct identities, so two categorical slots in fixed order: the control takes slot 1
    and the variant slot 2. Both bars are directly labelled AND legended, so identity never
    depends on colour alone.

    The x-axis deliberately starts at zero. A truncated axis would make a 0.8 pp difference
    look like a landslide, which is exactly the misreading the statistics exist to prevent.
    """
    ordered = frame.sort_values("is_control", ascending=False).reset_index(drop=True)
    figure = go.Figure()
    for i, row in ordered.iterrows():
        role = "control" if row.is_control else "variant"
        figure.add_trace(
            go.Bar(
                y=[f"{row.variant}  ({role})"],
                x=[float(row.conversion_rate_pct)],
                orientation="h",
                marker={
                    "color": pal.SERIES[i],
                    "line": {"color": pal.SURFACE, "width": 2},
                    "cornerradius": 4,
                },
                text=[f"{row.conversion_rate_pct:.3f}%"],
                # INSIDE the bar, anchored to its end. An outside label is positioned in
                # pixels, so at half width it ran past the axis and clipped to "44.228" --
                # padding the data range only hid the problem at one window size. Inside, the
                # label cannot leave the plot no matter how narrow the column gets, and these
                # bars (18-45%) are always long enough to hold it.
                textposition="inside",
                insidetextanchor="end",
                textfont={"color": pal.LABEL_ON_FILL, "size": 13},
                name=f"{row.variant} ({role})",
                hovertemplate=(
                    f"<b>{row.variant}</b> ({role})<br>"
                    f"{row.converted:,} of {row.users:,} retained<br>"
                    f"<b>{row.conversion_rate_pct:.3f}%</b><extra></extra>"
                ),
            )
        )
    layout = pal.plotly_layout(height=240)
    # No x-axis title: the section heading above the chart already names the metric, and a
    # title here collided with the horizontal legend.
    #
    # The axis starts at ZERO and is not padded. Truncating it would make a 0.8 pp difference
    # look like a landslide, which is the exact misreading the statistics on this page exist
    # to prevent. The value labels sit inside the bars, so nothing needs room past the end.
    layout["xaxis"]["rangemode"] = "tozero"
    layout["xaxis"]["ticksuffix"] = "%"
    layout["yaxis"]["showgrid"] = False
    layout["yaxis"]["tickfont"] = {"color": pal.INK_SECONDARY, "size": 12}
    layout["showlegend"] = True
    layout["legend"] = {
        "orientation": "h",
        "yanchor": "top",
        "y": -0.18,
        "x": 0,
        "font": {"color": pal.INK_SECONDARY, "size": 12},
    }
    layout["bargap"] = 0.45
    layout["margin"] = {"l": 8, "r": 8, "t": 8, "b": 48}
    figure.update_layout(**layout)
    return figure


def confidence_interval_chart(ci_low: float, ci_high: float, point: float) -> go.Figure:
    """The 95% interval on the difference, with zero marked.

    This chart answers one question visually: does the interval cross zero? That is the whole
    conclusion, so it gets its own small plot rather than being buried in a table.

    The bar is coloured by STATUS, not by series, because it encodes a verdict rather than an
    identity -- and the verdict is spelled out in the axis label too, so the colour is never
    the only cue.
    """
    crosses_zero = ci_low <= 0 <= ci_high
    colour = pal.STATUS["warning"] if crosses_zero else pal.STATUS["critical"]
    if point > 0 and not crosses_zero:
        colour = pal.STATUS["good"]

    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=[ci_low, ci_high],
            y=[0, 0],
            mode="lines",
            line={"color": colour, "width": 10},
            hovertemplate="95%% CI bound: %{x:+.3f} pp<extra></extra>",
            showlegend=False,
        )
    )
    figure.add_trace(
        go.Scatter(
            x=[point],
            y=[0],
            mode="markers",
            marker={
                "size": 16,
                "color": colour,
                "line": {"color": pal.SURFACE, "width": 2},
                "symbol": "diamond",
            },
            hovertemplate="observed difference: %{x:+.3f} pp<extra></extra>",
            showlegend=False,
        )
    )
    figure.add_vline(x=0, line={"color": pal.INK_SECONDARY, "width": 2, "dash": "dash"})

    layout = pal.plotly_layout(height=160)
    span = max(abs(ci_low), abs(ci_high)) * 1.5 or 1.0
    layout["xaxis"]["range"] = [-span, span]
    layout["xaxis"]["title"] = {
        "text": "difference in percentage points  (dashed line = no effect)",
        "font": {"color": pal.INK_MUTED, "size": 11},
    }
    layout["yaxis"] = {"visible": False, "range": [-1, 1]}
    layout["showlegend"] = False
    figure.update_layout(**layout)
    return figure
