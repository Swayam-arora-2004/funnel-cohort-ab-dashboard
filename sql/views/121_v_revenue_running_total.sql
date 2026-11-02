-- Is revenue growth accelerating or slowing?
-- SUM OVER for the running total, LAG for month-over-month, AVG OVER with an explicit
-- ROWS frame for the 3-month moving average -- the default frame would average everything
-- so far instead of the last three months.

\set ON_ERROR_STOP on

CREATE OR REPLACE VIEW analytics.v_revenue_running_total AS
WITH trading_months AS (
    -- trading months only: the three partial edge months hold 4 orders between them and
    -- would make LAG report a five-figure growth percentage
    SELECT * FROM analytics.v_revenue_by_month WHERE NOT is_sparse_month
)
SELECT
    order_month,
    orders,
    revenue,
    avg_order_value,
    sum(revenue) OVER (ORDER BY order_month)          AS cumulative_revenue,
    sum(orders)  OVER (ORDER BY order_month)          AS cumulative_orders,
    lag(revenue) OVER (ORDER BY order_month)          AS previous_month_revenue,
    revenue - lag(revenue) OVER (ORDER BY order_month) AS mom_revenue_change,
    round(
        100.0 * (revenue - lag(revenue) OVER (ORDER BY order_month))
        / nullif(lag(revenue) OVER (ORDER BY order_month), 0),
        2
    )                                                  AS mom_revenue_change_pct,
    round(
        avg(revenue) OVER (ORDER BY order_month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW),
        2
    )                                                  AS revenue_3mo_moving_avg
FROM trading_months
ORDER BY order_month;

COMMENT ON VIEW analytics.v_revenue_running_total IS
  'Cumulative revenue, month-over-month change and a 3-month moving average, built with SUM/LAG/AVG window functions. Restricted to trading months (is_sparse_month = false) so a 1-order edge month cannot produce a nonsense growth rate. Answers "is growth accelerating or slowing?".';

\echo 'v_revenue_running_total ready'
