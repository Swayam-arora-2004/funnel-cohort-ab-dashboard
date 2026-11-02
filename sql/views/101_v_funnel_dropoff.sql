-- Business question: between which two consecutive stages do we lose the most orders,
--                    and how big is that loss?
--
-- This is the view that actually answers "where should we focus?". It uses LAG to put each
-- stage next to the one before it, which is the natural fit: a drop-off is by definition a
-- comparison between neighbouring rows, and a window function compares rows without a
-- self-join.
--
-- Grain: one row per stage, across the whole dataset (all months combined).

\set ON_ERROR_STOP on

CREATE OR REPLACE VIEW analytics.v_funnel_dropoff AS
WITH totals AS (
    -- Roll the monthly grain of v_funnel_stages up to all-time.
    SELECT
        stage_order,
        stage_name,
        sum(orders_reaching) AS orders_reaching
    FROM analytics.v_funnel_stages
    GROUP BY stage_order, stage_name
),
with_previous AS (
    SELECT
        stage_order,
        stage_name,
        orders_reaching,
        -- LAG looks at the previous row in stage order. For stage 1 there is no previous row,
        -- so this is NULL and every rate below is correctly NULL rather than a fake 100%.
        lag(orders_reaching) OVER (ORDER BY stage_order) AS previous_stage_orders,
        -- FIRST_VALUE gives stage 1's count on every row, so we can express each stage as a
        -- share of the top of the funnel without a second query.
        first_value(orders_reaching) OVER (ORDER BY stage_order) AS funnel_entry_orders
    FROM totals
)
SELECT
    stage_order,
    stage_name,
    orders_reaching,
    previous_stage_orders,
    -- Orders lost at THIS step.
    previous_stage_orders - orders_reaching AS dropped_orders,
    -- Of those who reached the previous stage, what share continued? The 100.0 forces numeric
    -- division; with two integers PostgreSQL would do integer division and return 0.
    round(100.0 * orders_reaching / nullif(previous_stage_orders, 0), 2)
        AS step_conversion_pct,
    round(100.0 * (previous_stage_orders - orders_reaching)
          / nullif(previous_stage_orders, 0), 2)
        AS step_dropoff_pct,
    -- Share of ALL orders that got this far -- the cumulative view of the same funnel.
    round(100.0 * orders_reaching / nullif(funnel_entry_orders, 0), 2)
        AS pct_of_all_orders
FROM with_previous
ORDER BY stage_order;

COMMENT ON VIEW analytics.v_funnel_dropoff IS
  'Stage-to-stage drop-off across the whole dataset: orders lost, step conversion rate and cumulative share of all orders. Uses LAG to compare each stage with the one before it. Answers "where do we lose the most orders?".';

\echo 'v_funnel_dropoff ready'
