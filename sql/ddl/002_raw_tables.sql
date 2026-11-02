-- 002_raw_tables.sql
-- One table per source CSV we actually load. Typed, with primary keys.
-- Re-runnable (CREATE TABLE IF NOT EXISTS).
--
-- WHY declare types instead of letting pandas guess: a silent type coercion is how wrong
-- numbers get into a dashboard. Declaring the type here means a bad CSV fails the load
-- loudly (FR-3) instead of quietly storing a price as text.
--
-- Deliberately NOT loaded (SEC-6, FR-4):
--   * olist_geolocation_dataset.csv  -- precise lat/long, personal-data risk, not needed
--   * olist_sellers_dataset.csv      -- not needed by any numbered requirement
--   * review_comment_title / review_comment_message -- free text, may contain names
--
-- Money is numeric(12,2), never float. A float would make revenue totals drift by cents,
-- and "why doesn't your revenue tie out?" is a bad interview moment.

\set ON_ERROR_STOP on

-- ============================================================== Olist: customers
CREATE TABLE IF NOT EXISTS raw.customers (
    customer_id               text PRIMARY KEY,
    -- customer_unique_id is the PERSON. customer_id is issued fresh for every order, so
    -- counting customers by customer_id overstates them badly. This is the classic Olist
    -- trap (DECISIONS D-007) and the cohort views key on customer_unique_id.
    customer_unique_id        text        NOT NULL,
    customer_zip_code_prefix  text,
    customer_city             text,
    customer_state            char(2)
);
COMMENT ON TABLE raw.customers IS 'Olist customers. customer_unique_id is the person-level key; customer_id is per-order.';

-- ============================================================== Olist: orders
CREATE TABLE IF NOT EXISTS raw.orders (
    order_id                      text PRIMARY KEY,
    customer_id                   text NOT NULL,
    order_status                  text NOT NULL,
    -- The five lifecycle timestamps. These ARE the funnel (DECISIONS D-006): Olist has no
    -- clickstream, so an acquisition funnel is not derivable. These columns are real and
    -- observable, and the NULLs are the drop-off.
    order_purchase_timestamp      timestamp NOT NULL,
    order_approved_at             timestamp,
    order_delivered_carrier_date  timestamp,
    order_delivered_customer_date timestamp,
    order_estimated_delivery_date timestamp
);
COMMENT ON TABLE raw.orders IS 'Olist orders with lifecycle timestamps. A NULL timestamp means the order never reached that stage - this is what the funnel measures.';

-- ============================================================== Olist: order_items
CREATE TABLE IF NOT EXISTS raw.order_items (
    order_id        text    NOT NULL,
    order_item_id   integer NOT NULL,
    product_id      text    NOT NULL,
    seller_id       text,
    shipping_limit_date timestamp,
    price           numeric(12,2) NOT NULL,
    freight_value   numeric(12,2),
    PRIMARY KEY (order_id, order_item_id)
);
COMMENT ON TABLE raw.order_items IS 'One row per item within an order. Revenue = SUM(price); an order with 3 items has 3 rows, so revenue queries must aggregate before joining to orders.';

-- ============================================================== Olist: order_payments
CREATE TABLE IF NOT EXISTS raw.order_payments (
    order_id            text    NOT NULL,
    payment_sequential  integer NOT NULL,
    payment_type        text,
    payment_installments integer,
    payment_value       numeric(12,2),
    PRIMARY KEY (order_id, payment_sequential)
);
COMMENT ON TABLE raw.order_payments IS 'Payment attempts per order. An order can be paid with several instruments, hence payment_sequential.';

-- ============================================================== Olist: order_reviews
-- review_id is NOT reliably unique in the published CSV (a known data-quality issue), so we
-- use a surrogate key and keep the natural columns as-is. Loading with review_id as the PK
-- would fail; pretending it is unique would silently drop rows.
CREATE TABLE IF NOT EXISTS raw.order_reviews (
    review_pk            bigserial PRIMARY KEY,
    review_id            text NOT NULL,
    order_id             text NOT NULL,
    review_score         smallint,
    review_creation_date timestamp,
    review_answer_timestamp timestamp
    -- review_comment_title and review_comment_message are intentionally absent (SEC-6).
);
COMMENT ON TABLE raw.order_reviews IS 'Olist reviews, free-text columns dropped for privacy (SEC-6). Existence of a row = the order reached the final funnel stage.';

-- ============================================================== Olist: products
CREATE TABLE IF NOT EXISTS raw.products (
    product_id            text PRIMARY KEY,
    product_category_name text,
    product_weight_g      integer,
    product_length_cm     integer,
    product_height_cm     integer,
    product_width_cm      integer
);
COMMENT ON TABLE raw.products IS 'Products, kept only for product_category_name used by the ranked-categories view.';

-- ============================================================== Cookie Cats A/B test
CREATE TABLE IF NOT EXISTS raw.ab_cookie_cats (
    userid         bigint PRIMARY KEY,
    version        text    NOT NULL,   -- 'gate_30' or 'gate_40' (the randomised variant)
    sum_gamerounds integer NOT NULL,
    retention_1    boolean NOT NULL,   -- came back 1 day after install
    retention_7    boolean NOT NULL,   -- came back 7 days after install
    CONSTRAINT ab_version_known CHECK (version IN ('gate_30', 'gate_40'))
);
COMMENT ON TABLE raw.ab_cookie_cats IS 'Cookie Cats mobile-game A/B test: a REAL published experiment (CC0), not simulated (FR-15). Each row is one randomised player.';

-- Foreign keys are deliberately NOT declared here (DECISIONS D-011). The raw layer's job is
-- to accept the source data exactly as published; declaring an FK would abort the load on the
-- orphan rows the CSVs genuinely contain, which hides a data-quality fact instead of reporting
-- it. Instead, tests/test_load.py COUNTS orphans and records the number, and the join columns
-- are indexed in 003 so the analytics views are still fast.

\echo 'raw tables ready'
