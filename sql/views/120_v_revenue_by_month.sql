-- Business question: how much revenue did we make each month, from how many orders,
--                    and what was the average order value?
--
-- REVENUE DEFINITION, stated once here and used everywhere (this is the whole reason the
-- business logic lives in SQL, D-004):
--   revenue = SUM(order_items.price) for orders whose status is not 'canceled'
--   * freight_value is EXCLUDED -- it is shipping cost passed through, not merchandise revenue
--   * canceled orders are EXCLUDED -- the money was never realised
--
-- THE TRAP in this query: raw.order_items has one row PER ITEM, so an order with three items
-- has three rows. Joining orders to order_items and then counting orders would count that
-- order three times and inflate the order count (and therefore deflate AOV). The fix is to
-- aggregate items up to one row per order FIRST, then count.

\set ON_ERROR_STOP on

CREATE OR REPLACE VIEW analytics.v_order_revenue AS
SELECT
    o.order_id,
    date_trunc('month', o.order_purchase_timestamp)::date AS order_month,
    o.order_status,
    sum(i.price)         AS order_revenue,
    sum(i.freight_value) AS order_freight,
    count(*)             AS item_count
FROM raw.orders o
JOIN raw.order_items i ON i.order_id = o.order_id
WHERE o.order_status <> 'canceled'
GROUP BY o.order_id, o.order_purchase_timestamp, o.order_status;

COMMENT ON VIEW analytics.v_order_revenue IS
  'One row per non-canceled order with its merchandise revenue (sum of item prices, freight excluded). Collapses the one-row-per-item grain of raw.order_items so downstream order counts are not inflated.';

CREATE OR REPLACE VIEW analytics.v_revenue_by_month AS
SELECT
    order_month,
    count(*)                                   AS orders,
    round(sum(order_revenue), 2)               AS revenue,
    round(sum(order_freight), 2)               AS freight,
    -- AOV = revenue / orders. Because v_order_revenue is already one row per order,
    -- count(*) here is a true order count.
    round(sum(order_revenue) / nullif(count(*), 0), 2) AS avg_order_value,
    round(avg(item_count), 2)                  AS avg_items_per_order,
    -- Edge-month guard. The Olist extract does not start or stop cleanly: 2016-09 has 2
    -- orders, 2016-11 is missing entirely, 2016-12 has 1 order, 2018-09 has 1. Those months
    -- are not a business signal, they are the edges of the extract -- and they wreck derived
    -- metrics. Measured example: month-over-month revenue growth into 2017-01 computes as
    -- +1,101,719% purely because 2016-12 contained a single R$10.90 order.
    -- We FLAG rather than DELETE, so the totals still reconcile with raw.orders and the
    -- dashboard can decide. Threshold is 50 orders: every genuine trading month has
    -- thousands, every edge month has single digits, so nothing sits near the line.
    (count(*) < 50)                            AS is_sparse_month
FROM analytics.v_order_revenue
GROUP BY order_month
ORDER BY order_month;

COMMENT ON VIEW analytics.v_revenue_by_month IS
  'Monthly merchandise revenue, order count and average order value. Revenue = sum of item prices, excluding freight and canceled orders. AOV is correct because the grain was collapsed to one row per order first. is_sparse_month flags the partial months at the edges of the extract (<50 orders) - filter them out before reading any growth rate.';

\echo 'v_revenue_by_month ready'
