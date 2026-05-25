"""
Shared pytest fixtures and helpers for the expenses skill test suite.

All synthetic data uses two generic personas — `Mike Chen` and `Sarah Chen` —
matching the existing eval fixtures. Never use real names, addresses,
account numbers, or merchants from any author's data.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

# Make the skill's scripts importable as a top-level package.
SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT / "scripts"))


# ---------------------------------------------------------------------------
# Path fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def skill_root() -> Path:
    return SKILL_ROOT


@pytest.fixture(scope="session")
def evals_fixtures_dir() -> Path:
    return SKILL_ROOT / "evals" / "fixtures"


@pytest.fixture(scope="session")
def tests_fixtures_dir() -> Path:
    return SKILL_ROOT / "tests" / "fixtures"


# ---------------------------------------------------------------------------
# Existing realistic CSV fixtures (re-used from evals/)
# ---------------------------------------------------------------------------

@pytest.fixture
def apple_card_csv(evals_fixtures_dir: Path) -> Path:
    return evals_fixtures_dir / "apple_card.csv"


@pytest.fixture
def chase_csv(evals_fixtures_dir: Path) -> Path:
    return evals_fixtures_dir / "chase.csv"


@pytest.fixture
def checking_csv(evals_fixtures_dir: Path) -> Path:
    return evals_fixtures_dir / "checking.csv"


@pytest.fixture
def lifestyle_full_csv(evals_fixtures_dir: Path) -> Path:
    return evals_fixtures_dir / "lifestyle_expenses_full.csv"


# ---------------------------------------------------------------------------
# Synthetic-row builders for inline tests
#
# These produce small DataFrames in the canonical uniform schema:
#   Date | Source | Desc | OrigCat | Amount
# Amount sign: positive = outflow.
# ---------------------------------------------------------------------------

def _row(date_str: str, source: str, desc: str, amount: float,
          orig_cat: str = "") -> dict:
    return {"Date": date_str, "Source": source, "Desc": desc,
            "OrigCat": orig_cat, "Amount": amount}


@pytest.fixture
def empty_uniform_df() -> pd.DataFrame:
    return pd.DataFrame(columns=["Date", "Source", "Desc", "OrigCat", "Amount"])


@pytest.fixture
def sample_uniform_df() -> pd.DataFrame:
    """A small uniform-schema DataFrame for quick algorithmic tests.

    All synthetic. No real merchants or amounts.
    """
    return pd.DataFrame([
        _row("01/05/2025", "Mike AppleCard", "WHOLE FOODS MARKET", 145.30, "Grocery"),
        _row("01/12/2025", "Mike AppleCard", "BLUE BOTTLE COFFEE", 6.50, "Restaurants"),
        _row("01/15/2025", "Mike Chase", "DELTA AIR LINES", 412.00, "Travel"),
        _row("01/16/2025", "Mike Chase", "MARRIOTT BONVOY",  385.00, "Hotels"),
        _row("01/18/2025", "Mike Chase", "UBER TRIP", 38.50, "Ground Transport"),
        _row("02/01/2025", "Joint Checking", "WELLS FARGO MTG", 3850.00, "Mortgage"),
        _row("03/01/2025", "Joint Checking", "WELLS FARGO MTG", 3850.00, "Mortgage"),
        _row("04/01/2025", "Joint Checking", "WELLS FARGO MTG", 3850.00, "Mortgage"),
    ])


@pytest.fixture
def lifestyle_schema_df() -> pd.DataFrame:
    """The categorized-output schema:
       Date | Source | Description | Category | Subcategory | Amount | Original Category
    """
    return pd.DataFrame([
        {"Date": "01/05/2025", "Source": "Mike AppleCard", "Description": "WHOLE FOODS MARKET",
         "Category": "Food & Dining", "Subcategory": "Groceries", "Amount": 145.30,
         "Original Category": "Apple Card / Grocery"},
        {"Date": "01/12/2025", "Source": "Mike AppleCard", "Description": "BLUE BOTTLE COFFEE",
         "Category": "Food & Dining", "Subcategory": "Coffee", "Amount": 6.50,
         "Original Category": "Apple Card / Restaurants"},
        {"Date": "01/15/2025", "Source": "Mike Chase", "Description": "DELTA AIR LINES",
         "Category": "Travel", "Subcategory": "Airlines", "Amount": 412.00,
         "Original Category": "Chase / Travel"},
    ])


# ---------------------------------------------------------------------------
# Builders for specific scenarios
# ---------------------------------------------------------------------------

def make_loan_drift_series(start_amount: float = 4200.0,
                            drift_per_month: float = -25.0,
                            months: int = 6,
                            start_date: str = "01/01/2025",
                            desc: str = "ARM MORTGAGE AUTOPAY") -> pd.DataFrame:
    """Build a synthetic monthly loan-payment series that drifts down each month.

    Used by loan-drift detector tests. All synthetic — no real servicer name.
    """
    start = pd.Timestamp(start_date)
    rows = []
    for i in range(months):
        d = start + pd.DateOffset(months=i)
        amt = round(start_amount + i * drift_per_month, 2)
        rows.append(_row(d.strftime("%m/%d/%Y"), "Joint Checking", desc, amt, "Mortgage"))
    return pd.DataFrame(rows)


def make_recurring_subscription_series(desc: str = "FAKE STREAMING SVC",
                                        amount: float = 12.99,
                                        months: int = 12,
                                        start_date: str = "01/05/2025") -> pd.DataFrame:
    """Synthetic monthly subscription series (positive=outflow)."""
    start = pd.Timestamp(start_date)
    return pd.DataFrame([
        _row((start + pd.DateOffset(months=i)).strftime("%m/%d/%Y"),
             "Mike AppleCard", desc, amount, "Subscriptions")
        for i in range(months)
    ])


def make_trip(start: str, days: int = 5, dest_label: str = "London") -> pd.DataFrame:
    """Build a synthetic trip: flight + hotel + ground + meals across `days`.

    All merchants generic; amounts plausible but synthetic.
    """
    s = pd.Timestamp(start)
    rows = [
        _row((s - pd.Timedelta(days=10)).strftime("%m/%d/%Y"),
             "Mike Chase", f"FAKE AIRLINES {dest_label}", 850.00, "Travel"),
    ]
    for i in range(days):
        d = s + pd.Timedelta(days=i)
        date_str = d.strftime("%m/%d/%Y")
        rows.append(_row(date_str, "Mike Chase", f"HOTEL {dest_label}", 220.00, "Hotels"))
        rows.append(_row(date_str, "Mike Chase", "RESTAURANT GENERIC", 80.00, "Restaurants"))
    rows.append(_row((s + pd.Timedelta(days=days+1)).strftime("%m/%d/%Y"),
                     "Mike Chase", "AIRPORT TAXI", 65.00, "Ground Transport"))
    return pd.DataFrame(rows)


# Re-export builder functions for direct import in test files
__all__ = [
    "make_loan_drift_series",
    "make_recurring_subscription_series",
    "make_trip",
]
