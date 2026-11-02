-- Business question: in the Criteo incrementality test, how many users were in each arm,
--                    how many converted, and what was each arm's rate?
--
-- This view does the COUNTING only. The statistical test (z-test, confidence interval,
-- p-value, power) lives in src/analysis/ab_test.py, because PostgreSQL has no z-test and
-- faking one in SQL would be harder to read and harder to unit-test than ten lines of Python
-- (DECISIONS D-004, D-008).
--
-- The data is a REAL randomised experiment, not simulated (FR-15). Criteo call it an
-- *incrementality test*: a random part of the population is withheld from advertising
-- targeting. That withheld group IS the control arm, which is what makes the comparison
-- causal rather than observational.
--
-- WHY `treatment` AND NOT `exposure`: the source also records whether a user was actually
-- shown an ad. Analysing by exposure would compare people who saw an ad against people who
-- did not -- but being shown an ad is a CONSEQUENCE of the treatment, and the users who get
-- shown ads are systematically different (more active, more targetable). Splitting on it
-- throws away the randomisation and reintroduces exactly the selection bias the experiment
-- was run to avoid. This view splits on the random assignment, which is intention-to-treat.
--
-- Grain: one row per (metric, arm) -- four rows, because two outcomes are reported. Reporting
-- BOTH is deliberate: picking whichever one turned out significant is p-hacking.

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
    -- The withheld group is the control: it is the status quo the change is measured against.
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
