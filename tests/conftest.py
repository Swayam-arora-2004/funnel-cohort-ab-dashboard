"""Shared test fixtures.

Database tests are SKIPPED, not failed, when PostgreSQL is unreachable. That keeps `pytest`
useful on a machine where Docker is not running, while CI still runs the full set because CI
starts a Postgres service.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from src.db import engine_ro, engine_rw


def _reachable(engine_factory) -> bool:
    try:
        with engine_factory().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except (SQLAlchemyError, RuntimeError):
        return False


@pytest.fixture(scope="session")
def rw_engine():
    """Read-write engine (loader_rw). Used to assert what was loaded."""
    if not _reachable(engine_rw):
        pytest.skip("PostgreSQL is not reachable -- run `make db-up` first")
    return engine_rw()


@pytest.fixture(scope="session")
def ro_engine():
    """Read-only engine (dashboard_ro). Used to assert the privilege boundary holds."""
    if not _reachable(engine_ro):
        pytest.skip("PostgreSQL is not reachable -- run `make db-up` first")
    return engine_ro()
