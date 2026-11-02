"""Two-proportion A/B test: z-test, confidence interval, p-value and power.

Pure: four integers in, a result object out. No database, no I/O. That is what lets the
statistics be tested against hand-worked values, and why swapping the dataset did not touch
this file.

The arithmetic is written out rather than delegated to statsmodels, and tests/test_ab_test.py
cross-checks every quantity against statsmodels to 1e-10.

One subtlety: the test and the interval use different standard errors. The z-test uses the
POOLED rate, because the null hypothesis says the arms share one true rate. The interval uses
the UNPOOLED one, because estimating the size of a difference assumes nothing about the arms
being equal. Using the pooled SE for the interval is a common mistake.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from scipy.stats import norm


@dataclass(frozen=True)
class ABResult:
    """Everything needed to report an A/B test, in percentage points where it aids reading."""

    # --- arm A: the control ---
    n_a: int
    conv_a: int
    rate_a: float  # proportion, 0-1
    # --- arm B: the variant ---
    n_b: int
    conv_b: int
    rate_b: float
    # --- the comparison, in percentage points (pp) ---
    diff_pp: float  # rate_b - rate_a; positive means the variant did better
    relative_change_pct: float  # the same difference as a % of the control rate
    # --- the test ---
    z_stat: float
    p_value: float  # two-sided
    alpha: float
    significant: bool
    # --- the interval on the difference ---
    ci_low_pp: float
    ci_high_pp: float
    # --- power ---
    mde_pp: float  # smallest true difference detectable at 80% power with these sample sizes
    observed_power: float  # power this test actually had against the observed difference
    # --- the readout ---
    verdict: str
    caveats: tuple[str, ...]


def two_proportion_ztest(
    conv_a: int,
    n_a: int,
    conv_b: int,
    n_b: int,
    alpha: float = 0.05,
    power_target: float = 0.80,
) -> ABResult:
    """Compare two conversion rates.

    Args:
        conv_a, n_a: conversions and total users in the CONTROL arm.
        conv_b, n_b: conversions and total users in the VARIANT arm.
        alpha: significance level for the two-sided test and the interval. 0.05 -> 95% CI.
        power_target: power used for the minimum-detectable-effect calculation.

    Returns:
        An ABResult. Nothing is rounded for display; the dashboard formats it.
    """
    # input validation
    if n_a <= 0 or n_b <= 0:
        raise ValueError("each arm needs at least one user")
    if not (0 <= conv_a <= n_a) or not (0 <= conv_b <= n_b):
        raise ValueError("conversions must be between 0 and the number of users in that arm")
    if not (0 < alpha < 1):
        raise ValueError("alpha must be between 0 and 1")

    rate_a = conv_a / n_a
    rate_b = conv_b / n_b
    diff = rate_b - rate_a

    # z-test: pooled SE, because the null hypothesis says the arms share one rate
    pooled_rate = (conv_a + conv_b) / (n_a + n_b)
    se_pooled = math.sqrt(pooled_rate * (1 - pooled_rate) * (1 / n_a + 1 / n_b))

    if se_pooled == 0:
        # Both arms 0% or both 100%. There is no variance, so no test is possible.
        z_stat = 0.0
        p_value = 1.0
    else:
        z_stat = float(diff / se_pooled)
        # Two-sided: no direction was pre-committed. sf() is 1 - cdf, numerically stable.
        # float() because scipy returns a numpy scalar, which would leak a numpy bool_ into
        # a dataclass annotated bool.
        p_value = float(2 * norm.sf(abs(z_stat)))

    # interval: unpooled SE, because estimating a size assumes nothing about the arms
    se_unpooled = math.sqrt(rate_a * (1 - rate_a) / n_a + rate_b * (1 - rate_b) / n_b)
    z_critical = norm.ppf(1 - alpha / 2)  # 1.959964... for alpha = 0.05
    margin = float(z_critical * se_unpooled)
    ci_low, ci_high = diff - margin, diff + margin

    # MDE: the smallest true difference these sample sizes could detect at power_target.
    # Reporting it is what stops a null result being misread as "no effect".
    z_power = norm.ppf(power_target)
    mde = float((z_critical + z_power) * se_unpooled)

    # low observed power with a high p-value means "we learned little", not "no effect"
    observed_power = float(norm.cdf(abs(diff) / se_unpooled - z_critical)) if se_unpooled else 0.0

    significant = bool(p_value < alpha)

    return ABResult(
        n_a=n_a,
        conv_a=conv_a,
        rate_a=rate_a,
        n_b=n_b,
        conv_b=conv_b,
        rate_b=rate_b,
        diff_pp=diff * 100,
        relative_change_pct=(diff / rate_a * 100) if rate_a else float("nan"),
        z_stat=float(z_stat),
        p_value=float(p_value),
        alpha=alpha,
        significant=significant,
        ci_low_pp=ci_low * 100,
        ci_high_pp=ci_high * 100,
        mde_pp=mde * 100,
        observed_power=observed_power,
        verdict=_verdict(diff, p_value, alpha, ci_low, ci_high, mde, significant),
        caveats=_caveats(n_a, n_b, mde, abs(diff), significant),
    )


def format_p_value(p: float) -> str:
    """Format a p-value at any magnitude, carrying its own operator ("= 0.0016", "< 1e-300").

    Below float64's floor (~5e-324) a p-value underflows to exactly 0.0. Printing "p = 0"
    would be false -- a p-value is a probability and is always positive -- so print a bound.
    Here z = 65.2, so the true value is around 1e-926.
    """

    if p >= 1e-4:
        return f"= {p:.4f}"
    if p > 0:
        return f"= {p:.3e}"
    return "< 1e-300"


def _verdict(
    diff: float,
    p_value: float,
    alpha: float,
    ci_low: float,
    ci_high: float,
    mde: float,
    significant: bool,
) -> str:
    """A plain-language recommendation.

    Avoids the phrase "no difference" for a null result -- failing to detect an effect is not
    the same as establishing there is none.
    """
    direction = "better" if diff > 0 else "worse"
    size_pp = abs(diff) * 100

    if significant:
        if diff < 0:
            return (
                f"Do NOT ship the variant. It performed {size_pp:.2f} pp {direction} than the "
                f"control, and that gap is statistically significant "
                f"(p {format_p_value(p_value)}). "
                f"The true difference is most likely between {ci_low * 100:+.2f} pp and "
                f"{ci_high * 100:+.2f} pp -- the whole range is negative, so the variant is "
                f"worse, not merely unproven."
            )
        return (
            f"Ship the variant, with the size caveat below. It performed {size_pp:.2f} pp "
            f"{direction} than the control (p {format_p_value(p_value)}), and the true "
            f"difference is "
            f"most likely between {ci_low * 100:+.2f} pp and {ci_high * 100:+.2f} pp. Check "
            f"that the LOWER end of that range is still worth the cost of shipping."
        )

    # Not significant. The useful question becomes: was the test big enough to have found
    # something worth finding?
    if mde > 0 and abs(diff) < mde:
        return (
            f"Inconclusive -- do not ship on this evidence. The observed gap of "
            f"{size_pp:.2f} pp is not distinguishable from noise "
            f"(p {format_p_value(p_value)}), and the "
            f"95% interval, {ci_low * 100:+.2f} pp to {ci_high * 100:+.2f} pp, contains zero. "
            f"Note this test could only reliably detect a difference of {mde * 100:.2f} pp or "
            f"larger, so a real effect smaller than that would have been missed. This is "
            f"'we did not detect a difference', NOT 'there is no difference'."
        )
    return (
        f"Inconclusive -- do not ship on this evidence. The observed gap of {size_pp:.2f} pp "
        f"is not statistically significant (p {format_p_value(p_value)}) and the 95% interval, "
        f"{ci_low * 100:+.2f} pp to {ci_high * 100:+.2f} pp, contains zero."
    )


def _caveats(n_a: int, n_b: int, mde: float, abs_diff: float, significant: bool) -> tuple[str, ...]:
    """Caveats that apply to analysing someone else's published experiment."""
    items = [
        f"Sample size: {n_a:,} users in the control arm and {n_b:,} in the variant.",
        f"With these sample sizes the test can reliably detect a difference of "
        f"{mde * 100:.2f} pp or larger (80% power, alpha = 0.05). Smaller real effects would "
        f"probably be missed.",
        "We did not run this experiment. The randomisation, the ad-serving logic and the "
        "tracking are taken on trust from the published dataset.",
        "The experiment's intended PRIMARY metric is not documented, so the choice of metric "
        "here is ours, not the original team's.",
        "This is an intention-to-treat analysis: it splits on the random ASSIGNMENT, not on "
        "whether a user was actually shown an ad. Splitting on exposure would compare "
        "self-selected groups and destroy the randomisation.",
        "Two metrics are examined (site visit and conversion). Testing two outcomes doubles "
        "the chance of one looking significant by luck; a Bonferroni-corrected threshold would "
        "be alpha = 0.025 rather than 0.05. Both metrics are reported in full so neither can "
        "be cherry-picked after the fact.",
        "Each user is counted once and assumed independent. A person using two devices would "
        "appear as two users.",
        "This is a single fixed-horizon analysis. No sequential or peeking correction applies, "
        "because the data was analysed once, after collection ended.",
    ]
    if not significant and abs_diff < mde:
        items.append(
            "The observed difference is smaller than the minimum detectable effect, so this "
            "result cannot distinguish 'no effect' from 'an effect too small for this sample'."
        )
    return tuple(items)
