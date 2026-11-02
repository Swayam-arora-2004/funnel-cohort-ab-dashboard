-- Criteo Uplift v2.1: the A/B experiment table.
-- A random 15% of users were withheld from ad targeting; that withheld group is the control.
-- Only 4 of the 16 source columns are loaded -- the 11 anonymised features are unused.

\set ON_ERROR_STOP on

CREATE TABLE IF NOT EXISTS raw.ab_criteo_uplift (
    treatment  boolean NOT NULL,  -- the random assignment: TRUE = eligible for targeting
    visit      boolean NOT NULL,  -- outcome 1: reached the advertiser's site
    conversion boolean NOT NULL,  -- outcome 2: converted
    exposure   boolean NOT NULL   -- whether an ad was actually served (downstream of treatment)
);

COMMENT ON TABLE raw.ab_criteo_uplift IS
  'Criteo Uplift v2.1, a randomised incrementality test (CC BY-NC-SA 4.0). 13,979,592 users. treatment is the random assignment; visit and conversion are the outcomes. Analyse by treatment, not exposure -- exposure is a consequence of treatment.';

-- No index here. The only query aggregates the whole table with no WHERE clause, so a
-- sequential scan always wins -- a covering index measured 282 MB and 0 scans.

\echo 'criteo uplift table ready'
