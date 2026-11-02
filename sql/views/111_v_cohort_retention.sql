-- Of the customers acquired in a given month, what share ordered again N months later?
-- Expect very low numbers: Olist is a near-single-purchase marketplace. That is the finding.
-- months_since = 0 is the acquisition month and is 100% by construction.

\set ON_ERROR_STOP on

CREATE OR REPLACE VIEW analytics.v_cohort_retention AS
WITH customer_orders AS (
    -- Every order, tagged with the cohort of the person who placed it.
    SELECT
        f.cohort_month,
        f.customer_unique_id,
        date_trunc('month', o.order_purchase_timestamp)::date AS order_month
    FROM raw.orders o
    JOIN raw.customers c         ON c.customer_id        = o.customer_id
    JOIN analytics.v_customer_first_order f
                                 ON f.customer_unique_id = c.customer_unique_id
),
activity AS (
    -- whole months since acquisition: year difference x 12 plus the month difference
    SELECT
        cohort_month,
        customer_unique_id,
        (date_part('year',  order_month) - date_part('year',  cohort_month)) * 12
      + (date_part('month', order_month) - date_part('month', cohort_month))
            AS months_since_first_order
    FROM customer_orders
)
SELECT
    a.cohort_month,
    a.months_since_first_order::int        AS months_since,
    s.new_customers                        AS cohort_size,
    -- DISTINCT: two orders in one month is still one retained customer
    count(DISTINCT a.customer_unique_id)   AS active_customers,
    round(100.0 * count(DISTINCT a.customer_unique_id) / s.new_customers, 2)
        AS retention_pct
FROM activity a
JOIN analytics.v_cohort_sizes s ON s.cohort_month = a.cohort_month
GROUP BY a.cohort_month, a.months_since_first_order, s.new_customers
ORDER BY a.cohort_month, months_since;

COMMENT ON VIEW analytics.v_cohort_retention IS
  'Retention triangle: of each acquisition-month cohort, the share still ordering N months later. months_since = 0 is the acquisition month and is 100% by construction. Expect very low retention - Olist is a near-single-purchase marketplace, and that is a finding, not a bug.';

\echo 'v_cohort_retention ready'
