"""Colour tokens. The only module containing hex codes, so a colour is defined once and
referenced by role everywhere else.

The values were checked with a palette validator against the surface this renders on
(#fcfcfb): the categorical pair clears a colour-blind delta-E of 24.7 against a target of 8,
and the funnel ramp is monotone in lightness with its light end at 2.06:1.

Rules that should survive an edit: categorical hues are assigned in fixed order and never
cycled, so a series keeps its colour when a filter removes its neighbours; sequential
encoding is one hue light to dark, never a rainbow; status colours are reserved; text wears
ink tokens, never a series colour.
"""

from __future__ import annotations

# ---------------------------------------------------------------- surfaces and ink
SURFACE = "#fcfcfb"  # the colour every contrast check was run against
PAGE = "#f9f9f7"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"  # axis labels and ticks
GRID = "#e1e0d9"  # hairline gridlines
BASELINE = "#c3c2b7"
LABEL_ON_FILL = "#ffffff"

# ---------------------------------------------------------------- categorical
# assigned in this order, never cycled; the rest are listed so a new series takes the next slot
SERIES: tuple[str, ...] = (
    "#2a78d6",  # 1 blue
    "#eb6834",  # 2 orange
    "#1baf7a",  # 3 aqua
    "#eda100",  # 4 yellow
    "#e87ba4",  # 5 magenta
    "#008300",  # 6 green
    "#6250d6",  # 7 violet
    "#e34948",  # 8 red
)

# ---------------------------------------------------------------- ordinal (funnel)
# ordered stages, so one hue light -> dark. The lightest step still clears 2:1 on the surface.
FUNNEL_RAMP: tuple[str, ...] = ("#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281")

# ---------------------------------------------------------------- sequential (heatmap)
# continuous magnitude, so the full ramp is allowed
SEQUENTIAL: tuple[str, ...] = (
    "#cde2fb",
    "#b7d3f6",
    "#9ec5f4",
    "#86b6ef",
    "#6da7ec",
    "#5598e7",
    "#3987e5",
    "#2a78d6",
    "#256abf",
    "#1c5cab",
    "#184f95",
    "#104281",
    "#0d366b",
)

# ---------------------------------------------------------------- status (reserved)
# never reused for a series, and always paired with a word
STATUS: dict[str, str] = {
    "good": "#0ca30c",
    "warning": "#fab219",
    "serious": "#ec835a",
    "critical": "#d03b3b",
}
SUCCESS_TEXT = "#006300"  # for "+12%" style deltas, which need text contrast not fill contrast


def plotly_layout(height: int = 360) -> dict:
    """Shared layout, so the charts read as one system rather than five separate ones."""
    return {
        "height": height,
        "margin": {"l": 8, "r": 8, "t": 8, "b": 8},
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "font": {
            "family": 'system-ui, -apple-system, "Segoe UI", sans-serif',
            "size": 13,
            "color": INK_SECONDARY,
        },
        "xaxis": {
            "gridcolor": GRID,
            "linecolor": BASELINE,
            "zerolinecolor": BASELINE,
            "tickfont": {"color": INK_MUTED, "size": 12},
        },
        "yaxis": {
            "gridcolor": GRID,
            "linecolor": BASELINE,
            "zerolinecolor": BASELINE,
            "tickfont": {"color": INK_MUTED, "size": 12},
        },
        "hoverlabel": {
            "bgcolor": SURFACE,
            "bordercolor": BASELINE,
            "font": {"color": INK_PRIMARY, "size": 12},
        },
    }
