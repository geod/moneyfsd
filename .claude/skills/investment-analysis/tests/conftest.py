"""
Shared pytest fixtures for the investment-analysis skill test suite.

All synthetic data uses generic personas (primary / spouse), generic
employer aliases (employer_a / employer_b), and made-up tickers where
helpful. Real ETF tickers used in tests (VTI, BND, PIMIX, etc.) are
public-market data and not PII.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

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
def data_dir() -> Path:
    return SKILL_ROOT / "references" / "data"


@pytest.fixture(scope="session")
def tests_fixtures_dir() -> Path:
    return SKILL_ROOT / "tests" / "fixtures"


# ---------------------------------------------------------------------------
# Synthetic statement-text fixtures (read on demand)
# ---------------------------------------------------------------------------

@pytest.fixture
def schwab_taxable_text(tests_fixtures_dir: Path) -> str:
    return (tests_fixtures_dir / "pdf_extracted" / "schwab_taxable.txt").read_text()


@pytest.fixture
def schwab_pcra_qualified_text(tests_fixtures_dir: Path) -> str:
    return (tests_fixtures_dir / "pdf_extracted" / "schwab_pcra_qualified.txt").read_text()


@pytest.fixture
def schwab_pcra_nqdc_text(tests_fixtures_dir: Path) -> str:
    return (tests_fixtures_dir / "pdf_extracted" / "schwab_pcra_nqdc.txt").read_text()


@pytest.fixture
def qualified_401k_plan_text(tests_fixtures_dir: Path) -> str:
    return (tests_fixtures_dir / "pdf_extracted" / "qualified_401k_plan.txt").read_text()


# ---------------------------------------------------------------------------
# Synthetic ClassifiedRow / Position builders
# ---------------------------------------------------------------------------

def make_position_row(account: str = "brokerage_1",
                       account_type: str = "taxable_brokerage",
                       owner: str = "primary",
                       ticker: str = "VTI",
                       description: str = "VANGUARD TOTAL STOCK",
                       section: str = "etf",
                       quantity: float = 100.0,
                       price: float = 250.00,
                       market_value: float = 25_000.00,
                       cost_basis: float = 18_000.00,
                       employer: str | None = None,
                       nested_inside: str | None = None) -> dict:
    """Build one row in the consolidated positions.csv schema."""
    return {
        "account": account,
        "account_type": account_type,
        "wrapper_structure": None,
        "owner": owner,
        "joint_share": None,
        "employer": employer,
        "nested_inside": nested_inside,
        "ticker": ticker,
        "description": description,
        "section": section,
        "quantity": quantity,
        "price": price,
        "market_value_gross": market_value,
        "market_value_net": market_value,
        "cost_basis": cost_basis,
        "unrealized_gain": market_value - cost_basis,
        "vested": True,
        "vest_date": None,
        "est_annual_income": None,
        "est_yield_pct": None,
        "income_character": None,
        "methodology": None,
        "liquid": None,
        "source_file": f"{account}.pdf",
        "notes": None,
    }


@pytest.fixture
def positions_df_sample() -> pd.DataFrame:
    """A small but representative positions DataFrame for classification tests."""
    return pd.DataFrame([
        make_position_row(ticker="VTI",   description="VANGUARD TOTAL STOCK",
                           section="etf", market_value=100_000.00),
        make_position_row(ticker="BND",   description="VANGUARD TOTAL BOND",
                           section="etf", market_value=50_000.00),
        make_position_row(ticker="PIMIX", description="PIMCO INCOME INSTL",
                           section="mutual_fund", market_value=75_000.00,
                           account_type="nqdc", employer="employer_a"),
        make_position_row(ticker="CASH",  description="Cash and cash investments",
                           section="cash", quantity=None, price=None,
                           market_value=12_000.00, cost_basis=None),
        make_position_row(ticker="AAPL",  description="APPLE INC",
                           section="equity", market_value=15_000.00),
    ])


# ---------------------------------------------------------------------------
# Statement-meta synthetic builders for nesting/reconcile tests
# ---------------------------------------------------------------------------

def make_statement_meta(source_file: str, custodian: str = "schwab",
                          statement_type: str = "taxable_brokerage",
                          extracted_total: float = 1_000_000.00,
                          stated_total: float | None = None,
                          nesting_indicator: dict | None = None) -> dict:
    """Synthetic statement metadata, matches statements_meta.json schema."""
    return {
        "source_file": source_file,
        "custodian": custodian,
        "statement_type": statement_type,
        "statement_date": "2026-03-31",
        "account_number": "****-1234",
        "account_name": statement_type,
        "stated_total": stated_total if stated_total is not None else extracted_total,
        "extracted_total": extracted_total,
        "reconciled": True,
        "reconciliation_note": "",
        "nesting_indicator": nesting_indicator,
    }


# ---------------------------------------------------------------------------
# Real-estate sample dicts for compute_re_equity tests
# ---------------------------------------------------------------------------

@pytest.fixture
def re_defaults() -> dict:
    """Match the defaults shipped in references/data/thresholds.yaml."""
    return {
        "selling_costs_pct": 0.06,
        "fed_ltcg_rate": 0.20,
        "nii_surtax_rate": 0.038,
        "default_state_marginal_rate": 0.05,
        "sec_121_exclusion_single": 250_000,
        "sec_121_exclusion_married": 500_000,
        "depreciation_recapture_rate": 0.25,
    }


# Re-export the builders for direct import in test files
__all__ = ["make_position_row", "make_statement_meta"]
