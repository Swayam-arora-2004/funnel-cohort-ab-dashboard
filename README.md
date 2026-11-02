# Funnel, Cohort & A/B Analysis Dashboard

PostgreSQL + SQL + Python + Streamlit. Two real public datasets, twelve documented SQL views,
a statistically honest A/B readout, and a four-page dashboard.

**Every number below was produced by a query or script in this repo and is re-checked by a
test.** `tests/test_documented_numbers.py` re-derives all 56 published figures from the
database and fails if any of them stops matching.

![Funnel and KPIs](screenshots/01-home-funnel.png)

---

## What it answers

| Question | Where | Dataset |
|---|---|---|
| Where do orders drop out of the fulfilment pipeline? | Home → Fulfilment funnel | Olist |
| Do customers come back, and for how long? | Cohorts | Olist |
| Is revenue growth accelerating? | Home → Revenue over time | Olist |
| Did the experiment's change work? | A/B Test | Cookie Cats |
| So what should we actually do? | Insights | both |

---

## Measured results

### The funnel leaks in logistics, not in payments

| # | Stage | Orders | Lost here | Step conversion |
|---|---|---|---|---|
| 1 | Order placed | 99,441 | — | — |
| 2 | Payment approved | 99,281 | 160 | 99.84% |
| 3 | Handed to carrier | 97,644 | **1,637** | **98.35%** |
| 4 | Delivered | 96,461 | 1,183 | 98.79% |
| 5 | Delivered & reviewed | 95,815 | 646 | 99.33% |

The biggest single loss is **payment approved → handed to carrier: 1,637 orders (1.65%)** —
roughly **10×** the payment-approval failure rate of 0.16%. End to end, **96.35%** of placed
orders complete the journey. *(`analytics.v_funnel_dropoff`)*

### It is a single-purchase marketplace

**2,997 of 96,096 customers (3.12%)** ever placed a second order. Month-1 retention for
cohorts of 1,000+ customers runs **0.11%–0.72%**. Total merchandise revenue
**R$ 13,496,408.43** across **98,205** orders, **AOV R$ 137.43**.
*(`analytics.v_cohort_retention`, `v_repeat_purchase_summary`, `v_revenue_by_month`)*

### The A/B test says do not ship

| | Day-1 retention | Day-7 retention |
|---|---|---|
| `gate_30` (control) | 44.819% | 19.020% |
| `gate_40` (variant) | 44.228% | 18.200% |
| Difference | −0.591 pp | **−0.820 pp** |
| p-value | 0.074410 | **0.001554** |
| 95% CI on the difference | [−1.239, **+0.058**] pp | [−1.328, **−0.312**] pp |
| Min detectable effect (80% power) | 0.927 pp | 0.726 pp |
| Observed power | **43.0%** | 88.6% |

**Do not ship `gate_40`.** Day-7 retention is 0.82 pp worse, the whole 95% interval sits below
zero, and the result survives Bonferroni correction for having tested two metrics
(0.00155 < 0.025).

**Day-1 is inconclusive, which is a different claim.** Observed power was only 43% — this test
would have missed a real effect of that size more often than it found one — and the observed
gap (0.59 pp) is smaller than the 0.93 pp minimum the sample could reliably detect. The honest
reading is *"we did not detect a difference"*, not *"there is no difference"*.
*(`python -m src.analysis.ab_report`)*

![A/B readout](screenshots/03-ab-test.png)

---

## Architecture

```mermaid
flowchart TD
    A1["Olist e-commerce CSVs<br/>CC BY-NC-SA 4.0"] --> B["data/raw/ (git-ignored)"]
    A2["Cookie Cats A/B CSV<br/>real published experiment"] --> B
    B --> C["src/load/load_raw.py<br/>contracts + chunked COPY, idempotent"]
    C --> D[("PostgreSQL 16 · schema raw<br/>7 typed tables, 8 commented indexes")]
    D --> E["schema analytics · 12 views<br/>CTEs + window functions"]
    E --> F["src/analysis/ab_test.py<br/>PURE: z-test, CI, MDE, power"]
    E --> G["Streamlit + Plotly<br/>connects as dashboard_ro"]
    F --> G
    E --> H["src/export/export_views.py<br/>→ exports/*.csv"]
    H --> I["Tableau Public<br/>docs/BI_HANDOFF.md"]
```

**Business logic lives in SQL, not Python.** The dashboard, the CSV exports and this README all
read the same `analytics` views, so a metric has exactly one definition and they cannot
disagree. Python does only what SQL cannot: the statistical test.

**The dashboard connects as `dashboard_ro`** — `SELECT` on `analytics`, and *no privileges at
all* on `raw`. A view runs with its owner's privileges, so it reads `raw` on the caller's
behalf while the app cannot touch `raw` directly. This is asserted by tests, and it caught a
real mistake during development (see `ai-context/DECISIONS.md` D-018).

---

## Run it

Needs Docker, Python 3.11 and a Kaggle API token (`~/.kaggle/kaggle.json`).

```bash
git clone <this repo> && cd funnel-cohort-ab-dashboard
cp .env.example .env            # then set a password for each CHANGE_ME
                                # generate with: openssl rand -base64 24

python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt

# Download the data (42 MB) -- see docs/DATA.md for licences
mkdir -p data/raw/olist data/raw/cookie_cats
kaggle datasets download -d olistbr/brazilian-ecommerce       -p data/raw/olist        --unzip
kaggle datasets download -d yufengsui/mobile-games-ab-testing -p data/raw/cookie_cats  --unzip

make db-up db-init              # PostgreSQL 16 + schemas + roles + tables + indexes
make load                       # 637,782 rows in 5.6s
make views                      # 12 analytics views
make test                       # 105 tests
make app                        # http://localhost:8501
```

Other commands: `make export` (CSVs for Tableau), `make lint`, `make security`,
`make psql`, `make db-down`.

---

## The data

| | Olist Brazilian E-Commerce | Cookie Cats A/B test |
|---|---|---|
| Used for | funnel, cohorts, revenue | the experiment |
| Licence | **CC BY-NC-SA 4.0** (attribution required, non-commercial) | **not specified** — see below |
| Size | 99,441 orders, 2016-09 to 2018-10 | 90,189 randomised players |

Credit to **Olist** for publishing the e-commerce dataset.

> **Licence caveat, stated rather than papered over.** Kaggle reports **no licence** for the
> Cookie Cats dataset. It is a genuine published experiment and this is non-commercial
> portfolio use with attribution, but this project does **not** claim a specific licence for
> it, because none was verifiable. An earlier draft recorded it as CC0; that was an unverified
> assumption and was corrected (`ai-context/DECISIONS.md` D-011a).

**This is a fulfilment funnel, not an acquisition funnel.** Olist publishes no clickstream
data, so "visit → signup → cart → purchase" is not derivable from it and inventing those stages
would be fabricating results. The five stages are real order-lifecycle timestamps (D-006).

---

## Things this project got wrong, and fixed

Kept because the fixes are the interesting part. Full write-ups in `ai-context/DECISIONS.md`.

| What | Why it mattered |
|---|---|
| **The funnel reported a negative drop-off** | Stages were defined independently, so "has a review" counted 98,673 against 96,476 delivered. Olist sends its review survey at *order* time, so 2,843 undelivered orders had reviews. Stages are now cumulative. (D-013) |
| **Month-over-month growth read +1,101,719%** | 2016-12 contains a single R$10.90 order. Sparse edge months are now flagged and excluded from growth maths — flagged, not deleted, so totals still reconcile. (D-014) |
| **`pip-audit` found 56 CVEs in a fully pinned file** | Pinning guarantees reproducibility, not safety — the pins were stale. The worst offender, `pillow`, was never in `requirements.txt`; it arrived via `streamlit`. CI now audits the full transitive lock file. (D-012) |
| **The dashboard crashed with "permission denied for schema raw"** | A query reached into `raw` from the app. The fix was a new view, not a wider grant — the error was business logic in the wrong layer. (D-018) |
| **A CSV formula-injection guard that did nothing** | It tested `dtype == object`, correct on pandas 2.x. On pandas 3.x text columns are `str`, so the guard silently no-op'd. A security guard with no test is a guard you only think you have. (`tests/test_export.py`) |
| **Numbers truncated to "R$ 13…" at a 1280px window** | Built and screenshotted at 1500px. A truncated number is a wrong number. Layouts are now checked at 1100/1280/1440. (D-019) |

---

## Security

Full requirements in `docs/SRS.md` (SEC-1 … SEC-13), with a threat model mapped to the OWASP
Top 10. In short:

- **Two database roles.** `loader_rw` writes to `raw`; `dashboard_ro` has `SELECT` on
  `analytics` only and no rights on `raw`. Asserted by tests.
- **Parameterised SQL only.** `fetch_df` refuses a plain `str` and requires a
  `sqlalchemy.text()` object — the type system does the enforcing.
- **No secrets in git.** `.gitignore` was written *before* `git init`. CI runs gitleaks over
  the full history.
- **No personal data.** Free-text review columns and the geolocation table are never loaded;
  exports are aggregates only, with an identifier guard that fails the export rather than
  publishing one.
- **CI gates:** `ruff`, `bandit`, `pip-audit` (on the transitive lock file), `gitleaks`,
  `pytest`. A milestone is not done until all five pass.

---

## Repo map

```
ai-context/   ARCHITECTURE.md · DECISIONS.md (22 entries) · PROGRESS.md
docs/         SRS.md · TECH_SPECS.md · DATA.md · QUERIES.md · BI_HANDOFF.md
sql/ddl/      schemas, least-privilege roles, typed tables, commented indexes
sql/views/    12 views, each with a COMMENT ON VIEW stating its business question
src/          config · db · load · analysis · export
app/          Streamlit: Home, Cohorts, A/B Test, Insights
tests/        105 tests
```

Start with `docs/QUERIES.md` — it has every view's business question, its measured output, and
the bug each one caught.
