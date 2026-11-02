-- Business question: which product categories earn the most, and does the ranking change
--                    from month to month?
--
-- PARTITION BY is the key idea: the ranking restarts inside each month, so every month gets
-- its own #1, #2, #3 rather than one ranking across the whole dataset. The dashboard filters
-- to category_rank <= 10 to get a per-month top ten with a single query.
--
-- DENSE_RANK, not RANK or ROW_NUMBER, chosen deliberately:
--   ROW_NUMBER -> breaks ties arbitrarily; two categories with equal revenue get 1 and 2,
--                 and which one wins changes between runs. Not reproducible.
--   RANK       -> ties share a rank but then SKIP (1, 1, 3), so "top 3" can return 2 rows.
--   DENSE_RANK -> ties share a rank and the next value follows (1, 1, 2), so "rank <= 10"
--                 always returns the ten best revenue LEVELS. That is what a business means.

\set ON_ERROR_STOP on

CREATE OR REPLACE VIEW analytics.v_top_categories_ranked AS
WITH category_month AS (
    SELECT
        r.order_month,
        -- A small number of products have no category in the source data. Labelling them
        -- rather than dropping them keeps the monthly totals reconcilable with
        -- v_revenue_by_month; silently dropping rows is how two dashboards stop agreeing.
        coalesce(p.product_category_name, 'uncategorised') AS category,
        sum(i.price)                AS revenue,
        count(DISTINCT i.order_id)  AS orders
    FROM raw.order_items i
    JOIN analytics.v_order_revenue r ON r.order_id = i.order_id
    LEFT JOIN raw.products p         ON p.product_id = i.product_id
    GROUP BY r.order_month, coalesce(p.product_category_name, 'uncategorised')
)
SELECT
    order_month,
    category,
    round(revenue, 2) AS revenue,
    orders,
    dense_rank() OVER (PARTITION BY order_month ORDER BY revenue DESC) AS category_rank,
    round(
        100.0 * revenue / sum(revenue) OVER (PARTITION BY order_month),
        2
    ) AS pct_of_month_revenue
FROM category_month
ORDER BY order_month, category_rank;

COMMENT ON VIEW analytics.v_top_categories_ranked IS
  'Product categories ranked by revenue WITHIN each month (DENSE_RANK with PARTITION BY), plus each category share of that month revenue. Filter category_rank <= N for a per-month top N.';

\echo 'v_top_categories_ranked ready'
