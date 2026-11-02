"""Export the analytics views to CSV, for rebuilding the dashboard in a BI tool.

Three guards here are security decisions, not formatting:

* An allowlist of view names. SQL can bind a value but not an identifier, so a dynamic view
  name has to be interpolated -- the allowlist is what makes that safe.
* No identifier columns leave the database. Published workbooks are world-visible, so the
  guard refuses any column whose name looks like an id rather than trusting the views.
* A formula-injection guard. A cell starting with = + - or @ is executed as a formula by
  Excel and Sheets, so those get an apostrophe prefix.
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

# the complete set that may be exported; identifiers never come from input
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

# matched by name, so a future view that adds an id fails the export rather than publishing it
_IDENTIFIER_PATTERN = re.compile(
    r"(customer_unique_id|customer_id|order_id|product_id|seller_id|review_id|userid|zip)",
    re.IGNORECASE,
)

# Spreadsheets execute a cell starting with any of these.
_FORMULA_PREFIXES = ("=", "+", "-", "@")


class ExportError(RuntimeError):
    """Raised when an export would leak an identifier or name an unknown view."""


def sanitise_for_spreadsheets(frame: pd.DataFrame) -> pd.DataFrame:
    """Prefix any text cell a spreadsheet would execute as a formula."""
    out = frame.copy()
    for column in out.columns:
        # pandas' own predicate, not a hand-written dtype comparison. Checking for `object`
        # and `"string"` silently did nothing on pandas 3.x, where text columns are `str`.
        if pd.api.types.is_string_dtype(out[column]) or out[column].dtype == object:
            out[column] = out[column].map(
                lambda v: f"'{v}" if isinstance(v, str) and v.startswith(_FORMULA_PREFIXES) else v
            )
    return out


def export_one(view: str, exports_dir) -> int:
    """Export a single allowlisted view. Returns the number of rows written."""
    if view not in EXPORTABLE_VIEWS:
        raise ExportError(f"{view!r} is not in EXPORTABLE_VIEWS; refusing to export it")

    # `view` is a constant from the tuple above, never input
    frame = fetch_df(engine_ro(), text(f"SELECT * FROM analytics.{view}"))  # noqa: S608  # nosec B608

    leaked = [c for c in frame.columns if _IDENTIFIER_PATTERN.search(c)]
    if leaked:
        raise ExportError(
            f"{view} contains identifier column(s) {leaked}. Exports are world-visible once "
            "published, so they must be aggregates only. Aggregate the view or add an "
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
    print("  Load these into a BI tool as separate sources -- they are at different grains.\n")


if __name__ == "__main__":
    main()
