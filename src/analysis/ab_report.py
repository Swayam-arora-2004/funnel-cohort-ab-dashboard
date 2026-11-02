"""Bridge between the A/B summary view and the pure statistics module.

This file exists so that `src/analysis/ab_test.py` can stay completely free of I/O. All the
database reading happens here; all the arithmetic happens there. That split is what lets the
statistics be unit-tested against textbook values without a database.

Run it directly to print the readout:

    python -m src.analysis.ab_report
"""

from __future__ import annotations

from sqlalchemy import text

from src.analysis.ab_test import ABResult, format_p_value, two_proportion_ztest
from src.db import engine_ro, fetch_df

# The metrics the view exposes. User input is validated against this allowlist rather than
# being interpolated anywhere.
METRICS: tuple[str, ...] = ("visit", "conversion")

# Human-readable labels for the dashboard and the printed report.
METRIC_LABELS: dict[str, str] = {
    "visit": "Site visit",
    "conversion": "Conversion",
}

_SUMMARY_SQL = text(
    """
    SELECT variant, is_control, users, converted, conversion_rate_pct
    FROM analytics.v_ab_summary
    WHERE metric = :metric
    ORDER BY is_control DESC
    """
)


def run_metric(metric: str) -> ABResult:
    """Read one metric from the view and run the test on it.

    `metric` is checked against METRICS before it reaches the query. The query itself binds it
    as a parameter, so even an unvalidated value could not alter the SQL -- the allowlist is a
    second layer, and it also gives a clear error instead of an empty result.
    """
    if metric not in METRICS:
        raise ValueError(f"unknown metric {metric!r}; expected one of {METRICS}")

    frame = fetch_df(engine_ro(), _SUMMARY_SQL, {"metric": metric})
    if len(frame) != 2:
        raise RuntimeError(
            f"expected exactly 2 variants for metric {metric!r}, found {len(frame)}. "
            "Has analytics.v_ab_summary been created? Run `make views`."
        )

    # ORDER BY is_control DESC puts the control arm first, so row 0 is A and row 1 is B.
    control, variant = frame.iloc[0], frame.iloc[1]
    if not control.is_control:
        raise RuntimeError("the first row is not the control arm -- check v_ab_summary")

    return two_proportion_ztest(
        conv_a=int(control.converted),
        n_a=int(control.users),
        conv_b=int(variant.converted),
        n_b=int(variant.users),
    )


def run_all() -> dict[str, ABResult]:
    """Run every metric. Both are always reported so neither can be cherry-picked."""
    return {metric: run_metric(metric) for metric in METRICS}


def format_report(metric: str, result: ABResult) -> str:
    """Render one metric's readout as plain text."""
    label = METRIC_LABELS.get(metric, metric)
    lines = [
        f"{'=' * 78}",
        f"  {label}  ({metric})",
        f"{'=' * 78}",
        f"  Control (withheld):  {result.conv_a:>9,} / {result.n_a:>10,}  "
        f"= {result.rate_a * 100:7.4f}%",
        f"  Treatment (targeted):{result.conv_b:>9,} / {result.n_b:>10,}  "
        f"= {result.rate_b * 100:7.4f}%",
        "",
        f"  Absolute difference : {result.diff_pp:+.3f} pp",
        f"  Relative change     : {result.relative_change_pct:+.2f}%",
        f"  z statistic         : {result.z_stat:+.4f}",
        # Shared with the dashboard, so the CLI and the UI cannot print it differently.
        f"  p-value (two-sided) {format_p_value(result.p_value)}"
        f"{'  SIGNIFICANT at 0.05' if result.significant else '  not significant at 0.05'}",
        f"  95% CI on difference: [{result.ci_low_pp:+.3f}, {result.ci_high_pp:+.3f}] pp",
        f"  Min detectable effect: {result.mde_pp:.3f} pp  (80% power, alpha 0.05)",
        f"  Observed power      : {result.observed_power:.1%}",
        "",
        "  RECOMMENDATION",
        f"    {result.verdict}",
        "",
        "  CAVEATS",
    ]
    lines.extend(f"    - {c}" for c in result.caveats)
    return "\n".join(lines)


def main() -> None:
    for metric, result in run_all().items():
        print(format_report(metric, result))
        print()


if __name__ == "__main__":
    main()
