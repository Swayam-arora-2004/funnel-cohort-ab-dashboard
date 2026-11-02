-- Business question: of the customers we acquired in a given month, what share came back
--                    and ordered again 1, 2, 3 ... months later?
--
-- This is the classic retention triangle. Read a row left to right to watch one cohort decay.
--
-- HONEST WARNING, stated here and on the dashboard: Olist is a near-single-purchase
-- marketplace. Retention will be very low -- low single-digit percent. That is the real
-- finding about this business, not a bug in the query (DECISIONS D-007). The Insights page
-- reports it as a finding with the measured number.
--
-- months_since = 0 is the acquisition month itself and is always 100% by construction. It is
-- kept because a heatmap with a solid 100% first column makes the decay in the later columns
-- easy to read against a baseline.

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
    -- How many whole months after acquisition did this order happen?
    -- Multiplying the year difference by 12 and adding the month difference is the readable
    -- way to get a month offset; subtracting dates would give days, which is not what a
    -- cohort grid is indexed by.
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
    -- DISTINCT because a customer placing two orders in the same month is still one
    -- retained customer, not two.
    count(DISTINCT a.customer_unique_id)   AS active_customers,
    round(100.0 * count(DISTINCT a.customer_unique_id) / s.new_customers, 2)
        AS retention_pct
FROM activity a
JOIN analytics.v_cohort_sizes s ON s.cohort_month = a.cohort_month
GROUP BY a.cohort_month, a.months_since_first_order, s.new_customers
ORDER BY a.cohort_month, months_since;

COMMENT ON VIEW analytics.v_cohort_retention IS
  'Retention triangle: of each acquisition-month cohort, the share still ordering N months later. months_since = 0 is the acquisition month and is 100% by construction. Expect very low retention - Olist is a near-single-purchase marketplace, and that is a finding, not a bug (D-007).';

\echo 'v_cohort_retention ready'
