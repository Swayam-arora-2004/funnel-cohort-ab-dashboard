"""Colour tokens for every chart. The only module in the project containing hex codes.

Keeping them here means a colour is defined once and referenced by ROLE everywhere else, so
"what colour is series 2?" has exactly one answer and a theme change is a one-file edit.

**These values were validated by a script, not chosen by eye.** The categorical pair and the
funnel ramp were both run through the design system's palette validator against the light
surface this dashboard actually renders on (#fcfcfb, pinned in .streamlit/config.toml):

    categorical, 2 slots  -- lightness band PASS, chroma floor PASS,
                             CVD separation PASS (worst adjacent delta-E 24.7 protan),
                             normal-vision floor PASS (delta-E 33.6), contrast PASS
    funnel ordinal ramp   -- monotone lightness PASS, adjacent delta-L PASS,
                             light-end contrast PASS (2.06:1), single hue PASS (3 degree spread)

Rules that must survive any edit:
  * Categorical hues are assigned in FIXED order and never cycled. A series keeps its colour
    when a filter removes its neighbours -- colour follows the entity, never its rank.
  * Sequential encoding is ONE hue, light to dark. Never a rainbow.
  * Status colours are reserved and never reused as "series 3".
  * Text wears ink tokens, never a series colour.
"""

from __future__ import annotations

# ---------------------------------------------------------------- surfaces and ink
SURFACE = "#fcfcfb"  # chart surface; the colour every contrast check was run against
PAGE = "#f9f9f7"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"  # axis labels, ticks -- deliberately recessive
GRID = "#e1e0d9"  # hairline gridlines
BASELINE = "#c3c2b7"
LABEL_ON_FILL = "#ffffff"

# ---------------------------------------------------------------- categorical
# Assigned in this order, never cycled. Only the first two are used (gate_30, gate_40);
# the rest are listed so a future series takes the next slot rather than inventing a hue.
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
# Funnel stages are ORDERED, not independent categories, so they take one hue stepping
# light -> dark rather than five different colours. Five steps of the blue ramp; the lightest
# is step 250, which is the lightest step that still clears 2:1 against the light surface.
FUNNEL_RAMP: tuple[str, ...] = ("#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281")

# ---------------------------------------------------------------- sequential (heatmap)
# Continuous magnitude, so the full ramp is allowed: the lightest step means "near zero" and
# may recede toward the surface.
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
# Never reused for a series. Always paired with a word or an icon, so meaning is never
# carried by colour alone.
STATUS: dict[str, str] = {
    "good": "#0ca30c",
    "warning": "#fab219",
    "serious": "#ec835a",
    "critical": "#d03b3b",
}
SUCCESS_TEXT = "#006300"  # for "+12%" style deltas, which need text contrast not fill contrast


def plotly_layout(height: int = 360) -> dict:
    """Shared layout: recessive chrome, transparent surface, ink-token text.

    Every chart uses this so the dashboard reads as one system rather than five charts that
    happen to sit on the same page.
    """
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
