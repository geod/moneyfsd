"""Tests for ``categorize_row`` in consolidate.py.

Covers the priority chain:
    1. User overrides (Date, desc, amount, source)
    2. Source-specific bank-category mapping (e.g., Apple Card 'Grocery' → Food/Groceries)
    3. Merchant keyword matching from taxonomy
    4. Misc fallback

Word-boundary discipline: a keyword "rei" must NOT match "wineries".
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

from consolidate import categorize_row, load_taxonomy


# ---------------------------------------------------------------------------
# Tiny synthetic taxonomy
# ---------------------------------------------------------------------------

@pytest.fixture
def tiny_taxonomy() -> dict:
    """A minimal taxonomy for testing matching semantics in isolation.

    Real taxonomy lives in assets/default_taxonomy.yaml; this fixture
    keeps tests deterministic and decoupled.
    """
    return {
        "Food & Dining": {
            "Groceries": ["whole foods", "trader joe", "sprouts"],
            "Coffee":    ["starbucks", "blue bottle", "philz"],
        },
        "Travel": {
            "Airlines":  ["delta", "united airlines", "jetblue"],
            "Hotels":    ["marriott", "hyatt", "airbnb"],
            "Ski":       ["vail resorts", "mammoth mountain"],
        },
        "Shopping & Retail": {
            "Outdoor":   ["rei"],
        },
    }


def _row(desc: str, source: str = "Mike AppleCard", date: str = "01/15/2025",
         amount: float = 50.00, orig: str = "") -> dict:
    return {"Date": date, "Source": source, "Desc": desc,
            "OrigCat": orig, "Amount": amount}


# ---------------------------------------------------------------------------
# Keyword matching basics
# ---------------------------------------------------------------------------

class TestKeywordMatching:

    def test_simple_keyword_match(self, tiny_taxonomy):
        cat, sub = categorize_row(_row("WHOLE FOODS MARKET"), tiny_taxonomy, [], {})
        assert (cat, sub) == ("Food & Dining", "Groceries")

    def test_case_insensitive(self, tiny_taxonomy):
        cat, sub = categorize_row(_row("whole foods market"), tiny_taxonomy, [], {})
        assert (cat, sub) == ("Food & Dining", "Groceries")

    def test_substring_match_within_longer_description(self, tiny_taxonomy):
        cat, sub = categorize_row(
            _row("STARBUCKS COFFEE #1234 OAKLAND"), tiny_taxonomy, [], {}
        )
        assert (cat, sub) == ("Food & Dining", "Coffee")

    def test_no_match_falls_through_to_misc(self, tiny_taxonomy):
        cat, sub = categorize_row(
            _row("MYSTERY MERCHANT XYZ"), tiny_taxonomy, [], {}
        )
        assert (cat, sub) == ("Misc", "Unknown")

    def test_first_match_wins(self, tiny_taxonomy):
        """A description matching multiple categories takes the first declared one."""
        # "delta" matches Travel/Airlines first
        cat, sub = categorize_row(
            _row("DELTA AIR LINES TICKET"), tiny_taxonomy, [], {}
        )
        assert cat == "Travel"
        assert sub == "Airlines"


# ---------------------------------------------------------------------------
# Word-boundary discipline
# ---------------------------------------------------------------------------

class TestWordBoundary:

    def test_short_keyword_does_not_match_inside_other_word(self, tiny_taxonomy):
        """The keyword 'rei' should NOT match 'WINERIES' or 'COWORKING'."""
        cat, sub = categorize_row(
            _row("NAPA WINERIES TASTING"), tiny_taxonomy, [], {}
        )
        # Must NOT be classed as Outdoor — that would be the 'rei' false positive
        assert cat != "Shopping & Retail"

    def test_short_keyword_matches_real_occurrence(self, tiny_taxonomy):
        cat, sub = categorize_row(
            _row("REI #1234 BERKELEY"), tiny_taxonomy, [], {}
        )
        assert (cat, sub) == ("Shopping & Retail", "Outdoor")


# ---------------------------------------------------------------------------
# Override precedence
# ---------------------------------------------------------------------------

class TestOverridePrecedence:

    def test_override_beats_taxonomy_keyword(self, tiny_taxonomy):
        """User override should win over a default keyword match."""
        overrides = [{
            "match": {"description_contains": "WHOLE FOODS"},
            "category": "Charity & Gifts",
            "subcategory": "Gifts",
        }]
        cat, sub = categorize_row(
            _row("WHOLE FOODS GIFT BASKET"), tiny_taxonomy, overrides, {}
        )
        assert (cat, sub) == ("Charity & Gifts", "Gifts")

    def test_override_with_date_and_amount(self, tiny_taxonomy):
        overrides = [{
            "match": {"date": "11/15/2025", "amount": 1200.00,
                      "description_contains": "BAMBULAB"},
            "category": "Charity & Gifts",
            "subcategory": "Gifts",
        }]
        # Matching row → override applies
        cat, sub = categorize_row(
            _row("BAMBULAB X1 CARBON", date="11/15/2025", amount=1200.00),
            tiny_taxonomy, overrides, {},
        )
        assert (cat, sub) == ("Charity & Gifts", "Gifts")

        # Wrong amount → override does NOT apply
        cat, sub = categorize_row(
            _row("BAMBULAB X1 CARBON", date="11/15/2025", amount=950.00),
            tiny_taxonomy, overrides, {},
        )
        assert (cat, sub) != ("Charity & Gifts", "Gifts")

    def test_override_with_source_filter(self, tiny_taxonomy):
        overrides = [{
            "match": {"description_contains": "PATAGONIA", "source": "Mike AppleCard"},
            "category": "Sports & Hobbies",
            "subcategory": "Outdoor",
        }]
        cat, sub = categorize_row(
            _row("PATAGONIA STORE", source="Mike AppleCard"),
            tiny_taxonomy, overrides, {},
        )
        assert (cat, sub) == ("Sports & Hobbies", "Outdoor")

        # Same desc, different source → override does NOT apply
        cat, sub = categorize_row(
            _row("PATAGONIA STORE", source="Mike Chase"),
            tiny_taxonomy, overrides, {},
        )
        assert (cat, sub) != ("Sports & Hobbies", "Outdoor")


# ---------------------------------------------------------------------------
# Source-specific category map
# ---------------------------------------------------------------------------

class TestSourceCategoryMap:

    def test_apple_card_grocery_maps_through(self, tiny_taxonomy):
        """When a row arrives with Apple Card's native Category='Grocery',
        the source_category_maps should claim it before falling to keywords.
        """
        src_maps = {
            "AppleCard": {
                "Grocery": ["Food & Dining", "Groceries"],
                "Restaurants": ["Food & Dining", "Restaurants"],
            },
        }
        cat, sub = categorize_row(
            _row("UNFAMILIAR LOCAL MARKET", source="Mike AppleCard", orig="Grocery"),
            tiny_taxonomy, [], src_maps,
        )
        assert (cat, sub) == ("Food & Dining", "Groceries")


# ---------------------------------------------------------------------------
# Default taxonomy loads
# ---------------------------------------------------------------------------

def test_default_taxonomy_loads(skill_root):
    """The shipped default taxonomy must be valid YAML and parseable."""
    path = skill_root / "assets" / "default_taxonomy.yaml"
    if not path.is_file():
        pytest.skip(f"default taxonomy not found at {path}")
    tax = load_taxonomy(path)
    assert isinstance(tax, dict)
    assert len(tax) > 0
    # Sanity: each top-level category maps to a dict of subcategory → list-of-keywords
    for cat, subs in tax.items():
        assert isinstance(subs, dict), f"{cat} should map to a dict"
        for subcat, kws in subs.items():
            assert isinstance(kws, list), f"{cat}/{subcat} keywords should be a list"
