"""Cohort retention heatmap (FR-18, FR-21)."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import streamlit as st

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.components import charts, layout, queries  # noqa: E402 - after the sys.path fix

log = logging.getLogger(__name__)
st.set_page_config(page_title="Cohorts", page_icon="bar_chart", layout="wide")

# Scroll the browser window, not Streamlit\'s inner container (D-021).
layout.use_window_scrolling()

st.title("Cohort retention")
st.caption(
    "**Source: Olist Brazilian E-Commerce.** A customer's cohort is the month of their first "
    "ever order. Retention in month *k* is the share of that cohort who placed another order "
    "in month *k*."
)

try:
    repeat = queries.repeat_purchase_rate()

    st.subheader("The headline first")
    tiles = st.columns(3)
    with tiles[0]:
        charts.kpi_tile(
            "Customers",
            f"{int(repeat.total_customers):,}",
            "Distinct customer_unique_id values. NOT customer_id -- Olist issues a fresh "
            "customer_id for every order, so counting those gives 99,441 and overstates the "
            "customer base by about 3,300 people.",
        )
    with tiles[1]:
        charts.kpi_tile(
            "Ever bought twice",
            f"{int(repeat.repeat_customers):,}",
            "Customers with more than one order, over the full two-year window.",
        )
    with tiles[2]:
        charts.kpi_tile(
            "Repeat-purchase rate",
            f"{float(repeat.repeat_pct):.2f}%",
            "The honest single number for retention on this dataset.",
        )

    st.warning(
        f"**Only {float(repeat.repeat_pct):.2f}% of customers ever place a second order**, so "
        "every cell below is small by nature — that is the real shape of this marketplace, not "
        "a broken query."
    )

    with st.container(border=True):
        min_size = st.select_slider(
            "Minimum cohort size",
            options=[1, 100, 500, 1000, 2000],
            value=1000,
            help=(
                "Not cosmetic. The 2016-12 cohort contains ONE customer, so if that person "
                "returns the cohort reads 100% and drags any average up tenfold. Averaging "
                "month-1 retention across all cohorts gives 5.22%; the real figure for "
                "meaningful cohorts is under 1%. Set this to 1 to see the distortion."
            ),
        )

    retention = queries.cohort_retention(min_cohort_size=min_size)
    if retention.empty:
        st.info("No cohorts meet that minimum size.")
    else:
        st.subheader("Retention triangle")
        st.plotly_chart(charts.cohort_heatmap(retention), width="stretch")
        st.caption(
            "Read a row left to right to watch one cohort decay. **M0 is the acquisition month "
            "itself and is 100% by construction** — kept as the baseline to read the later "
            "columns against, and excluded from the colour scale so the real variation is not "
            "compressed into the palest step."
        )

        month1 = retention[retention.months_since == 1]
        if not month1.empty:
            best = month1.nlargest(1, "retention_pct").iloc[0]
            st.info(
                f"**Best month-1 retention: {best.cohort_month:%B %Y}** — "
                f"{best.retention_pct:.2f}% "
                f"({int(best.active_customers):,} of {int(best.cohort_size):,} customers "
                "returned the following month)."
            )

        # Table view, so nothing on this page requires seeing colour.
        with st.expander("Table view (every value in the heatmap)"):
            display = retention.copy()
            display.columns = [
                "Cohort",
                "Months since",
                "Cohort size",
                "Active customers",
                "Retention %",
            ]
            st.dataframe(
                display,
                hide_index=True,
                width="stretch",
                column_config={"Retention %": st.column_config.NumberColumn(format="%.2f%%")},
            )

except Exception as exc:  # noqa: BLE001
    log.exception("cohort page query failed")
    st.error("Could not load cohort data. See the server log for details.")
    st.caption(f"Error type: {type(exc).__name__}")
