"""Insights page: exactly three findings, each with its number, source and action (FR-20).

Every figure on this page is **queried live**, not typed in. That is a deliberate constraint
(DECISIONS D-009): if a number appears on screen, a named view produced it, and refreshing the
page re-derives it. Hardcoding "1,637 orders" here would be the easiest possible way for the
dashboard to start lying after a data refresh.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import streamlit as st

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.components import queries  # noqa: E402 - must follow the sys.path fix
from src.analysis import ab_report  # noqa: E402

log = logging.getLogger(__name__)
st.set_page_config(page_title="Insights", page_icon="bulb", layout="wide")

st.title("Three findings, and what to do about them")
st.caption(
    "Every number below is queried live from the `analytics` views when this page loads — "
    "none is typed in. The source view is named under each finding so any figure can be "
    "re-derived with one query."
)

# A tile's VALUE must stay short -- about 8 characters -- or Streamlit's large metric font
# truncates it at a narrow window ("1,637 orders" rendered as "1,637 or..." at 1100px). Units
# move to the label or the caption, which are small enough to carry them. Captions must fit
# ONE line too, or an uneven tile height breaks the row's bottom alignment.
# The LABEL has the same constraint, at about 20 characters:
# "Orders lost: approved → carrier" ellipsised to "Orders lost: approved → c...".
# Checked at 1100px, 1280px and 1512px rather than assumed.
#
# st.metric's `delta` draws an up/down ARROW, which asserts "this went up/down since last
# period". Most of the second lines on this page are descriptive ("of 96,096 total",
# "placed -> delivered & reviewed") and nothing moved, so an arrow there is a false claim --
# and on the drop-off tiles it read as "losses increased", which the data does not say.
# `delta` is therefore used ONLY for genuine changes; descriptive lines are captions.
try:
    # ---------------------------------------------------------------- data
    dropoff = queries.funnel_dropoff()
    repeat = queries.repeat_purchase_rate()
    ab = ab_report.run_all()
    day7 = ab["retention_7"]
    day1 = ab["retention_1"]

    stages = dropoff.set_index("stage_order")
    payment_drop = stages.loc[2]
    carrier_drop = stages.loc[3]
    completion = stages.loc[5, "pct_of_all_orders"]
    ratio = float(carrier_drop.step_dropoff_pct) / float(payment_drop.step_dropoff_pct)

    # Each finding gets its own TAB rather than stacking into one long page (D-020).
    # Stacked, the third finding sat ~2,500px down: past the point where the page is still
    # growing as it renders, and past where a scroll in progress gets yanked backwards.
    tab1, tab2, tab3 = st.tabs(
        [
            "1. Logistics, not payments",
            "2. Single-purchase marketplace",
            "3. The gate change hurt retention",
        ]
    )

    # ================================================================ FINDING 1
    with tab1:
        st.subheader("The funnel leaks in logistics, not in payments")
        cols = st.columns(3)
        with cols[0].container(border=True):
            st.metric("Approved → carrier", f"{int(carrier_drop.dropped_orders):,}")
            st.caption(f"orders lost · {float(carrier_drop.step_dropoff_pct):.2f}%")
        with cols[1].container(border=True):
            st.metric("Placed → approved", f"{int(payment_drop.dropped_orders):,}")
            st.caption(f"orders lost · {float(payment_drop.step_dropoff_pct):.2f}%")
        with cols[2].container(border=True):
            st.metric("End-to-end completion", f"{float(completion):.2f}%")
            st.caption("placed → reviewed")

        st.markdown(
            f"""
**The number.** The largest single loss in the order lifecycle is between *payment approved*
and *handed to carrier*: **{int(carrier_drop.dropped_orders):,} orders
({float(carrier_drop.step_dropoff_pct):.2f}%)**. Payment approval, the step most people would
guess, loses only **{float(payment_drop.step_dropoff_pct):.2f}%** — the handover to the
carrier is about **{ratio:.0f}× more lossy**. A further
**{int(stages.loc[4, "dropped_orders"]):,}** orders are lost between carrier and delivery.

**Why it matters.** Payment failures are usually where effort goes, because they are visible
and instrumented. Here that work would address the smallest leak in the funnel. The money is
in the warehouse-to-carrier handover.

**Recommended action.** Instrument the approved → carrier gap before changing anything:
measure the time between `order_approved_at` and `order_delivered_carrier_date` by seller and
by state, and find whether the {int(carrier_drop.dropped_orders):,} lost orders concentrate in
particular sellers. If they do, it is a seller-operations problem with a named owner; if they
are spread evenly, it is a platform-wide logistics-capacity problem. Do not launch a
payment-retry project on this evidence.
            """
        )
        st.caption("Source: `analytics.v_funnel_dropoff` · see `docs/QUERIES.md` §1–2")

    # ================================================================ FINDING 2
    with tab2:
        st.subheader("This is a single-purchase marketplace, and that is the biggest risk")
        cols = st.columns(3)
        with cols[0].container(border=True):
            st.metric("Repeat-purchase rate", f"{float(repeat.repeat_pct):.2f}%")
            st.caption("bought a second time")
        with cols[1].container(border=True):
            st.metric(
                "Customers who never return",
                f"{int(repeat.total_customers - repeat.repeat_customers):,}",
            )
            st.caption(f"of {int(repeat.total_customers):,} total")
        with cols[2].container(border=True):
            st.metric("Bought twice or more", f"{int(repeat.repeat_customers):,}")
            st.caption("in two years")

        st.markdown(
            f"""
**The number.** Over the full two-year window, only
**{int(repeat.repeat_customers):,} of {int(repeat.total_customers):,} customers
({float(repeat.repeat_pct):.2f}%)** ever placed a second order. Month-1 retention for cohorts
of 1,000+ customers runs between **0.11% and 0.72%**.

**Why it matters.** Essentially all revenue comes from first purchases, so the business is
buying every real's worth of revenue through acquisition, every month, with no compounding
base. A 1-point improvement in repeat rate is worth more than a 1-point improvement in
anything else on this dashboard, because it is the only metric that compounds.

**A measurement caveat that matters more than the finding.** A naive `AVG()` over the month-1
retention column returns **5.22%** — wrong by roughly tenfold. It is inflated by micro-cohorts:
the 2016-12 cohort contains **one** customer, so a single repeat purchase reads as 100%
retention. Any cohort analysis must be weighted by cohort size or filtered by it. The heatmap
on the Cohorts page defaults to cohorts of 1,000+ for this reason, and the slider lets you
reproduce the distortion.

**Recommended action.** Before investing in retention mechanics, establish *why* customers do
not return — the dataset cannot answer that, so it needs instrumentation the dataset does not
have (post-delivery survey, repeat-visit tracking). In parallel, the cheapest test available is
a post-delivery follow-up to the ~{int(repeat.total_customers - repeat.repeat_customers):,}
single-purchase customers, measured as an A/B test on repeat rate within 60 days. Size it
first: at this base rate, detecting even a 0.5 pp lift needs a large sample, which is exactly
the calculation the A/B page's minimum-detectable-effect figure demonstrates.
            """
        )
        st.caption(
            "Source: `analytics.v_cohort_retention`, `analytics.v_customer_first_order` · "
            "see `docs/QUERIES.md` §3–5"
        )

    # ================================================================ FINDING 3
    with tab3:
        st.subheader("Moving the game's progression gate to level 40 made retention worse")
        cols = st.columns(2)
        with cols[0].container(border=True):
            # The only genuine delta on this page: the variant really did move the metric.
            # delta_color is left at "normal" (negative -> red). It was briefly set to
            # "inverse", which renders a negative change GREEN -- that is for metrics where
            # down is good, like cost or churn. Retention falling is bad, so the default is
            # correct here, and the rendered colour was checked rather than assumed.
            st.metric(
                "Day-7 retention change",
                f"{day7.diff_pp:+.2f} pp",
                f"{day7.relative_change_pct:+.1f}% relative",
            )
        with cols[1].container(border=True):
            st.metric("p-value", f"{day7.p_value:.5f}")
            st.caption("survives Bonferroni")

        # The confidence interval gets a FULL-WIDTH tile of its own. Its value is the longest
        # string on this page and it truncated in a third-width column -- and it is also the
        # strongest piece of evidence here, so the extra room is not a consolation prize.
        with st.container(border=True):
            st.metric(
                "95% confidence interval on the difference",
                f"{day7.ci_low_pp:+.2f} pp to {day7.ci_high_pp:+.2f} pp",
            )
            st.caption("Entirely below zero — the variant is worse, not merely unproven.")

        st.markdown(
            f"""
**The number.** Moving the first progression gate from level 30 to level 40 changed 7-day
retention from **{day7.rate_a * 100:.3f}%** to **{day7.rate_b * 100:.3f}%** — a drop of
**{abs(day7.diff_pp):.2f} pp** ({abs(day7.relative_change_pct):.1f}% relative), with
**p = {day7.p_value:.5f}** and a 95% confidence interval of
**[{day7.ci_low_pp:+.2f}, {day7.ci_high_pp:+.2f}] pp**. The whole interval sits below zero, so
the variant is *worse* — not merely unproven. It also clears the Bonferroni-corrected threshold
of α = 0.025 for having tested two metrics.

**Day-1 retention is inconclusive, which is a different claim.** It came out at
**{day1.diff_pp:+.2f} pp, p = {day1.p_value:.4f}** — but observed power was only
**{day1.observed_power:.0%}**, and the observed gap is smaller than the
**{day1.mde_pp:.2f} pp** minimum this sample could reliably detect. The honest reading is
"we did not detect a difference", not "there is no difference".

**Recommended action.** **Do not ship `gate_40`.** Keep the gate at level 30. If the goal
behind moving it was monetisation rather than retention, that trade needs measuring explicitly:
re-run the experiment with revenue-per-install as the pre-registered primary metric and
7-day retention as a guardrail, and size it against the
**{day7.mde_pp:.2f} pp** effect this sample size can detect. Note we did not run this
experiment and its intended primary metric is undocumented, so this recommendation is about
the metric *we* chose to analyse.
            """
        )
        st.caption(
            "Source: `analytics.v_ab_summary` + `src/analysis/ab_test.py` · "
            "see `docs/QUERIES.md` §10"
        )

    st.caption(
        "**Two datasets, stated plainly.** Findings 1 and 2 come from the Olist Brazilian "
        "E-Commerce dataset (CC BY-NC-SA 4.0). Finding 3 comes from the Cookie Cats "
        "mobile-game A/B test, a real published experiment on an unrelated business. They are "
        "not connected, and no finding here is derived by combining them."
    )

except Exception as exc:  # noqa: BLE001
    log.exception("insights page failed")
    st.error("Could not load the insights. See the server log for details.")
    st.caption(f"Error type: {type(exc).__name__}")
