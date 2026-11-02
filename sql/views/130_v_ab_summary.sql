-- Business question: in the Cookie Cats experiment, how many players were in each variant,
--                    how many came back, and what was each variant's retention rate?
--
-- This view does the COUNTING only. The statistical test (z-test, confidence interval,
-- p-value, power) lives in src/analysis/ab_test.py, because PostgreSQL has no z-test and
-- faking one in SQL would be harder to read and harder to test than ten lines of Python
-- (DECISIONS D-004, D-008).
--
-- The data is a REAL published experiment, not simulated (FR-15). gate_30 is the control
-- (the existing behaviour: first progression gate at level 30); gate_40 is the variant.
--
-- Grain: one row per (metric, variant) -- four rows in total, because two metrics are
-- reported. Reporting BOTH is deliberate: picking whichever one turned out significant and
-- presenting only that is p-hacking. The dashboard shows both and names the caveat.

\set ON_ERROR_STOP on

CREATE OR REPLACE VIEW analytics.v_ab_summary AS
WITH per_variant AS (
    SELECT
        version                                     AS variant,
        count(*)                                    AS users,
        count(*) FILTER (WHERE retention_1)         AS converted_day1,
        count(*) FILTER (WHERE retention_7)         AS converted_day7
    FROM raw.ab_cookie_cats
    GROUP BY version
)
SELECT
    m.metric,
    p.variant,
    -- gate_30 is the status quo, so it is the control arm the other is compared against.
    (p.variant = 'gate_30')                         AS is_control,
    p.users,
    m.converted,
    round(100.0 * m.converted / nullif(p.users, 0), 3) AS conversion_rate_pct
FROM per_variant p
CROSS JOIN LATERAL (VALUES
    ('retention_1', p.converted_day1),
    ('retention_7', p.converted_day7)
) AS m(metric, converted)
ORDER BY m.metric, p.variant;

COMMENT ON VIEW analytics.v_ab_summary IS
  'Cookie Cats A/B test: users, conversions and conversion rate per variant, for BOTH day-1 and day-7 retention. Counting only - the z-test, CI and p-value are in src/analysis/ab_test.py. Real published experiment, not simulated (FR-15).';

\echo 'v_ab_summary ready'
