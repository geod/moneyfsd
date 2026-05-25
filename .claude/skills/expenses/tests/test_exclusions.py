"""Tests for ``apply_exclusions`` in consolidate.py.

Covers exclusion rule matching semantics (any-of subfields), `kind:` dispatch,
and the audit-trail discipline of always reporting *something* was excluded.
"""

from __future__ import annotations

import pandas as pd
import pytest

from consolidate import apply_exclusions


def _df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["Date", "Source", "Desc", "OrigCat", "Amount"])


@pytest.fixture
def mixed_ledger() -> pd.DataFrame:
    return _df([
        {"Date": "01/05/2025", "Source": "Mike AppleCard",
         "Desc": "WHOLE FOODS",          "OrigCat": "", "Amount": 145.30},
        {"Date": "01/15/2025", "Source": "Mike Chase",
         "Desc": "DELTA AIR LINES",      "OrigCat": "", "Amount": 612.00},
        {"Date": "07/10/2025", "Source": "Mike Chase",
         "Desc": "HOTEL OKURA TOKYO",    "OrigCat": "", "Amount": 412.00},
        {"Date": "07/11/2025", "Source": "Mike Chase",
         "Desc": "HANEDA AIRPORT TAXI",  "OrigCat": "", "Amount": 50.00},
        {"Date": "08/01/2025", "Source": "Joint Checking",
         "Desc": "RENTAL HOA AUTOPAY",   "OrigCat": "Rental", "Amount": 850.00},
        {"Date": "08/02/2025", "Source": "Joint Checking",
         "Desc": "TENANT ZELLE INFLOW",  "OrigCat": "Rental", "Amount": -2500.00},
    ])


# ---------------------------------------------------------------------------

def test_description_contains_string(mixed_ledger: pd.DataFrame):
    rules = [{
        "description": "rental property",
        "kind": "rental_operating",
        "match": {"description_contains": "RENTAL"},
    }]
    out = apply_exclusions(mixed_ledger, rules)
    assert "RENTAL HOA AUTOPAY" not in set(out["Desc"])
    assert len(out) == 5


def test_description_contains_list_any_match(mixed_ledger: pd.DataFrame):
    rules = [{
        "description": "work trip — Tokyo",
        "match": {"description_contains": ["hotel okura", "haneda"]},
    }]
    out = apply_exclusions(mixed_ledger, rules)
    descs = set(out["Desc"])
    assert "HOTEL OKURA TOKYO" not in descs
    assert "HANEDA AIRPORT TAXI" not in descs
    assert "WHOLE FOODS" in descs


def test_date_filter_must_match_with_other_criteria(mixed_ledger: pd.DataFrame):
    """Date + description_contains must BOTH match — they AND together."""
    rules = [{
        "description": "specific work trip days",
        "match": {
            "date": ["07/10/2025", "07/11/2025"],
            "description_contains": ["hotel okura", "haneda"],
        },
    }]
    out = apply_exclusions(mixed_ledger, rules)
    # Both Tokyo rows on those dates should be excluded
    assert len(out) == 4


def test_amount_match(mixed_ledger: pd.DataFrame):
    rules = [{
        "description": "exact-amount autopay",
        "match": {"amount": 850.00},
    }]
    out = apply_exclusions(mixed_ledger, rules)
    assert 850.00 not in set(out["Amount"].round(2))


def test_source_match(mixed_ledger: pd.DataFrame):
    rules = [{
        "description": "all of one source",
        "match": {"source": "Joint Checking"},
    }]
    out = apply_exclusions(mixed_ledger, rules)
    assert "Joint Checking" not in set(out["Source"])


def test_no_rules_is_passthrough(mixed_ledger: pd.DataFrame):
    out = apply_exclusions(mixed_ledger, [])
    pd.testing.assert_frame_equal(
        out.reset_index(drop=True), mixed_ledger.reset_index(drop=True),
    )


def test_none_rules_is_passthrough(mixed_ledger: pd.DataFrame):
    out = apply_exclusions(mixed_ledger, None)
    pd.testing.assert_frame_equal(
        out.reset_index(drop=True), mixed_ledger.reset_index(drop=True),
    )


def test_zero_match_rule_leaves_dataframe_intact(mixed_ledger: pd.DataFrame):
    """A rule that matches nothing is silently a no-op."""
    rules = [{"description": "nothing", "match": {"description_contains": "ZZZZZZZ"}}]
    out = apply_exclusions(mixed_ledger, rules)
    assert len(out) == len(mixed_ledger)


def test_multiple_rules_apply_sequentially(mixed_ledger: pd.DataFrame):
    rules = [
        {"description": "rental ops", "match": {"description_contains": "RENTAL"}},
        {"description": "tokyo trip", "match": {"description_contains": ["hotel okura", "haneda"]}},
    ]
    out = apply_exclusions(mixed_ledger, rules)
    assert len(out) == 3   # 6 minus 1 RENTAL minus 2 Tokyo
    assert "RENTAL HOA AUTOPAY" not in set(out["Desc"])
    assert "HOTEL OKURA TOKYO" not in set(out["Desc"])


def test_kind_field_defaults_to_other_without_crash(mixed_ledger: pd.DataFrame, capsys):
    """Rules without `kind:` should still apply and not crash."""
    rules = [{"description": "no-kind rule", "match": {"description_contains": "WHOLE FOODS"}}]
    out = apply_exclusions(mixed_ledger, rules)
    assert len(out) == len(mixed_ledger) - 1


def test_exclusion_audit_emits_to_stdout(mixed_ledger: pd.DataFrame, capsys):
    """The README promises an exclusion audit. Verify *something* gets printed."""
    rules = [{
        "description": "audit-trail test",
        "kind": "rental_operating",
        "match": {"description_contains": "WHOLE FOODS"},
    }]
    apply_exclusions(mixed_ledger, rules)
    captured = capsys.readouterr().out
    assert "Excluding rule" in captured
    assert "audit-trail test" in captured
