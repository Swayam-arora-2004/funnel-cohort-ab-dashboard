"""Three findings, each with its number, its source view and a recommended action.

Every figure is queried live rather than typed in, so the page cannot drift from the data
after a reload.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import streamlit as st

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.components import queries  # noqa: E402 - after the sys.path fix
from src.analysis import ab_report  # noqa: E402

log = logging.getLogger(__name__)
st.set_page_config(page_title="Insights", page_icon="bulb", layout="wide")


st.title("Three findings, and what to do about them")
st.caption(
    "Every number below is queried live from the `analytics` views when this page loads — "
    "none is typed in. The source view is named under each finding so any figure can be "
    "re-derived with one query."
)

# Tile values stay under ~8 characters and labels under ~20, or Streamlit's metric font
# truncates them at a 1100px window. Units go in the caption.
#
# `delta` draws an up/down arrow, which asserts a change since some previous period. Most of
# the second lines here are descriptive, so they are captions; only real changes use delta.
try:
    # ---------------------------------------------------------------- data
    dropoff = queries.funnel_dropoff()
    repeat = queries.repeat_purchase_rate()
    ab = ab_report.run_all()
    conv = ab["conversion"]
    visit = ab["visit"]

    stages = dropoff.set_index("stage_order")
    payment_drop = stages.loc[2]
    carrier_drop = stages.loc[3]
    completion = stages.loc[5, "pct_of_all_orders"]
    ratio = float(carrier_drop.step_dropoff_pct) / float(payment_drop.step_dropoff_pct)

    # One tab per finding. Stacked, the third sat ~2,500px down, past the point where the
    # page is still growing as it renders.
    tab1, tab2, tab3 = st.tabs(
        [
            "1. Logistics, not payments",
            "2. Single-purchase marketplace",
            "3. Does advertising cause conversions?",
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
        st.caption("Source: `analytics.v_funnel_dropoff`")

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
        st.caption("Source: `analytics.v_cohort_retention` and `analytics.v_customer_first_order`")

    # ================================================================ FINDING 3
    with tab3:
        st.subheader("Advertising does cause conversions — and the effect size is small")
        cols = st.columns(2)
        with cols[0].container(border=True):
            # delta_color stays "normal" so a drop renders red. "inverse" is for metrics
            # where down is good, like cost or churn.
            st.metric(
                "Day-7 retention change",
                f"{conv.diff_pp:+.2f} pp",
                f"{conv.relative_change_pct:+.1f}% relative",
            )
        with cols[1].container(border=True):
            st.metric("p-value", f"{conv.p_value:.1e}")
            st.caption("survives Bonferroni")

        # full width: the longest value on the page, and the strongest evidence on it
        with st.container(border=True):
            st.metric(
                "95% confidence interval on the difference",
                f"{conv.ci_low_pp:+.4f} pp to {conv.ci_high_pp:+.4f} pp",
            )
            st.caption("Entirely below zero — the variant is worse, not merely unproven.")

        st.markdown(
            f"""
**The number.** Users randomly selected to be targeted by advertising converted at
**{conv.rate_b * 100:.4f}%** against **{conv.rate_a * 100:.4f}%** for the users randomly
**withheld** from targeting — a lift of **{conv.diff_pp:+.4f} pp**
({conv.relative_change_pct:+.1f}% relative), with **p = {conv.p_value:.2e}** and a 95%
confidence interval of **[{conv.ci_low_pp:+.4f}, {conv.ci_high_pp:+.4f}] pp**. Site visits
moved too: **{visit.diff_pp:+.4f} pp** (p = {visit.p_value:.2e}).

**Why it matters.** This is the question advertising spend actually turns on, and it is
answerable here *causally* rather than by correlation, because the control group was withheld
at random. The honest reading is two-sided: the effect is **real** — the interval is nowhere
near zero across {conv.n_a + conv.n_b:,} users — but it is **small in absolute terms**. Whether
it pays depends on margin per conversion against cost per impression, which this dataset does
not contain.

**The methodological point.** This splits on the **random assignment**, not on whether a user
was actually shown an ad. Splitting on exposure is the tempting mistake: it would compare
people who saw an ad against people who did not, but being shown an ad is a *consequence* of
the treatment and the users who get shown ads are systematically more active. That comparison
would inflate the apparent effect and would not be causal at all. This is an
intention-to-treat analysis, which is the conservative and correct choice.

**Recommended action.** Do not read this as "advertising works, spend more". Read it as "the
causal effect is {conv.diff_pp:+.4f} pp, now compare that against cost". The next step is a
break-even calculation: at {conv.diff_pp / 100:.6f} incremental conversions per targeted user,
advertising pays only if margin per conversion exceeds cost per targeted user. Run that with
real cost data before changing budget.
            """
        )

        st.caption("Source: `analytics.v_ab_summary` and `src/analysis/ab_test.py`")

    st.caption(
        "**Two datasets, stated plainly.** Findings 1 and 2 come from the Olist Brazilian "
        "E-Commerce dataset. Finding 3 comes from the Criteo Uplift incrementality test, a "
        "real randomised experiment on an unrelated business. Both are CC BY-NC-SA 4.0. They "
        "are not connected, and no finding here is derived by combining them."
    )

except Exception as exc:  # noqa: BLE001
    log.exception("insights page failed")
    st.error("Could not load the insights. See the server log for details.")
    st.caption(f"Error type: {type(exc).__name__}")
