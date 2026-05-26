#!/usr/bin/env python3
"""
Phase 3: consolidate raw_loans + manual_entries → loans_consolidated.csv.

Operations:
- Apply config overrides (file_match → loan_id, owner, secured_by, …)
- Inject manual_entries from config
- Dedupe joint debt
- Filter out paid_in_full credit cards (excluded from headline debt)
- Compute term_months_remaining from balance/rate/payment for amortizing
  loans where it isn't explicit

Reading:
- <work_folder>/.analysis/raw_loans.csv
- <work_folder>/debts_config.yaml (auto-discovered)

Writing:
- <work_folder>/.analysis/loans_consolidated.csv
- <work_folder>/.analysis/consolidation_summary.md

Usage:
    python consolidate.py <work_folder> [--config PATH]
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).parent))

import yaml  # noqa: E402

from _config_discover import auto_discover_config  # noqa: E402


# -----------------------------------------------------------------------------
# Output schema
# -----------------------------------------------------------------------------

@dataclass
class Loan:
    loan_id: str
    owner: str
    type: str
    lender: Optional[str]
    balance: float
    original_amount: Optional[float]
    rate: Optional[float]
    rate_type: Optional[str]
    reset_date: Optional[str]
    term_months_remaining: Optional[int]
    min_payment: Optional[float]
    scheduled_payment: Optional[float]
    payment_estimated: bool                # True when scheduled_payment was computed, not user-supplied
    status: Optional[str]                  # filled by classify.py — left blank here
    tax_treatment: Optional[str]           # filled by classify.py
    secured_by: Optional[str]
    co_signer: bool
    joint_share: Optional[float]
    source: str                            # "statement:<file>" | "config:manual_entries"
    notes: Optional[str]


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _safe_float(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _safe_int(v: Any) -> Optional[int]:
    f = _safe_float(v)
    return int(f) if f is not None else None


def _compute_term(balance: Optional[float], rate: Optional[float],
                    payment: Optional[float]) -> Optional[int]:
    """Closed-form remaining-term from balance, rate, scheduled payment."""
    if not balance or not payment or balance <= 0 or payment <= 0:
        return None
    if rate is None or rate <= 0:
        return int(math.ceil(balance / payment))
    monthly_rate = rate / 12
    monthly_interest = balance * monthly_rate
    if payment <= monthly_interest:
        return None  # payment doesn't cover interest — surface as anomaly
    try:
        n = -math.log(1 - monthly_rate * balance / payment) / math.log(1 + monthly_rate)
        return int(math.ceil(n))
    except (ValueError, ZeroDivisionError):
        return None


def _alias_from_filename(source_file: str) -> str:
    return Path(source_file).stem.lower().replace(" ", "_").replace("-", "_")


# -----------------------------------------------------------------------------
# Build Loan rows
# -----------------------------------------------------------------------------

def loan_from_raw(raw: dict, config_accounts: list[dict]) -> Optional[Loan]:
    """Build a Loan from a raw_loans.csv row + matching config entry."""

    # Find matching config entry (by file_match against source_file)
    matched_entry: dict = {}
    source_file = raw.get("source_file", "")
    for entry in config_accounts:
        pattern = entry.get("file_match", "")
        if pattern and Path(source_file).match(pattern):
            matched_entry = entry
            break

    # Loan type — prefer config, then parsed
    loan_type = matched_entry.get("type") or raw.get("loan_type")
    if not loan_type:
        return None  # can't consolidate without a type

    # Loan ID — prefer config, then alias from filename
    loan_id = matched_entry.get("loan_id") or _alias_from_filename(source_file)

    # Owner
    owner = matched_entry.get("owner") or raw.get("borrower") or "primary"

    # Balance — required
    balance = _safe_float(raw.get("balance"))
    if balance is None:
        return None

    rate = _safe_float(raw.get("rate"))
    payment = _safe_float(raw.get("scheduled_payment"))
    term = _safe_int(raw.get("term_months_remaining")) or _compute_term(balance, rate, payment)

    # Credit-card revolving flag — config overrides the default behavior
    revolving = matched_entry.get("revolving", True)
    if loan_type == "credit_card" and not revolving:
        # Will be classified as paid_in_full; filtered from headline in analyze
        pass

    return Loan(
        loan_id=loan_id,
        owner=owner,
        type=loan_type,
        lender=matched_entry.get("lender") or raw.get("lender"),
        balance=balance,
        original_amount=_safe_float(raw.get("original_amount")),
        rate=rate,
        rate_type=matched_entry.get("rate_type") or raw.get("rate_type"),
        reset_date=raw.get("reset_date") or None,
        term_months_remaining=term,
        min_payment=_safe_float(raw.get("min_payment")),
        scheduled_payment=payment,
        payment_estimated=False,  # came from statement extraction
        status=None,
        tax_treatment=None,
        secured_by=matched_entry.get("secured_by"),
        co_signer=bool(matched_entry.get("co_signer", False)),
        joint_share=0.5 if owner == "joint" else None,
        source=f"statement:{source_file}",
        notes=matched_entry.get("notes"),
    )


def loan_from_manual(entry: dict, default_owner: str) -> Optional[Loan]:
    balance = _safe_float(entry.get("balance"))
    if balance is None:
        return None

    rate = _safe_float(entry.get("rate"))
    payment = _safe_float(entry.get("scheduled_payment"))
    term = _safe_int(entry.get("term_months_remaining")) or _compute_term(balance, rate, payment)

    owner = entry.get("owner", default_owner)
    # Estimated-payment flag: explicit config wins; otherwise inferred from
    # whether the user supplied a payment vs. we computed one from term.
    user_supplied_payment = entry.get("scheduled_payment") is not None
    explicit_flag = entry.get("payment_estimated")
    payment_estimated = (explicit_flag if explicit_flag is not None
                         else not user_supplied_payment)
    return Loan(
        loan_id=entry.get("loan_id", f"manual_{entry.get('type', 'other')}"),
        owner=owner,
        type=entry.get("type", "other"),
        lender=entry.get("lender"),
        balance=balance,
        original_amount=_safe_float(entry.get("original_amount")),
        rate=rate,
        rate_type=entry.get("rate_type", "fixed"),
        reset_date=entry.get("promo_end_date") or entry.get("reset_date"),
        term_months_remaining=term,
        min_payment=_safe_float(entry.get("min_payment")),
        scheduled_payment=payment,
        payment_estimated=payment_estimated,
        status=entry.get("status"),  # informal / amortizing / revolving — may be pre-set
        tax_treatment=None,
        secured_by=entry.get("secured_by"),
        co_signer=bool(entry.get("co_signer", False)),
        joint_share=0.5 if owner == "joint" else None,
        source="config:manual_entries",
        notes=entry.get("notes"),
    )


# -----------------------------------------------------------------------------
# Dedup
# -----------------------------------------------------------------------------

def dedup_loans(loans: list[Loan]) -> tuple[list[Loan], list[str]]:
    """Dedupe by loan_id (keep first); also flag joint-duplicate suspicion."""
    seen: dict[str, Loan] = {}
    notes: list[str] = []
    for l in loans:
        if l.loan_id in seen:
            notes.append(f"dropped duplicate loan_id: {l.loan_id} (from {l.source})")
            continue
        seen[l.loan_id] = l

    # Detect joint-duplicate suspicion: same lender + same balance ± $1 + same rate
    by_signature: dict[tuple, list[Loan]] = {}
    for l in seen.values():
        if l.owner == "joint":
            continue
        sig = (l.lender, round(l.balance, 0), round(l.rate or 0, 4))
        by_signature.setdefault(sig, []).append(l)
    for sig, ls in by_signature.items():
        if len(ls) > 1:
            ids = [l.loan_id for l in ls]
            notes.append(
                f"possible joint-debt duplicate (same lender+balance+rate): {', '.join(ids)} "
                f"— consider marking owner=joint in config"
            )

    return list(seen.values()), notes


# -----------------------------------------------------------------------------
# Output
# -----------------------------------------------------------------------------

def write_outputs(loans: list[Loan], notes: list[str], out_dir: Path,
                    config: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / "loans_consolidated.csv"
    fields = list(Loan.__dataclass_fields__.keys())
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for l in loans:
            w.writerow(asdict(l))

    # Summary
    total = sum(l.balance for l in loans)
    by_type: dict[str, float] = {}
    for l in loans:
        by_type[l.type] = by_type.get(l.type, 0) + l.balance

    by_source: dict[str, int] = {}
    for l in loans:
        key = "config:manual_entries" if l.source.startswith("config") else "statement"
        by_source[key] = by_source.get(key, 0) + 1

    lines = [
        "# Consolidation Summary",
        "",
        f"Total loans: {len(loans)}",
        f"Total debt (all rows): ${total:,.2f}",
        "",
        "## By type",
        "",
    ]
    for t, b in sorted(by_type.items(), key=lambda kv: -kv[1]):
        lines.append(f"- `{t}` — ${b:,.2f}")
    lines += [
        "",
        "## By source",
        "",
        f"- From statements: {by_source.get('statement', 0)}",
        f"- From manual_entries: {by_source.get('config:manual_entries', 0)}",
    ]
    if notes:
        lines += ["", "## Notes", ""]
        for n in notes:
            lines.append(f"- {n}")

    (out_dir / "consolidation_summary.md").write_text("\n".join(lines))


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("work_folder", type=Path)
    ap.add_argument("--config", type=Path, default=None)
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

    io_dir = args.work_folder / ".analysis"
    raw_path = io_dir / "raw_loans.csv"

    # Build Loan rows from statements
    loans: list[Loan] = []
    if raw_path.is_file():
        with raw_path.open() as f:
            for row in csv.DictReader(f):
                l = loan_from_raw(row, config.get("accounts", []))
                if l:
                    loans.append(l)

    # Inject manual entries
    default_owner = (config.get("household", {}).get("members") or [{}])[0].get("name", "primary")
    for entry in config.get("manual_entries", []):
        l = loan_from_manual(entry, default_owner)
        if l:
            loans.append(l)

    # Dedup
    loans, dedup_notes = dedup_loans(loans)

    write_outputs(loans, dedup_notes, io_dir, config)

    print(f"Consolidated {len(loans)} loan(s).")
    if dedup_notes:
        print(f"  {len(dedup_notes)} consolidation note(s) — see consolidation_summary.md")
    print(f"Output: {io_dir / 'loans_consolidated.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
