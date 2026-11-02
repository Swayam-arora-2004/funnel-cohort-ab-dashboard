-- Schemas and the two least-privilege roles. Re-runnable.
-- Passwords arrive as psql variables from the Makefile, so none is written in this file.

\set ON_ERROR_STOP on

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS analytics;

COMMENT ON SCHEMA raw IS
  'Landing zone. One table per source file, typed, no business logic. Written only by loader_rw.';
COMMENT ON SCHEMA analytics IS
  'Business logic. Views only -- the single definition of every metric the dashboard shows.';

-- psql does not substitute :'vars' inside a DO $$ block, so build the statement as text and
-- run it with \gexec. format() quotes the identifier (%I) and the literal (%L).
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'loader_user', :'loader_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'loader_user');
\gexec
SELECT format('ALTER ROLE %I LOGIN PASSWORD %L', :'loader_user', :'loader_password');
\gexec

SELECT format('CREATE ROLE %I LOGIN NOINHERIT PASSWORD %L', :'ro_user', :'ro_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'ro_user');
\gexec
SELECT format('ALTER ROLE %I LOGIN NOINHERIT PASSWORD %L', :'ro_user', :'ro_password');
\gexec

-- Postgres lets every role create objects in public by default.
REVOKE ALL ON SCHEMA public FROM PUBLIC;

-- loader_rw: DML on raw, nothing else.
GRANT USAGE ON SCHEMA raw TO :"loader_user";
GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA raw TO :"loader_user";
ALTER DEFAULT PRIVILEGES IN SCHEMA raw
  GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON TABLES TO :"loader_user";

-- order_reviews has a bigserial, so inserting calls nextval(). USAGE, not ownership --
-- ownership would also let the loader drop the sequence.
GRANT USAGE ON ALL SEQUENCES IN SCHEMA raw TO :"loader_user";
ALTER DEFAULT PRIVILEGES IN SCHEMA raw GRANT USAGE ON SEQUENCES TO :"loader_user";

-- dashboard_ro: SELECT on analytics only, and deliberately nothing on raw. A view runs with
-- its owner's privileges, so the views can still read raw on its behalf.
GRANT USAGE ON SCHEMA analytics TO :"ro_user";
GRANT SELECT ON ALL TABLES IN SCHEMA analytics TO :"ro_user";
ALTER DEFAULT PRIVILEGES IN SCHEMA analytics GRANT SELECT ON TABLES TO :"ro_user";

\echo 'schemas and roles ready'
