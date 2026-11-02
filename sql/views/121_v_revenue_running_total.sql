-- Business question: how is revenue accumulating over time, and is month-on-month growth
--                    speeding up or slowing down?
--
-- Three window functions over the same monthly series, which is the point of the view:
--   SUM(...) OVER (ORDER BY ...)   -> running total (each row sees all rows up to itself)
--   LAG(...)  OVER (ORDER BY ...)  -> the previous month, for month-over-month change
--   AVG(...)  OVER (... ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) -> 3-month moving average
--
-- The frame clause matters. A plain `SUM(x) OVER (ORDER BY m)` defaults to
-- RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW, which is what a running total wants.
-- The moving average has to say ROWS BETWEEN 2 PRECEDING AND CURRENT ROW explicitly,
-- otherwise it would average everything so far instead of the last three months.

\set ON_ERROR_STOP on

CREATE OR REPLACE VIEW analytics.v_revenue_running_total AS
WITH trading_months AS (
    -- Growth rates are computed over TRADING months only. Leaving the partial edge months in
    -- would make LAG compare a full month against a 1-order month and report a five-figure
    -- growth percentage (measured: +1,101,719% into 2017-01). The cumulative totals below are
    -- therefore also over trading months; the sparse months hold 4 orders in total, so the
    -- difference to the all-time total is immaterial and is stated in docs/QUERIES.md.
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
