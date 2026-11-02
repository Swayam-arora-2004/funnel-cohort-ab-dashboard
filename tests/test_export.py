"""Tests for the CSV export (milestone M5).

The export is the one place where data LEAVES the database for a world-visible destination:
published Tableau Public workbooks are public by design. So these tests are about the
three guards in `src/export/export_views.py`, not about formatting.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.config import get_settings
from src.export.export_views import (
    EXPORTABLE_VIEWS,
    ExportError,
    export_all,
    export_one,
    sanitise_for_spreadsheets,
)

# ------------------------------------------------------------------ pure, no database needed


def test_formula_injection_is_neutralised():
    """A cell starting with = + - or @ is executed as a formula by Excel and Sheets.

    `=HYPERLINK("http://evil","click")` in a file shared with colleagues is a real attack, and
    category names come from a downloaded dataset. The apostrophe prefix makes a spreadsheet
    treat the cell as text.
    """
    frame = pd.DataFrame(
        {
            "category": ['=HYPERLINK("http://evil","click")', "+1+1", "-cmd", "@SUM(A1)", "normal"],
            "revenue": [1.0, 2.0, 3.0, 4.0, 5.0],
        }
    )
    out = sanitise_for_spreadsheets(frame)
    assert list(out.category) == [
        '\'=HYPERLINK("http://evil","click")',
        "'+1+1",
        "'-cmd",
        "'@SUM(A1)",
        "normal",
    ]
    # Numbers are untouched -- only text cells can carry a formula.
    assert list(out.revenue) == [1.0, 2.0, 3.0, 4.0, 5.0]


def test_a_view_outside_the_allowlist_is_refused():
    """Identifiers cannot be bound as SQL parameters, so the allowlist is the control."""
    with pytest.raises(ExportError, match="not in EXPORTABLE_VIEWS"):
        export_one("v_customer_order_counts", get_settings().exports_dir)
    with pytest.raises(ExportError, match="not in EXPORTABLE_VIEWS"):
        export_one("orders; DROP TABLE raw.orders", get_settings().exports_dir)


def test_views_holding_identifiers_are_not_exportable():
    """The two person-level building blocks must never be in the allowlist."""
    assert "v_customer_first_order" not in EXPORTABLE_VIEWS
    assert "v_customer_order_counts" not in EXPORTABLE_VIEWS


# ------------------------------------------------------------------ needs the database


@pytest.mark.db
def test_export_writes_every_allowlisted_view(ro_engine):  # noqa: ARG001 - forces the skip
    results = export_all()
    assert set(results) == set(EXPORTABLE_VIEWS)
    assert all(rows > 0 for rows in results.values())


@pytest.mark.db
def test_no_exported_file_contains_an_identifier(ro_engine):  # noqa: ARG001 - forces the skip
    """Read the files back and assert no identifier column reached disk.

    Asserting on the written FILES rather than on the DataFrames is deliberate: the guard is
    only worth anything if it holds for what actually lands on disk and gets uploaded.
    """
    export_all()
    exports_dir = get_settings().exports_dir
    banned = ("customer_id", "customer_unique_id", "order_id", "product_id", "seller_id", "userid")
    for view in EXPORTABLE_VIEWS:
        columns = pd.read_csv(exports_dir / f"{view}.csv", nrows=0).columns
        leaked = [c for c in columns if any(b in c.lower() for b in banned)]
        assert not leaked, f"{view}.csv would publish {leaked}"


@pytest.mark.db
def test_exported_ab_summary_matches_the_view(ro_engine):  # noqa: ARG001 - forces the skip
    """A spot check that the CSV holds the same numbers the dashboard shows."""
    export_all()
    frame = pd.read_csv(get_settings().exports_dir / "v_ab_summary.csv")
    conv = frame[frame.metric == "conversion"].set_index("variant")
    assert int(conv.loc["control", "users"]) == 2_096_937
    assert int(conv.loc["treatment", "users"]) == 11_882_655
    assert float(conv.loc["control", "conversion_rate_pct"]) == pytest.approx(0.1938, abs=0.0001)
    assert float(conv.loc["treatment", "conversion_rate_pct"]) == pytest.approx(0.3089, abs=0.0001)
