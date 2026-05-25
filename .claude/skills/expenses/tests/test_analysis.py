"""Tests for analyze.py — trip clustering, recurring subscriptions, drilldowns.

Schema in: the categorized 'Lifestyle' schema:
    Date | Source | Description | Category | Subcategory | Amount | Original Category
"""

from __future__ import annotations

import pandas as pd
import pytest

from analyze import (
    big_transactions,
    category_by_person,
    drill_down,
    recurring_subscriptions,
    subcategory_breakdown,
    trip_clusters,
    ttm_summary,
    yoy_change,
)


# ---------------------------------------------------------------------------
# Helpers — build categorized-schema data inline
# ---------------------------------------------------------------------------

def _ctx_row(date_str: str, source: str, desc: str, category: str,
              subcategory: str, amount: float) -> dict:
    return {"Date": date_str, "Source": source, "Description": desc,
            "Category": category, "Subcategory": subcategory,
            "Amount": amount,
            "Original Category": f"{source} / {category}"}


def _build_simple_year(period_end: str = "12/31/2025") -> pd.DataFrame:
    """A balanced 12-month synthetic ledger for TTM tests."""
    rows = []
    for month in range(1, 13):
        date = f"{month:02d}/15/2025"
        rows.append(_ctx_row(date, "Mike AppleCard", "WHOLE FOODS",
                              "Food & Dining", "Groceries", 120.00))
        rows.append(_ctx_row(date, "Mike AppleCard", "STARBUCKS",
                              "Food & Dining", "Coffee", 6.50))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# TTM filter + summary
# ---------------------------------------------------------------------------

class TestTTMSummary:

    def test_returns_formatted_string(self):
        """ttm_summary returns a human-readable string, not a DataFrame."""
        df = _build_simple_year()
        summary = ttm_summary(df, period_end="12/31/2025")
        assert isinstance(summary, str)
        assert "Last 12 months total" in summary
        assert "Food & Dining" in summary

    def test_amount_aggregation_appears_in_output(self):
        df = _build_simple_year()
        summary = ttm_summary(df, period_end="12/31/2025")
        # 12 months × (120 + 6.50) = 1518 — round-formatted to "1,518"
        assert "1,518" in summary


# ---------------------------------------------------------------------------
# Trip clustering
# ---------------------------------------------------------------------------

class TestTripClusters:

    def test_groups_concurrent_travel_charges_into_one_trip(self):
        """Travel charges within `gap_days` of each other form one trip."""
        rows = [
            # All within a 5-day window — should be one trip
            _ctx_row("06/08/2025", "Mike Chase", "DELTA AIR LINES",
                     "Travel", "Airlines", 850.00),
            _ctx_row("06/10/2025", "Mike Chase", "MARRIOTT TOKYO",
                     "Travel", "Hotels", 1200.00),
            _ctx_row("06/12/2025", "Mike Chase", "TOKYO METRO PASS",
                     "Travel", "Ground Transport", 35.00),
            # Separate trip months later
            _ctx_row("11/01/2025", "Mike Chase", "UNITED AIRLINES",
                     "Travel", "Airlines", 320.00),
        ]
        df = pd.DataFrame(rows)
        trips = trip_clusters(df, period_end="12/31/2025", include_extras=False)
        # Two distinct trips: one in June, one in November
        assert len(trips) == 2

    def test_home_base_merchant_excluded_from_trip_extras(self):
        """A coffee shop the user hits monthly should NOT be added to a trip's extras."""
        rows = []
        # Mike's daily coffee — 12 months of Blue Bottle (home-base merchant)
        for month in range(1, 13):
            rows.append(_ctx_row(f"{month:02d}/10/2025", "Mike AppleCard",
                                 "BLUE BOTTLE COFFEE",
                                 "Food & Dining", "Coffee", 6.50))
        # A trip in June — flight, hotel, all within 5 days
        rows.append(_ctx_row("06/08/2025", "Mike Chase", "DELTA AIR LINES",
                             "Travel", "Airlines", 850.00))
        rows.append(_ctx_row("06/10/2025", "Mike Chase", "MARRIOTT TOKYO",
                             "Travel", "Hotels", 1200.00))
        # Bonus: a one-off restaurant during the trip — SHOULD count as extra
        rows.append(_ctx_row("06/11/2025", "Mike Chase", "SUSHI JIRO TOKYO",
                             "Food & Dining", "Restaurants", 280.00))

        df = pd.DataFrame(rows)
        trips = trip_clusters(df, period_end="12/31/2025", include_extras=True,
                              extras_window=3)
        assert len(trips) == 1
        extras_total = trips.iloc[0]["extras_total"]
        # Home-base Blue Bottle (12 distinct months) must be excluded;
        # one-off Sushi Jiro (only that month) should be included.
        # The 06/10 Blue Bottle that falls in the trip window also gets
        # filtered out because Blue Bottle is home-base.
        assert extras_total == 280.0


# ---------------------------------------------------------------------------
# Recurring subscriptions
# ---------------------------------------------------------------------------

class TestRecurringSubscriptions:

    def test_detects_monthly_subscription(self):
        # 12 months of "GENERIC STREAMING SVC" → recurring
        rows = [_ctx_row(f"{m:02d}/05/2025", "Mike AppleCard",
                          "GENERIC STREAMING SVC", "Subscriptions & Software",
                          "Streaming", 12.99) for m in range(1, 13)]
        df = pd.DataFrame(rows)
        recur = recurring_subscriptions(df, min_count=6, period_end="12/31/2025")
        assert "GENERIC STREAMING SVC" in recur.index
        assert int(recur.loc["GENERIC STREAMING SVC", "n"]) == 12

    def test_does_not_flag_one_off_subscription(self):
        df = pd.DataFrame([
            _ctx_row("06/05/2025", "Mike AppleCard", "ONE-OFF APP PURCHASE",
                     "Subscriptions & Software", "Software", 49.99),
        ])
        recur = recurring_subscriptions(df, min_count=6, period_end="12/31/2025")
        assert "ONE-OFF APP PURCHASE" not in recur.index


# ---------------------------------------------------------------------------
# big_transactions / drilldown / subcategory_breakdown
# ---------------------------------------------------------------------------

class TestBigTransactions:

    def test_filters_by_threshold(self):
        df = pd.DataFrame([
            _ctx_row("01/15/2025", "Mike Chase", "BIG ITEM", "Shopping & Retail",
                     "Electronics", 1500.00),
            _ctx_row("01/16/2025", "Mike Chase", "SMALL ITEM", "Food & Dining",
                     "Coffee", 6.50),
        ])
        big = big_transactions(df, threshold=1000, period_end="12/31/2025")
        assert len(big) == 1
        assert big.iloc[0]["Description"] == "BIG ITEM"


class TestDrillDown:

    def test_filters_by_category(self):
        df = pd.DataFrame([
            _ctx_row("01/15/2025", "Mike Chase", "FOOD A", "Food & Dining",
                     "Restaurants", 50.00),
            _ctx_row("01/16/2025", "Mike Chase", "TRAVEL A", "Travel",
                     "Airlines", 500.00),
        ])
        out = drill_down(df, "Food & Dining", period_end="12/31/2025")
        descs = list(out["Description"])
        assert "FOOD A" in descs
        assert "TRAVEL A" not in descs


class TestSubcategoryBreakdown:

    def test_aggregates_per_subcategory(self):
        df = pd.DataFrame([
            _ctx_row("01/05/2025", "M", "X", "Food & Dining", "Coffee", 10.00),
            _ctx_row("02/05/2025", "M", "Y", "Food & Dining", "Coffee", 12.00),
            _ctx_row("03/05/2025", "M", "Z", "Food & Dining", "Groceries", 100.00),
        ])
        out = subcategory_breakdown(df, "Food & Dining", period_end="12/31/2025")
        # Returns DataFrame indexed by Subcategory with `txns` and `total` columns
        assert "Coffee" in out.index
        assert "Groceries" in out.index
        # Round-formatted with .round(0); 10 + 12 = 22
        assert int(out.loc["Coffee", "total"]) == 22
        assert int(out.loc["Coffee", "txns"]) == 2


# ---------------------------------------------------------------------------
# Year-over-year
# ---------------------------------------------------------------------------

class TestYearOverYear:

    def test_calculates_delta(self):
        rows = []
        # 2024: $200/mo on groceries
        for m in range(1, 13):
            rows.append(_ctx_row(f"{m:02d}/15/2024", "Mike", "WHOLE FOODS",
                                 "Food & Dining", "Groceries", 200.00))
        # 2025: $250/mo on groceries
        for m in range(1, 13):
            rows.append(_ctx_row(f"{m:02d}/15/2025", "Mike", "WHOLE FOODS",
                                 "Food & Dining", "Groceries", 250.00))

        df = pd.DataFrame(rows)
        out = yoy_change(df, period_end="12/31/2025")
        food = out.loc["Food & Dining"]
        # TTM (2025) = 12 × 250 = 3000; Prior (2024) = 12 × 200 = 2400; delta = +600
        assert food["TTM"] == 3000
        assert food["Prior"] == 2400
        assert food["$ change"] == 600


# ---------------------------------------------------------------------------
# Person split
# ---------------------------------------------------------------------------

class TestCategoryByPerson:

    def test_returns_per_person_category_breakdown(self):
        """category_by_person infers Person from the first word of Source."""
        df = pd.DataFrame([
            _ctx_row("01/15/2025", "Mike AppleCard", "X", "Food & Dining",
                     "Groceries", 100.00),
            _ctx_row("01/16/2025", "Sarah AppleCard", "Y", "Food & Dining",
                     "Groceries", 150.00),
        ])
        out = category_by_person(df, period_end="12/31/2025")
        # Pivot is indexed by Category, columns = Person names + Total
        assert "Food & Dining" in out.index
        assert "Mike" in out.columns
        assert "Sarah" in out.columns
        assert "Total" in out.columns
        assert int(out.loc["Food & Dining", "Mike"]) == 100
        assert int(out.loc["Food & Dining", "Sarah"]) == 150
        assert int(out.loc["Food & Dining", "Total"]) == 250
