-- Business question: how many orders reach each stage of the fulfilment lifecycle,
--                    and how does that change month to month?
--
-- This is a FULFILMENT funnel, not an acquisition funnel (DECISIONS D-006). Olist has no
-- clickstream data, so "visit -> signup -> cart -> purchase" is not derivable from it and
-- inventing those stages would be fabricating results. What IS real is the five lifecycle
-- timestamps on every order, and the NULLs in them are genuine operational drop-off:
-- a payment that never cleared, a parcel never handed to the carrier, a delivery that failed.
--
-- Grain: one row per (order_month, stage). The dashboard SUMs orders_reaching over the
-- selected months; summing counts across months is exact, so the filter cannot distort it.

\set ON_ERROR_STOP on

CREATE OR REPLACE VIEW analytics.v_funnel_stages AS
WITH order_flags AS (
    -- One row per order, with a boolean per stage. Kept separate from the counting step so
    -- the stage DEFINITIONS are readable in one place.
    --
    -- Each flag is CUMULATIVE: "reached stage N" means "passed every stage up to N". That is
    -- what a funnel means, and in this data it is not merely pedantic -- the source genuinely
    -- contains out-of-order records, and a non-cumulative definition produced a NEGATIVE
    -- drop-off. Measured on 2026-11-02:
    --   * 2,843 orders have a review but no delivery date (605 of them were canceled).
    --     Olist sends its review survey when the order is placed, not when it arrives, so a
    --     naive "has a review" stage counted 98,673 reviews against only 96,476 deliveries.
    --   *    14 orders have a carrier date but no approval date.
    --   *     1 order has a delivery date but no carrier date.
    -- These are recorded in docs/DATA.md as data-quality findings rather than silently
    -- smoothed over. The cumulative AND chain below is what makes the funnel monotonic.
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
    -- Turn the five boolean COLUMNS into five ROWS. CROSS JOIN LATERAL (VALUES ...) is the
    -- standard PostgreSQL way to unpivot; it reads the order_flags row once and emits five
    -- rows from it, so there is no self-join and no repeated table scan.
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
    -- count(*) FILTER (WHERE ...) is cleaner than sum(CASE WHEN ... THEN 1 ELSE 0 END) and
    -- lets PostgreSQL evaluate every stage in a single pass over the rows.
    count(*) FILTER (WHERE reached) AS orders_reaching
FROM stages_per_order
GROUP BY order_month, stage_order, stage_name;

COMMENT ON VIEW analytics.v_funnel_stages IS
  'How many orders reach each fulfilment stage (placed -> approved -> carrier -> delivered -> reviewed), per month. Stages are CUMULATIVE: reaching stage N requires passing every earlier stage, which the source data does not guarantee on its own. A NULL lifecycle timestamp is real drop-off, not missing data. Fulfilment funnel, not acquisition (D-006).';

\echo 'v_funnel_stages ready'
