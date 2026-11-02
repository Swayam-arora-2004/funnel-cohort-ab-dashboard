-- Users, conversions and rate per experiment arm, for both outcomes.
-- Counting only; the z-test and confidence interval are in src/analysis/ab_test.py.
-- Splits on `treatment` (the random assignment), NOT on `exposure`. Being shown an ad is a
-- consequence of the treatment, so splitting on it would compare self-selected groups and
-- destroy the randomisation. This is intention-to-treat.
-- Both outcomes are returned so neither can be cherry-picked.

\set ON_ERROR_STOP on

CREATE OR REPLACE VIEW analytics.v_ab_summary AS
WITH per_arm AS (
    SELECT
        treatment,
        count(*)                              AS users,
        count(*) FILTER (WHERE visit)         AS visited,
        count(*) FILTER (WHERE conversion)    AS converted_users
    FROM raw.ab_criteo_uplift
    GROUP BY treatment
)
SELECT
    m.metric,
    CASE WHEN p.treatment THEN 'treatment' ELSE 'control' END AS variant,
    -- the withheld group is the control
    (NOT p.treatment)                          AS is_control,
    p.users,
    m.converted,
    round(100.0 * m.converted / nullif(p.users, 0), 4) AS conversion_rate_pct
FROM per_arm p
CROSS JOIN LATERAL (VALUES
    ('visit',      p.visited),
    ('conversion', p.converted_users)
) AS m(metric, converted)
ORDER BY m.metric, is_control DESC;

COMMENT ON VIEW analytics.v_ab_summary IS
  'Criteo Uplift incrementality test: users, conversions and rate per arm, for BOTH visit and conversion. Splits on the RANDOM ASSIGNMENT (treatment), not on exposure - exposure is downstream of treatment and splitting on it would destroy the randomisation. Counting only; the z-test, CI and p-value are in src/analysis/ab_test.py. Real randomised experiment, not simulated (FR-15).';

\echo 'v_ab_summary ready'
