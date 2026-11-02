"""Load the source CSVs into schema `raw`.

Design points worth being able to defend in an interview:

1. **Idempotent (FR-2).** Each table is TRUNCATEd and re-inserted inside ONE transaction. If
   anything fails mid-file, the transaction rolls back and the table is left exactly as it was,
   never half-loaded. Running `make load` twice gives the same row counts, not double.

2. **COPY, not INSERT.** We stream the DataFrame to PostgreSQL's COPY command through an
   in-memory buffer. COPY is one bulk operation instead of ~540,000 individual INSERT
   round-trips, which turns minutes into seconds. This is the standard way to bulk-load
   PostgreSQL and the reason the load is fast enough to re-run freely.

3. **Validate first, write second (FR-3, SEC-3).** The expected column set is checked against
   the contract in schemas.py before a single row is written. A missing or renamed source column
   fails loudly, naming the file and the column, instead of writing NULLs into the warehouse.

4. **Untrusted input (SRS threat model).** The CSVs were downloaded from the internet. They are
   read only with pandas and explicit dtypes -- never eval'd, never used to build SQL text
   (SEC-4, SEC-7). Table names come from the contract constants in this repo, never from a file.
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

# Cookie Cats writes booleans as the strings TRUE/FALSE, which pandas will not coerce to its
# nullable boolean dtype on its own. Map them explicitly so an unexpected third value becomes
# NA and is caught by the NOT NULL constraint rather than being guessed at.
# Two sources write booleans differently: Cookie Cats used the strings TRUE/FALSE, Criteo
# writes 0/1. Both are mapped explicitly so an unexpected third value becomes NA and is caught
# by the NOT NULL constraint, rather than being guessed at.
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
    """Raised when a CSV does not match its contract. Names the file and the problem."""


def read_csv(contract: CsvContract, raw_dir) -> pd.DataFrame:
    """Read one CSV, validate it against its contract, and return only the columns we keep."""
    path = raw_dir / contract.filename
    if not path.exists():
        raise LoadError(
            f"{contract.filename} not found under {raw_dir}. "
            "See docs/DATA.md for the download commands."
        )

    # Two dtypes cannot be handed straight to read_csv:
    #   boolean -> the file holds the strings TRUE/FALSE, so read as text and map below.
    #   Int64   -> the file holds "225.0" (a blank somewhere made pandas infer float), so read
    #              as float and convert below. Reading "225.0" directly as Int64 raises.
    _READ_AS = {"boolean": "string", "Int64": "float64"}
    read_dtypes = {col: _READ_AS.get(dtype, dtype) for col, dtype in contract.dtypes.items()}

    # usecols makes pandas skip the unwanted columns while PARSING, rather than reading them
    # and dropping them afterwards. On the 25M-row experiment file that is the difference
    # between a few hundred MB and several GB of memory.
    usecols = (
        [*contract.dtypes, *contract.date_columns] if contract.read_only_contract_columns else None
    )

    frame = pd.read_csv(
        path,
        dtype=read_dtypes,
        usecols=usecols,
        parse_dates=list(contract.date_columns) or None,
        # The reviews CSV contains quoted free text with embedded newlines, so the C parser's
        # default handling matters; keep_default_na keeps empty strings as NA consistently.
        keep_default_na=True,
    )

    # ---- contract check: every expected column must be present (FR-3) ----
    expected = set(contract.dtypes) | set(contract.date_columns)
    missing = expected - set(frame.columns)
    if missing:
        raise LoadError(
            f"{contract.filename}: missing expected column(s) {sorted(missing)}. "
            "The source file has changed -- update src/load/schemas.py before loading."
        )

    # ---- drop privacy-sensitive and unused columns BEFORE anything is written (SEC-6) ----
    present_drops = [c for c in contract.drop_columns if c in frame.columns]
    if present_drops:
        frame = frame.drop(columns=present_drops)
        log.info("  dropped %s (SEC-6 / FR-4)", ", ".join(present_drops))

    # ---- convert the two dtypes that had to be read as something else ----
    for col, dtype in contract.dtypes.items():
        if dtype == "boolean":
            # .map leaves anything unexpected as NA, which the NOT NULL constraint will then
            # reject -- better than silently guessing what a third value meant.
            frame[col] = frame[col].map(_BOOL_MAP).astype("boolean")
        elif dtype == "Int64":
            # These are physical measurements recorded as whole units; the ".0" is an artefact
            # of pandas' float inference, not real precision. round() before casting so a
            # stored 224.99999 could never silently truncate to 224.
            frame[col] = frame[col].round().astype("Int64")

    # Keep exactly the contract columns, in a deterministic order. Any extra column in the
    # source is ignored rather than written, so a new upstream column cannot break the load.
    keep = [c for c in (*contract.dtypes, *contract.date_columns) if c in frame.columns]
    frame = frame[keep]
    if contract.rename:
        frame = frame.rename(columns=contract.rename)

    # ---- sanity bounds: count violations, never silently drop rows (SEC-3) ----
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
    """TRUNCATE the table and bulk-COPY the DataFrame into it, in one transaction (FR-2).

    `table` comes from a CsvContract constant in this repo, never from user input or file
    content, so interpolating it into the SQL text cannot be injection (SEC-4). Values are not
    interpolated at all -- they travel through the COPY stream.
    """
    buffer = io.StringIO()
    # Write a headerless CSV with \N for NULL, which is what COPY expects by default.
    frame.to_csv(buffer, index=False, header=False, na_rep="\\N")
    buffer.seek(0)

    columns = ", ".join(f'"{c}"' for c in frame.columns)
    raw_conn = engine.raw_connection()
    try:
        with raw_conn.cursor() as cur:
            # Plain TRUNCATE, deliberately WITHOUT `RESTART IDENTITY`: restarting a sequence
            # requires OWNERSHIP of it, and granting the loader ownership would let it drop
            # the sequence -- a privilege it has no business holding (SEC-5). The surrogate
            # key simply continues counting across reloads, which nothing depends on.
            # `table` is a repo constant (see the note in count_rows), not input.
            cur.execute(f"TRUNCATE TABLE {table}")  # noqa: S608  # nosec B608
            cur.copy_expert(
                # Same: identifiers are repo constants, values travel in the COPY stream.
                f"COPY {table} ({columns}) FROM STDIN WITH (FORMAT csv, NULL '\\N')",  # noqa: S608  # nosec B608
                buffer,
            )
        raw_conn.commit()  # one commit => the whole file is in, or none of it is
    except Exception:
        raw_conn.rollback()
        raise
    finally:
        raw_conn.close()
    return len(frame)


def count_rows(table: str, engine: Engine) -> int:
    with engine.connect() as conn:
        # The table name is a constant from src/load/schemas.py, never user input or file
        # content, so this f-string cannot be an injection vector. Both linters flag it anyway
        # because they cannot see where `table` came from; each needs its own marker --
        # `noqa: S608` for ruff, `nosec B608` for bandit -- with the reason stated (SEC-12).
        return int(
            conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()  # noqa: S608  # nosec B608
        )


def main() -> None:
    settings = get_settings()
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
        # A contract failure is a data problem, not a crash: print the message, not a traceback.
        log.error("load failed: %s", exc)
        sys.exit(1)
