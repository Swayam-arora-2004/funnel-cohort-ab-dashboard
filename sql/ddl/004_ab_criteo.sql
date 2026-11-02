-- 004_ab_criteo.sql
-- The A/B experiment table: Criteo Uplift v2.1.
--
-- WHY THIS REPLACED COOKIE CATS (DECISIONS D-023): Kaggle reported no licence at all for the
-- Cookie Cats dataset. This one is published by Criteo's own AI Lab under an explicit
-- **CC BY-NC-SA 4.0** licence -- the same licence as the Olist data -- so the whole project now
-- has a verifiable licence chain instead of one dataset we could only describe as "unknown".
--
-- It is a genuine randomised trial: Criteo call it an *incrementality test*, where a random
-- part of the population is withheld from being targeted by advertising. That random
-- withholding IS the control arm. 25 million users, one row each.
--
-- ONLY FOUR COLUMNS ARE LOADED. The source also carries 11 anonymised features f0..f11, which
-- no numbered requirement needs; at ~14M rows they would cost gigabytes to store and nothing to
-- gain (FR-4, the same rule that drops Olist's free-text review columns). The experiment needs
-- the assignment and the outcomes, and that is what is here.
--
-- No identifier column exists in the source at all, which is the strongest possible form of
-- SEC-6: there is no personal data to exclude.

\set ON_ERROR_STOP on

CREATE TABLE IF NOT EXISTS raw.ab_criteo_uplift (
    -- Randomised assignment. TRUE = this user was eligible to be targeted by advertising,
    -- FALSE = withheld. This is the treatment/control split and it is what makes the
    -- comparison causal rather than observational.
    treatment  boolean NOT NULL,
    -- Outcome 1: did the user visit the advertiser's site?
    visit      boolean NOT NULL,
    -- Outcome 2: did the user convert? The stricter, more commercially meaningful outcome.
    conversion boolean NOT NULL,
    -- Whether the user was actually SHOWN an ad. Note this is downstream of randomisation --
    -- it is an outcome of the treatment, not part of the assignment -- so analysing by
    -- `exposure` instead of `treatment` would break randomisation and reintroduce selection
    -- bias. It is loaded so that caveat can be stated from the data rather than asserted.
    exposure   boolean NOT NULL
);
COMMENT ON TABLE raw.ab_criteo_uplift IS
  'Criteo Uplift v2.1: a REAL randomised incrementality test (CC BY-NC-SA 4.0), 13,979,592 users. treatment is the random assignment; visit and conversion are the outcomes. Only 4 of the 16 source columns are loaded - the 11 anonymised features are unused (FR-4). No identifier column exists in the source.';

-- NO INDEX ON THIS TABLE, DELIBERATELY.
--
-- The first version of this file created a covering index on (treatment) INCLUDE (visit,
-- conversion), on the reasoning that analytics.v_ab_summary groups by treatment. Measured
-- after loading, that was wrong:
--
--     heap                     484 MB
--     index                    282 MB
--     index scans since load   0
--
-- The only query against this table aggregates the WHOLE table with no WHERE clause, and
-- PostgreSQL correctly chooses a parallel sequential scan every time -- there is nothing for
-- an index to narrow down. The rows are four booleans, so the heap is already about as small
-- as data gets; an index over the same columns is not a cheaper thing to read, it is a second
-- copy. It cost 282 MB and load time to be scanned zero times.
--
-- This is the rule in 003_indexes.sql applied to its author: "Every index here exists to
-- serve a named query. If you cannot name the query, the index should not exist." Naming a
-- query it *might* serve is not the same as checking that the planner uses it. The check is
-- `SELECT idx_scan FROM pg_stat_user_indexes`, and it takes one minute.
--
-- The aggregate runs in about 1.1 s over 14M rows, comfortably inside NFR-1, and the
-- dashboard caches it for 10 minutes anyway.

\echo 'criteo uplift table ready'
