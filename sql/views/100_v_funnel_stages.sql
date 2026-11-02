-- How many orders reach each stage of the order lifecycle, per month.
-- This is a fulfilment funnel, not an acquisition one: Olist publishes no clickstream, so the
-- stages are the lifecycle timestamps that actually exist and their NULLs are the drop-off.
-- Grain: one row per (month, stage). Summing counts across months is exact.

\set ON_ERROR_STOP on

CREATE OR REPLACE VIEW analytics.v_funnel_stages AS
WITH order_flags AS (
    -- Flags are CUMULATIVE: reaching stage N requires passing every earlier stage. The
    -- source has out-of-order records -- 2,843 orders carry a review but no delivery, because
    -- the survey fires at order time -- so a non-cumulative definition gave a negative
    -- drop-off.
    SELECT
        date_trunc('month', o.order_purchase_timestamp)::date AS order_month,
        TRUE                                              AS reached_placed,
        (o.order_approved_at IS NOT NULL)                 AS reached_approved,
        (o.order_approved_at IS NOT NULL
         AND o.order_delivered_carrier_date IS NOT NULL)  AS reached_carrier,
        (o.order_approved_at IS NOT NULL
         AND o.order_delivered_carrier_date IS NOT NULL
         AND o.order_delivered_customer_date IS NOT NULL) AS reached_delivered,
        (o.order_approved_at IS NOT NULL
         AND o.order_delivered_carrier_date IS NOT NULL
         AND o.order_delivered_customer_date IS NOT NULL
         AND EXISTS (
             SELECT 1 FROM raw.order_reviews r WHERE r.order_id = o.order_id
         ))                                               AS reached_reviewed
    FROM raw.orders o
),
stages_per_order AS (
    -- unpivot five boolean columns into five rows, reading each order once
    SELECT
        f.order_month,
        s.stage_order,
        s.stage_name,
        s.reached
    FROM order_flags f
    CROSS JOIN LATERAL (VALUES
        (1, 'Order placed',      f.reached_placed),
        (2, 'Payment approved',  f.reached_approved),
        (3, 'Handed to carrier', f.reached_carrier),
        (4, 'Delivered',         f.reached_delivered),
        (5, 'Delivered & reviewed', f.reached_reviewed)
    ) AS s(stage_order, stage_name, reached)
)
SELECT
    order_month,
    stage_order,
    stage_name,
    count(*) FILTER (WHERE reached) AS orders_reaching
FROM stages_per_order
GROUP BY order_month, stage_order, stage_name;

COMMENT ON VIEW analytics.v_funnel_stages IS
  'How many orders reach each fulfilment stage (placed -> approved -> carrier -> delivered -> reviewed), per month. Stages are CUMULATIVE: reaching stage N requires passing every earlier stage, which the source data does not guarantee on its own. A NULL lifecycle timestamp is real drop-off, not missing data. Fulfilment funnel, not acquisition (D-006).';

\echo 'v_funnel_stages ready'
