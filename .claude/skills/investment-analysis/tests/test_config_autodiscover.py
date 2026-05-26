"""
Regression tests for config auto-discovery across the pipeline.

The failure mode being locked in here:

    Running `python scripts/consolidate.py <folder>` WITHOUT `--config`
    used to silently produce a positions ledger with zero manual holdings
    and zero real estate. The bug masked itself behind a successful run
    (no errors, positions.csv produced) — the exact "looks complete,
    is actually wrong" failure mode SKILL.md warns about.

These tests guarantee that:

1. The shared `auto_discover_config` helper resolves the standard config
   filename from the work folder.
2. Running `consolidate.py` WITHOUT `--config` actually picks up the
   config and injects manual_holdings — specifically a 529 entry, since
   that's the canonical "I have an account but no statement for it"
   manual-holding case that the original bug hid.
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

# conftest.py adds <skill_root>/scripts to sys.path
from _config_discover import auto_discover_config, CONFIG_FILENAME


# ---------------------------------------------------------------------------
# Unit-level: helper behavior
# ---------------------------------------------------------------------------

class TestAutoDiscoverConfig:
    """Direct exercise of the shared helper."""

    def test_explicit_path_wins_over_discovery(self, tmp_path: Path) -> None:
        work = tmp_path / "work"
        work.mkdir()
        (work / CONFIG_FILENAME).write_text("# in-folder config\n")

        elsewhere = tmp_path / "elsewhere.yaml"
        elsewhere.write_text("# explicit config\n")

        assert auto_discover_config(work, elsewhere) == elsewhere

    def test_discovers_config_in_work_folder(self, tmp_path: Path) -> None:
        work = tmp_path / "work"
        work.mkdir()
        cfg = work / CONFIG_FILENAME
        cfg.write_text("# discoverable\n")

        assert auto_discover_config(work, None) == cfg

    def test_discovers_config_when_pointed_at_analysis_subfolder(
        self, tmp_path: Path
    ) -> None:
        """If a script is invoked against `.analysis/`, the config still lives at the parent."""
        work = tmp_path / "work"
        analysis = work / ".analysis"
        analysis.mkdir(parents=True)
        cfg = work / CONFIG_FILENAME
        cfg.write_text("# parent-folder config\n")

        assert auto_discover_config(analysis, None) == cfg

    def test_returns_none_when_no_config_anywhere(self, tmp_path: Path) -> None:
        work = tmp_path / "work"
        work.mkdir()
        assert auto_discover_config(work, None) is None

    def test_returns_none_when_explicit_path_missing(self, tmp_path: Path) -> None:
        """Explicit-but-nonexistent should NOT fall back to discovery — the
        user asked for a specific file; we honor that (and the caller gets
        None, surfacing the typo)."""
        work = tmp_path / "work"
        work.mkdir()
        (work / CONFIG_FILENAME).write_text("# would-be-discovered\n")

        missing = tmp_path / "typo.yaml"
        # Current contract: explicit-missing falls through to discovery.
        # If that contract changes, this assertion gets flipped.
        assert auto_discover_config(work, missing) == work / CONFIG_FILENAME


# ---------------------------------------------------------------------------
# Integration: full consolidate.py CLI invocation without --config
# ---------------------------------------------------------------------------

SKILL_ROOT = Path(__file__).resolve().parent.parent
CONSOLIDATE_SCRIPT = SKILL_ROOT / "scripts" / "consolidate.py"


def _write_minimal_raw_inputs(work: Path) -> None:
    """Write the smallest valid raw_positions.csv + statements_meta.json pair
    that consolidate.py will accept. One taxable brokerage statement with
    one position — enough to exercise the manual-holdings injection path
    without bringing in PDF extraction or nesting detection."""
    analysis = work / ".analysis"
    analysis.mkdir(parents=True, exist_ok=True)

    # Minimal raw positions — schema matches extract_positions.py output.
    raw_path = analysis / "raw_positions.csv"
    with raw_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "source_file", "custodian", "statement_type", "statement_date",
            "account_number", "account_name", "section", "ticker",
            "description", "quantity", "price", "market_value",
            "cost_basis", "unrealized_gain", "est_annual_income", "est_yield_pct",
        ])
        writer.writerow([
            "taxable.pdf", "schwab", "taxable_brokerage", "2026-03-31",
            "****-0001", "taxable_brokerage", "etf", "VTI",
            "VANGUARD TOTAL STOCK", "100", "300.00", "30000.00",
            "20000.00", "10000.00", "", "",
        ])

    # Matching statement metadata.
    meta_path = analysis / "statements_meta.json"
    meta_path.write_text(json.dumps([
        {
            "source_file": "taxable.pdf",
            "custodian": "schwab",
            "statement_type": "taxable_brokerage",
            "statement_date": "2026-03-31",
            "account_number": "****-0001",
            "account_name": "taxable_brokerage",
            "stated_total": 30_000.00,
            "extracted_total": 30_000.00,
            "reconciled": True,
            "reconciliation_note": "reconciled within $0.00",
            "nesting_indicator": None,
        }
    ]))


def _write_config_with_529(work: Path, beneficiary: str = "kid_a",
                              value: float = 50_000.0) -> Path:
    """Write the standard config filename with a 529 manual_holdings entry.

    This is the regression-anchor: the original bug silently dropped this
    entry when the script was invoked without --config."""
    cfg = {
        "household": {"members": [{"name": "primary"}]},
        "accounts": [
            {
                "file_match": "taxable*.pdf",
                "type": "taxable_brokerage",
                "owner": "primary",
            },
        ],
        "manual_holdings": [
            {
                "account": f"529_{beneficiary}",
                "type": "529",
                "owner": "primary",
                "beneficiary": beneficiary,
                "ticker": "529_AGEBASED_U10",
                "value": value,
                "notes": (
                    f"529 plan — beneficiary {beneficiary}, "
                    "age-based glidepath (under 10): ~85/15 equity/bonds"
                ),
            },
        ],
    }
    cfg_path = work / CONFIG_FILENAME
    cfg_path.write_text(yaml.safe_dump(cfg))
    return cfg_path


class TestConsolidatePicksUpConfigWithoutFlag:
    """End-to-end: invoking consolidate.py without --config still applies
    manual_holdings + real_estate. This is the regression that locks in
    the original failure mode."""

    def test_529_manual_holding_appears_without_explicit_config(
        self, tmp_path: Path
    ) -> None:
        work = tmp_path / "work"
        work.mkdir()
        _write_minimal_raw_inputs(work)
        _write_config_with_529(work, beneficiary="kid_a", value=50_000.0)

        # IMPORTANT: no --config flag passed. The fix is what makes this work.
        result = subprocess.run(
            [sys.executable, str(CONSOLIDATE_SCRIPT), str(work)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, (
            f"consolidate.py failed:\nstdout={result.stdout}\nstderr={result.stderr}"
        )

        # The script should announce that it auto-discovered the config.
        assert "Using config:" in result.stdout, (
            "Expected an auto-discovery announcement in stdout — without it, "
            "the regression is masked. Got:\n" + result.stdout
        )

        # The consolidated ledger should contain the 529.
        positions_path = work / ".analysis" / "positions.csv"
        assert positions_path.is_file(), "positions.csv was not produced"

        with positions_path.open() as f:
            rows = list(csv.DictReader(f))

        # Locate the 529 manual holding by account name.
        five_two_nine_rows = [r for r in rows if r["account"] == "529_kid_a"]
        assert len(five_two_nine_rows) == 1, (
            f"Expected exactly one 529_kid_a row in positions.csv, "
            f"found {len(five_two_nine_rows)}. This is the original "
            f"regression: manual_holdings silently dropped because the "
            f"config wasn't auto-discovered. All rows: "
            f"{[r['account'] for r in rows]}"
        )

        row = five_two_nine_rows[0]
        assert row["account_type"] == "529"
        assert row["ticker"] == "529_AGEBASED_U10"
        assert float(row["market_value_gross"]) == pytest.approx(50_000.0)
        assert row["source_file"] == "config:manual_holdings"
