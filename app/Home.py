"""Streamlit entry point: KPI tiles and the funnel (FR-16, FR-17, FR-21).

Security notes for this whole app:
  * It connects as `dashboard_ro`, which has SELECT on `analytics` and NO privileges on `raw`
    (SEC-5). A write attempt from this role fails -- asserted by
    tests/test_load.py::test_readonly_role_cannot_write.
  * Every query is parameterised in app/components/queries.py (SEC-4).
  * Database errors are caught and shown as a generic message. Raw exception text, SQL and
    connection strings are never rendered in the browser (SEC-10).
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

from app.components import charts, queries  # noqa: E402 - must follow the sys.path fix above

log = logging.getLogger(__name__)

st.set_page_config(
    page_title="Funnel, Cohort & A/B Dashboard",
    page_icon="chart_with_upwards_trend",
    layout="wide",
)


def show_database_error(exc: Exception) -> None:
    """Generic message to the user, detail only to the server log (SEC-10)."""
    log.exception("dashboard query failed")
    st.error(
        "Could not load data from the database. Check that it is running "
        "(`make db-up`) and that the views exist (`make views`). "
        "Details are in the server log, not shown here."
    )
    st.caption(f"Error type: {type(exc).__name__}")


st.title("Funnel, Cohort & A/B Analysis")
st.caption(
    "**This page: Olist Brazilian E-Commerce** (real marketplace data, 2016-09 to 2018-10). "
    "The A/B Test page uses a different dataset -- the Cookie Cats mobile-game experiment. "
    "Each page names its source."
)

try:
    first_month, last_month = queries.available_date_range()

    # ---- filters in one row above the charts, never beside them ----
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
                    "Bounds come from the data itself, so the picker cannot offer a month that "
                    "does not exist. Partial months at the edges of the extract are already "
                    "excluded."
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

    # ---------------------------------------------------------------- KPI tiles (FR-16)
    kpis = queries.kpi_totals(start, end)
    completion = queries.delivery_completion_rate(start, end)

    st.subheader("Key figures")
    # TWO ROWS OF TWO, not one row of four.
    #
    # Four tiles across needs about 190px each for these values. With the sidebar open, a
    # 1100px window leaves roughly 165px per tile, and Streamlit's metric font is large enough
    # that "R$ 137.43" truncated to "R$ 13..." -- the headline figures became unreadable, and
    # shortening the values could not fix it because even "R$ 137.43" did not fit.
    #
    # The alternatives were worse: CSS injected against Streamlit's internal class names to
    # shrink the font would break silently on a version upgrade, and Streamlit has no
    # width breakpoint to switch layouts on. Two rows of two give every tile roughly 360px at
    # 1100px and more above that, so the row never has to be checked again.
    #
    # Each caption must still fit ONE line: a caption that wraps makes its tile taller than
    # its neighbour and the pair's bottom edges stop lining up.
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
        # Abbreviated headline, exact figure in the caption. At a 1280px window the full
        # number overflowed the tile and rendered as "R$ 13,49..." -- see charts.compact_money.
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
            "definition as the funnel chart below.",
            caption="placed → reviewed",
        )

    # ---------------------------------------------------------------- funnel (FR-17)
    st.subheader("Fulfilment funnel")
    st.caption(
        "**This is a fulfilment funnel, not an acquisition funnel.** Olist publishes no "
        "clickstream data, so 'visit → signup → cart → purchase' is not derivable from it and "
        "inventing those stages would be fabricating results. These five stages are real "
        "order-lifecycle timestamps, and a missing timestamp is genuine operational drop-off. "
        "Stages are cumulative: reaching one requires passing all the earlier ones."
    )

    funnel = queries.funnel_stages(start, end)
    if funnel.empty:
        st.info("No orders in the selected range.")
    else:
        # The chart and the table each get the FULL width, stacked, rather than sharing a row.
        # Side by side, the table was squeezed into ~380px at a 1280px window and its last
        # column clipped to "Step co...". Streamlit has no breakpoint to fix that per-width,
        # so the layout that works at every width wins over the one that looks tidier at 1500px.
        st.plotly_chart(charts.funnel_chart(funnel), width="stretch")

        # A table view under every chart, so no reading depends on seeing colour.
        # Values are formatted as strings rather than left to a number formatter: thousands
        # separators matter for reading these at a glance, and the first row genuinely has no
        # "previous stage", which should read as a dash rather than the word "None".
        display = pd.DataFrame(
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
        )
        st.dataframe(display, hide_index=True, width="stretch")

        worst = funnel.iloc[1:].nlargest(1, "dropped_orders").iloc[0]
        previous_stage = funnel.loc[funnel.stage_order == worst.stage_order - 1, "stage_name"]
        st.info(
            f"**Biggest single loss: {previous_stage.iloc[0]} → {worst.stage_name}** — "
            f"{int(worst.dropped_orders):,} orders "
            f"({100 - worst.step_conversion_pct:.2f}% of those that got that far)."
        )

    # ---------------------------------------------------------------- revenue over time
    st.subheader("Revenue over time")
    revenue = queries.revenue_by_month(start, end)
    if not revenue.empty:
        left, right = st.columns(2)
        with left:
            st.markdown("**Monthly revenue**")
            st.plotly_chart(
                charts.revenue_line(revenue, "revenue", "Monthly revenue"),
                width="stretch",
            )
        with right:
            # Two measures of different scale => TWO charts. Never one chart with two y-axes.
            st.markdown("**Monthly order count**")
            st.plotly_chart(
                charts.revenue_line(revenue, "orders", "Orders", as_currency=False),
                width="stretch",
            )
        st.caption(
            "Revenue and order count are shown as two charts rather than one chart with two "
            "y-axes. A dual-axis chart lets the author choose where the lines cross, which "
            "makes any relationship between them look like whatever was intended."
        )

except Exception as exc:  # noqa: BLE001 - the UI must degrade, not traceback at the user
    show_database_error(exc)
