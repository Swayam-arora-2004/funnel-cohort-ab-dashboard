-- 001_schemas_and_roles.sql
-- Creates the two schemas and the two least-privilege roles (SEC-5, DECISIONS D-005).
-- Re-runnable.
--
-- WHY two roles: the dashboard takes user input and puts it into queries. Even with
-- parameterised SQL (SEC-4), a read-only role means a successful injection still cannot
-- write or drop anything. Defence in depth, and it costs us almost nothing.
--
-- Passwords arrive as psql variables, so no credential is written in this file (SEC-2).
-- `make db-init` supplies them from .env with -v.
--
-- NOTE on the \gexec pattern below: psql does NOT substitute :'vars' inside a
-- dollar-quoted block, so a `DO $$ ... $$` body cannot see them. Instead we SELECT the
-- command as text (format() quotes the identifier with %I and the literal with %L, which is
-- what makes this injection-safe) and \gexec runs the result.

\set ON_ERROR_STOP on

-- ---------------------------------------------------------------- schemas
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS analytics;

COMMENT ON SCHEMA raw IS
  'Landing zone. One table per source CSV, typed, no business logic. Written only by loader_rw.';
COMMENT ON SCHEMA analytics IS
  'Business logic layer. Views only. Single source of truth for every number in the dashboard, the CSV exports and the README.';

-- ---------------------------------------------------------------- roles
-- loader_rw: writes to raw. Used only by src/load/load_raw.py.
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'loader_user', :'loader_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'loader_user');
\gexec

SELECT format('ALTER ROLE %I LOGIN PASSWORD %L', :'loader_user', :'loader_password');
\gexec

-- dashboard_ro: SELECT on analytics only. NOINHERIT so it can never pick up privileges
-- by being granted some other role later.
SELECT format('CREATE ROLE %I LOGIN NOINHERIT PASSWORD %L', :'ro_user', :'ro_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'ro_user');
\gexec

SELECT format('ALTER ROLE %I LOGIN NOINHERIT PASSWORD %L', :'ro_user', :'ro_password');
\gexec

-- ---------------------------------------------------------------- grants
-- PostgreSQL lets every role create objects in `public` by default. Remove that.
REVOKE ALL ON SCHEMA public FROM PUBLIC;

-- loader_rw: DML on raw, no CREATE anywhere, no access to analytics.
GRANT USAGE ON SCHEMA raw TO :"loader_user";
GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA raw TO :"loader_user";
ALTER DEFAULT PRIVILEGES IN SCHEMA raw
  GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON TABLES TO :"loader_user";

-- raw.order_reviews has a bigserial surrogate key, so inserting a row calls nextval() on its
-- sequence. That needs USAGE on the sequence -- a table grant is not enough.
-- Note we grant USAGE, not OWNERSHIP: ownership would let loader_rw drop the sequence, and it
-- is also what `TRUNCATE ... RESTART IDENTITY` demands, which is exactly why the loader does
-- NOT use RESTART IDENTITY (see src/load/load_raw.py).
GRANT USAGE ON ALL SEQUENCES IN SCHEMA raw TO :"loader_user";
ALTER DEFAULT PRIVILEGES IN SCHEMA raw GRANT USAGE ON SEQUENCES TO :"loader_user";

-- dashboard_ro: SELECT on analytics only. Deliberately NO usage on raw, so the dashboard
-- cannot read a raw table even by accident -- it must go through a documented view.
GRANT USAGE ON SCHEMA analytics TO :"ro_user";
GRANT SELECT ON ALL TABLES IN SCHEMA analytics TO :"ro_user";
ALTER DEFAULT PRIVILEGES IN SCHEMA analytics GRANT SELECT ON TABLES TO :"ro_user";

-- A view executes with the privileges of its OWNER, not the caller. The views live in
-- analytics and are owned by the superuser, so they read raw on dashboard_ro's behalf while
-- dashboard_ro itself still has no direct access to raw. That is exactly the boundary we want.

\echo 'schemas and roles ready'
