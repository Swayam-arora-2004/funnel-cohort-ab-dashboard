"""What each source CSV must contain and how it must be typed.

Declarative and separate from the loader, so the validation rules can be reviewed without
reading loader logic and a test can check them without a database. Columns in drop_columns
are removed before anything is written.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CsvContract:
    """One source CSV and its destination table."""

    filename: str
    table: str
    # dtypes for the columns we keep; dates need parse_dates, not a dtype
    dtypes: dict[str, str]
    date_columns: tuple[str, ...] = ()
    # dropped for privacy, or because nothing needs them
    drop_columns: tuple[str, ...] = ()
    # Rename source -> destination, where the source CSV has a typo or an awkward name.
    rename: dict[str, str] = field(default_factory=dict)
    # Columns the destination table generates itself (e.g. a bigserial surrogate key).
    generated_columns: tuple[str, ...] = ()
    # read only the contract's columns; on the 14M-row source this saves several GB
    read_only_contract_columns: bool = False
    # violations are counted and reported, never silently dropped
    non_negative: tuple[str, ...] = ()
    expected_min_rows: int = 1


# Olist files live in data/raw/olist/ and the experiment in data/raw/criteo/ -- each dataset in
# its own directory so it is always obvious which file came from which source.
CSV_CONTRACTS: tuple[CsvContract, ...] = (
    CsvContract(
        filename="olist/olist_customers_dataset.csv",
        table="raw.customers",
        dtypes={
            "customer_id": "string",
            "customer_unique_id": "string",
            "customer_zip_code_prefix": "string",
            "customer_city": "string",
            "customer_state": "string",
        },
        expected_min_rows=99_000,
    ),
    CsvContract(
        filename="olist/olist_orders_dataset.csv",
        table="raw.orders",
        dtypes={
            "order_id": "string",
            "customer_id": "string",
            "order_status": "string",
        },
        # the funnel: a NULL means the order never reached that stage
        date_columns=(
            "order_purchase_timestamp",
            "order_approved_at",
            "order_delivered_carrier_date",
            "order_delivered_customer_date",
            "order_estimated_delivery_date",
        ),
        expected_min_rows=99_000,
    ),
    CsvContract(
        filename="olist/olist_order_items_dataset.csv",
        table="raw.order_items",
        dtypes={
            "order_id": "string",
            "order_item_id": "int64",
            "product_id": "string",
            "seller_id": "string",
            "price": "float64",
            "freight_value": "float64",
        },
        date_columns=("shipping_limit_date",),
        non_negative=("price", "freight_value"),
        expected_min_rows=110_000,
    ),
    CsvContract(
        filename="olist/olist_order_payments_dataset.csv",
        table="raw.order_payments",
        dtypes={
            "order_id": "string",
            "payment_sequential": "int64",
            "payment_type": "string",
            "payment_installments": "int64",
            "payment_value": "float64",
        },
        non_negative=("payment_value",),
        expected_min_rows=100_000,
    ),
    CsvContract(
        filename="olist/olist_order_reviews_dataset.csv",
        table="raw.order_reviews",
        dtypes={
            "review_id": "string",
            "order_id": "string",
            "review_score": "int64",
        },
        date_columns=("review_creation_date", "review_answer_timestamp"),
        # free text, may contain customer names -- never written to the database
        drop_columns=("review_comment_title", "review_comment_message"),
        # review_pk is a bigserial; review_id is not unique in this CSV
        generated_columns=("review_pk",),
        expected_min_rows=99_000,
    ),
    CsvContract(
        filename="olist/olist_products_dataset.csv",
        table="raw.products",
        dtypes={
            "product_id": "string",
            "product_category_name": "string",
            # blanks make pandas read these as float ("225.0"), so they are declared as
            # nullable Int64 and converted after reading
            "product_weight_g": "Int64",
            "product_length_cm": "Int64",
            "product_height_cm": "Int64",
            "product_width_cm": "Int64",
        },
        # Not needed by any numbered requirement.
        drop_columns=(
            "product_name_lenght",  # the source CSV really does misspell "length"
            "product_description_lenght",
            "product_photos_qty",
        ),
        expected_min_rows=32_000,
    ),
    CsvContract(
        filename="criteo/criteo-research-uplift-v2.1.csv.gz",
        table="raw.ab_criteo_uplift",
        dtypes={
            # the assignment, the two outcomes, then exposure. Written as 0/1, not TRUE/FALSE.
            "treatment": "boolean",
            "visit": "boolean",
            "conversion": "boolean",
            "exposure": "boolean",
        },
        # the 11 anonymised features f0..f11 are unused and would cost GB at this row count
        read_only_contract_columns=True,
        expected_min_rows=13_900_000,
    ),
)

# Files and columns present in the downloads that we deliberately do NOT load, with the
# reason. Listed here so a reader can see each omission is a decision, not an oversight.
INTENTIONALLY_NOT_LOADED: dict[str, str] = {
    "criteo columns f0..f11": (
        "11 anonymised features; no requirement needs them, and at 25M rows "
        "they would cost gigabytes for nothing (FR-4)"
    ),
    "olist/olist_geolocation_dataset.csv": "precise lat/long, personal-data risk, unused (SEC-6)",
    "olist/olist_sellers_dataset.csv": "no numbered requirement needs seller attributes",
    "olist/product_category_name_translation.csv": (
        "category names are shown in the source language"
    ),
}
