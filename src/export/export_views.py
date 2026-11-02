"""Export the analytics views to CSV, for rebuilding the dashboard in Tableau Public.

Three things here are security decisions, not formatting choices (SEC-11):

1. **An allowlist of view names.** The view to export is never taken from user input or from a
   file. SQL identifiers cannot be bound as parameters -- only values can -- so a dynamic table
   name would have to be interpolated into the statement, which is exactly the injection path
   SEC-4 forbids. The allowlist below is the whole set, and anything not in it is refused.

2. **No identifiers leave the database.** Published Tableau Public workbooks are world-visible
   (D-002), so every export is an aggregate. The guard rejects any column whose name looks like
   an identifier rather than trusting that the views happen not to contain one today.

3. **A formula-injection guard.** A CSV cell beginning with `=`, `+`, `-` or `@` is executed as
   a formula when the file is opened in Excel or Sheets. `=HYPERLINK(...)` in a shared export
   is a real attack. Every text cell that starts with one of those is prefixed with an
   apostrophe, which spreadsheets treat as "this is text".
"""

from __future__ import annotations

import logging
import re
import sys

import pandas as pd
from sqlalchemy import text

from src.config import get_settings
from src.db import engine_ro, fetch_df

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S"
)
log = logging.getLogger("export_views")

# The complete set of views that may be exported. Identifiers never come from input (SEC-4).
EXPORTABLE_VIEWS: tuple[str, ...] = (
    "v_funnel_stages",
    "v_funnel_dropoff",
    "v_cohort_sizes",
    "v_cohort_retention",
    "v_revenue_by_month",
    "v_revenue_running_total",
    "v_top_categories_ranked",
    "v_ab_summary",
    "v_repeat_purchase_summary",
)

# Columns that must never reach a published file. Matched by name, so a future view that adds
# one is caught rather than silently exported (SEC-11, SEC-6).
_IDENTIFIER_PATTERN = re.compile(
    r"(customer_unique_id|customer_id|order_id|product_id|seller_id|review_id|userid|zip)",
    re.IGNORECASE,
)

# Spreadsheets execute a cell starting with any of these.
_FORMULA_PREFIXES = ("=", "+", "-", "@")


class ExportError(RuntimeError):
    """Raised when an export would leak an identifier or name an unknown view."""


def sanitise_for_spreadsheets(frame: pd.DataFrame) -> pd.DataFrame:
    """Prefix any text cell that a spreadsheet would execute as a formula (SEC-11)."""
    out = frame.copy()
    for column in out.columns:
        # Detect text columns with pandas' own predicate rather than comparing dtypes by hand.
        # The hand-written version checked for `object` and `"string"` and silently did
        # NOTHING on pandas 3.x, where text columns default to the `str` dtype -- so the guard
        # was a no-op and the first export ran unsanitised. A test now covers this.
        if pd.api.types.is_string_dtype(out[column]) or out[column].dtype == object:
            out[column] = out[column].map(
                lambda v: f"'{v}" if isinstance(v, str) and v.startswith(_FORMULA_PREFIXES) else v
            )
    return out


def export_one(view: str, exports_dir) -> int:
    """Export a single allowlisted view. Returns the number of rows written."""
    if view not in EXPORTABLE_VIEWS:
        raise ExportError(f"{view!r} is not in EXPORTABLE_VIEWS; refusing to export it")

    # `view` is a constant from the tuple above, never input, so this f-string cannot be an
    # injection vector. Both linters flag it anyway because they cannot see where it came from.
    frame = fetch_df(engine_ro(), text(f"SELECT * FROM analytics.{view}"))  # noqa: S608  # nosec B608

    leaked = [c for c in frame.columns if _IDENTIFIER_PATTERN.search(c)]
    if leaked:
        raise ExportError(
            f"{view} contains identifier column(s) {leaked}. Exports are world-visible once "
            "published (D-002), so they must be aggregates only. Aggregate the view or add an "
            "explicit projection before exporting it."
        )

    path = exports_dir / f"{view}.csv"
    sanitise_for_spreadsheets(frame).to_csv(path, index=False)
    log.info("  %-28s %7d rows -> %s", view, len(frame), path.name)
    return len(frame)


def export_all() -> dict[str, int]:
    """Export every allowlisted view. Returns {view name: rows written}."""
    exports_dir = get_settings().exports_dir
    exports_dir.mkdir(parents=True, exist_ok=True)
    log.info("exporting %d views to %s", len(EXPORTABLE_VIEWS), exports_dir)
    return {view: export_one(view, exports_dir) for view in EXPORTABLE_VIEWS}


def main() -> None:
    try:
        results = export_all()
    except ExportError as exc:
        log.error("export failed: %s", exc)
        sys.exit(1)
    total = sum(results.values())
    print(f"\n  {len(results)} files written, {total:,} rows in total")
    print("  Next: docs/BI_HANDOFF.md has the Tableau Public steps.\n")


if __name__ == "__main__":
    main()
