"""Entry point: KPI tiles, the funnel and revenue over time.

The whole app connects as dashboard_ro -- SELECT on analytics, nothing on raw. Every query is
parameterised in queries.py, and database errors surface as a generic message rather than a
traceback in the browser.

Sections are tabs rather than one long page: this page grew from 800px to 2,243px over the
~800ms the charts took to lay out, and scrolling during that jumped backwards by 198px.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# Streamlit runs this file as a script, not as a package module, so the repo root has to be on
# sys.path for `import src...` and `import app...` to resolve. Inserting it here rather than
# relying on PYTHONPATH keeps `make app` a single command that works from a clean clone.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.components import charts, queries  # noqa: E402 - after the sys.path fix

log = logging.getLogger(__name__)

st.set_page_config(
    page_title="Funnel, Cohort & A/B Dashboard",
    page_icon="chart_with_upwards_trend",
    layout="wide",
)


def show_database_error(exc: Exception) -> None:
    """Generic message to the user; the detail goes to the server log."""
    log.exception("dashboard query failed")
    st.error(
        "Could not load data from the database. Check that it is running "
        "(`make db-up`) and that the views exist (`make views`). "
        "Details are in the server log, not shown here."
    )
    st.caption(f"Error type: {type(exc).__name__}")


def render_kpis(start, end) -> None:
    """The four headline figures, as two rows of two.

    Four across needs ~190px per tile; a 1100px window with the sidebar open gives ~165px, and
    "R$ 137.43" truncated to "R$ 13...". Each caption has to fit one line, or its tile grows
    taller than its neighbour and the row stops lining up.
    """
    kpis = queries.kpi_totals(start, end)
    completion = queries.delivery_completion_rate(start, end)

    row_one = st.columns(2)
    row_two = st.columns(2)
    tiles = [row_one[0], row_one[1], row_two[0], row_two[1]]

    with tiles[0]:
        charts.kpi_tile(
            "Orders",
            f"{int(kpis.orders):,}",
            "Non-canceled orders containing at least one item, in the selected months.",
            caption="non-canceled",
        )
    with tiles[1]:
        # abbreviated headline, exact figure in the caption
        charts.kpi_tile(
            "Revenue",
            charts.compact_money(float(kpis.revenue)),
            "Sum of item prices. Freight is excluded -- it is pass-through shipping cost, "
            "not merchandise revenue.",
            caption=f"R$ {float(kpis.revenue):,.0f} exact",
        )
    with tiles[2]:
        charts.kpi_tile(
            "Average order value",
            f"R$ {float(kpis.avg_order_value):,.2f}",
            "Revenue divided by order count. Recomputed from the totals, NOT an average of "
            "monthly AOVs -- that would weight a quiet month the same as a busy one.",
            caption="revenue ÷ orders",
        )
    with tiles[3]:
        charts.kpi_tile(
            "Funnel completion",
            f"{completion:.2f}%",
            "Share of placed orders that were delivered AND reviewed. Same cumulative stage "
            "definition as the funnel chart.",
            caption="placed → reviewed",
        )


def render_funnel(start, end) -> None:
    """The funnel chart, a table view of the same numbers, and the biggest-loss callout."""
    funnel = queries.funnel_stages(start, end)
    if funnel.empty:
        st.info("No orders in the selected range.")
        return

    # stacked, not side by side: in a side column the table clipped to "Step co..." at 1280px
    st.plotly_chart(charts.funnel_chart(funnel), width="stretch")

    worst = funnel.iloc[1:].nlargest(1, "dropped_orders").iloc[0]
    previous_stage = funnel.loc[funnel.stage_order == worst.stage_order - 1, "stage_name"]
    st.info(
        f"**Biggest single loss: {previous_stage.iloc[0]} → {worst.stage_name}** — "
        f"{int(worst.dropped_orders):,} orders "
        f"({100 - worst.step_conversion_pct:.2f}% of those that got that far)."
    )

    # a table for every chart, so nothing depends on seeing colour. Formatted as strings:
    # the first row has no previous stage, which should read as a dash, not "None".
    with st.expander("Table view — the same five stages as numbers"):
        st.dataframe(
            pd.DataFrame(
                {
                    "Stage": funnel.stage_name,
                    "Orders": funnel.orders_reaching.map("{:,.0f}".format),
                    "Lost here": funnel.dropped_orders.map(
                        lambda v: "—" if pd.isna(v) else f"{v:,.0f}"
                    ),
                    "Step conversion": funnel.step_conversion_pct.map(
                        lambda v: "—" if pd.isna(v) else f"{v:.2f}%"
                    ),
                }
            ),
            hide_index=True,
            width="stretch",
        )

    st.caption(
        "**This is a fulfilment funnel, not an acquisition funnel.** Olist publishes no "
        "clickstream data, so 'visit → signup → cart → purchase' is not derivable from it and "
        "inventing those stages would be fabricating results. These five stages are real "
        "order-lifecycle timestamps, and a missing timestamp is genuine operational drop-off. "
        "Stages are cumulative: reaching one requires passing all the earlier ones."
    )


def render_revenue(start, end) -> None:
    """Revenue and order count as two charts -- never one with two y-axes."""
    revenue = queries.revenue_by_month(start, end)
    if revenue.empty:
        st.info("No revenue in the selected range.")
        return

    left, right = st.columns(2)
    with left:
        st.markdown("**Monthly revenue**")
        st.plotly_chart(charts.revenue_line(revenue, "revenue", "Monthly revenue"), width="stretch")
    with right:
        st.markdown("**Monthly order count**")
        st.plotly_chart(
            charts.revenue_line(revenue, "orders", "Orders", as_currency=False),
            width="stretch",
        )
    st.caption(
        "Revenue and order count are shown as two charts rather than one chart with two "
        "y-axes. A dual-axis chart lets the author choose where the lines cross, which makes "
        "any relationship between them look like whatever was intended."
    )


# ---------------------------------------------------------------------------- page

st.title("Funnel, Cohort & A/B Analysis")
st.caption(
    "**This page: Olist Brazilian E-Commerce** (real marketplace data, 2016-09 to 2018-10). "
    "The A/B Test page uses a different dataset -- the Criteo Uplift advertising experiment. "
    "Each page names its source."
)

try:
    first_month, last_month = queries.available_date_range()

    # Filters in one row above everything, never beside the charts.
    with st.container(border=True):
        left, right = st.columns([3, 2])
        with left:
            selected = st.slider(
                "Order month range",
                min_value=first_month,
                max_value=last_month,
                value=(first_month, last_month),
                format="MMM YYYY",
                help=(
                    "Bounds come from the data itself, so the picker cannot offer a month "
                    "that does not exist. Partial months at the edges of the extract are "
                    "already excluded."
                ),
            )
        with right:
            st.caption(
                "The three partial months at the edges of the extract "
                "(2016-09, 2016-12, 2018-09 -- 4 orders in total) are excluded from every "
                "figure on this page. Including them made month-over-month growth read "
                "+1,101,719%."
            )
    start, end = selected

    render_kpis(start, end)

    # tabs, not one long scroll -- see the module docstring
    funnel_tab, revenue_tab = st.tabs(["Fulfilment funnel", "Revenue over time"])
    with funnel_tab:
        render_funnel(start, end)
    with revenue_tab:
        render_revenue(start, end)

except Exception as exc:  # noqa: BLE001 - the UI must degrade, not traceback at the user
    show_database_error(exc)
