#!/usr/bin/env python3
"""
Phase 2: ingest loan statements + emit `raw_loans.csv` + `statements_meta.json`.

For v1, statement parsing is a **best-effort regex pass** for the CFPB / TILA
standardized formats (mortgage, credit card, auto). Failures fall through to
manual entry — the user's config carries enough info to keep the pipeline
running.

Reading:
- <work_folder>/*.pdf, *.csv (statement files)
- <work_folder>/debts_config.yaml (auto-discovered)

Writing:
- <work_folder>/.analysis/raw_loans.csv
- <work_folder>/.analysis/statements_meta.json

Usage:
    python extract_loans.py <work_folder> [--config PATH]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

# Make _config_discover importable when run as a script.
sys.path.insert(0, str(Path(__file__).parent))

import yaml  # noqa: E402

try:
    import pdfplumber  # noqa: E402
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False

from _config_discover import auto_discover_config  # noqa: E402


# -----------------------------------------------------------------------------
# Data shapes
# -----------------------------------------------------------------------------

@dataclass
class RawLoan:
    source_file: str
    loan_type: Optional[str] = None
    lender: Optional[str] = None
    statement_date: Optional[str] = None
    balance: Optional[float] = None
    original_amount: Optional[float] = None
    rate: Optional[float] = None
    rate_type: Optional[str] = None
    reset_date: Optional[str] = None
    term_months_remaining: Optional[int] = None
    scheduled_payment: Optional[float] = None
    min_payment: Optional[float] = None
    ytd_interest_paid: Optional[float] = None
    borrower: Optional[str] = None
    co_borrower: Optional[str] = None


@dataclass
class StatementMeta:
    source_file: str
    loan_type_inferred: Optional[str]
    stated_balance: Optional[float]
    extracted_balance: Optional[float]
    reconciled: bool
    reconciliation_note: str = ""
    parse_method: str = "regex"
    parse_errors: list[str] = field(default_factory=list)


# -----------------------------------------------------------------------------
# Loan-type inference from statement text
# -----------------------------------------------------------------------------

# Compact marker list; lifted from references/data/loan_type_taxonomy.yaml.
LOAN_TYPE_MARKERS = {
    "mortgage": ["mortgage statement", "principal balance", "escrow"],
    "heloc": ["home equity line", "heloc", "draw period"],
    "auto": ["auto loan", "vehicle financing"],
    "student_federal": ["federal student aid", "mohela", "nelnet",
                        "edfinancial", "aidvantage"],
    "student_private": ["sallie mae", "earnest", "sofi student"],
    "credit_card": ["minimum payment due", "interest charge calculation",
                    "credit limit"],
    "personal": ["personal loan", "installment loan"],
    "bnpl": ["affirm", "klarna", "afterpay"],
    "medical": ["hospital payment plan", "medical billing"],
    "tax": ["irs installment", "internal revenue service"],
}


def infer_loan_type(text: str) -> Optional[str]:
    lower = text.lower()
    scores = {t: sum(1 for m in markers if m in lower) for t, markers in LOAN_TYPE_MARKERS.items()}
    best = max(scores.items(), key=lambda kv: kv[1], default=(None, 0))
    return best[0] if best[1] > 0 else None


# -----------------------------------------------------------------------------
# Regex patterns (intentionally lenient — catch the common case, fall through
# to manual entry on miss)
# -----------------------------------------------------------------------------

MONEY = r"\$?\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?|\d+(?:\.\d{2})?)"
PERCENT = r"(\d+(?:\.\d+)?)\s*%"
DATE = r"(\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})"


def _to_float(s: str) -> Optional[float]:
    if s is None:
        return None
    try:
        return float(s.replace(",", "").replace("$", "").strip())
    except (ValueError, AttributeError):
        return None


def _search(pattern: str, text: str, group: int = 1) -> Optional[str]:
    m = re.search(pattern, text, flags=re.IGNORECASE)
    return m.group(group) if m else None


# -----------------------------------------------------------------------------
# Per-type parsers
# -----------------------------------------------------------------------------

def parse_mortgage(text: str) -> dict[str, Any]:
    """Best-effort mortgage parse following CFPB-standardized landmarks."""
    out: dict[str, Any] = {}

    balance = _search(rf"principal\s+balance[^\$]*{MONEY}", text)
    out["balance"] = _to_float(balance) if balance else None

    rate = _search(rf"interest\s+rate[^\d]*{PERCENT}", text)
    out["rate"] = float(rate) / 100 if rate else None

    # Principal + Interest payment (excludes escrow)
    pi = _search(rf"principal\s+(?:and|\&)\s+interest[^\$]*{MONEY}", text)
    out["scheduled_payment"] = _to_float(pi) if pi else None

    ytd = _search(rf"interest\s+paid\s+year[^\$]*{MONEY}", text)
    out["ytd_interest_paid"] = _to_float(ytd) if ytd else None

    # ARM detection
    if re.search(r"adjustable\s+rate|\barm\b", text, re.IGNORECASE):
        out["rate_type"] = "variable"
        reset = _search(rf"next\s+adjustment\s+date[^\d]*{DATE}", text)
        out["reset_date"] = reset
    else:
        out["rate_type"] = "fixed"

    return out


def parse_credit_card(text: str) -> dict[str, Any]:
    """Best-effort credit-card parse using TILA-standardized landmarks."""
    out: dict[str, Any] = {}

    bal = _search(rf"(?:new|statement)\s+balance[^\$]*{MONEY}", text)
    out["balance"] = _to_float(bal) if bal else None

    minpay = _search(rf"minimum\s+payment\s+due[^\$]*{MONEY}", text)
    out["min_payment"] = _to_float(minpay) if minpay else None

    apr = _search(rf"annual\s+percentage\s+rate[^\d]*{PERCENT}", text)
    out["rate"] = float(apr) / 100 if apr else None
    out["rate_type"] = "variable"
    out["scheduled_payment"] = None  # revolving — no scheduled

    return out


def parse_auto(text: str) -> dict[str, Any]:
    out: dict[str, Any] = {}

    bal = _search(rf"principal\s+balance[^\$]*{MONEY}", text) or \
          _search(rf"current\s+balance[^\$]*{MONEY}", text)
    out["balance"] = _to_float(bal) if bal else None

    rate = _search(rf"(?:apr|interest\s+rate)[^\d]*{PERCENT}", text)
    out["rate"] = float(rate) / 100 if rate else None
    out["rate_type"] = "fixed"

    pay = _search(rf"monthly\s+payment[^\$]*{MONEY}", text)
    out["scheduled_payment"] = _to_float(pay) if pay else None

    return out


def parse_student(text: str) -> dict[str, Any]:
    out: dict[str, Any] = {}

    bal = _search(rf"current\s+balance[^\$]*{MONEY}", text) or \
          _search(rf"principal\s+balance[^\$]*{MONEY}", text)
    out["balance"] = _to_float(bal) if bal else None

    rate = _search(rf"interest\s+rate[^\d]*{PERCENT}", text)
    out["rate"] = float(rate) / 100 if rate else None
    out["rate_type"] = "fixed"  # federal student loans are fixed

    pay = _search(rf"monthly\s+payment[^\$]*{MONEY}", text)
    out["scheduled_payment"] = _to_float(pay) if pay else None

    return out


PARSERS = {
    "mortgage": parse_mortgage,
    "heloc": parse_mortgage,           # HELOC follows mortgage statement layout
    "credit_card": parse_credit_card,
    "auto": parse_auto,
    "student_federal": parse_student,
    "student_private": parse_student,
}


# -----------------------------------------------------------------------------
# PDF / CSV reading
# -----------------------------------------------------------------------------

def extract_pdf_text(path: Path) -> str:
    if not HAS_PDFPLUMBER:
        return ""
    try:
        with pdfplumber.open(path) as pdf:
            return "\n".join(p.extract_text() or "" for p in pdf.pages)
    except Exception:
        return ""


def parse_statement_file(path: Path, accounts_config: list[dict]) -> tuple[RawLoan, StatementMeta]:
    """Parse a single statement file → (RawLoan, StatementMeta)."""

    # Read text
    text = ""
    if path.suffix.lower() == ".pdf":
        text = extract_pdf_text(path)
    elif path.suffix.lower() in (".txt",):
        text = path.read_text()

    # Infer loan type from text
    loan_type = infer_loan_type(text)

    raw = RawLoan(source_file=path.name)
    meta = StatementMeta(
        source_file=path.name,
        loan_type_inferred=loan_type,
        stated_balance=None,
        extracted_balance=None,
        reconciled=False,
    )

    if loan_type and loan_type in PARSERS:
        try:
            parsed = PARSERS[loan_type](text)
            raw.loan_type = loan_type
            for k, v in parsed.items():
                setattr(raw, k, v)
            meta.extracted_balance = parsed.get("balance")
            meta.stated_balance = parsed.get("balance")
            meta.reconciled = parsed.get("balance") is not None
            if not meta.reconciled:
                meta.reconciliation_note = "could not extract balance"
        except Exception as e:
            meta.parse_errors.append(f"parser error: {e}")
            meta.reconciliation_note = "parser raised exception"
    else:
        meta.reconciliation_note = "no loan-type marker matched"

    # Apply config override matching (file_match glob)
    for entry in accounts_config:
        pattern = entry.get("file_match", "")
        if pattern and path.match(pattern):
            for field_name in ("loan_id", "type", "owner", "lender",
                                "secured_by", "rate_type", "co_signer",
                                "servicer", "notes"):
                if field_name in entry:
                    if field_name == "type":
                        raw.loan_type = entry["type"]
                    elif hasattr(raw, field_name):
                        setattr(raw, field_name, entry[field_name])
            # config override is enough to "reconcile" — user took responsibility
            if not meta.reconciled and entry.get("type"):
                meta.reconciled = True
                meta.reconciliation_note = f"config file_match override applied ({pattern})"
            break

    return raw, meta


# -----------------------------------------------------------------------------
# Folder processing
# -----------------------------------------------------------------------------

def process_folder(folder: Path, config: dict) -> tuple[list[RawLoan], list[StatementMeta]]:
    accounts = config.get("accounts", [])
    raws: list[RawLoan] = []
    metas: list[StatementMeta] = []

    for path in sorted(folder.iterdir()):
        if path.is_file() and path.suffix.lower() in (".pdf", ".csv", ".txt"):
            raw, meta = parse_statement_file(path, accounts)
            raws.append(raw)
            metas.append(meta)

    return raws, metas


def write_outputs(raws: list[RawLoan], metas: list[StatementMeta], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    raw_path = out_dir / "raw_loans.csv"
    fields = list(RawLoan.__dataclass_fields__.keys())
    with raw_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in raws:
            w.writerow(asdict(r))

    meta_path = out_dir / "statements_meta.json"
    meta_path.write_text(json.dumps([asdict(m) for m in metas], indent=2, default=str))


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("work_folder", type=Path, help="Folder with loan statements")
    ap.add_argument("--config", type=Path, default=None,
                    help="debts_config.yaml (auto-discovered if omitted)")
    args = ap.parse_args()

    if not args.work_folder.is_dir():
        print(f"error: not a directory: {args.work_folder}", file=sys.stderr)
        return 2

    config: dict[str, Any] = {}
    resolved = auto_discover_config(args.work_folder, args.config)
    if resolved:
        with resolved.open() as f:
            config = yaml.safe_load(f) or {}
        if not args.config:
            print(f"  Using config: {resolved}")

    raws, metas = process_folder(args.work_folder, config)
    out_dir = args.work_folder / ".analysis"
    write_outputs(raws, metas, out_dir)

    print(f"Parsed {len(raws)} statement file(s).")
    unreconciled = [m for m in metas if not m.reconciled]
    if unreconciled:
        print(f"  {len(unreconciled)} statement(s) did not reconcile — surface for Stage 3:")
        for m in unreconciled:
            print(f"    - {m.source_file}: {m.reconciliation_note}")
    print(f"Output: {out_dir / 'raw_loans.csv'}")
    print(f"        {out_dir / 'statements_meta.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
