"""The only module that creates database connections (docs/TECH_SPECS.md section 3).

Two engines, deliberately separate (SEC-5, DECISIONS D-005):

    engine_rw()  -> loader_rw     INSERT/TRUNCATE on schema raw.      Loader only.
    engine_ro()  -> dashboard_ro  SELECT on schema analytics only.    Dashboard and exports.

`fetch_df` is the single query path and it REFUSES a plain string. That is not style policing:
accepting `str` is what makes f-string SQL possible, so the type system is doing the security
work here (SEC-4).
"""

from __future__ import annotations

import logging

import pandas as pd
from sqlalchemy import Engine, create_engine
from sqlalchemy.sql.elements import TextClause

from src.config import get_settings

log = logging.getLogger(__name__)

# Engines are cached because creating one per query would throw away connection pooling.
_engines: dict[str, Engine] = {}


def _engine(key: str, url: str) -> Engine:
    if key not in _engines:
        # pool_pre_ping avoids handing out a connection the database has already dropped,
        # which is common when the Docker container restarts between dashboard reloads.
        _engines[key] = create_engine(url, pool_pre_ping=True, future=True)
        # Log the ROLE, never the URL -- the URL contains the password (SEC-10).
        log.info("created database engine for role=%s", key)
    return _engines[key]


def engine_rw() -> Engine:
    """Read-write engine for the loader. Must never be imported by anything under app/."""
    return _engine("loader_rw", get_settings().loader_url)


def engine_ro() -> Engine:
    """Read-only engine for the dashboard and the CSV exports."""
    return _engine("dashboard_ro", get_settings().ro_url)


def fetch_df(engine: Engine, sql: TextClause, params: dict | None = None) -> pd.DataFrame:
    """Run a parameterised SELECT and return a DataFrame.

    `sql` must be a sqlalchemy.text() object, not a str. Values belong in `params`, which
    SQLAlchemy sends to the server separately from the statement, so a value can never be
    parsed as SQL (SEC-4).
    """
    if not isinstance(sql, TextClause):
        raise TypeError(
            "fetch_df requires a sqlalchemy.text() object, not a string. "
            "Values must be passed via params so they are bound, never interpolated (SEC-4)."
        )
    with engine.connect() as conn:
        return pd.read_sql_query(sql, conn, params=params or {})
