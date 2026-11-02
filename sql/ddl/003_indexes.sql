-- 003_indexes.sql
-- Every index here exists to serve a named query. If you cannot name the query, the index
-- should not exist -- an unused index costs write time and disk for nothing.
-- Re-runnable (CREATE INDEX IF NOT EXISTS).
--
-- Interview note: PostgreSQL already creates an index for every PRIMARY KEY, so none of the
-- PK columns are repeated below. These are the FOREIGN-KEY-side and FILTER/GROUP-BY columns,
-- which Postgres does NOT index automatically.

\set ON_ERROR_STOP on

-- ---------------------------------------------------------------- orders
-- Serves: v_cohort_* -- joins orders to customers to reach customer_unique_id.
CREATE INDEX IF NOT EXISTS ix_orders_customer_id
    ON raw.orders (customer_id);
COMMENT ON INDEX raw.ix_orders_customer_id IS
  'Serves analytics.v_cohort_sizes and v_cohort_retention: the orders -> customers join.';

-- Serves: every view with a date range -- the funnel, revenue by month, the KPI tiles.
-- The expression matches date_trunc('month', ...) used in the revenue views, so Postgres can
-- use the index instead of computing date_trunc for every row.
CREATE INDEX IF NOT EXISTS ix_orders_purchase_month
    ON raw.orders (date_trunc('month', order_purchase_timestamp));
COMMENT ON INDEX raw.ix_orders_purchase_month IS
  'Serves analytics.v_revenue_by_month and v_cohort_*: GROUP BY date_trunc(month, order_purchase_timestamp).';

-- Serves: the dashboard date-range filter, which bounds the raw timestamp directly.
CREATE INDEX IF NOT EXISTS ix_orders_purchase_ts
    ON raw.orders (order_purchase_timestamp);
COMMENT ON INDEX raw.ix_orders_purchase_ts IS
  'Serves app/components/queries.py date-range filters (BETWEEN on order_purchase_timestamp).';

-- Serves: v_funnel_stages -- counts orders by status, and the delivery-rate KPI tile.
CREATE INDEX IF NOT EXISTS ix_orders_status
    ON raw.orders (order_status);
COMMENT ON INDEX raw.ix_orders_status IS
  'Serves analytics.v_funnel_stages and the delivery-completion KPI tile: filter/group on order_status.';

-- ---------------------------------------------------------------- order_items
-- The PK is (order_id, order_item_id), so order_id alone is already covered by that index's
-- leading column -- no separate index needed. This one is for the product join.
-- Serves: v_top_categories_ranked -- order_items -> products.
CREATE INDEX IF NOT EXISTS ix_order_items_product_id
    ON raw.order_items (product_id);
COMMENT ON INDEX raw.ix_order_items_product_id IS
  'Serves analytics.v_top_categories_ranked: the order_items -> products join.';

-- ---------------------------------------------------------------- order_reviews
-- Serves: v_funnel_stages -- the final funnel stage is "a review exists for this order".
CREATE INDEX IF NOT EXISTS ix_order_reviews_order_id
    ON raw.order_reviews (order_id);
COMMENT ON INDEX raw.ix_order_reviews_order_id IS
  'Serves analytics.v_funnel_stages: EXISTS lookup for the "reviewed" stage.';

-- ---------------------------------------------------------------- customers
-- Serves: v_cohort_* -- grouping 99k customer_ids down to ~96k unique people.
CREATE INDEX IF NOT EXISTS ix_customers_unique_id
    ON raw.customers (customer_unique_id);
COMMENT ON INDEX raw.ix_customers_unique_id IS
  'Serves analytics.v_cohort_*: GROUP BY customer_unique_id (the person-level key, D-007).';

\echo 'indexes ready'
