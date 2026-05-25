"""Tests for anomaly detectors in consolidate.py.

Covers:
- ``detect_loan_drift`` — monotone decline over 3+ months
- ``detect_multiple_loan_streams`` — two+ loan-shaped recurring streams
- ``detect_orphan_airfare`` — flight charges with no surrounding lodging
- ``detect_processor`` / ``strip_processor_prefix`` — payment-processor prefix extraction

All synthetic data — generic merchant names, no real servicer names beyond
generic phrases ("ARM MORTGAGE", "AUTOPAY"), no real account numbers.
"""

from __future__ import annotations

import pandas as pd
import pytest

from conftest import (
    make_loan_drift_series,
    make_recurring_subscription_series,
)
from consolidate import (
    detect_loan_drift,
    detect_multiple_loan_streams,
    detect_orphan_airfare,
    detect_processor,
    strip_processor_prefix,
    _misc_stem,
)


# ---------------------------------------------------------------------------
# detect_loan_drift
# ---------------------------------------------------------------------------

class TestLoanDrift:

    def test_flags_monotone_decline_over_4_plus_months(self):
        # 6 months, each $25 less than prior — clearly a drift signal
        df = make_loan_drift_series(start_amount=4200, drift_per_month=-25,
                                    months=6, desc="ARM MORTGAGE AUTOPAY")
        out = detect_loan_drift(df)
        assert len(out) == 1
        assert "ARM MORTGAGE" in out[0][1].lower() or "arm mortgage" in out[0][1].lower()

    def test_stable_payment_does_not_fire(self):
        # 6 months at identical amount — fixed mortgage; no drift
        df = make_loan_drift_series(start_amount=3850, drift_per_month=0, months=6,
                                    desc="FIXED MORTGAGE AUTOPAY")
        out = detect_loan_drift(df)
        assert out == []

    def test_increasing_payment_does_not_fire(self):
        # Detector specifically looks for DECREASING — increases (rate rise) ignored
        df = make_loan_drift_series(start_amount=3500, drift_per_month=+15, months=6,
                                    desc="MORTGAGE AUTOPAY UP")
        out = detect_loan_drift(df)
        assert out == []

    def test_short_series_does_not_fire(self):
        # Only 2 months of data — too few to call drift
        df = make_loan_drift_series(start_amount=4000, drift_per_month=-50, months=2,
                                    desc="MORTGAGE AUTOPAY SHORT")
        out = detect_loan_drift(df)
        assert out == []

    def test_small_amount_payment_ignored(self):
        # $50/mo decreasing — too small to be a loan; subscription drift, not loan
        df = make_loan_drift_series(start_amount=50, drift_per_month=-1, months=6,
                                    desc="SOME SUB DRIFT")
        out = detect_loan_drift(df)
        assert out == []


# ---------------------------------------------------------------------------
# detect_multiple_loan_streams
# ---------------------------------------------------------------------------

class TestMultipleLoanStreams:

    def test_flags_two_loan_streams(self):
        """Two distinct loan streams must be detected as separate.

        Note: _misc_stem strips 6+ digit runs and keeps the first 4 tokens,
        so to be detected as distinct, the descriptions must differ in the
        FIRST 4 non-digit tokens — different servicer prefixes work.
        """
        m1 = make_loan_drift_series(start_amount=3850, drift_per_month=0, months=8,
                                    desc="ROCKET MORTGAGE PYMT AUTOPAY")
        m2 = make_loan_drift_series(start_amount=2200, drift_per_month=0, months=8,
                                    desc="WELLS FARGO MTG PYMT AUTOPAY")
        df = pd.concat([m1, m2], ignore_index=True)
        out = detect_multiple_loan_streams(df)
        assert len(out) == 1
        msg = out[0][1].lower()
        assert "multiple" in msg
        assert "loan-shaped" in msg or "mortgage" in msg or "stream" in msg

    def test_single_loan_does_not_fire(self):
        df = make_loan_drift_series(start_amount=3850, drift_per_month=0, months=8,
                                    desc="SINGLE MORTGAGE PYMT")
        out = detect_multiple_loan_streams(df)
        assert out == []


# ---------------------------------------------------------------------------
# detect_orphan_airfare
# ---------------------------------------------------------------------------

class TestOrphanAirfare:

    def test_airfare_with_lodging_nearby_is_clean(self):
        df = pd.DataFrame([
            {"Date": "06/10/2025", "Source": "Mike Chase",
             "Desc": "DELTA AIR LINES", "Category": "Travel", "Amount": 850.00},
            {"Date": "06/12/2025", "Source": "Mike Chase",
             "Desc": "MARRIOTT HOTEL", "Category": "Travel", "Amount": 420.00},
        ])
        out = detect_orphan_airfare(df, lookback_days=5, threshold=500)
        assert out == []

    def test_orphan_airfare_with_no_lodging_fires(self):
        df = pd.DataFrame([
            {"Date": "06/10/2025", "Source": "Mike Chase",
             "Desc": "DELTA AIR LINES", "Category": "Travel", "Amount": 850.00},
            # No hotel / rental / non-airline Travel charge anywhere nearby
        ])
        out = detect_orphan_airfare(df, lookback_days=5, threshold=500)
        assert len(out) == 1
        assert "orphan" in out[0][1].lower()

    def test_small_airfare_below_threshold_not_flagged(self):
        df = pd.DataFrame([
            {"Date": "06/10/2025", "Source": "Mike Chase",
             "Desc": "SOUTHWEST AIRLINES", "Category": "Travel", "Amount": 120.00},
        ])
        out = detect_orphan_airfare(df, lookback_days=5, threshold=500)
        assert out == []

    def test_no_category_column_returns_empty(self):
        df = pd.DataFrame([{"Date": "06/10/2025", "Source": "Mike Chase",
                            "Desc": "DELTA", "Amount": 850.00}])
        out = detect_orphan_airfare(df)
        assert out == []


# ---------------------------------------------------------------------------
# Payment-processor prefix handling
# ---------------------------------------------------------------------------

class TestProcessorPrefix:

    @pytest.mark.parametrize("desc,expected_label", [
        ("SQ*COFFEE SHOP DOWNTOWN", "Square"),
        ("SP*SOME WEB MERCHANT", "Stripe"),
        ("PP*BAY AREA RUNNERS", "PayPal"),
        ("AMZ*ELECTRONICS", "Amazon Marketplace"),
    ])
    def test_known_prefixes_detected(self, desc, expected_label):
        assert detect_processor(desc) == expected_label

    def test_unknown_prefix_returns_empty(self):
        assert detect_processor("RAW MERCHANT NAME") == ""

    def test_strip_removes_known_prefix(self):
        stripped = strip_processor_prefix("SQ*COFFEE SHOP")
        # Should NOT start with SQ*
        assert not stripped.lower().startswith("sq*")
        assert "COFFEE SHOP" in stripped

    def test_strip_no_op_for_unknown_prefix(self):
        assert strip_processor_prefix("RAW MERCHANT") == "RAW MERCHANT"


# ---------------------------------------------------------------------------
# _misc_stem — used internally by detectors for grouping
# ---------------------------------------------------------------------------

class TestMiscStem:

    def test_strips_processor_prefix(self):
        stem = _misc_stem("SQ*COFFEE SHOP DOWNTOWN")
        assert "sq*" not in stem.lower()

    def test_strips_long_numeric_ids(self):
        """6+ digit numeric IDs (transaction confirmation codes, account
        numbers) shouldn't fragment merchant grouping. Shorter digit
        sequences (store numbers like '#1234') are kept as-is."""
        s1 = _misc_stem("STARBUCKS COFFEE 123456789")
        s2 = _misc_stem("STARBUCKS COFFEE 987654321")
        assert s1 == s2
