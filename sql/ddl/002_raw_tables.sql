-- One table per source file, typed, with primary keys. Re-runnable.
-- Declared types mean a malformed CSV fails the load instead of silently storing a price as text.
-- Not loaded: olist_geolocation (lat/long), olist_sellers, and the free-text review columns.
-- Money is numeric(12,2), never float.

\set ON_ERROR_STOP on

-- ============================================================== Olist: customers
CREATE TABLE IF NOT EXISTS raw.customers (
    customer_id               text PRIMARY KEY,
    -- the person-level key. customer_id is issued fresh per order, so counting it
    -- overstates customers: 99,441 ids for 96,096 people.
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
    -- the five lifecycle timestamps are the funnel; a NULL means the order never got there
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
COMMENT ON TABLE raw.order_items IS 'One row per ITEM, not per order. A 3-item order is 3 rows, so aggregate to order level before counting orders.';

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
-- review_id is not unique in the published CSV, so the PK is a surrogate.
CREATE TABLE IF NOT EXISTS raw.order_reviews (
    review_pk            bigserial PRIMARY KEY,
    review_id            text NOT NULL,
    order_id             text NOT NULL,
    review_score         smallint,
    review_creation_date timestamp,
    review_answer_timestamp timestamp
    -- the two free-text comment columns are deliberately not loaded
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

-- The A/B experiment table lives in 004_ab_criteo.sql, because it comes from a different
-- source with a different licence and is the one piece a reader may want to swap.

-- No foreign keys: raw accepts the source as published. tests/test_load.py counts orphans
-- instead, so a broken reference is reported rather than aborting the load.

\echo 'raw tables ready'
