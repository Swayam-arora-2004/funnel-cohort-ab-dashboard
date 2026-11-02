-- How many new customers did each month bring in?
-- A customer's cohort is the month of their first ever order, and it never changes.
-- Keyed on customer_unique_id -- customer_id is issued per order.

\set ON_ERROR_STOP on

CREATE OR REPLACE VIEW analytics.v_customer_first_order AS
SELECT
    c.customer_unique_id,
    min(o.order_purchase_timestamp)                           AS first_order_at,
    date_trunc('month', min(o.order_purchase_timestamp))::date AS cohort_month
FROM raw.orders o
JOIN raw.customers c ON c.customer_id = o.customer_id
GROUP BY c.customer_unique_id;

COMMENT ON VIEW analytics.v_customer_first_order IS
  'One row per real customer (customer_unique_id) with their first order date and cohort month. Building block for the cohort views; keyed on customer_unique_id, not customer_id.';

CREATE OR REPLACE VIEW analytics.v_cohort_sizes AS
SELECT
    cohort_month,
    count(*) AS new_customers
FROM analytics.v_customer_first_order
GROUP BY cohort_month
ORDER BY cohort_month;

COMMENT ON VIEW analytics.v_cohort_sizes IS
  'How many new customers each month brought in, where "new" = month of the customer first ever order. The denominator for every retention percentage.';

\echo 'v_cohort_sizes ready'
