"""Plotly chart builders.

A few rules held throughout: form follows what the data is for (ordered stages get one hue
stepping darker, continuous magnitude gets a sequential ramp, distinct identities get
categorical slots); never two measures on two y-axes; colour never carries meaning on its own,
so every multi-series chart is both legended and labelled; grid and axes stay recessive; and
labels go on the marks that matter rather than every point.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.components import palette as pal


def compact_money(value: float, currency: str = "R$") -> str:
    """Shorten a large amount so it fits a KPI tile: 13496044.67 -> "R$ 13.50M".

    The exact figure overflowed the tile at 1280px and rendered as "R$ 13,49...". It moves to
    the caption rather than being dropped.
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
    """A single KPI number. `caption` carries the exact value under an abbreviated one."""
    with st.container(border=True):
        st.metric(label=label, value=value, delta=delta, help=help_text)
        if caption:
            st.caption(caption)


def funnel_chart(frame: pd.DataFrame) -> go.Figure:
    """Horizontal funnel of stage counts.

    go.Funnel rather than bars because the shape itself encodes the narrowing. One hue getting
    darker, because the stages are ordered.
    """
    figure = go.Figure(
        go.Funnel(
            y=frame.stage_name,
            x=frame.orders_reaching,
            # textinfo's default formatter abbreviates 99,417 to "99.417k" and rounds 99.86%
            # to "100%", which is wrong on a chart about small losses
            texttemplate="%{value:,} &#183; %{percentInitial:.2%} of all orders",
            textposition="inside",
            textfont={"color": pal.LABEL_ON_FILL, "size": 13},
            marker={
                "color": list(pal.FUNNEL_RAMP[: len(frame)]),
                # 2px surface gap so adjacent fills never touch
                "line": {"color": pal.SURFACE, "width": 2},
            },
            # fill the connector with the surface colour; Plotly's grey reads as a sixth band
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
    """Retention triangle: acquisition month down, months since across.

    Month 0 is excluded from the colour range -- it is 100% by construction, and leaving it in
    compresses every real value into the palest step. The column is still shown as a baseline.
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
    # Plotly thins categorical ticks when it thinks they are crowded, which hid half the
    # cohort labels. tickmode="array" with the values spelled out; "linear" with dtick=1 is
    # the obvious guess and removes them entirely on a categorical axis.
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
    """One measure over time -- never two y-axes on one chart.

    A single series needs no legend; the title names it. Only the first, last and peak points
    are labelled.
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
    """Conversion rate per arm, as two bars.

    Both labelled and legended, so identity never depends on colour alone. The axis starts at
    zero: truncating it would make a fraction of a percentage point look like a landslide.
    """
    ordered = frame.sort_values("is_control", ascending=False).reset_index(drop=True)
    figure = go.Figure()
    for i, row in ordered.iterrows():
        role = "control" if row.is_control else "treatment"
        figure.add_trace(
            go.Bar(
                y=[f"{row.variant}"],
                x=[float(row.conversion_rate_pct)],
                orientation="h",
                marker={
                    "color": pal.SERIES[i],
                    "line": {"color": pal.SURFACE, "width": 2},
                    "cornerradius": 4,
                },
                text=[f"{row.conversion_rate_pct:.4f}%"],
                # inside the bar: an outside label is positioned in pixels and clipped at
                # half width. Padding the data range only hid that at one window size.
                textposition="inside",
                insidetextanchor="end",
                textfont={"color": pal.LABEL_ON_FILL, "size": 13},
                name=f"{row.variant}",
                hovertemplate=(
                    f"<b>{row.variant}</b> ({role})<br>"
                    f"{row.converted:,} of {row.users:,} users<br>"
                    f"<b>{row.conversion_rate_pct:.4f}%</b><extra></extra>"
                ),
            )
        )
    layout = pal.plotly_layout(height=240)
    # no axis title: the heading names the metric, and it collided with the legend
    #
    # zero-based and unpadded; the labels sit inside the bars so nothing needs room past the end
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

    One question, visually: does the interval cross zero? Coloured by status rather than by
    series, because it encodes a verdict -- and the verdict is in the axis label too.
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
