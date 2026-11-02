"""Tests for the dashboard layer (milestone M4).

Streamlit pages cannot easily be unit-tested, but everything that actually breaks can be:
the queries and the chart builders. These tests run them headlessly, which catches the two
failure modes that matter:

  1. **A query the read-only role cannot run.** This is not hypothetical -- an earlier version
     of `repeat_purchase_rate()` joined `raw.orders` directly and failed in the browser with
     "permission denied for schema raw". The privilege boundary (SEC-5) caught a real mistake,
     and the fix was to move the logic into a view where it belonged anyway (D-004).

  2. **A chart that raises while being built.** A Plotly figure is constructed eagerly, so a
     bad column name or a shape mismatch raises here rather than rendering an empty panel.

These are marked `db` and skip without a database, like the other integration tests.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def dashboard_modules(ro_engine):  # noqa: ARG001 - the fixture forces the skip when no DB
    from app.components import charts, queries

    return charts, queries


def test_every_query_runs_as_the_readonly_role(dashboard_modules):
    """Each dashboard query must work with ONLY SELECT on analytics.

    Note what is being asserted: not that the numbers are right (test_views.py does that) but
    that the app never needs a privilege it does not have.
    """
    charts, queries = dashboard_modules
    start, end = queries.available_date_range()

    assert queries.kpi_totals(start, end).orders > 0
    assert queries.delivery_completion_rate(start, end) > 0
    assert not queries.funnel_stages(start, end).empty
    assert not queries.funnel_dropoff().empty
    assert not queries.cohort_retention().empty
    assert queries.repeat_purchase_rate().total_customers == 96_096
    assert not queries.revenue_by_month(start, end).empty
    assert not queries.revenue_running_total().empty
    assert not queries.top_categories().empty
    for metric in queries.AB_METRICS:
        assert len(queries.ab_summary(metric)) == 2


def test_every_chart_builds(dashboard_modules):
    """Build each figure. A broken column reference raises at construction time."""
    charts, queries = dashboard_modules
    start, end = queries.available_date_range()

    funnel = queries.funnel_stages(start, end)
    assert charts.funnel_chart(funnel).data

    retention = queries.cohort_retention()
    assert charts.cohort_heatmap(retention).data

    revenue = queries.revenue_by_month(start, end)
    assert charts.revenue_line(revenue, "revenue", "Monthly revenue").data
    assert charts.revenue_line(revenue, "orders", "Orders", as_currency=False).data

    for metric in queries.AB_METRICS:
        assert charts.ab_comparison_chart(queries.ab_summary(metric), metric).data

    assert charts.confidence_interval_chart(-1.33, -0.31, -0.82).data


def test_ab_metric_is_allowlisted(dashboard_modules):
    """An unknown metric is rejected before it reaches the query (SEC-3)."""
    charts, queries = dashboard_modules
    with pytest.raises(ValueError, match="unknown metric"):
        queries.ab_summary("conversion'; DROP TABLE raw.orders; --")


def test_date_range_comes_from_the_data(dashboard_modules):
    """The picker's bounds are read from the data, so it cannot offer a month that is absent.

    It must also exclude the sparse edge months -- offering 2018-09 (one order) as a selectable
    bound would let a user produce a chart of a single data point.
    """
    charts, queries = dashboard_modules
    start, end = queries.available_date_range()
    assert str(start) == "2016-10-01"
    assert str(end) == "2018-08-01"


def test_kpi_aov_is_recomputed_not_averaged(dashboard_modules):
    """AOV over a window must be total revenue / total orders, not the mean of monthly AOVs.

    The two differ because averaging weights a quiet month the same as a busy one. This test
    pins the correct one.
    """
    charts, queries = dashboard_modules
    start, end = queries.available_date_range()

    kpis = queries.kpi_totals(start, end)
    monthly = queries.revenue_by_month(start, end)

    recomputed = float(kpis.revenue) / float(kpis.orders)
    naive_mean = float(monthly.avg_order_value.mean())

    assert float(kpis.avg_order_value) == pytest.approx(recomputed, abs=0.01)
    # They really are different, which is why this matters.
    assert abs(float(kpis.avg_order_value) - naive_mean) > 0.01


def test_funnel_percentages_are_recomputed_per_window(dashboard_modules):
    """Stage COUNTS sum across months; stage RATES do not.

    Summing counts is exact. Averaging monthly conversion rates would weight months equally
    regardless of volume, so the percentages are recomputed from the summed counts.
    """
    charts, queries = dashboard_modules
    start, end = queries.available_date_range()
    funnel = queries.funnel_stages(start, end)

    entry = funnel.orders_reaching.iloc[0]
    for _, row in funnel.iterrows():
        assert row.pct_of_all_orders == pytest.approx(row.orders_reaching / entry * 100, abs=1e-9)
    # And the funnel must still be monotonic after the window filter.
    counts = list(funnel.orders_reaching)
    assert counts == sorted(counts, reverse=True)
