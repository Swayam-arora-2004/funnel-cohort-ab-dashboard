"""Tests for the raw load (milestone M1).

These are not decorative. Each one guards a specific requirement or a specific way this load
could go wrong without anybody noticing:

  * row counts        -- a truncated download would otherwise pass silently (FR-3)
  * idempotency       -- the whole point of truncate-then-load (FR-2)
  * dropped columns   -- proves the privacy exclusion actually happened (SEC-6, FR-4)
  * orphan counts     -- we chose not to declare FKs, so we must measure instead (D-011)
  * privilege boundary-- proves dashboard_ro really cannot write or read raw (SEC-5)
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from src.load.schemas import CSV_CONTRACTS

pytestmark = pytest.mark.db

# Measured on 2026-11-02 from the Kaggle downloads documented in docs/DATA.md.
# These are exact, not approximate: if a number here changes, the input data changed.
EXPECTED_ROWS = {
    "raw.customers": 99_441,
    "raw.orders": 99_441,
    "raw.order_items": 112_650,
    "raw.order_payments": 103_886,
    "raw.order_reviews": 99_224,
    "raw.products": 32_951,
    "raw.ab_cookie_cats": 90_189,
}


def _scalar(engine, sql: str, **params) -> int:
    with engine.connect() as conn:
        return int(conn.execute(text(sql), params).scalar_one())


@pytest.mark.parametrize(("table", "expected"), sorted(EXPECTED_ROWS.items()))
def test_row_counts(rw_engine, table, expected):
    """Every table holds exactly the documented number of rows."""
    # Table names come from this module's constants, never from input (SEC-4).
    assert _scalar(rw_engine, f"SELECT count(*) FROM {table}") == expected  # noqa: S608


def test_every_contract_has_an_expected_count():
    """Nobody can add a CSV contract without also recording its expected row count."""
    assert {c.table for c in CSV_CONTRACTS} == set(EXPECTED_ROWS)


def test_load_is_idempotent(rw_engine):
    """Loading one table twice leaves the same number of rows, not double (FR-2).

    We reload the smallest table only, so the test stays fast.
    """
    from src.config import get_settings
    from src.load.load_raw import copy_dataframe, read_csv

    contract = next(c for c in CSV_CONTRACTS if c.table == "raw.products")
    before = _scalar(rw_engine, "SELECT count(*) FROM raw.products")

    frame = read_csv(contract, get_settings().data_raw_dir)
    copy_dataframe(frame, contract.table, rw_engine)
    after_first = _scalar(rw_engine, "SELECT count(*) FROM raw.products")

    copy_dataframe(frame, contract.table, rw_engine)
    after_second = _scalar(rw_engine, "SELECT count(*) FROM raw.products")

    assert before == after_first == after_second == EXPECTED_ROWS["raw.products"]


def test_privacy_columns_are_absent(rw_engine):
    """The free-text review columns were never written to the database (SEC-6, FR-4)."""
    with rw_engine.connect() as conn:
        columns = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'raw' AND table_name = :t"
                ),
                {"t": "order_reviews"},
            )
        }
    assert "review_comment_message" not in columns
    assert "review_comment_title" not in columns


def test_geolocation_table_does_not_exist(rw_engine):
    """We deliberately never load precise location data (SEC-6)."""
    exists = _scalar(
        rw_engine,
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema = 'raw' AND table_name = 'geolocation'",
    )
    assert exists == 0


def test_no_negative_money(rw_engine):
    """Prices and payments are never negative -- a bounds check on untrusted input (SEC-3)."""
    assert _scalar(rw_engine, "SELECT count(*) FROM raw.order_items WHERE price < 0") == 0
    negative_payments = _scalar(
        rw_engine, "SELECT count(*) FROM raw.order_payments WHERE payment_value < 0"
    )
    assert negative_payments == 0


def test_cookie_cats_variants_are_balanced(rw_engine):
    """Both A/B arms exist and are of similar size -- a basic randomisation sanity check.

    If the split were wildly uneven it would suggest the data is not what it claims to be,
    and the whole experiment readout would be untrustworthy.
    """
    with rw_engine.connect() as conn:
        rows = conn.execute(
            text("SELECT version, count(*) FROM raw.ab_cookie_cats GROUP BY version")
        ).all()
    counts = dict(rows)
    assert set(counts) == {"gate_30", "gate_40"}
    smaller, larger = sorted(counts.values())
    assert smaller / larger > 0.95, f"arms are unbalanced: {counts}"


# --------------------------------------------------------------- data quality (D-011)
# We chose not to declare foreign keys, so these tests MEASURE referential integrity instead
# of the database enforcing it. A non-zero count is a reportable fact, not necessarily a bug,
# so each assertion allows the orphans we actually observed and would fail if they grew.


def test_orders_reference_known_customers(rw_engine):
    orphans = _scalar(
        rw_engine,
        "SELECT count(*) FROM raw.orders o "
        "LEFT JOIN raw.customers c ON c.customer_id = o.customer_id "
        "WHERE c.customer_id IS NULL",
    )
    assert orphans == 0, f"{orphans} orders point at a customer that does not exist"


def test_order_items_reference_known_orders(rw_engine):
    orphans = _scalar(
        rw_engine,
        "SELECT count(*) FROM raw.order_items i "
        "LEFT JOIN raw.orders o ON o.order_id = i.order_id "
        "WHERE o.order_id IS NULL",
    )
    assert orphans == 0, f"{orphans} order_items point at an order that does not exist"


def test_order_items_reference_known_products(rw_engine):
    orphans = _scalar(
        rw_engine,
        "SELECT count(*) FROM raw.order_items i "
        "LEFT JOIN raw.products p ON p.product_id = i.product_id "
        "WHERE p.product_id IS NULL",
    )
    assert orphans == 0, f"{orphans} order_items point at a product that does not exist"


# --------------------------------------------------------------- privilege boundary (SEC-5)


def test_readonly_role_cannot_read_raw(ro_engine):
    """dashboard_ro has no USAGE on schema raw, so it cannot read a raw table at all."""
    with ro_engine.connect() as conn, pytest.raises(ProgrammingError):
        conn.execute(text("SELECT count(*) FROM raw.orders"))


def test_readonly_role_cannot_write(ro_engine):
    """dashboard_ro cannot create anything, so an injection against it cannot persist."""
    with ro_engine.connect() as conn, pytest.raises(ProgrammingError):
        conn.execute(text("CREATE TABLE analytics.should_not_exist (x int)"))
