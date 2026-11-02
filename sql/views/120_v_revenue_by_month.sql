-- Revenue, order count and average order value per month.
-- Revenue = SUM(order_items.price) for non-canceled orders. Freight excluded -- it is
-- pass-through shipping cost, not merchandise revenue.
-- order_items is one row per ITEM, so v_order_revenue collapses to one row per order first;
-- counting orders before that would triple-count a 3-item order and deflate AOV.

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
    -- count(*) is a true order count because v_order_revenue is one row per order
    round(sum(order_revenue) / nullif(count(*), 0), 2) AS avg_order_value,
    round(avg(item_count), 2)                  AS avg_items_per_order,
    -- The extract has partial months at both ends (2016-12 holds one R$10.90 order), which
    -- made growth into 2017-01 read +1,101,719%. Flagged rather than deleted so the totals
    -- still reconcile. Real months have thousands of orders, edge months single digits.
    (count(*) < 50)                            AS is_sparse_month
FROM analytics.v_order_revenue
GROUP BY order_month
ORDER BY order_month;

COMMENT ON VIEW analytics.v_revenue_by_month IS
  'Monthly merchandise revenue, order count and average order value. Revenue = sum of item prices, excluding freight and canceled orders. AOV is correct because the grain was collapsed to one row per order first. is_sparse_month flags the partial months at the edges of the extract (<50 orders) - filter them out before reading any growth rate.';

\echo 'v_revenue_by_month ready'
