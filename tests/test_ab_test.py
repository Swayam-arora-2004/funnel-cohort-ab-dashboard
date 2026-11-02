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

# Two realistic shapes for the cross-checks below. They are deliberately NOT the project's
# current dataset: these tests verify the ARITHMETIC against statsmodels, and tying them to
# whichever experiment the project happens to use would mean swapping the dataset breaks the
# maths tests. The published figures are pinned in tests/test_documented_numbers.py instead;
# the live numbers are exercised by the bridge tests at the bottom of this file.
#
# CASE_SMALL is a near-null difference in a 45k-per-arm test; CASE_LARGE is a tiny but real
# difference in a multi-million-user test, which is the shape the Criteo data has.
CASE_SMALL = {"conv_a": 8502, "n_a": 44700, "conv_b": 8279, "n_b": 45489}
CASE_LARGE = {"conv_a": 4800, "n_a": 2_000_000, "conv_b": 29000, "n_b": 11_000_000}


# --------------------------------------------------------------- cross-check vs statsmodels


@pytest.mark.parametrize("case", [CASE_SMALL, CASE_LARGE], ids=["small", "large"])
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


@pytest.mark.parametrize("case", [CASE_SMALL, CASE_LARGE], ids=["small", "large"])
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
    for case in (CASE_SMALL, CASE_LARGE):
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
    result = two_proportion_ztest(**CASE_SMALL)
    assert result.significant
    assert result.diff_pp < 0
    assert "do not ship" in result.verdict.lower()


def test_caveats_mention_power_and_multiple_metrics():
    """FR-14: sample size, power and the two-metric caveat must always be stated."""
    joined = " ".join(two_proportion_ztest(**CASE_SMALL).caveats).lower()
    assert "80% power" in joined
    assert "bonferroni" in joined
    assert "did not run this experiment" in joined
    assert "primary metric" in joined
    # The Criteo data makes this caveat load-bearing: it records both the random assignment
    # and whether an ad was actually served, and splitting on the latter would destroy the
    # randomisation. The readout must say which one it used.
    assert "intention-to-treat" in joined


# --------------------------------------------------------------- the DB bridge (ab_report)
# These need a database, so they carry the `db` marker and skip without one. Everything above
# runs anywhere, which is the benefit of keeping ab_test.py pure.


@pytest.mark.db
def test_report_runs_both_metrics(ro_engine):  # noqa: ARG001 - the fixture forces the skip
    """Both outcomes are always returned, so neither can be cherry-picked (FR-14, D-016)."""
    from src.analysis.ab_report import METRICS, run_all

    results = run_all()
    assert set(results) == set(METRICS)
    assert len(results) == 2


@pytest.mark.db
def test_report_arms_partition_the_users(ro_engine):  # noqa: ARG001 - forces the skip
    """Per metric, the two arms must account for every user exactly once.

    Reading the total from the source table rather than hardcoding it means this test survives
    a dataset swap -- which is exactly what just happened (D-023).
    """
    from sqlalchemy import text

    from src.analysis.ab_report import run_all
    from src.db import engine_rw

    with engine_rw().connect() as conn:
        total = int(conn.execute(text("SELECT count(*) FROM raw.ab_criteo_uplift")).scalar_one())

    for metric, result in run_all().items():
        assert result.n_a + result.n_b == total, f"{metric} covers {result.n_a + result.n_b}"


@pytest.mark.db
def test_report_rejects_an_unknown_metric(ro_engine):  # noqa: ARG001 - forces the skip
    """Metric names are validated against an allowlist before reaching the query (SEC-3)."""
    from src.analysis.ab_report import run_metric

    with pytest.raises(ValueError, match="unknown metric"):
        run_metric("conversion; DROP TABLE raw.orders")


@pytest.mark.db
def test_report_matches_the_pure_function(ro_engine):  # noqa: ARG001 - forces the skip
    """The bridge must not do any arithmetic of its own."""
    from src.analysis.ab_report import run_metric

    live = run_metric("conversion")
    recomputed = two_proportion_ztest(
        conv_a=live.conv_a, n_a=live.n_a, conv_b=live.conv_b, n_b=live.n_b
    )
    assert live.p_value == pytest.approx(recomputed.p_value, abs=1e-12)
    assert live.ci_low_pp == pytest.approx(recomputed.ci_low_pp, abs=1e-12)


@pytest.mark.db
def test_control_arm_is_the_withheld_group(ro_engine):  # noqa: ARG001 - forces the skip
    """Arm A must be the randomly WITHHELD group.

    If the arms were swapped, every sign in the readout would flip and the recommendation
    would be exactly backwards -- a silent, catastrophic error. The withheld group is the
    smaller one here, which gives a cheap independent check.
    """
    from src.analysis.ab_report import run_metric

    result = run_metric("conversion")
    assert result.n_a < result.n_b, "control should be the smaller, withheld arm"
