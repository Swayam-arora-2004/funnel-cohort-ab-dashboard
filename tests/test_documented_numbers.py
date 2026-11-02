"""Every published figure is re-derived here and compared to what is written down.

This is what makes "never invent a result" enforceable rather than
aspirational. If a view changes, or the data is reloaded differently, the documentation stops
matching reality and this test says so, naming the figure.

The DOCUMENTED column below is what the project notes
claim today. The LIVE column is recomputed from the database when the test runs.

Two things this test taught, both kept as comments where they apply:
  * `dashboard_ro` cannot read schema `raw`, so raw-layer checks need `engine_rw`.
  * The tolerance must match the precision the docs actually print. A figure published as
    "43.0%" claims one decimal, so comparing to three flagged a false mismatch.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from src.analysis import ab_report
from src.db import engine_ro, engine_rw, fetch_df

pytestmark = pytest.mark.db


def _exponent(value: float) -> int:
    """Base-10 exponent of a very small number, so a p-value can be pinned without pinning
    all 15 of its digits."""
    import math

    return math.floor(math.log10(value))


def _tolerance_for(fmt: str) -> float:
    """Half a unit of the last decimal place the docs actually print.

    A figure published as "43.0%" is only claimed to one decimal, so the honest test is
    whether the live value rounds to it. A fixed 0.005 tolerance flagged observed power as a
    mismatch when both columns read 43.0 -- a bug in the checker, not in the number.
    """
    decimals = int(fmt.split(".")[1].split("f")[0]) if "." in fmt else 0
    return 0.5 * (10**-decimals)


def test_every_documented_number_still_holds(rw_engine, ro_engine):
    """Re-derive all 56 published figures and compare. Reports every mismatch at once."""

    def q(sql, **p):
        """Analytics layer, as dashboard_ro -- the same role the dashboard uses."""
        return fetch_df(engine_ro(), text(sql), p)

    def qraw(sql, **p):
        """Raw layer. Needs loader_rw: dashboard_ro has NO privileges on `raw`."""
        return fetch_df(engine_rw(), text(sql), p)

    rows: list[tuple[str, str, str, bool]] = []

    def check(label, documented, live, fmt="{}"):
        if isinstance(documented, str):
            ok = str(documented) == str(live)
        else:
            ok = abs(float(documented) - float(live)) < _tolerance_for(fmt)
        rows.append((label, fmt.format(documented), fmt.format(live), ok))

    # ---------------------------------------------------------------- funnel (QUERIES.md 1-2)
    f = q("SELECT * FROM analytics.v_funnel_dropoff ORDER BY stage_order").set_index("stage_order")
    check("funnel stage 1 orders", 99441, int(f.loc[1, "orders_reaching"]), "{:,}")
    check("funnel stage 2 orders", 99281, int(f.loc[2, "orders_reaching"]), "{:,}")
    check("funnel stage 3 orders", 97644, int(f.loc[3, "orders_reaching"]), "{:,}")
    check("funnel stage 4 orders", 96461, int(f.loc[4, "orders_reaching"]), "{:,}")
    check("funnel stage 5 orders", 95815, int(f.loc[5, "orders_reaching"]), "{:,}")
    check("biggest drop (orders)", 1637, int(f.loc[3, "dropped_orders"]), "{:,}")
    check("biggest drop (%)", 1.65, float(f.loc[3, "step_dropoff_pct"]), "{:.2f}")
    check("payment drop (%)", 0.16, float(f.loc[2, "step_dropoff_pct"]), "{:.2f}")
    check("end-to-end completion (%)", 96.35, float(f.loc[5, "pct_of_all_orders"]), "{:.2f}")

    # ---------------------------------------------------------------- revenue (QUERIES.md 6-9)
    r = q(
        "SELECT round(sum(revenue),2) rev, sum(orders) ords FROM analytics.v_revenue_by_month"
    ).iloc[0]
    check("total revenue", 13496408.43, float(r.rev), "{:,.2f}")
    check("orders counted for revenue", 98205, int(r.ords), "{:,}")
    check("overall AOV", 137.43, float(r.rev) / int(r.ords), "{:,.2f}")

    cat = q(
        "SELECT category, round(sum(revenue),2) rev FROM analytics.v_top_categories_ranked "
        "GROUP BY category ORDER BY rev DESC LIMIT 1"
    ).iloc[0]
    check("top category name", "beleza_saude", str(cat.category))
    check("top category revenue", 1255695.13, float(cat.rev), "{:,.2f}")

    # ---------------------------------------------------------------- cohorts (QUERIES.md 3-5)
    rp = q("SELECT * FROM analytics.v_repeat_purchase_summary").iloc[0]
    check("customers (people)", 96096, int(rp.total_customers), "{:,}")
    check("repeat customers", 2997, int(rp.repeat_customers), "{:,}")
    check("repeat-purchase rate (%)", 3.12, float(rp.repeat_pct), "{:.2f}")

    m1 = q(
        "SELECT min(retention_pct) lo, max(retention_pct) hi FROM analytics.v_cohort_retention "
        "WHERE months_since = 1 AND cohort_size >= 1000"
    ).iloc[0]
    check("month-1 retention min (%)", 0.11, float(m1.lo), "{:.2f}")
    check("month-1 retention max (%)", 0.72, float(m1.hi), "{:.2f}")
    naive = q(
        "SELECT round(avg(retention_pct),2) a FROM analytics.v_cohort_retention "
        "WHERE months_since = 1"
    ).iloc[0]
    check("naive AVG() trap (%)", 5.22, float(naive["a"]), "{:.2f}")

    # ---------------------------------------------------------------- A/B (QUERIES.md 10)
    res = ab_report.run_all()
    visit, conv = res["visit"], res["conversion"]
    check("A/B control visit rate (%)", 3.8201, visit.rate_a * 100, "{:.4f}")
    check("A/B treatment visit rate (%)", 4.8543, visit.rate_b * 100, "{:.4f}")
    check("A/B control conversion rate (%)", 0.1938, conv.rate_a * 100, "{:.4f}")
    check("A/B treatment conversion rate (%)", 0.3089, conv.rate_b * 100, "{:.4f}")
    check("A/B visit lift (pp)", 1.0342, visit.diff_pp, "{:+.4f}")
    check("A/B conversion lift (pp)", 0.1152, conv.diff_pp, "{:+.4f}")
    check("A/B visit relative change (%)", 27.07, visit.relative_change_pct, "{:+.2f}")
    check("A/B conversion relative change (%)", 59.45, conv.relative_change_pct, "{:+.2f}")
    check("A/B visit z statistic", 65.2474, visit.z_stat, "{:+.4f}")
    check("A/B conversion z statistic", 28.5165, conv.z_stat, "{:+.4f}")
    check("A/B visit CI low (pp)", 1.0056, visit.ci_low_pp, "{:+.4f}")
    check("A/B visit CI high (pp)", 1.0629, visit.ci_high_pp, "{:+.4f}")
    check("A/B conversion CI low (pp)", 0.1085, conv.ci_low_pp, "{:+.4f}")
    check("A/B conversion CI high (pp)", 0.1219, conv.ci_high_pp, "{:+.4f}")
    check("A/B visit MDE (pp)", 0.0410, visit.mde_pp, "{:.4f}")
    check("A/B conversion MDE (pp)", 0.0096, conv.mde_pp, "{:.4f}")
    check("A/B control arm n", 2096937, conv.n_a, "{:,}")
    check("A/B treatment arm n", 11882655, conv.n_b, "{:,}")
    check("A/B control conversions", 4063, conv.conv_a, "{:,}")
    check("A/B treatment conversions", 36711, conv.conv_b, "{:,}")
    # The conversion p-value is representable; the visit one underflows float64 entirely
    # (z = 65.2), which is why _format_p prints a BOUND rather than claiming p = 0.
    check("A/B conversion p-value exponent", -179, _exponent(conv.p_value), "{:d}")
    assert visit.p_value == 0.0, "visit p-value is expected to underflow float64"

    # ---------------------------------------------------------------- data quality (DATA.md)
    dq = qraw(
        """
        SELECT
          (SELECT count(*) FROM raw.orders)         AS orders,
          (SELECT count(*) FROM raw.customers)      AS customers,
          (SELECT count(*) FROM raw.order_items)    AS items,
          (SELECT count(*) FROM raw.order_payments) AS pays,
          (SELECT count(*) FROM raw.order_reviews)  AS reviews,
          (SELECT count(*) FROM raw.products)       AS products,
          (SELECT count(*) FROM raw.ab_criteo_uplift) AS ab,
          (SELECT count(DISTINCT customer_id) FROM raw.customers)        AS cid,
          (SELECT count(DISTINCT customer_unique_id) FROM raw.customers) AS cuid
        """
    ).iloc[0]
    for lbl, doc, live in [
        ("rows raw.orders", 99441, dq["orders"]),
        ("rows raw.customers", 99441, dq["customers"]),
        ("rows raw.order_items", 112650, dq["items"]),
        ("rows raw.order_payments", 103886, dq["pays"]),
        ("rows raw.order_reviews", 99224, dq["reviews"]),
        ("rows raw.products", 32951, dq["products"]),
        ("rows criteo uplift", 13979592, dq["ab"]),
        ("distinct customer_id", 99441, dq["cid"]),
        ("distinct customer_unique_id", 96096, dq["cuid"]),
    ]:
        check(lbl, doc, int(live), "{:,}")
    check(
        "total rows loaded",
        14527185,
        int(
            dq["orders"]
            + dq["customers"]
            + dq["items"]
            + dq["pays"]
            + dq["reviews"]
            + dq["products"]
            + dq["ab"]
        ),
        "{:,}",
    )

    rev_no_del = qraw(
        "SELECT count(*) c FROM raw.orders o "
        "WHERE EXISTS (SELECT 1 FROM raw.order_reviews r WHERE r.order_id = o.order_id) "
        "AND o.order_delivered_customer_date IS NULL"
    ).iloc[0]
    check("reviews without delivery", 2843, int(rev_no_del["c"]), "{:,}")

    sparse = q(
        "SELECT count(*) c, sum(orders) o FROM analytics.v_revenue_by_month WHERE is_sparse_month"
    ).iloc[0]
    check("sparse months", 3, int(sparse["c"]), "{:,}")
    check("orders in sparse months", 4, int(sparse["o"]), "{:,}")

    mom = q("SELECT max(mom_revenue_change_pct) m FROM analytics.v_revenue_running_total").iloc[0]
    check("max genuine MoM growth (%)", 158.19, float(mom["m"]), "{:.2f}")

    ab_split = qraw(
        "SELECT treatment, count(*) c FROM raw.ab_criteo_uplift "
        "GROUP BY treatment ORDER BY treatment"
    )
    check("criteo withheld (control)", 2096937, int(ab_split.iloc[0]["c"]), "{:,}")
    check("criteo targeted (treatment)", 11882655, int(ab_split.iloc[1]["c"]), "{:,}")
    check(
        "criteo control share (%)",
        15.00,
        100 * int(ab_split.iloc[0]["c"]) / 13979592,
        "{:.2f}",
    )

    dates = qraw(
        "SELECT min(order_purchase_timestamp)::date a, max(order_purchase_timestamp)::date b "
        "FROM raw.orders"
    ).iloc[0]
    check("Olist period start", "2016-09-04", str(dates["a"]))
    check("Olist period end", "2018-10-17", str(dates["b"]))

    mismatches = [
        f"{label}: docs say {doc}, live is {live}" for label, doc, live, ok in rows if not ok
    ]
    assert not mismatches, (
        f"{len(mismatches)} of {len(rows)} documented figures no longer match the data:\n  "
        + "\n  ".join(mismatches)
    )
    assert len(rows) >= 60, "figures were removed from this check without being removed from docs"
