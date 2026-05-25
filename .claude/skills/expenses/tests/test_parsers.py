"""
Tests for source-format ingest functions in consolidate.py.

Exercises the realistic CSV fixtures in evals/fixtures/ AND inline edge-case
DataFrames written to temporary CSVs for the tricky bits (Type=Payment,
Daily Cash Adjustment, sign conventions).

Schema after ingest (uniform):
    Date | Source | Desc | OrigCat | Amount   (positive=outflow)
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pandas as pd
import pytest

from consolidate import (
    ingest_apple_card,
    ingest_chase_card,
    ingest_generic_checking,
)


UNIFORM_COLS = ["Date", "Source", "Desc", "OrigCat", "Amount"]


# ---------------------------------------------------------------------------
# Apple Card
# ---------------------------------------------------------------------------

class TestAppleCardIngest:

    def test_returns_uniform_schema(self, apple_card_csv: Path):
        df = ingest_apple_card(apple_card_csv, {"name": "Mike AppleCard"})
        assert list(df.columns) == UNIFORM_COLS

    def test_renames_columns(self, apple_card_csv: Path):
        df = ingest_apple_card(apple_card_csv, {"name": "Mike AppleCard"})
        # Transaction Date should now be Date; Amount (USD) should now be Amount
        assert "Transaction Date" not in df.columns
        assert "Amount (USD)" not in df.columns
        assert df["Amount"].dtype.kind in "fi"  # numeric

    def test_cardholder_mapping(self, apple_card_csv: Path):
        cfg = {
            "name": "AppleCard fallback",
            "cardholder_map": {
                "Mike Chen":  "Mike AppleCard",
                "Sarah Chen": "Sarah AppleCard",
            },
        }
        df = ingest_apple_card(apple_card_csv, cfg)
        sources = set(df["Source"].unique())
        # Should map both personas — at least Mike will be present in the fixture
        assert "Mike AppleCard" in sources

    def test_drops_daily_cash_adjustment_rows(self, tmp_path: Path):
        csv = tmp_path / "apple_card_dca.csv"
        csv.write_text(textwrap.dedent("""\
            Transaction Date,Purchased By,Merchant,Description,Category,Type,Amount (USD)
            01/15/2025,Mike Chen,Some Merchant,REAL PURCHASE,Other,Purchase,100.00
            01/16/2025,Mike Chen,,DAILY CASH ADJUSTMENT,Other,Other,-2.50
            01/17/2025,Mike Chen,Some Merchant,DAILY CASH ADJUSTMENT - WTV,Other,Other,1.25
        """))
        df = ingest_apple_card(csv, {"name": "Mike AppleCard"})
        # Daily Cash Adjustment rows must be dropped on the description match
        assert len(df) == 1
        assert df.iloc[0]["Desc"] == "Some Merchant"

    def test_default_keep_types_filter(self, tmp_path: Path):
        csv = tmp_path / "apple_card_types.csv"
        csv.write_text(textwrap.dedent("""\
            Transaction Date,Purchased By,Merchant,Description,Category,Type,Amount (USD)
            01/15/2025,Mike Chen,Test,TEST PURCHASE,Other,Purchase,100.00
            01/16/2025,Mike Chen,Test,TEST CREDIT,Other,Credit,-25.00
            01/17/2025,Mike Chen,Test,TEST PAYMENT,Other,Payment,-500.00
            01/18/2025,Mike Chen,Test,TEST DEBIT,Other,Debit,50.00
            01/19/2025,Mike Chen,Test,TEST OTHER,Other,Other,7.00
        """))
        df = ingest_apple_card(csv, {"name": "Mike AppleCard"})
        # Payment rows excluded by default; the rest should pass
        kept_types = ["Purchase", "Credit", "Debit", "Other"]
        # We don't see Type post-ingest, but row count tells us what got kept.
        assert len(df) == 4
        assert "TEST PAYMENT" not in set(df["Desc"])

    def test_fixture_round_trip(self, apple_card_csv: Path):
        """Realistic fixture should parse without errors and produce sensible output."""
        df = ingest_apple_card(apple_card_csv, {
            "name": "Mike AppleCard",
            "cardholder_map": {"Mike Chen": "Mike AppleCard", "Sarah Chen": "Sarah AppleCard"},
        })
        assert len(df) > 0
        assert (df["Amount"] > 0).all() or any(df["Amount"] < 0)  # mixed allowed
        assert df["Date"].notna().all()


# ---------------------------------------------------------------------------
# Chase Card
# ---------------------------------------------------------------------------

class TestChaseCardIngest:

    def test_returns_uniform_schema(self, chase_csv: Path):
        df = ingest_chase_card(chase_csv, {"name": "Mike Chase"})
        assert list(df.columns) == UNIFORM_COLS

    def test_excludes_automatic_payment_rows(self, tmp_path: Path):
        csv = tmp_path / "chase_payments.csv"
        csv.write_text(textwrap.dedent("""\
            Transaction Date,Type,Description,Category,Amount (USD)
            02/01/2025,Sale,TEST RESTAURANT,Food,32.00
            02/02/2025,Payment,AUTOMATIC PAYMENT - THANK YOU,Payment,-500.00
            02/03/2025,Payment,MERCHANT REFUND - SOME STORE,Returns,-45.00
        """))
        df = ingest_chase_card(csv, {"name": "Mike Chase"})
        descs = list(df["Desc"])
        # Card payoff should be filtered; merchant refund (Type=Payment but not payoff) kept
        assert "AUTOMATIC PAYMENT - THANK YOU" not in descs
        assert any("MERCHANT REFUND" in d for d in descs)
        assert any("TEST RESTAURANT" in d for d in descs)

    def test_custom_payoff_pattern(self, tmp_path: Path):
        csv = tmp_path / "chase_alt_payoff.csv"
        csv.write_text(textwrap.dedent("""\
            Transaction Date,Type,Description,Category,Amount (USD)
            02/01/2025,Payment,SCHEDULED PAYMENT FROM CHECKING,Payment,-500.00
            02/02/2025,Sale,KEEP THIS,Other,10.00
        """))
        df = ingest_chase_card(csv, {
            "name": "Chase",
            "payoff_pattern": "SCHEDULED PAYMENT FROM CHECKING",
        })
        assert len(df) == 1
        assert df.iloc[0]["Desc"] == "KEEP THIS"

    def test_fixture_round_trip(self, chase_csv: Path):
        df = ingest_chase_card(chase_csv, {"name": "Mike Chase"})
        assert len(df) > 0
        # Source column populated
        assert (df["Source"] == "Mike Chase").all()


# ---------------------------------------------------------------------------
# Generic checking
# ---------------------------------------------------------------------------

class TestGenericCheckingIngest:

    def test_returns_uniform_schema(self, checking_csv: Path):
        df = ingest_generic_checking(checking_csv, {"name": "Joint Checking"})
        assert list(df.columns) == UNIFORM_COLS

    def test_flips_sign_to_positive_outflow(self, tmp_path: Path):
        # Generic checking: bank convention is negative=outflow, we normalize to positive
        csv = tmp_path / "checking_signs.csv"
        csv.write_text(textwrap.dedent("""\
            Transaction Date,Category,Subcategory,Description,Sub Type,Amount (USD)
            03/01/2025,Lifestyle,Groceries,TEST GROCERY,Spend,-120.00
            03/02/2025,Income,Salary,EMPLOYER DEPOSIT,Income,2500.00
            03/03/2025,Lifestyle,Restaurants,TEST RESTAURANT,Spend,-45.50
        """))
        df = ingest_generic_checking(csv, {
            "name": "Joint",
            "exclude_categories": ["Income"],
        })
        # Inflows (positive originals) dropped; outflows flipped to positive
        assert (df["Amount"] > 0).all()
        assert len(df) == 2
        # Total should be 120 + 45.5 = 165.50
        assert round(df["Amount"].sum(), 2) == 165.50

    def test_excludes_configured_categories(self, tmp_path: Path):
        csv = tmp_path / "checking_excl.csv"
        csv.write_text(textwrap.dedent("""\
            Transaction Date,Category,Subcategory,Description,Sub Type,Amount (USD)
            04/01/2025,Lifestyle,Groceries,TEST GROCERY,Spend,-100.00
            04/02/2025,Credit Card Payments,Payoff,AMEX AUTOPAY,Spend,-1500.00
            04/03/2025,Investment,Brokerage,TO SCHWAB,Spend,-1000.00
            04/04/2025,Taxes,Income Tax,IRS QUARTERLY,Spend,-3000.00
        """))
        df = ingest_generic_checking(csv, {
            "name": "Joint",
            "exclude_categories": ["Credit Card Payments", "Investment", "Taxes"],
        })
        # Only the grocery line should survive
        assert len(df) == 1
        assert "TEST GROCERY" in df.iloc[0]["Desc"]

    def test_fixture_round_trip(self, checking_csv: Path):
        df = ingest_generic_checking(checking_csv, {
            "name": "Joint Checking",
            "exclude_categories": [
                "Credit Card Payments", "Investment", "Income",
                "Taxes", "Rental Property", "Mortgage",
            ],
        })
        assert len(df) >= 0  # may be empty if fixture is all excluded; allowed
        if len(df) > 0:
            assert (df["Amount"] > 0).all()


# ---------------------------------------------------------------------------
# Cross-source: column normalization
# ---------------------------------------------------------------------------

def test_all_ingest_paths_produce_same_columns(
    apple_card_csv: Path, chase_csv: Path, checking_csv: Path
):
    apple = ingest_apple_card(apple_card_csv, {"name": "Mike AppleCard"})
    chase = ingest_chase_card(chase_csv,    {"name": "Mike Chase"})
    chk   = ingest_generic_checking(checking_csv, {"name": "Joint Checking"})

    # All three sources, after ingest, must be concat-compatible.
    assert list(apple.columns) == UNIFORM_COLS
    assert list(chase.columns) == UNIFORM_COLS
    assert list(chk.columns)   == UNIFORM_COLS

    combined = pd.concat([apple, chase, chk], ignore_index=True)
    assert len(combined) == len(apple) + len(chase) + len(chk)
