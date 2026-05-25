"""Tests for refund netting in apply_refunds.py.

Covers:
- The pure function ``apply_refunds_to_df``
- Idempotence guarantee (re-running same spec produces same dataset)
- Sign preservation (refunds stay negative in the same category as the purchase)
- Audit trail (Original Category tag survives re-run)
- Empty-spec edge case
"""

from __future__ import annotations

import pandas as pd
import pytest

from apply_refunds import (
    REFUND_TAG_REGEX,
    apply_refunds_to_df,
    build_refund_rows,
    drop_existing_refunds,
)


@pytest.fixture
def base_ledger() -> pd.DataFrame:
    return pd.DataFrame([
        {"Date": "07/05/2025", "Source": "Mike AppleCard",
         "Description": "SUMMER CAMP REGISTRATION", "Category": "Kids",
         "Subcategory": "Camps", "Amount": 1400.00,
         "Original Category": "Apple Card / Kids"},
        {"Date": "08/02/2025", "Source": "Mike Chase",
         "Description": "DELTA AIR LINES", "Category": "Travel",
         "Subcategory": "Airlines", "Amount": 612.00,
         "Original Category": "Chase / Travel"},
    ])


@pytest.fixture
def refund_spec() -> dict:
    return {
        "refunds": [
            {
                "date": "07/20/2025",
                "source": "Mike AppleCard",
                "description": "SUMMER CAMP REFUND (PARTIAL)",
                "category": "Kids",
                "subcategory": "Camps",
                "amount": -140.00,
                "original_category": "Apple Card / RETURN",
            },
        ],
    }


# ---------------------------------------------------------------------------

def test_appends_refund_row(base_ledger: pd.DataFrame, refund_spec: dict):
    result = apply_refunds_to_df(base_ledger, refund_spec)
    assert len(result) == 3
    refund_rows = result[result["Original Category"].str.contains("RETURN", na=False)]
    assert len(refund_rows) == 1
    assert refund_rows.iloc[0]["Amount"] == -140.00


def test_idempotent(base_ledger: pd.DataFrame, refund_spec: dict):
    """Re-running the same spec must not produce duplicate refund rows."""
    once = apply_refunds_to_df(base_ledger, refund_spec)
    twice = apply_refunds_to_df(once, refund_spec)
    assert len(once) == len(twice)
    assert once["Amount"].sum() == twice["Amount"].sum()


def test_refunds_in_same_category_as_purchase(
    base_ledger: pd.DataFrame, refund_spec: dict
):
    result = apply_refunds_to_df(base_ledger, refund_spec)
    refund = result[result["Original Category"].str.contains("RETURN", na=False)].iloc[0]
    purchase = result[result["Description"] == "SUMMER CAMP REGISTRATION"].iloc[0]
    assert refund["Category"] == purchase["Category"]
    assert refund["Subcategory"] == purchase["Subcategory"]


def test_refund_amount_remains_negative(base_ledger: pd.DataFrame, refund_spec: dict):
    """Refunds are stored as NEGATIVE amounts so naive sums net them out."""
    result = apply_refunds_to_df(base_ledger, refund_spec)
    # Original $1400 camp + $-140 refund = $1260 net for the Kids/Camps subcat
    kids_total = result[
        (result["Category"] == "Kids") & (result["Subcategory"] == "Camps")
    ]["Amount"].sum()
    assert kids_total == 1260.00


def test_empty_spec_returns_unchanged(base_ledger: pd.DataFrame):
    result = apply_refunds_to_df(base_ledger, {"refunds": []})
    pd.testing.assert_frame_equal(
        result.reset_index(drop=True), base_ledger.reset_index(drop=True),
    )


def test_missing_refunds_key_returns_unchanged(base_ledger: pd.DataFrame):
    """Spec without a top-level 'refunds' key shouldn't crash."""
    result = apply_refunds_to_df(base_ledger, {})
    pd.testing.assert_frame_equal(
        result.reset_index(drop=True), base_ledger.reset_index(drop=True),
    )


def test_drop_existing_refunds_pure_function(base_ledger: pd.DataFrame):
    # Add an existing refund row
    seeded = pd.concat([base_ledger, pd.DataFrame([{
        "Date": "07/20/2025", "Source": "Mike AppleCard",
        "Description": "PRE-EXISTING REFUND", "Category": "Kids",
        "Subcategory": "Camps", "Amount": -50.00,
        "Original Category": "Apple Card / REFUND",
    }])], ignore_index=True)

    trimmed, removed = drop_existing_refunds(seeded)
    assert removed == 1
    assert len(trimmed) == 2
    assert "PRE-EXISTING REFUND" not in set(trimmed["Description"])


def test_default_original_category(base_ledger: pd.DataFrame):
    """When the spec omits original_category, default uses '{source} / REFUND'."""
    spec = {"refunds": [{
        "date": "08/20/2025",
        "source": "Mike Chase",
        "description": "FLIGHT REFUND",
        "category": "Travel",
        "subcategory": "Airlines",
        "amount": -612.00,
    }]}
    result = apply_refunds_to_df(base_ledger, spec)
    refund = result[result["Description"] == "FLIGHT REFUND"].iloc[0]
    assert refund["Original Category"] == "Mike Chase / REFUND"


def test_refund_tag_regex_recognizes_variants():
    """The tag-matching regex must catch all three flavors of refund marker."""
    samples = ["Apple Card / REFUND", "Chase / RETURN", "AmEx / CREDIT REVERSAL"]
    import re
    for s in samples:
        assert re.search(REFUND_TAG_REGEX, s, flags=re.IGNORECASE)


def test_build_refund_rows_preserves_all_fields(refund_spec: dict):
    rows = build_refund_rows(refund_spec)
    assert len(rows) == 1
    r = rows[0]
    expected_keys = {"Date", "Source", "Description", "Category", "Subcategory",
                     "Amount", "Original Category"}
    assert set(r.keys()) == expected_keys
    assert r["Amount"] == -140.00
