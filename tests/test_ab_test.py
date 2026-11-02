"""Tests for the A/B statistics (milestone M3).

`src/analysis/ab_test.py` writes the arithmetic out by hand so it can be explained line by
line. These tests are what make that safe: every quantity is cross-checked against
`statsmodels`, which is an independently implemented, widely used reference. "Written by hand"
must not mean "unverified".

Tolerance is 1e-10 for exact agreement and 1e-9 where a different but equivalent formula is
used. No database is needed -- the module is pure, which is the point.
"""

from __future__ import annotations

import math

import pytest
from scipy.stats import norm
from statsmodels.stats.proportion import (
    confint_proportions_2indep,
    proportions_ztest,
)

from src.analysis.ab_test import two_proportion_ztest

# The real Cookie Cats numbers, from analytics.v_ab_summary (docs/QUERIES.md).
DAY1 = {"conv_a": 20034, "n_a": 44700, "conv_b": 20119, "n_b": 45489}
DAY7 = {"conv_a": 8502, "n_a": 44700, "conv_b": 8279, "n_b": 45489}


# --------------------------------------------------------------- cross-check vs statsmodels


@pytest.mark.parametrize("case", [DAY1, DAY7], ids=["day1", "day7"])
def test_z_and_p_match_statsmodels(case):
    """Our pooled z-test must agree with statsmodels.proportions_ztest exactly.

    Note the argument order: we pass the VARIANT first, so a positive z means the variant did
    better -- the same convention as our diff_pp. statsmodels computes count[0]/nobs[0] minus
    count[1]/nobs[1], so the arms go in as (B, A).
    """
    result = two_proportion_ztest(**case)
    z_ref, p_ref = proportions_ztest(
        count=[case["conv_b"], case["conv_a"]],
        nobs=[case["n_b"], case["n_a"]],
    )
    assert result.z_stat == pytest.approx(z_ref, abs=1e-10)
    assert result.p_value == pytest.approx(p_ref, abs=1e-10)


@pytest.mark.parametrize("case", [DAY1, DAY7], ids=["day1", "day7"])
def test_confidence_interval_matches_statsmodels_wald(case):
    """Our unpooled interval must match statsmodels' Wald interval on the difference.

    `method="wald"` is specified explicitly because statsmodels defaults to Newcombe, which is
    a different (slightly better for small samples) interval. With ~45,000 per arm the two
    agree to three decimals anyway, but the test must compare like with like.
    """
    result = two_proportion_ztest(**case)
    low_ref, high_ref = confint_proportions_2indep(
        count1=case["conv_b"],
        nobs1=case["n_b"],
        count2=case["conv_a"],
        nobs2=case["n_a"],
        method="wald",
        compare="diff",
        alpha=0.05,
    )
    assert result.ci_low_pp / 100 == pytest.approx(low_ref, abs=1e-10)
    assert result.ci_high_pp / 100 == pytest.approx(high_ref, abs=1e-10)


# --------------------------------------------------------------- hand-worked values


def test_hand_worked_textbook_example():
    """A small example whose every step can be checked with a calculator.

    Control: 100 of 1,000 convert -> 10%.  Variant: 150 of 1,000 -> 15%.
      pooled p = 250 / 2000                    = 0.125
      SE_pooled = sqrt(.125 * .875 * (2/1000))  = 0.0147901995...
      z         = 0.05 / SE_pooled              = 3.380617...
      p         = 2 * sf(3.380617...)           = 0.000723...
    """
    result = two_proportion_ztest(conv_a=100, n_a=1000, conv_b=150, n_b=1000)

    pooled = 250 / 2000
    se_pooled = math.sqrt(pooled * (1 - pooled) * (1 / 1000 + 1 / 1000))
    expected_z = 0.05 / se_pooled

    assert result.rate_a == 0.10
    assert result.rate_b == 0.15
    assert result.diff_pp == pytest.approx(5.0, abs=1e-12)
    assert result.relative_change_pct == pytest.approx(50.0, abs=1e-12)
    assert result.z_stat == pytest.approx(expected_z, abs=1e-12)
    assert result.z_stat == pytest.approx(3.3806170189, abs=1e-9)
    assert result.p_value == pytest.approx(2 * norm.sf(expected_z), abs=1e-12)
    assert result.significant is True


def test_hand_worked_confidence_interval():
    """The interval uses the UNPOOLED SE. Checked against a separate calculation.

    SE_unpooled = sqrt(.10*.90/1000 + .15*.85/1000) = 0.01431782...
    margin      = 1.959963985 * SE_unpooled        = 0.02806...
    """
    result = two_proportion_ztest(conv_a=100, n_a=1000, conv_b=150, n_b=1000)
    se_unpooled = math.sqrt(0.10 * 0.90 / 1000 + 0.15 * 0.85 / 1000)
    margin = norm.ppf(0.975) * se_unpooled

    assert result.ci_low_pp == pytest.approx((0.05 - margin) * 100, abs=1e-12)
    assert result.ci_high_pp == pytest.approx((0.05 + margin) * 100, abs=1e-12)
    # The interval must be centred on the observed difference.
    assert (result.ci_low_pp + result.ci_high_pp) / 2 == pytest.approx(result.diff_pp, abs=1e-12)


def test_pooled_and_unpooled_standard_errors_differ():
    """Guards the design point: test and interval use DIFFERENT standard errors.

    If someone "simplified" the module to share one SE, the CI half-width would become exactly
    z * SE_pooled and this test would fail.
    """
    result = two_proportion_ztest(conv_a=100, n_a=1000, conv_b=150, n_b=1000)
    half_width = (result.ci_high_pp - result.ci_low_pp) / 2 / 100
    se_pooled_half = norm.ppf(0.975) * math.sqrt(0.125 * 0.875 * (2 / 1000))
    assert half_width != pytest.approx(se_pooled_half, abs=1e-6)


# --------------------------------------------------------------- properties and edge cases


def test_identical_arms_give_zero_effect_and_p_of_one():
    result = two_proportion_ztest(conv_a=500, n_a=1000, conv_b=500, n_b=1000)
    assert result.diff_pp == 0.0
    assert result.z_stat == 0.0
    assert result.p_value == pytest.approx(1.0, abs=1e-12)
    assert result.significant is False


def test_no_variance_at_all_is_handled_not_crashed():
    """Both arms at 0% means a zero standard error. Must not divide by zero."""
    result = two_proportion_ztest(conv_a=0, n_a=1000, conv_b=0, n_b=1000)
    assert result.z_stat == 0.0
    assert result.p_value == 1.0
    assert result.significant is False


def test_direction_is_variant_minus_control():
    """A positive diff must mean the VARIANT did better. Sign errors are easy and silent."""
    better = two_proportion_ztest(conv_a=100, n_a=1000, conv_b=150, n_b=1000)
    worse = two_proportion_ztest(conv_a=150, n_a=1000, conv_b=100, n_b=1000)
    assert better.diff_pp > 0
    assert worse.diff_pp < 0
    assert better.z_stat == pytest.approx(-worse.z_stat, abs=1e-12)
    assert better.p_value == pytest.approx(worse.p_value, abs=1e-12)


def test_significance_and_interval_agree():
    """A significant result must have an interval that excludes zero, and vice versa.

    These are two expressions of the same arithmetic, so a mismatch means a bug. (They can
    disagree in principle because one uses the pooled SE and the other does not; with ~45,000
    per arm they do not, and if that ever changed we would want to know.)
    """
    for case in (DAY1, DAY7):
        result = two_proportion_ztest(**case)
        excludes_zero = result.ci_low_pp > 0 or result.ci_high_pp < 0
        assert result.significant == excludes_zero, case


def test_larger_sample_detects_smaller_effects():
    """MDE must shrink as the sample grows -- the core intuition behind statistical power."""
    small = two_proportion_ztest(conv_a=100, n_a=1_000, conv_b=105, n_b=1_000)
    large = two_proportion_ztest(conv_a=10_000, n_a=100_000, conv_b=10_500, n_b=100_000)
    assert large.mde_pp < small.mde_pp


def test_mde_scales_as_inverse_square_root_of_n():
    """Quadrupling the sample should roughly halve the MDE (1/sqrt(n))."""
    base = two_proportion_ztest(conv_a=1_000, n_a=10_000, conv_b=1_000, n_b=10_000)
    quad = two_proportion_ztest(conv_a=4_000, n_a=40_000, conv_b=4_000, n_b=40_000)
    assert quad.mde_pp == pytest.approx(base.mde_pp / 2, rel=1e-9)


# --------------------------------------------------------------- input validation (SEC-3)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"conv_a": 10, "n_a": 0, "conv_b": 10, "n_b": 100},  # empty arm
        {"conv_a": 10, "n_a": 100, "conv_b": 10, "n_b": -5},  # negative arm
        {"conv_a": 200, "n_a": 100, "conv_b": 10, "n_b": 100},  # conversions > users
        {"conv_a": -1, "n_a": 100, "conv_b": 10, "n_b": 100},  # negative conversions
    ],
)
def test_invalid_input_raises(kwargs):
    with pytest.raises(ValueError):
        two_proportion_ztest(**kwargs)


@pytest.mark.parametrize("alpha", [0, 1, -0.1, 1.5])
def test_invalid_alpha_raises(alpha):
    with pytest.raises(ValueError):
        two_proportion_ztest(conv_a=10, n_a=100, conv_b=10, n_b=100, alpha=alpha)


# --------------------------------------------------------------- the readout


def test_verdict_never_claims_no_difference():
    """A null result must not be reported as proof of equivalence.

    This is the single most common way an A/B readout misleads its reader, so it is a test.
    """
    result = two_proportion_ztest(conv_a=500, n_a=1000, conv_b=502, n_b=1000)
    assert not result.significant
    lowered = result.verdict.lower()
    assert "no difference" not in lowered or "not 'there is no difference'" in lowered
    assert "inconclusive" in lowered


def test_significant_negative_result_says_do_not_ship():
    result = two_proportion_ztest(**DAY7)
    assert result.significant
    assert result.diff_pp < 0
    assert "do not ship" in result.verdict.lower()


def test_caveats_mention_power_and_multiple_metrics():
    """FR-14: sample size, power and the two-metric caveat must always be stated."""
    joined = " ".join(two_proportion_ztest(**DAY7).caveats).lower()
    assert "80% power" in joined
    assert "bonferroni" in joined
    assert "did not run this experiment" in joined
    assert "primary metric" in joined


# --------------------------------------------------------------- the DB bridge (ab_report)
# These need a database, so they carry the `db` marker and skip without one. Everything above
# runs anywhere, which is the benefit of keeping ab_test.py pure.


@pytest.mark.db
def test_report_reproduces_the_pure_function(ro_engine):  # noqa: ARG001 - fixture forces the skip
    """The numbers the view feeds in must match the numbers recorded in docs/QUERIES.md.

    If someone edits v_ab_summary, this fails -- which is the point: the documented results and
    the live view must never drift apart.
    """
    from src.analysis.ab_report import run_all

    results = run_all()
    assert set(results) == {"retention_1", "retention_7"}

    day7 = results["retention_7"]
    assert (day7.conv_a, day7.n_a) == (8502, 44700)
    assert (day7.conv_b, day7.n_b) == (8279, 45489)
    assert day7.p_value == pytest.approx(two_proportion_ztest(**DAY7).p_value, abs=1e-12)

    day1 = results["retention_1"]
    assert (day1.conv_a, day1.n_a) == (20034, 44700)
    assert (day1.conv_b, day1.n_b) == (20119, 45489)


@pytest.mark.db
def test_report_rejects_an_unknown_metric(ro_engine):  # noqa: ARG001 - fixture forces the skip
    """Metric names are validated against an allowlist before reaching the query (SEC-3)."""
    from src.analysis.ab_report import run_metric

    with pytest.raises(ValueError, match="unknown metric"):
        run_metric("retention_7; DROP TABLE raw.orders")


@pytest.mark.db
def test_day7_survives_bonferroni_correction(ro_engine):  # noqa: ARG001 - fixture forces the skip
    """Two metrics were tested, so the honest threshold is 0.025, not 0.05.

    Asserting this means the headline conclusion does not rest on the uncorrected threshold.
    """
    from src.analysis.ab_report import run_metric

    assert run_metric("retention_7").p_value < 0.025


@pytest.mark.db
def test_day1_is_underpowered(ro_engine):  # noqa: ARG001 - fixture forces the skip
    """Day-1 is not merely non-significant: the test was too small to settle it.

    Recorded as a test because 'not significant' and 'no effect' are different claims, and the
    difference is exactly what the observed power tells you.
    """
    from src.analysis.ab_report import run_metric

    day1 = run_metric("retention_1")
    assert not day1.significant
    assert day1.observed_power < 0.5
    assert abs(day1.diff_pp) < day1.mde_pp
