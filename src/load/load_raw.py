"""Load the source CSVs into schema `raw`.

Idempotent: each table is truncated and re-inserted in one transaction, so a failure
mid-file rolls back rather than leaving half a table. Running it twice gives the same counts.

Uses COPY rather than INSERT -- one bulk operation instead of 14.5 million round-trips,
which is what makes re-running the whole load cheap enough to be the reload strategy.

Columns are checked against the contract in schemas.py before anything is written, so a
renamed upstream column fails loudly instead of writing NULLs.
"""

from __future__ import annotations

import io
import logging
import sys
import time

import pandas as pd
from sqlalchemy import Engine, text

from src.config import get_settings
from src.db import engine_rw
from src.load.schemas import CSV_CONTRACTS, CsvContract

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("load_raw")

# Sources spell booleans differently (TRUE/FALSE vs 0/1). Mapping explicitly means an
# unexpected third value becomes NA and is caught by NOT NULL rather than guessed at.
_BOOL_MAP = {
    "TRUE": True,
    "FALSE": False,
    "True": True,
    "False": False,
    "true": True,
    "false": False,
    "1": True,
    "0": False,
}


class LoadError(RuntimeError):
    """A CSV does not match its contract."""


def read_csv(contract: CsvContract, raw_dir) -> pd.DataFrame:
    """Read one CSV, validate it against its contract, and return only the columns we keep."""
    path = raw_dir / contract.filename
    if not path.exists():
        raise LoadError(
            f"{contract.filename} not found under {raw_dir}. "
            "See the README for the download commands."
        )

    # boolean and Int64 cannot go straight to read_csv: the files hold TRUE/FALSE strings and
    # float-looking integers ("225.0"), so both are read as something else and converted below.
    _READ_AS = {"boolean": "string", "Int64": "float64"}
    read_dtypes = {col: _READ_AS.get(dtype, dtype) for col, dtype in contract.dtypes.items()}

    # usecols skips unwanted columns while parsing rather than after -- several GB on the
    # 14M-row experiment file
    usecols = (
        [*contract.dtypes, *contract.date_columns] if contract.read_only_contract_columns else None
    )

    frame = pd.read_csv(
        path,
        dtype=read_dtypes,
        usecols=usecols,
        parse_dates=list(contract.date_columns) or None,
        # the reviews CSV has quoted text with embedded newlines
        keep_default_na=True,
    )

    # every expected column must be present
    expected = set(contract.dtypes) | set(contract.date_columns)
    missing = expected - set(frame.columns)
    if missing:
        raise LoadError(
            f"{contract.filename}: missing expected column(s) {sorted(missing)}. "
            "The source file has changed -- update src/load/schemas.py before loading."
        )

    # drop privacy-sensitive and unused columns before anything is written
    present_drops = [c for c in contract.drop_columns if c in frame.columns]
    if present_drops:
        frame = frame.drop(columns=present_drops)
        log.info("  dropped %s", ", ".join(present_drops))

    for col, dtype in contract.dtypes.items():
        if dtype == "boolean":
            # anything unexpected becomes NA and is rejected by NOT NULL
            frame[col] = frame[col].map(_BOOL_MAP).astype("boolean")
        elif dtype == "Int64":
            # round before casting so 224.99999 cannot truncate to 224
            frame[col] = frame[col].round().astype("Int64")

    # keep exactly the contract columns, so a new upstream column cannot break the load
    keep = [c for c in (*contract.dtypes, *contract.date_columns) if c in frame.columns]
    frame = frame[keep]
    if contract.rename:
        frame = frame.rename(columns=contract.rename)

    # count bound violations; never silently drop rows
    for col in contract.non_negative:
        bad = int((frame[col] < 0).sum())
        if bad:
            log.warning(
                "  %s: %d row(s) with negative %s -- kept and reported",
                contract.table,
                bad,
                col,
            )

    if len(frame) < contract.expected_min_rows:
        raise LoadError(
            f"{contract.filename}: only {len(frame):,} rows, expected at least "
            f"{contract.expected_min_rows:,}. The download may be truncated."
        )
    return frame


def copy_dataframe(frame: pd.DataFrame, table: str, engine: Engine) -> int:
    """Truncate and bulk-COPY the frame in, in one transaction.

    `table` is a constant from schemas.py, never input, so interpolating it is not injection.
    Values are not interpolated at all -- they travel through the COPY stream.
    """
    buffer = io.StringIO()
    # headerless CSV with \N for NULL, which is what COPY expects
    frame.to_csv(buffer, index=False, header=False, na_rep="\\N")
    buffer.seek(0)

    columns = ", ".join(f'"{c}"' for c in frame.columns)
    raw_conn = engine.raw_connection()
    try:
        with raw_conn.cursor() as cur:
            # No RESTART IDENTITY: that needs ownership of the sequence, which would also
            # let the loader drop it. The surrogate key just keeps counting.
            cur.execute(f"TRUNCATE TABLE {table}")  # noqa: S608  # nosec B608
            cur.copy_expert(
                f"COPY {table} ({columns}) FROM STDIN WITH (FORMAT csv, NULL '\\N')",  # noqa: S608  # nosec B608
                buffer,
            )
        raw_conn.commit()  # one commit: the whole file is in, or none of it is
    except Exception:
        raw_conn.rollback()
        raise
    finally:
        raw_conn.close()
    return len(frame)


def count_rows(table: str, engine: Engine) -> int:
    with engine.connect() as conn:
        # `table` is a constant from schemas.py, not input. Both linters flag it anyway
        # because they cannot see that, hence the two markers.
        return int(
            conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()  # noqa: S608  # nosec B608
        )


def main() -> None:
    settings = get_settings()
    settings.data_raw_dir.mkdir(parents=True, exist_ok=True)
    engine = engine_rw()
    started = time.perf_counter()
    results: list[tuple[str, int, int]] = []

    for contract in CSV_CONTRACTS:
        log.info("loading %s -> %s", contract.filename, contract.table)
        frame = read_csv(contract, settings.data_raw_dir)
        written = copy_dataframe(frame, contract.table, engine)
        in_db = count_rows(contract.table, engine)
        if written != in_db:
            raise LoadError(f"{contract.table}: wrote {written:,} rows but table holds {in_db:,}")
        log.info("  %s rows", f"{in_db:,}")
        results.append((contract.table, written, in_db))

    elapsed = time.perf_counter() - started
    print("\n  table                    rows loaded")
    print("  " + "-" * 38)
    for table, written, _ in results:
        print(f"  {table:<24} {written:>11,}")
    print("  " + "-" * 38)
    print(f"  {'TOTAL':<24} {sum(r[1] for r in results):>11,}")
    print(f"\n  completed in {elapsed:.1f}s")


if __name__ == "__main__":
    try:
        main()
    except LoadError as exc:
        # a contract failure is a data problem: print the message, not a traceback
        log.error("load failed: %s", exc)
        sys.exit(1)
