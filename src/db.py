"""Database connections. Two engines, kept separate on purpose.

    engine_rw()  -> loader_rw     writes to schema raw. Loader only.
    engine_ro()  -> dashboard_ro  SELECT on analytics only. Dashboard and exports.

fetch_df refuses a plain string: accepting str is what makes f-string SQL possible.
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
        # pre_ping so a connection dropped by a container restart is not handed out
        _engines[key] = create_engine(url, pool_pre_ping=True, future=True)
        # log the role, never the URL -- the URL contains the password
        log.info("created database engine for role=%s", key)
    return _engines[key]


def engine_rw() -> Engine:
    """Read-write engine for the loader. Must never be imported by anything under app/."""
    return _engine("loader_rw", get_settings().loader_url)


def engine_ro() -> Engine:
    """Read-only engine for the dashboard and the CSV exports."""
    return _engine("dashboard_ro", get_settings().ro_url)


def fetch_df(engine: Engine, sql: TextClause, params: dict | None = None) -> pd.DataFrame:
    """Run a parameterised SELECT. `sql` must be a text() object; values go in `params`,
    which SQLAlchemy sends separately from the statement."""
    if not isinstance(sql, TextClause):
        raise TypeError(
            "fetch_df requires a sqlalchemy.text() object, not a string -- "
            "values must be bound via params, never interpolated."
        )
    with engine.connect() as conn:
        return pd.read_sql_query(sql, conn, params=params or {})
