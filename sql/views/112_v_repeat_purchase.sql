-- What share of customers ever buy a second time? The honest headline for retention.
-- Lives in a view, not a dashboard query: dashboard_ro has no access to raw at all.

\set ON_ERROR_STOP on

CREATE OR REPLACE VIEW analytics.v_customer_order_counts AS
SELECT
    c.customer_unique_id,
    count(*)                            AS orders,
    min(o.order_purchase_timestamp)     AS first_order_at,
    max(o.order_purchase_timestamp)     AS last_order_at
FROM raw.orders o
JOIN raw.customers c ON c.customer_id = o.customer_id
GROUP BY c.customer_unique_id;

COMMENT ON VIEW analytics.v_customer_order_counts IS
  'One row per real customer (customer_unique_id) with their lifetime order count and first/last order dates. Building block for the repeat-purchase headline.';

CREATE OR REPLACE VIEW analytics.v_repeat_purchase_summary AS
SELECT
    count(*) FILTER (WHERE orders > 1)                        AS repeat_customers,
    count(*)                                                  AS total_customers,
    count(*) FILTER (WHERE orders = 1)                         AS single_purchase_customers,
    round(100.0 * count(*) FILTER (WHERE orders > 1) / count(*), 2) AS repeat_pct,
    round(avg(orders), 4)                                      AS avg_orders_per_customer,
    max(orders)                                                AS max_orders_by_one_customer
FROM analytics.v_customer_order_counts;

COMMENT ON VIEW analytics.v_repeat_purchase_summary IS
  'The honest single number for retention: how many customers ever placed a second order. Expect a low figure - Olist is a near-single-purchase marketplace, and that is a finding, not a bug.';

\echo 'v_repeat_purchase_summary ready'
