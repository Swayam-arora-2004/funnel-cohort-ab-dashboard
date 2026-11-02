"""A/B test readout (FR-11 to FR-15, FR-19, FR-21)."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import streamlit as st

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.components import charts, queries  # noqa: E402 - must follow the sys.path fix
from src.analysis import ab_report  # noqa: E402

log = logging.getLogger(__name__)
st.set_page_config(page_title="A/B Test", page_icon="test_tube", layout="wide")

st.title("A/B test: Cookie Cats progression gate")
st.caption(
    "**Source: Cookie Cats mobile-game A/B test — a REAL published experiment, not simulated.** "
    "This is a different dataset from the rest of the dashboard, which uses Olist e-commerce "
    "data. 90,189 players installing the game were randomised to one of two variants, differing "
    "only in where the first progression gate appears: `gate_30` (level 30, the existing "
    "behaviour, i.e. the control) or `gate_40` (level 40, the change being tested). "
    "Licence note: Kaggle reports no licence for this dataset; see `docs/DATA.md`."
)

try:
    st.subheader("Both metrics, always")
    st.caption(
        "Day-1 and day-7 retention are both shown. **Running two tests and presenting only "
        "whichever came out significant is p-hacking**, so neither is hidden, and the threshold "
        "corrected for having tested two outcomes is reported alongside the raw p-value."
    )

    results = ab_report.run_all()

    for metric, result in results.items():
        label = ab_report.METRIC_LABELS[metric]
        st.markdown(f"### {label}")

        summary = queries.ab_summary(metric)
        chart_col, stat_col = st.columns([3, 2])

        with chart_col:
            st.plotly_chart(
                charts.ab_comparison_chart(summary, label),
                width="stretch",
            )
            st.plotly_chart(
                charts.confidence_interval_chart(
                    result.ci_low_pp, result.ci_high_pp, result.diff_pp
                ),
                width="stretch",
            )
            st.caption(
                "The lower chart is the whole conclusion in one picture: **if the bar crosses "
                "the dashed line, the data cannot rule out 'no effect'.**"
            )

        with stat_col:
            # Significance is stated in WORDS, not by colour alone.
            if result.significant:
                st.markdown(f"**Statistically significant** at α = 0.05 (p = {result.p_value:.6f})")
            else:
                st.markdown(
                    f"**Not statistically significant** at α = 0.05 (p = {result.p_value:.6f})"
                )

            st.dataframe(
                {
                    "Measure": [
                        "Control (gate_30)",
                        "Variant (gate_40)",
                        "Absolute difference",
                        "Relative change",
                        "z statistic",
                        "p-value (two-sided)",
                        "95% CI on difference",
                        "Bonferroni threshold (2 metrics)",
                        "Min detectable effect (80% power)",
                        "Observed power",
                    ],
                    "Value": [
                        f"{result.rate_a * 100:.3f}%  ({result.conv_a:,} / {result.n_a:,})",
                        f"{result.rate_b * 100:.3f}%  ({result.conv_b:,} / {result.n_b:,})",
                        f"{result.diff_pp:+.3f} pp",
                        f"{result.relative_change_pct:+.2f}%",
                        f"{result.z_stat:+.4f}",
                        f"{result.p_value:.6f}",
                        f"[{result.ci_low_pp:+.3f}, {result.ci_high_pp:+.3f}] pp",
                        f"α = 0.025 — {'passes' if result.p_value < 0.025 else 'does not pass'}",
                        f"{result.mde_pp:.3f} pp",
                        f"{result.observed_power:.1%}",
                    ],
                },
                hide_index=True,
                width="stretch",
            )

        st.markdown("**Recommendation**")
        if result.significant and result.diff_pp < 0:
            st.error(result.verdict)
        elif result.significant:
            st.success(result.verdict)
        else:
            st.warning(result.verdict)

        with st.expander(f"Caveats for {label} — read before quoting this result"):
            for caveat in result.caveats:
                st.markdown(f"- {caveat}")

        st.divider()

    # ---------------------------------------------------------------- method note
    with st.expander("Method: why the test and the interval use different standard errors"):
        st.markdown(
            """
The z-test and the confidence interval are computed with **different** standard
errors, on purpose. Conflating them is a common error.

**The z-test uses the POOLED standard error** — one shared conversion rate
estimated from both arms combined. The null hypothesis *asserts* that the arms
share one true rate; that is the world the p-value describes, so the best
estimate of that single rate should use all the data.

**The confidence interval uses the UNPOOLED standard error** — each arm
contributes its own variance. Estimating the *size* of a difference assumes
nothing about the arms being equal, so neither arm's variance should be replaced
by a shared one.

Using the pooled standard error for the interval produces an interval that is
subtly inconsistent with the estimate it is centred on. A test named
`test_pooled_and_unpooled_standard_errors_differ` fails if anyone "simplifies"
the module to share one standard error between the two.

The arithmetic is written out by hand in `src/analysis/ab_test.py` rather than
delegated to a library, so it can be explained line by line — and every quantity
is cross-checked against `statsmodels` to 1e-10 in the test suite, so "written by
hand" does not mean "unverified".
            """
        )

except Exception as exc:  # noqa: BLE001
    log.exception("A/B page failed")
    st.error("Could not load the A/B results. See the server log for details.")
    st.caption(f"Error type: {type(exc).__name__}")
