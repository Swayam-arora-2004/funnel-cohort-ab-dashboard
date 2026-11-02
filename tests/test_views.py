"""Invariant tests for the analytics views (milestone M2).

These do not assert specific business numbers -- those live in docs/QUERIES.md and would
change if the source data were refreshed. They assert properties that must hold for the SQL
to be CORRECT, which is what catches a broken query after an edit.

Every one of these was written because the view could plausibly violate it. The funnel
monotonicity test in particular caught a real bug: before the stage flags were made
cumulative, "Delivered & reviewed" counted 98,673 against only 96,476 deliveries, because
Olist sends its review survey when an order is placed rather than when it arrives.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.db

ALL_VIEWS = [
    "v_funnel_stages",
    "v_funnel_dropoff",
    "v_customer_first_order",
    "v_cohort_sizes",
    "v_cohort_retention",
    "v_customer_order_counts",
    "v_repeat_purchase_summary",
    "v_order_revenue",
    "v_revenue_by_month",
    "v_revenue_running_total",
    "v_top_categories_ranked",
    "v_ab_summary",
]


def _rows(engine, sql: str, **params):
    with engine.connect() as conn:
        return conn.execute(text(sql), params).all()


def _scalar(engine, sql: str, **params):
    with engine.connect() as conn:
        return conn.execute(text(sql), params).scalar_one()


# --------------------------------------------------------------- existence & documentation


@pytest.mark.parametrize("view", ALL_VIEWS)
def test_view_returns_rows(ro_engine, view):
    """Every view exists, is readable by dashboard_ro, and is not empty."""
    assert _scalar(ro_engine, f"SELECT count(*) FROM analytics.{view}") > 0  # noqa: S608


@pytest.mark.parametrize("view", ALL_VIEWS)
def test_view_has_a_comment(ro_engine, view):
    """FR-7: every view documents its business question. An undocumented view fails here."""
    comment = _scalar(
        ro_engine,
        "SELECT obj_description(format('analytics.%I', :v)::regclass, 'pg_class')",
        v=view,
    )
    assert comment and len(comment) > 40, f"analytics.{view} has no meaningful COMMENT ON VIEW"


def test_at_least_six_views_exist(ro_engine):
    """FR-7 requires at least six documented views."""
    count = _scalar(
        ro_engine,
        "SELECT count(*) FROM information_schema.views WHERE table_schema = 'analytics'",
    )
    assert count >= 6


# --------------------------------------------------------------- funnel


def test_funnel_is_monotonically_non_increasing(ro_engine):
    """An order cannot reach stage N without having reached stage N-1.

    This is THE funnel invariant. It failed on the first implementation and is the reason the
    stage flags are cumulative (see the comment block in 100_v_funnel_stages.sql).
    """
    rows = _rows(
        ro_engine,
        "SELECT stage_order, stage_name, orders_reaching "
        "FROM analytics.v_funnel_dropoff ORDER BY stage_order",
    )
    counts = [r.orders_reaching for r in rows]
    assert counts == sorted(counts, reverse=True), "funnel is not monotonic: " + ", ".join(
        f"{r.stage_name}={r.orders_reaching}" for r in rows
    )


def test_funnel_has_five_stages(ro_engine):
    assert _scalar(ro_engine, "SELECT count(*) FROM analytics.v_funnel_dropoff") == 5


def test_funnel_first_stage_equals_total_orders(ro_engine):
    """Stage 1 is every order placed, so it must equal the row count of raw.orders."""
    stage1 = _scalar(
        ro_engine, "SELECT orders_reaching FROM analytics.v_funnel_dropoff WHERE stage_order = 1"
    )
    assert stage1 == 99_441


def test_funnel_percentages_are_in_range(ro_engine):
    """No conversion or drop-off rate may fall outside 0-100%."""
    bad = _scalar(
        ro_engine,
        "SELECT count(*) FROM analytics.v_funnel_dropoff "
        "WHERE step_conversion_pct < 0 OR step_conversion_pct > 100 "
        "   OR step_dropoff_pct    < 0 OR step_dropoff_pct    > 100 "
        "   OR pct_of_all_orders   < 0 OR pct_of_all_orders   > 100",
    )
    assert bad == 0


# --------------------------------------------------------------- cohorts


def test_retention_never_exceeds_100_percent(ro_engine):
    """More customers cannot return than were acquired."""
    bad = _scalar(
        ro_engine,
        "SELECT count(*) FROM analytics.v_cohort_retention WHERE retention_pct > 100",
    )
    assert bad == 0


def test_month_zero_retention_is_always_100(ro_engine):
    """Every customer is active in their own acquisition month, by construction."""
    bad = _scalar(
        ro_engine,
        "SELECT count(*) FROM analytics.v_cohort_retention "
        "WHERE months_since = 0 AND retention_pct <> 100",
    )
    assert bad == 0


def test_no_negative_month_offsets(ro_engine):
    """A customer cannot be active before their own first order."""
    bad = _scalar(
        ro_engine, "SELECT count(*) FROM analytics.v_cohort_retention WHERE months_since < 0"
    )
    assert bad == 0


def test_cohort_sizes_sum_to_customer_count(ro_engine):
    """Every customer belongs to exactly one cohort, so the cohorts must partition them."""
    total_cohorts = _scalar(ro_engine, "SELECT sum(new_customers) FROM analytics.v_cohort_sizes")
    customers = _scalar(ro_engine, "SELECT count(*) FROM analytics.v_customer_first_order")
    assert total_cohorts == customers == 96_096


# --------------------------------------------------------------- revenue


def test_revenue_is_never_negative(ro_engine):
    bad = _scalar(
        ro_engine,
        "SELECT count(*) FROM analytics.v_revenue_by_month "
        "WHERE revenue < 0 OR orders < 0 OR avg_order_value < 0",
    )
    assert bad == 0


def test_order_revenue_grain_is_one_row_per_order(ro_engine):
    """v_order_revenue must collapse the one-row-per-item grain of raw.order_items.

    If this breaks, every order count is inflated and every AOV is wrong.
    """
    rows = _scalar(ro_engine, "SELECT count(*) FROM analytics.v_order_revenue")
    distinct_orders = _scalar(
        ro_engine, "SELECT count(DISTINCT order_id) FROM analytics.v_order_revenue"
    )
    assert rows == distinct_orders


def test_canceled_orders_are_excluded_from_revenue(ro_engine):
    excluded = _scalar(
        ro_engine,
        "SELECT count(*) FROM analytics.v_order_revenue WHERE order_status = 'canceled'",
    )
    assert excluded == 0


def test_running_total_is_non_decreasing(ro_engine):
    """A cumulative sum of non-negative revenue can only go up."""
    values = [
        r.cumulative_revenue
        for r in _rows(
            ro_engine,
            "SELECT cumulative_revenue FROM analytics.v_revenue_running_total ORDER BY order_month",
        )
    ]
    assert values == sorted(values)


def test_running_total_excludes_sparse_months(ro_engine):
    """The growth series must not include the partial months at the edges of the extract."""
    sparse_in_series = _scalar(
        ro_engine,
        "SELECT count(*) FROM analytics.v_revenue_running_total t "
        "JOIN analytics.v_revenue_by_month m USING (order_month) "
        "WHERE m.is_sparse_month",
    )
    assert sparse_in_series == 0


def test_category_shares_sum_to_100_per_month(ro_engine):
    """Within a month, every category's share of revenue must add up to 100%."""
    bad = _scalar(
        ro_engine,
        "SELECT count(*) FROM ("
        "  SELECT order_month, sum(pct_of_month_revenue) AS total"
        "  FROM analytics.v_top_categories_ranked GROUP BY order_month"
        ") s WHERE abs(total - 100) > 0.5",  # 0.5pp tolerance for per-row rounding
    )
    assert bad == 0


def test_category_rank_starts_at_one_each_month(ro_engine):
    """PARTITION BY must restart the ranking per month, not rank across the whole dataset."""
    bad = _scalar(
        ro_engine,
        "SELECT count(*) FROM ("
        "  SELECT order_month, min(category_rank) AS top"
        "  FROM analytics.v_top_categories_ranked GROUP BY order_month"
        ") s WHERE top <> 1",
    )
    assert bad == 0


# --------------------------------------------------------------- A/B


def test_ab_summary_has_four_rows(ro_engine):
    """Two metrics x two variants. Both metrics are reported so neither can be cherry-picked."""
    assert _scalar(ro_engine, "SELECT count(*) FROM analytics.v_ab_summary") == 4


def test_ab_conversions_never_exceed_users(ro_engine):
    bad = _scalar(ro_engine, "SELECT count(*) FROM analytics.v_ab_summary WHERE converted > users")
    assert bad == 0


def test_ab_user_totals_match_the_source_table(ro_engine):
    """Per metric, the two arms must account for every player exactly once."""
    rows = _rows(
        ro_engine,
        "SELECT metric, sum(users) AS total FROM analytics.v_ab_summary GROUP BY metric",
    )
    assert len(rows) == 2
    for row in rows:
        assert row.total == 90_189, f"{row.metric} covers {row.total} users, expected 90,189"


def test_exactly_one_control_arm_per_metric(ro_engine):
    bad = _scalar(
        ro_engine,
        "SELECT count(*) FROM ("
        "  SELECT metric, count(*) FILTER (WHERE is_control) AS controls"
        "  FROM analytics.v_ab_summary GROUP BY metric"
        ") s WHERE controls <> 1",
    )
    assert bad == 0


def test_repeat_purchase_summary_is_internally_consistent(ro_engine):
    """repeat + single must account for every customer, and the percentage must match."""
    with ro_engine.connect() as conn:
        row = conn.execute(text("SELECT * FROM analytics.v_repeat_purchase_summary")).one()
    assert row.repeat_customers + row.single_purchase_customers == row.total_customers
    assert row.total_customers == 96_096
    expected = round(100 * row.repeat_customers / row.total_customers, 2)
    assert float(row.repeat_pct) == pytest.approx(expected, abs=0.01)


def test_dashboard_role_can_read_every_view_it_needs(ro_engine):
    """The app must never need a privilege it does not have.

    This test exists because an earlier version of app/components/queries.py joined raw.orders
    directly and failed at runtime with "permission denied for schema raw" (SEC-5). Asserting
    that every view the dashboard reads is reachable as dashboard_ro turns that class of
    mistake into a test failure rather than a broken page.
    """
    for view in ALL_VIEWS:
        _scalar(ro_engine, f"SELECT count(*) FROM analytics.{view}")  # noqa: S608
