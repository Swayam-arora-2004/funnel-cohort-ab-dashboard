"""Tests for the raw load (milestone M1).

These are not decorative. Each one guards a specific requirement or a specific way this load
could go wrong without anybody noticing:

  * row counts        -- a truncated download would otherwise pass silently
  * idempotency       -- the whole point of truncate-then-load
  * dropped columns   -- proves the privacy exclusion actually happened
  * orphan counts     -- we chose not to declare FKs, so we must measure instead
  * privilege boundary-- proves dashboard_ro really cannot write or read raw
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from src.load.schemas import CSV_CONTRACTS

pytestmark = pytest.mark.db

# Measured on 2026-11-02 from the downloads described in the README.
# These are exact, not approximate: if a number here changes, the input data changed.
EXPECTED_ROWS = {
    "raw.customers": 99_441,
    "raw.orders": 99_441,
    "raw.order_items": 112_650,
    "raw.order_payments": 103_886,
    "raw.order_reviews": 99_224,
    "raw.products": 32_951,
    "raw.ab_criteo_uplift": 13_979_592,
}


def _scalar(engine, sql: str, **params) -> int:
    with engine.connect() as conn:
        return int(conn.execute(text(sql), params).scalar_one())


@pytest.mark.parametrize(("table", "expected"), sorted(EXPECTED_ROWS.items()))
def test_row_counts(rw_engine, table, expected):
    """Every table holds exactly the documented number of rows."""
    # Table names come from this module's constants, never from input.
    assert _scalar(rw_engine, f"SELECT count(*) FROM {table}") == expected  # noqa: S608


def test_every_contract_has_an_expected_count():
    """Nobody can add a CSV contract without also recording its expected row count."""
    assert {c.table for c in CSV_CONTRACTS} == set(EXPECTED_ROWS)


def test_load_is_idempotent(rw_engine):
    """Loading one table twice leaves the same number of rows, not double.

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
    """The free-text review columns were never written to the database."""
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
    """We deliberately never load precise location data."""
    exists = _scalar(
        rw_engine,
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema = 'raw' AND table_name = 'geolocation'",
    )
    assert exists == 0


def test_no_negative_money(rw_engine):
    """Prices and payments are never negative -- a bounds check on untrusted input."""
    assert _scalar(rw_engine, "SELECT count(*) FROM raw.order_items WHERE price < 0") == 0
    negative_payments = _scalar(
        rw_engine, "SELECT count(*) FROM raw.order_payments WHERE payment_value < 0"
    )
    assert negative_payments == 0


def test_criteo_randomisation_split_is_as_published(rw_engine):
    """The withheld control arm must be ~15% of users, which is how Criteo ran the test.

    This is a sanity check on the randomisation itself: if the split were not what the
    publisher describes, the data is not what it claims to be and the whole readout would be
    untrustworthy. Unlike a 50/50 test the arms here are deliberately uneven -- most users are
    targeted, a random 15% are withheld -- which is normal for an incrementality test because
    withholding advertising costs real revenue.
    """
    with rw_engine.connect() as conn:
        control_pct = float(
            conn.execute(
                text(
                    "SELECT round(100.0 * count(*) FILTER (WHERE NOT treatment) / count(*), 2) "
                    "FROM raw.ab_criteo_uplift"
                )
            ).scalar_one()
        )
    assert 14.5 < control_pct < 15.5, f"control arm is {control_pct}% of users, expected ~15%"


def test_criteo_has_no_identifier_column(rw_engine):
    """There is no personal data in this source to exclude -- no identifier column exists."""
    with rw_engine.connect() as conn:
        columns = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'raw' AND table_name = 'ab_criteo_uplift'"
                )
            )
        }
    assert columns == {"treatment", "visit", "conversion", "exposure"}


# --------------------------------------------------------------- data quality
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


# --------------------------------------------------------------- privilege boundary


def test_readonly_role_cannot_read_raw(ro_engine):
    """dashboard_ro has no USAGE on schema raw, so it cannot read a raw table at all."""
    with ro_engine.connect() as conn, pytest.raises(ProgrammingError):
        conn.execute(text("SELECT count(*) FROM raw.orders"))


def test_readonly_role_cannot_write(ro_engine):
    """dashboard_ro cannot create anything, so an injection against it cannot persist."""
    with ro_engine.connect() as conn, pytest.raises(ProgrammingError):
        conn.execute(text("CREATE TABLE analytics.should_not_exist (x int)"))
