-- Which categories earn the most, and does the ranking change month to month?
-- PARTITION BY restarts the ranking inside each month. DENSE_RANK rather than RANK or
-- ROW_NUMBER: ties share a rank with no gap, so "rank <= 10" always returns ten revenue levels.

\set ON_ERROR_STOP on

CREATE OR REPLACE VIEW analytics.v_top_categories_ranked AS
WITH category_month AS (
    SELECT
        r.order_month,
        -- label the uncategorised rather than drop them, so monthly totals still reconcile
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
