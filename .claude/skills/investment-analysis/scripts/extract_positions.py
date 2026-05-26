#!/usr/bin/env python3
"""
Phase 2: Extract positions from investment statements.

Walks an input folder, identifies each file's format and custodian, runs the
appropriate parser, and emits raw_positions.csv plus a reconciliation report.

This script is INGESTION ONLY — no classification, no consolidation, no
analysis. It produces a flat raw ledger that consolidate.py picks up.

Usage:
    python extract_positions.py <input_folder> [--config PATH] [--output PATH]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

# -----------------------------------------------------------------------------
# Auto-install heavy deps on first run
# -----------------------------------------------------------------------------

def _ensure(pkg: str, import_name: Optional[str] = None) -> None:
    name = import_name or pkg
    try:
        __import__(name)
    except ImportError:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", pkg, "-q"],
            check=True,
        )

_ensure("pandas")
_ensure("pdfplumber")
_ensure("openpyxl")
_ensure("PyYAML", "yaml")

import pandas as pd  # noqa: E402
import pdfplumber  # noqa: E402
import yaml  # noqa: E402

from _config_discover import auto_discover_config  # noqa: E402


# -----------------------------------------------------------------------------
# Data types
# -----------------------------------------------------------------------------

@dataclass
class RawPosition:
    """One line item from a statement, pre-classification."""
    source_file: str
    custodian: str
    statement_type: str
    statement_date: Optional[str]
    account_number: str
    account_name: str
    section: str  # cash | equity | mutual_fund | etf | bond | other
    ticker: str
    description: str
    quantity: Optional[float]
    price: Optional[float]
    market_value: float
    cost_basis: Optional[float]
    unrealized_gain: Optional[float]
    est_annual_income: Optional[float]
    est_yield_pct: Optional[float]


@dataclass
class StatementMeta:
    """Statement-level summary used for reconciliation."""
    source_file: str
    custodian: str
    statement_type: str
    statement_date: Optional[str]
    account_number: str
    account_name: str
    stated_total: Optional[float]
    extracted_total: float = 0.0
    reconciled: bool = False
    reconciliation_note: str = ""
    nesting_indicator: Optional[dict] = None  # if statement contains a self-directed sleeve line


@dataclass
class ExtractionResult:
    positions: list[RawPosition] = field(default_factory=list)
    statements: list[StatementMeta] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# -----------------------------------------------------------------------------
# Custodian fingerprinting
# -----------------------------------------------------------------------------

CUSTODIAN_SIGNALS: dict[str, list[str]] = {
    # Public custodian names — these are not PII, they're the industry.
    "schwab": ["Charles Schwab & Co.", "schwab.com", "Schwab Personal Choice"],
    "schwab_trust_ttee": ["Charles Schwab Trust Bank TTEE", "Schwab Trust Bank, TTEE"],
    "schwab_trust_cust": ["Charles Schwab Trust Bank CUST", "Schwab Trust Bank, CUST"],
    "fidelity": ["Fidelity Investments", "fidelity.com", "Fidelity Brokerage"],
    "vanguard": ["The Vanguard Group", "vanguard.com"],
    "etrade": ["E*TRADE Securities", "etrade.com", "Morgan Stanley"],
    "tiaa": ["TIAA-CREF", "TIAA, FSB"],
    "empower": ["Empower Retirement"],
    "voya": ["Voya Financial", "Voya Institutional"],
    "principal": ["Principal Financial"],
}

STATEMENT_TYPE_SIGNALS: list[tuple[str, list[str]]] = [
    ("roth_ira", ["Roth IRA", "Roth Individual Retirement"]),
    ("traditional_ira", ["Traditional IRA", "Rollover IRA", "Traditional Individual Retirement"]),
    ("roth_401k", ["Roth 401(k)"]),
    ("qualified_401k", ["401(k) Savings", "401(k) Profit Sharing", "401(K) PLAN"]),
    ("qualified_403b", ["403(b) Tax-Sheltered", "403(b)(7)"]),
    ("qualified_457", ["457(b) Deferred Compensation"]),
    ("nqdc", ["Executive Deferred Compensation", "Nonqualified Deferred Comp", "EXEC DEF COMP"]),
    ("pension_db", ["Defined Benefit Pension"]),
    ("pension_cb", ["Cash Balance Plan"]),
    ("hsa", ["Health Savings Account"]),
    ("529", ["529 College Savings", "529 Plan"]),
    ("pcra", ["Personal Choice Retirement Account", "PCRA"]),
    ("brokeragelink", ["BrokerageLink"]),
    ("taxable_brokerage", ["Brokerage Account"]),
]


def fingerprint(first_page_text: str) -> tuple[str, str]:
    """Return (custodian, statement_type) inferred from the first page text."""
    custodian = "unknown"
    for name, signals in CUSTODIAN_SIGNALS.items():
        if any(sig.lower() in first_page_text.lower() for sig in signals):
            custodian = name
            break

    statement_type = "unknown"
    for stype, signals in STATEMENT_TYPE_SIGNALS:
        if any(sig.lower() in first_page_text.lower() for sig in signals):
            statement_type = stype
            break

    return custodian, statement_type


# -----------------------------------------------------------------------------
# PDF extraction
# -----------------------------------------------------------------------------

def _read_pdf_text(path: Path) -> list[str]:
    """Return per-page text. Empty list if extraction fails."""
    try:
        with pdfplumber.open(str(path)) as pdf:
            return [p.extract_text() or "" for p in pdf.pages]
    except Exception as e:
        return []


def _parse_money(s: str) -> Optional[float]:
    """Parse a money-formatted string. Returns None if unparseable."""
    if not s or s.strip() in ("", "—", "--", "N/A", "n/a"):
        return None
    cleaned = re.sub(r"[,\s$]", "", s)
    cleaned = cleaned.replace("(", "-").replace(")", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _extract_ending_value(pages: list[str]) -> Optional[float]:
    """Try to find the statement's stated ending account value.

    Statement text comes out of pdfplumber with words often glued together
    (no whitespace between adjacent run-on words like "EndingAccountValue").
    Patterns are written to tolerate that.
    """
    patterns = [
        # "EndingAccountValue $X,XXX.XX" — Schwab brokerage / PCRA / NQDC style
        r"Ending\s*Account\s*Value\s*\$?\s*([\d,]+\.\d{2})",
        # "EndingValue $X,XXX.XX" — 401(k) plan statement
        r"Ending\s*Value\s+\$?\s*([\d,]+\.\d{2})",
        # "YourAccountValue" with dollar value on the line above
        r"\$([\d,]+\.\d{2})\s*\n\s*Your\s*Account\s*Value",
        # Fallback: "Total Account Value" with a dollar in the vicinity
        r"Total\s*Account\s*Value\s*\$?\s*([\d,]+\.\d{2})",
    ]
    full_text = "\n".join(pages[:3])
    for pat in patterns:
        m = re.search(pat, full_text, re.IGNORECASE)
        if m:
            return _parse_money(m.group(1))
    return None


def _extract_statement_date(pages: list[str]) -> Optional[str]:
    """Extract period-end date as ISO string. Best-effort."""
    patterns = [
        r"(?:as of|period\s+ending|ending)\s+(\w+\s+\d{1,2},?\s+\d{4})",
        r"(\w+\s+\d{1,2}\s*[-–]\s*\w+\s+\d{1,2},?\s+\d{4})",
        r"Statement Period[:\s]+\w+\s+\d{1,2}\s*[-–]\s*(\w+\s+\d{1,2},?\s+\d{4})",
    ]
    for page in pages[:2]:
        for pat in patterns:
            m = re.search(pat, page, re.IGNORECASE)
            if m:
                try:
                    return pd.to_datetime(m.group(1)).date().isoformat()
                except Exception:
                    continue
    return None


def _extract_account_number(pages: list[str]) -> str:
    """Find the account number (often masked)."""
    patterns = [
        r"Account\s+Number\s+([\d\-\*]+)",
        r"Account\s+#?\s*([\d\-\*]{4,})",
    ]
    for page in pages[:2]:
        for pat in patterns:
            m = re.search(pat, page)
            if m:
                return m.group(1)
    return ""


# Position line patterns — generic enough to handle most Schwab variants and
# similar layouts. Format: <TICKER> <DESCRIPTION...> <QTY> <PRICE> <MV> ...
# Description char class includes quality markers (◊ ◇ ‡ † *) that some
# custodians attach to fund names.
POSITION_LINE_PATTERN = re.compile(
    r"^(?P<ticker>[A-Z][A-Z0-9.]{0,5})\s+"
    r"(?P<desc>[A-Z][A-Z0-9 .,&'/◊◇‡†*-]+?)\s+,?\s*"
    r"(?P<qty>[\d,]+\.\d{1,4})\s+"
    r"(?P<price>[\d,]+\.\d{2,5})\s+"
    r"(?P<mv>[\d,]+\.\d{2})"
)

# Self-directed sleeve indicator — matches lines like
# "Personal Choice Retirement Acct -- -- $190,349.41" (spaced) OR
# "PersonalChoiceRetirementAcct -- -- $190,349.41" (run-on, as pdfplumber emits)
NESTING_INDICATOR_PATTERN = re.compile(
    r"(Personal\s*Choice\s*Retirement|PCRA|Self\s*[-]?\s*Directed\s*Brokerage|BrokerageLink)"
    r"[^\d]*(\$?[\d,]+\.\d{2})",
    re.IGNORECASE,
)


def _classify_section(text: str) -> str:
    """Identify which section the current text belongs to."""
    t = text.lower()
    if "cash and cash investments" in t or "money market" in t:
        return "cash"
    if "positions - equities" in t or "positions - common stocks" in t:
        return "equity"
    if "positions - mutual funds" in t:
        return "mutual_fund"
    if "exchange traded funds" in t or "positions - etfs" in t:
        return "etf"
    if "positions - bonds" in t or "fixed income" in t:
        return "bond"
    if "positions - other" in t or "alternative" in t:
        return "other"
    return ""


# Qualified plan (401(k) etc.) statement position pattern. Format:
#   "FundNameWithoutSpaces 26,735.4880 $18.38 $491,398.27"
#   "PersonalChoiceRetirementAcct -- -- $190,349.41"
QUALIFIED_PLAN_POSITION_PATTERN = re.compile(
    r"^(?P<name>[A-Z][A-Za-z0-9. ]{4,60}?)\s+"
    r"(?P<qty>[\d,]+\.\d{2,4}|--)\s+"
    r"\$?(?P<price>[\d,]+\.\d{2,5}|--)\s+"
    r"\$(?P<mv>[\d,]+\.\d{2})"
)


def parse_qualified_plan_pdf(path: Path, pages: list[str], custodian: str, stype: str) -> tuple[list[RawPosition], StatementMeta]:
    """Parse a 401(k) / 403(b) / 457 plan statement (different layout from brokerage)."""
    stated_total = _extract_ending_value(pages)
    statement_date = _extract_statement_date(pages)
    account_number = _extract_account_number(pages)

    meta = StatementMeta(
        source_file=path.name,
        custodian=custodian,
        statement_type=stype,
        statement_date=statement_date,
        account_number=account_number,
        account_name=stype,
        stated_total=stated_total,
    )

    positions: list[RawPosition] = []
    for page_text in pages:
        for line in page_text.splitlines():
            # Skip totals and section headers
            if "TOTAL" in line.upper() and "VALUE" in line.upper():
                continue
            m = QUALIFIED_PLAN_POSITION_PATTERN.match(line)
            if not m:
                continue
            name = m.group("name").strip()
            mv = _parse_money(m.group("mv"))
            if mv is None or mv < 0.01:
                continue
            # Nesting indicator: PCRA / self-directed within a plan
            if NESTING_INDICATOR_PATTERN.search(name + " $" + m.group("mv")):
                meta.nesting_indicator = {"phrase": name, "value": mv}
                continue
            qty_str = m.group("qty")
            price_str = m.group("price")
            positions.append(RawPosition(
                source_file=path.name,
                custodian=custodian,
                statement_type=stype,
                statement_date=statement_date,
                account_number=account_number,
                account_name=stype,
                section="mutual_fund",
                ticker=name[:20],          # use truncated name as proxy ticker
                description=name,
                quantity=_parse_money(qty_str) if qty_str != "--" else None,
                price=_parse_money(price_str) if price_str != "--" else None,
                market_value=mv,
                cost_basis=None,
                unrealized_gain=None,
                est_annual_income=None,
                est_yield_pct=None,
            ))

    meta.extracted_total = sum(p.market_value for p in positions)
    # Also include the nesting-indicator value in the extracted total (PCRA sleeve
    # is still part of the plan's stated total).
    if meta.nesting_indicator:
        meta.extracted_total += meta.nesting_indicator["value"]
    return positions, meta


def parse_schwab_like_pdf(path: Path, pages: list[str], custodian: str, stype: str) -> tuple[list[RawPosition], StatementMeta]:
    """Parse a Schwab-style brokerage / PCRA / NQDC statement.

    The layout is consistent enough across the Schwab family (taxable brokerage,
    PCRA, trust-bank-CUST NQDC, trust-bank-TTEE qualified plan PCRA) that one
    parser handles them all. Other custodians need their own parsers.
    """
    stated_total = _extract_ending_value(pages)
    statement_date = _extract_statement_date(pages)
    account_number = _extract_account_number(pages)
    # Account name: try to pick up nickname / type label from first page
    account_name = stype  # fallback
    m = re.search(r"Account\s+Nickname\s+(\w+)", pages[0] if pages else "")
    if m:
        account_name = m.group(1)

    meta = StatementMeta(
        source_file=path.name,
        custodian=custodian,
        statement_type=stype,
        statement_date=statement_date,
        account_number=account_number,
        account_name=account_name,
        stated_total=stated_total,
    )

    positions: list[RawPosition] = []
    current_section = ""

    for page_text in pages:
        for line in page_text.splitlines():
            section_hint = _classify_section(line)
            if section_hint:
                current_section = section_hint
                continue

            # Look for nesting indicator
            nest_match = NESTING_INDICATOR_PATTERN.search(line)
            if nest_match:
                nest_value = _parse_money(nest_match.group(2))
                if nest_value:
                    meta.nesting_indicator = {
                        "phrase": nest_match.group(1),
                        "value": nest_value,
                    }
                continue

            # Cash row: special-case as it doesn't have a ticker in the normal pattern.
            # Two layouts:
            #   "Cash 0.00 192.65 192.65 0.00 <1%"           → type only, capture ending = 2nd value
            #   "BankSweep CHARLESSCHWAB 670.36 1,233.31 ..." → type + bank name, capture ending = 2nd value
            if current_section == "cash":
                cm = re.match(
                    r"^(?:Cash|Bank\s*Sweep)\s+(?:[A-Z][A-Z0-9.,&]*\s+)?"
                    r"([\d,]+\.\d{2})\s+([\d,]+\.\d{2})",
                    line,
                    re.IGNORECASE,
                )
                if cm:
                    mv = _parse_money(cm.group(2))  # ending balance
                    if mv:
                        positions.append(RawPosition(
                            source_file=path.name,
                            custodian=custodian,
                            statement_type=stype,
                            statement_date=statement_date,
                            account_number=account_number,
                            account_name=account_name,
                            section="cash",
                            ticker="CASH",
                            description="Cash and cash investments",
                            quantity=None,
                            price=None,
                            market_value=mv,
                            cost_basis=None,
                            unrealized_gain=None,
                            est_annual_income=None,
                            est_yield_pct=None,
                        ))
                continue

            # Standard position row
            pm = POSITION_LINE_PATTERN.match(line)
            if pm and current_section in {"equity", "mutual_fund", "etf", "bond", "other"}:
                mv = _parse_money(pm.group("mv"))
                if mv is None:
                    continue
                qty = _parse_money(pm.group("qty"))
                price = _parse_money(pm.group("price"))
                positions.append(RawPosition(
                    source_file=path.name,
                    custodian=custodian,
                    statement_type=stype,
                    statement_date=statement_date,
                    account_number=account_number,
                    account_name=account_name,
                    section=current_section,
                    ticker=pm.group("ticker"),
                    description=pm.group("desc").strip(),
                    quantity=qty,
                    price=price,
                    market_value=mv,
                    cost_basis=None,        # filled in below if a cost-basis column exists
                    unrealized_gain=None,
                    est_annual_income=None,
                    est_yield_pct=None,
                ))

    meta.extracted_total = sum(p.market_value for p in positions)
    return positions, meta


# -----------------------------------------------------------------------------
# CSV / Excel handling
# -----------------------------------------------------------------------------

BALANCE_SHEET_HEADERS = {
    "category", "account", "mv", "market value", "market_value",
    "mortgage", "net asset", "net_asset", "net equity", "owner",
    "vested", "liquid", "notes",
}


def is_balance_sheet(df: pd.DataFrame) -> bool:
    """Heuristic: does this CSV look like a household balance-sheet spreadsheet
    rather than a positions export?"""
    cols = {c.strip().lower() for c in df.columns}
    overlap = cols & BALANCE_SHEET_HEADERS
    return len(overlap) >= 3


def parse_csv_or_excel(path: Path) -> tuple[list[RawPosition], StatementMeta]:
    """Parse a CSV/Excel file. Two flavors:
    - Custodian export of transactions/positions → parse as positions.
    - Household balance sheet → defer to consolidate (returns empty positions).
    """
    try:
        if path.suffix.lower() in (".xlsx", ".xls"):
            df = pd.read_excel(path)
        else:
            df = pd.read_csv(path)
    except Exception as e:
        return [], StatementMeta(
            source_file=path.name,
            custodian="unknown",
            statement_type="parse_failed",
            statement_date=None,
            account_number="",
            account_name="",
            stated_total=None,
            reconciliation_note=f"parse error: {e}",
        )

    if is_balance_sheet(df):
        # Balance sheet — return placeholder meta; consolidate.py picks it up.
        return [], StatementMeta(
            source_file=path.name,
            custodian="user",
            statement_type="balance_sheet",
            statement_date=None,
            account_number="",
            account_name="balance_sheet",
            stated_total=None,
            reconciliation_note="balance_sheet — handled in consolidate",
        )

    # Otherwise: not implemented as a default — many custodian CSV formats vary.
    # Real implementations should add format-specific parsers here.
    return [], StatementMeta(
        source_file=path.name,
        custodian="unknown",
        statement_type="csv_unhandled",
        statement_date=None,
        account_number="",
        account_name="",
        stated_total=None,
        reconciliation_note="CSV parser not implemented for this format — add a custodian-specific parser",
    )


# -----------------------------------------------------------------------------
# Reconciliation
# -----------------------------------------------------------------------------

def reconcile(meta: StatementMeta, tol_abs: float = 1.0, tol_pct: float = 0.001) -> None:
    """Set meta.reconciled and meta.reconciliation_note."""
    if meta.stated_total is None:
        meta.reconciled = False
        meta.reconciliation_note = "no stated total found — cannot reconcile"
        return

    diff = abs(meta.extracted_total - meta.stated_total)
    pct = diff / meta.stated_total if meta.stated_total else 0

    if diff <= tol_abs or pct <= tol_pct:
        meta.reconciled = True
        meta.reconciliation_note = f"reconciled within ${diff:.2f}"
    else:
        meta.reconciled = False
        meta.reconciliation_note = (
            f"MISMATCH: extracted ${meta.extracted_total:,.2f} vs "
            f"stated ${meta.stated_total:,.2f} (off by ${diff:,.2f} / {pct:.2%})"
        )


# -----------------------------------------------------------------------------
# Folder walk + dispatch
# -----------------------------------------------------------------------------

OUTPUT_FILENAMES = {
    "raw_positions.csv", "statements_meta.json", "extract_warnings.txt",
    "positions.csv", "positions_classified.csv",
    "consolidation_log.csv", "consolidation_summary.md",
    "classification_unknowns.md",
    "Allocation.csv", "Concentration.md", "TaxLocation.md",
    "Fees.csv", "Income.csv", "Anomalies.md",
    "Investment Positions.csv", "Commentary.md",
    "_analyze_summary.json",
    "investment_analysis_config.yaml",
}


def process_folder(input_folder: Path, config: dict) -> ExtractionResult:
    result = ExtractionResult()

    for path in sorted(input_folder.iterdir()):
        if not path.is_file():
            continue
        # Skip our own output files so re-runs are idempotent
        if path.name in OUTPUT_FILENAMES or path.name.startswith("chart_"):
            continue
        if path.suffix.lower() == ".pdf":
            pages = _read_pdf_text(path)
            if not pages:
                result.warnings.append(f"{path.name}: PDF text extraction failed (image-based?)")
                continue
            custodian, stype = fingerprint(pages[0] if pages else "")
            # Dispatch based on statement type — 401(k) plans have a different
            # layout than brokerage statements.
            if stype in {"qualified_401k", "qualified_403b", "qualified_457", "roth_401k"}:
                positions, meta = parse_qualified_plan_pdf(path, pages, custodian, stype)
            elif custodian.startswith("schwab"):
                positions, meta = parse_schwab_like_pdf(path, pages, custodian, stype)
            else:
                # Other custodians — stub out for now; surface as unhandled
                positions = []
                meta = StatementMeta(
                    source_file=path.name,
                    custodian=custodian,
                    statement_type=stype,
                    statement_date=_extract_statement_date(pages),
                    account_number=_extract_account_number(pages),
                    account_name="",
                    stated_total=_extract_ending_value(pages),
                    reconciliation_note=f"no parser implemented for custodian={custodian} — add one",
                )
            recon = config.get("reconciliation", {}).get("per_statement", {})
            reconcile(meta, tol_abs=recon.get("absolute_usd", 1.0), tol_pct=recon.get("relative_pct", 0.001))
            result.positions.extend(positions)
            result.statements.append(meta)

        elif path.suffix.lower() in (".csv", ".xlsx", ".xls"):
            positions, meta = parse_csv_or_excel(path)
            result.positions.extend(positions)
            result.statements.append(meta)

        else:
            continue  # skip non-data files (images, etc.)

    return result


# -----------------------------------------------------------------------------
# Output
# -----------------------------------------------------------------------------

def write_outputs(result: ExtractionResult, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    # raw_positions.csv
    pos_path = output_dir / "raw_positions.csv"
    with pos_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(RawPosition(
            source_file="", custodian="", statement_type="", statement_date=None,
            account_number="", account_name="", section="", ticker="",
            description="", quantity=None, price=None, market_value=0.0,
            cost_basis=None, unrealized_gain=None, est_annual_income=None,
            est_yield_pct=None,
        )).keys()))
        writer.writeheader()
        for p in result.positions:
            writer.writerow(asdict(p))

    # statements_meta.json — reconciliation results + nesting indicators
    meta_path = output_dir / "statements_meta.json"
    with meta_path.open("w") as f:
        json.dump(
            [asdict(m) for m in result.statements],
            f, indent=2, default=str,
        )

    # warnings.txt
    if result.warnings:
        warn_path = output_dir / "extract_warnings.txt"
        with warn_path.open("w") as f:
            f.write("\n".join(result.warnings))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input_folder", type=Path, help="Folder with statements")
    ap.add_argument("--config", type=Path, default=None,
                    help="investment_analysis_config.yaml (optional; defaults will be used otherwise)")
    ap.add_argument("--output", type=Path, default=None,
                    help="Output directory (default: input_folder)")
    args = ap.parse_args()

    if not args.input_folder.is_dir():
        print(f"error: not a directory: {args.input_folder}", file=sys.stderr)
        return 2

    config: dict[str, Any] = {}
    resolved_config = auto_discover_config(args.input_folder, args.config)
    if resolved_config:
        with resolved_config.open() as f:
            config = yaml.safe_load(f) or {}
        if not args.config:
            print(f"  Using config: {resolved_config}")

    # All intermediate artifacts go into a .analysis/ subfolder inside the
    # input folder, keeping the user's source statements + final deliverables
    # at the root.
    output_dir = args.output or (args.input_folder / ".analysis")
    output_dir.mkdir(exist_ok=True)
    result = process_folder(args.input_folder, config)
    write_outputs(result, output_dir)

    # Summarize
    print(f"Parsed {len(result.statements)} statements, {len(result.positions)} positions.")
    unreconciled = [m for m in result.statements if not m.reconciled]
    if unreconciled:
        print(f"  ⚠ {len(unreconciled)} statement(s) failed reconciliation:")
        for m in unreconciled:
            print(f"    - {m.source_file}: {m.reconciliation_note}")
    if result.warnings:
        print(f"  ⚠ {len(result.warnings)} warning(s) — see extract_warnings.txt")
    print(f"Output: {output_dir / 'raw_positions.csv'}")
    print(f"        {output_dir / 'statements_meta.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
