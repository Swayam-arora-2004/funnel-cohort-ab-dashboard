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


def _loaded() -> bool:
    """Is there actually any data in the warehouse?

    Reachability is not enough. CI builds the schema and the views but cannot load the data —
    it is 425 MB and licence-restricted, so it is not in git. The first CI run proved the
    point: Postgres was up, so every `db` test ran, and 69 of them failed on empty tables.
    A test that needs data should SKIP when there is none, not fail: the absence of data in
    CI is a known, deliberate condition, not a defect.
    """
    try:
        with engine_rw().connect() as conn:
            return int(conn.execute(text("SELECT count(*) FROM raw.orders")).scalar_one()) > 0
    except (SQLAlchemyError, RuntimeError):
        return False


@pytest.fixture(scope="session")
def rw_engine():
    """Read-write engine (loader_rw). Used to assert what was loaded."""
    if not _reachable(engine_rw):
        pytest.skip("PostgreSQL is not reachable -- run `make db-up` first")
    if not _loaded():
        pytest.skip("the warehouse is empty -- run `make load` first")
    return engine_rw()


@pytest.fixture(scope="session")
def ro_engine():
    """Read-only engine (dashboard_ro). Used to assert the privilege boundary holds."""
    if not _reachable(engine_ro):
        pytest.skip("PostgreSQL is not reachable -- run `make db-up` first")
    if not _loaded():
        pytest.skip("the warehouse is empty -- run `make load` first")
    return engine_ro()
