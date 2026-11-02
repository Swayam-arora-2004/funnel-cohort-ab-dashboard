-- Indexes on the foreign-key and filter columns. Primary keys are already indexed by Postgres.
-- Every index names the query it serves; if you cannot name one, delete the index.

\set ON_ERROR_STOP on

-- orders -> customers join, used by the cohort views
CREATE INDEX IF NOT EXISTS ix_orders_customer_id
    ON raw.orders (customer_id);

-- matches the date_trunc in the revenue and cohort views, so Postgres can use the index
-- instead of computing date_trunc per row
CREATE INDEX IF NOT EXISTS ix_orders_purchase_month
    ON raw.orders (date_trunc('month', order_purchase_timestamp));

-- the dashboard's date-range filter bounds the raw timestamp
CREATE INDEX IF NOT EXISTS ix_orders_purchase_ts
    ON raw.orders (order_purchase_timestamp);

-- v_funnel_stages and the delivery-rate tile group on status
CREATE INDEX IF NOT EXISTS ix_orders_status
    ON raw.orders (order_status);

-- order_items -> products, used by v_top_categories_ranked.
-- The PK already covers order_id as its leading column.
CREATE INDEX IF NOT EXISTS ix_order_items_product_id
    ON raw.order_items (product_id);

-- the "reviewed" funnel stage is an EXISTS lookup on order_id
CREATE INDEX IF NOT EXISTS ix_order_reviews_order_id
    ON raw.order_reviews (order_id);

-- the cohort views group 99k customer_ids down to 96k people
CREATE INDEX IF NOT EXISTS ix_customers_unique_id
    ON raw.customers (customer_unique_id);

\echo 'indexes ready'
