"""Every query the dashboard runs. No SQL text exists anywhere else under app/.

All of it is parameterised and all of it goes through engine_ro(), which connects as
dashboard_ro -- SELECT on analytics, nothing on raw.

Cached with st.cache_data; the TTL means a reload after `make load` picks up new data without
a restart.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st
from sqlalchemy import text

from src.db import engine_ro, fetch_df

CACHE_TTL_SECONDS = 600

# checked against this allowlist before reaching the query, for a clear error
AB_METRICS: tuple[str, ...] = ("visit", "conversion")


def _run(sql: str, params: dict | None = None) -> pd.DataFrame:
    return fetch_df(engine_ro(), text(sql), params)


# ---------------------------------------------------------------- date bounds


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def available_date_range() -> tuple[date, date]:
    """Bounds for the date picker, read from the data so it cannot offer a month that is
    not there."""
    frame = _run(
        "SELECT min(order_month) AS first_month, max(order_month) AS last_month "
        "FROM analytics.v_revenue_by_month WHERE NOT is_sparse_month"
    )
    return frame.first_month.iloc[0], frame.last_month.iloc[0]


# ---------------------------------------------------------------- KPI tiles (FR-16)


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def kpi_totals(start: date, end: date) -> pd.Series:
    """Orders, revenue and AOV for the selected months.

    AOV is recomputed from the totals, not averaged across months -- averaging would weight a
    quiet month the same as a busy one.
    """
    frame = _run(
        """
        SELECT
            sum(orders)                                AS orders,
            sum(revenue)                               AS revenue,
            sum(revenue) / nullif(sum(orders), 0)      AS avg_order_value,
            sum(freight)                               AS freight
        FROM analytics.v_revenue_by_month
        WHERE order_month BETWEEN :start AND :end
          AND NOT is_sparse_month
        """,
        {"start": start, "end": end},
    )
    return frame.iloc[0]


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def delivery_completion_rate(start: date, end: date) -> float:
    """Share of orders that completed the whole funnel. Reads the funnel view, so it uses the
    same stage definition as the chart."""
    frame = _run(
        """
        SELECT
            sum(orders_reaching) FILTER (WHERE stage_order = 5)::numeric
          / nullif(sum(orders_reaching) FILTER (WHERE stage_order = 1), 0) * 100
                AS completion_pct
        FROM analytics.v_funnel_stages
        WHERE order_month BETWEEN :start AND :end
        """,
        {"start": start, "end": end},
    )
    value = frame.completion_pct.iloc[0]
    return float(value) if value is not None else 0.0


# ---------------------------------------------------------------- funnel (FR-17)


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def funnel_stages(start: date, end: date) -> pd.DataFrame:
    """Stage counts for the selected months, with step and cumulative conversion.

    Counts sum across months; rates do not, so the percentages are recomputed from the summed
    counts. The stage definition itself stays in SQL.
    """
    frame = _run(
        """
        SELECT stage_order, stage_name, sum(orders_reaching) AS orders_reaching
        FROM analytics.v_funnel_stages
        WHERE order_month BETWEEN :start AND :end
        GROUP BY stage_order, stage_name
        ORDER BY stage_order
        """,
        {"start": start, "end": end},
    )
    if frame.empty:
        return frame
    entry = frame.orders_reaching.iloc[0]
    previous = frame.orders_reaching.shift(1)
    frame["pct_of_all_orders"] = frame.orders_reaching / entry * 100
    frame["step_conversion_pct"] = frame.orders_reaching / previous * 100
    frame["dropped_orders"] = previous - frame.orders_reaching
    return frame


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def funnel_dropoff() -> pd.DataFrame:
    """All-time stage-to-stage drop-off, straight from the view (no re-derivation)."""
    return _run("SELECT * FROM analytics.v_funnel_dropoff ORDER BY stage_order")


# ---------------------------------------------------------------- cohorts (FR-18)


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def cohort_retention(min_cohort_size: int = 1000, max_months: int = 12) -> pd.DataFrame:
    """Retention matrix, restricted to cohorts large enough to mean anything.

    The 2016-12 cohort has one customer, so one repeat purchase reads as 100% and drags an
    unweighted average up tenfold -- 5.22% against a real sub-1%.
    """
    return _run(
        """
        SELECT cohort_month, months_since, cohort_size, active_customers, retention_pct
        FROM analytics.v_cohort_retention
        WHERE cohort_size >= :min_size
          AND months_since BETWEEN 0 AND :max_months
        ORDER BY cohort_month, months_since
        """,
        {"min_size": min_cohort_size, "max_months": max_months},
    )


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def repeat_purchase_rate() -> pd.Series:
    """Share of customers who ever placed a second order.

    Reads the view rather than joining raw.orders here -- dashboard_ro has no rights on raw,
    and the definition of "repeat customer" belongs in the analytics layer anyway.
    """
    return _run("SELECT * FROM analytics.v_repeat_purchase_summary").iloc[0]


# ---------------------------------------------------------------- revenue


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def revenue_by_month(start: date, end: date) -> pd.DataFrame:
    """Monthly revenue, orders and AOV. Sparse edge months excluded (D-014)."""
    return _run(
        """
        SELECT order_month, orders, revenue, avg_order_value, avg_items_per_order
        FROM analytics.v_revenue_by_month
        WHERE order_month BETWEEN :start AND :end
          AND NOT is_sparse_month
        ORDER BY order_month
        """,
        {"start": start, "end": end},
    )


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def revenue_running_total() -> pd.DataFrame:
    return _run("SELECT * FROM analytics.v_revenue_running_total ORDER BY order_month")


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def top_categories(limit: int = 10) -> pd.DataFrame:
    """Top categories by all-time revenue. LIMIT takes a bind parameter, so it is bound."""
    return _run(
        """
        SELECT category, sum(revenue) AS revenue, sum(orders) AS orders
        FROM analytics.v_top_categories_ranked
        GROUP BY category
        ORDER BY revenue DESC
        LIMIT :limit
        """,
        {"limit": limit},
    )


# ---------------------------------------------------------------- A/B (FR-19)


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def ab_summary(metric: str) -> pd.DataFrame:
    """Per-arm counts for one metric. `metric` is allowlisted before use."""
    if metric not in AB_METRICS:
        raise ValueError(f"unknown metric {metric!r}; expected one of {AB_METRICS}")
    return _run(
        """
        SELECT metric, variant, is_control, users, converted, conversion_rate_pct
        FROM analytics.v_ab_summary
        WHERE metric = :metric
        ORDER BY is_control DESC
        """,
        {"metric": metric},
    )
