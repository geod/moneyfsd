"""
PDF ingest tests via pdfplumber mocking.

Strategy: the real PDF parser calls pdfplumber.open(path) and reads
extract_text() per page. We patch pdfplumber.open to return a fake context
manager whose pages yield our synthetic text fixtures. This tests OUR
parser logic against realistic statement-text — without needing real PDFs
in the repo.

Fixtures in tests/fixtures/pdf_extracted/ are hand-crafted to mirror
real bank-statement layouts. ZERO PII — all use Mike Chen / Sarah Chen
generic personas and made-up merchants.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from consolidate import ingest_chase_card_pdf


# ---------------------------------------------------------------------------
# pdfplumber mocking helper
# ---------------------------------------------------------------------------

def fake_pdfplumber_for_text(text: str):
    """Return a mock object that mimics pdfplumber.open's context manager.

    Splits the text on '--- PAGE BREAK ---' markers; each chunk becomes one
    page returning that chunk via extract_text().
    """
    chunks = text.split("--- PAGE BREAK ---")
    pages = []
    for chunk in chunks:
        page = MagicMock()
        page.extract_text.return_value = chunk
        pages.append(page)

    fake_pdf = MagicMock()
    fake_pdf.pages = pages

    fake_open = MagicMock()
    fake_open.__enter__ = MagicMock(return_value=fake_pdf)
    fake_open.__exit__ = MagicMock(return_value=False)
    return fake_open


# ---------------------------------------------------------------------------
# Chase credit-card PDF parser
# ---------------------------------------------------------------------------

class TestChaseCardPDF:

    def test_parses_chase_fixture(self, tests_fixtures_dir: Path, tmp_path: Path):
        """Round-trip our synthetic Chase fixture through ingest_chase_card_pdf
        and assert we got the right shape + filtering.
        """
        fixture = (tests_fixtures_dir / "pdf_extracted"
                   / "chase_card_2025_03.txt").read_text()

        # The function expects a file path; we point it at a sentinel that the
        # mock will short-circuit before reading.
        sentinel_pdf = tmp_path / "fake.pdf"
        sentinel_pdf.write_bytes(b"")  # exists but empty

        fake_open = fake_pdfplumber_for_text(fixture)
        with patch("consolidate._ensure_pdfplumber") as mock_ensure:
            mock_pdfplumber = MagicMock()
            mock_pdfplumber.open = lambda _path: fake_open
            mock_ensure.return_value = mock_pdfplumber

            df = ingest_chase_card_pdf(
                str(sentinel_pdf),
                {"name": "Mike Chase"},
                base=tmp_path,
            )

        # Should have parsed transaction rows
        assert len(df) > 0, "no transactions parsed from Chase fixture"

        # Schema check
        assert {"Date", "Source", "Desc", "OrigCat", "Amount"}.issubset(df.columns)
        assert (df["Source"] == "Mike Chase").all()

        # Card-payoff row must be excluded (AUTOMATIC PAYMENT - THANK YOU)
        descs = df["Desc"].str.upper().tolist()
        assert not any("AUTOMATIC PAYMENT" in d for d in descs), \
            "card-payoff row leaked through — would double-count on checking side"

        # Merchant refund row SHOULD remain (it's negative but legitimate)
        refund_rows = df[df["Desc"].str.contains("REFUND", case=False, na=False)]
        assert len(refund_rows) >= 1, "merchant refund row was incorrectly filtered"
        assert (refund_rows["Amount"] < 0).all(), \
            "merchant refund should be negative (credit to account)"

    def test_handles_dollar_sign_prefix(self, tmp_path: Path):
        """Amount column with leading $ should parse cleanly."""
        text = (
            "Date     Description                    Amount\n"
            "03/16    GENERIC MERCHANT                $138.42\n"
            "03/17    ANOTHER MERCHANT                 $52.10\n"
        )
        sentinel = tmp_path / "fake.pdf"
        sentinel.write_bytes(b"")
        with patch("consolidate._ensure_pdfplumber") as mock_ensure:
            mock_pdfplumber = MagicMock()
            mock_pdfplumber.open = lambda _p: fake_pdfplumber_for_text(text)
            mock_ensure.return_value = mock_pdfplumber

            df = ingest_chase_card_pdf(
                str(sentinel),
                {"name": "Chase"},
                base=tmp_path,
            )
        assert len(df) == 2
        assert round(df.iloc[0]["Amount"], 2) == 138.42

    def test_empty_text_returns_empty_dataframe(self, tmp_path: Path):
        sentinel = tmp_path / "fake.pdf"
        sentinel.write_bytes(b"")
        with patch("consolidate._ensure_pdfplumber") as mock_ensure:
            mock_pdfplumber = MagicMock()
            mock_pdfplumber.open = lambda _p: fake_pdfplumber_for_text("")
            mock_ensure.return_value = mock_pdfplumber

            df = ingest_chase_card_pdf(
                str(sentinel),
                {"name": "Chase"},
                base=tmp_path,
            )
        assert len(df) == 0
        # Even when empty, schema must be intact for downstream concat
        assert list(df.columns) == ["Date", "Source", "Desc", "OrigCat", "Amount"]


# ---------------------------------------------------------------------------
# Fixture sanity (smoke)
# ---------------------------------------------------------------------------

class TestFixturesAreValid:

    @pytest.mark.parametrize("name", [
        "chase_card_2025_03.txt",
        "amex_card_2025_06.txt",
        "generic_checking_2025_q1.txt",
    ])
    def test_fixture_exists_and_has_personas(self, tests_fixtures_dir: Path, name: str):
        path = tests_fixtures_dir / "pdf_extracted" / name
        assert path.is_file(), f"fixture missing: {path}"
        text = path.read_text()
        # Must use the generic personas, never real names
        assert "MIKE CHEN" in text.upper() or "SARAH CHEN" in text.upper(), \
            f"fixture {name} doesn't use Mike/Sarah Chen personas"

    @pytest.mark.parametrize("name", [
        "chase_card_2025_03.txt",
        "amex_card_2025_06.txt",
        "generic_checking_2025_q1.txt",
    ])
    def test_no_unmasked_long_digit_runs(self, tests_fixtures_dir: Path, name: str):
        """Account numbers must be masked (**** prefix)."""
        text = (tests_fixtures_dir / "pdf_extracted" / name).read_text()
        import re
        # Strip out any deliberately-allowed digit runs (year-like, masked).
        # Anything 8+ digits that ISN'T preceded by '****' or '#' is suspicious.
        suspicious = re.findall(r"(?<!\*\*\*\*)(?<!#)\b\d{8,}\b", text)
        # Allow YYYY-MM-DD-looking 8-digit timestamps
        suspicious = [s for s in suspicious if not re.fullmatch(r"20\d{6}", s)]
        assert not suspicious, f"unmasked digit runs in {name}: {suspicious[:5]}"
